"""LLM bridge: subprocess call to an external CLI tool, or direct HTTP to an OpenAI-compatible endpoint."""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class BridgeResult:
    ok: bool
    raw: str
    error: str | None
    attempts: int
    latency_ms: int


# HTTP provider: statuses worth retrying vs. failing fast
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class _RetryableHTTPError(Exception):
    """A transient HTTP failure that ask() should retry."""


class _NonRetryableHTTPError(Exception):
    """A permanent HTTP failure that ask() should fail fast."""


# Sampling params we type/range check. Unknown keys pass through unvalidated so
# new provider-specific params work before this table knows about them.
_SAMPLING_VALIDATORS = {
    "temperature": (float, 0.0, 2.0),
    "max_tokens": (int, 1, None),
    "top_p": (float, 0.0, 1.0),
    "seed": (int, None, None),
}


def _validate_sampling(sampling: dict) -> dict:
    """Range/type check known sampling keys. bool is rejected for numeric keys.

    TOML parses `1` as an int and `1.0` as a float, so a float-typed param
    accepts either. bool is excluded even where int would pass.
    """
    for key, value in sampling.items():
        if key not in _SAMPLING_VALIDATORS:
            continue
        expected, low, high = _SAMPLING_VALIDATORS[key]
        # int is acceptable wherever float is expected: TOML ints and floats
        # are interchangeable for these params, and bool is an int subclass.
        accepted = (int, float) if expected is float else (int,)
        if isinstance(value, bool) or not isinstance(value, accepted):
            raise ValueError(
                f"llm.http.{key} must be {expected.__name__}, got {value!r}"
            )
        if low is not None and value < low:
            raise ValueError(f"llm.http.{key} must be >= {low}, got {value!r}")
        if high is not None and value > high:
            raise ValueError(f"llm.http.{key} must be <= {high}, got {value!r}")
    return dict(sampling)


class LLMBridge:
    def __init__(self, argv: list[str], timeout: int, retries: int):
        self.argv = argv
        self.timeout = timeout
        self.retries = retries

    def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
        last_error = None
        total_attempts = 0
        stdin = f"{system}\n\n{prompt}" if system else prompt

        for attempt in range(self.retries + 1):
            if attempt > 0:
                backoff = min(2 ** (attempt - 1), 30)
                time.sleep(backoff)

            total_attempts += 1
            start = time.perf_counter()

            try:
                proc = self._spawn()
            except FileNotFoundError:
                return BridgeResult(
                    ok=False,
                    raw="",
                    error=f"Command not found: {self.argv[0]}",
                    attempts=total_attempts,
                    latency_ms=0,
                )

            try:
                stdout, stderr = proc.communicate(input=stdin, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self._kill_process(proc)
                last_error = f"Timed out after {self.timeout}s"
                continue

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            if proc.returncode != 0:
                last_error = f"Exit code {proc.returncode}: {stderr.strip()[:200]}"
                continue

            if not stdout.strip():
                last_error = "Empty output"
                continue

            return BridgeResult(
                ok=True,
                raw=stdout,
                error=None,
                attempts=total_attempts,
                latency_ms=elapsed_ms,
            )

        return BridgeResult(
            ok=False,
            raw="",
            error=last_error,
            attempts=total_attempts,
            latency_ms=0,
        )

    def _spawn(self) -> subprocess.Popen:
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(self.argv, **kwargs)

    def _kill_process(self, proc: subprocess.Popen) -> None:
        try:
            if sys.platform == "win32":
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


class HTTPBridge:
    """Direct HTTP bridge to an OpenAI-compatible endpoint (no subprocess).

    Same public surface as LLMBridge: ask(prompt) -> BridgeResult.
    Retries transient failures (429/5xx, timeouts, connection errors) with
    exponential backoff; fails fast on client errors (401/400/404) and on
    malformed responses.

    Optional: sampling params, custom headers, and a real system message.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int,
        retries: int,
        sampling: dict | None = None,
        headers: dict | None = None,
        system_role: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.sampling = _validate_sampling(sampling or {})
        self.headers = dict(headers or {})
        self.system_role = system_role

    def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
        last_error = None
        total_attempts = 0

        for attempt in range(self.retries + 1):
            if attempt > 0:
                backoff = min(2 ** (attempt - 1), 30)
                time.sleep(backoff)

            total_attempts += 1
            start = time.perf_counter()

            try:
                raw = self._post(prompt, system)
            except _NonRetryableHTTPError as e:
                return BridgeResult(
                    ok=False,
                    raw="",
                    error=str(e),
                    attempts=total_attempts,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                )
            except _RetryableHTTPError as e:
                last_error = str(e)
                continue

            return BridgeResult(
                ok=True,
                raw=raw,
                error=None,
                attempts=total_attempts,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        return BridgeResult(
            ok=False,
            raw="",
            error=last_error,
            attempts=total_attempts,
            latency_ms=0,
        )

    def _build_payload(self, prompt: str, system: str | None = None) -> dict:
        """Build the request body. Pure — no I/O, so tests assert on this."""
        messages = []
        if self.system_role and system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {"model": self.model, "messages": messages, **self.sampling}

    def _build_headers(self) -> dict:
        headers = dict(self.headers)
        supplied = {k.lower() for k in headers}
        if self.api_key and "authorization" not in supplied and "api-key" not in supplied:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers["Content-Type"] = "application/json"
        return headers

    def _post(self, prompt: str, system: str | None = None) -> str:
        """Send one prompt and return the assistant text. Raises a typed HTTP error."""
        payload = json.dumps(self._build_payload(prompt, system)).encode("utf-8")

        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=payload,
            headers=self._build_headers(),
            method="POST",
        )

        try:
            response = self._open(request)
            data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in _RETRYABLE_STATUS:
                raise _RetryableHTTPError(f"HTTP {e.code}: {e.reason}") from e
            raise _NonRetryableHTTPError(f"HTTP {e.code}: {e.reason}") from e
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            json.JSONDecodeError,
        ) as e:
            raise _RetryableHTTPError(str(e)) from e

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise _NonRetryableHTTPError(f"Malformed response: {e}") from e
        if not isinstance(content, str) or not content.strip():
            raise _NonRetryableHTTPError("Empty or null message content")
        return content

    def _open(self, request: urllib.request.Request):
        """Call site for urlopen so tests can patch it."""
        return urllib.request.urlopen(request, timeout=self.timeout)
