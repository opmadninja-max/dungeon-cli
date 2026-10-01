"""Tests for the LLM bridge."""

import io
import json
import os
import sys
import tempfile
import urllib.error
from unittest.mock import patch

import pytest

from dm.bridge import LLMBridge

FAKE_LLM = [sys.executable, "tests/fakes/fake_llm.py"]
FAKE_LLM_RETRY = [sys.executable, "tests/fakes/fake_llm_retry.py"]


def _env(mode: str) -> dict:
    env = os.environ.copy()
    env["FAKE_MODE"] = mode
    return env


class TestBridgeHappyPath:
    def test_ok_true_with_output(self, monkeypatch):
        monkeypatch.setenv("FAKE_MODE", "happy")
        bridge = LLMBridge(FAKE_LLM, timeout=10, retries=0)
        result = bridge.ask("hello")
        assert result.ok is True
        assert '{"ok": true}' in result.raw
        assert result.error is None
        assert result.attempts == 1

    def test_latency_recorded(self, monkeypatch):
        monkeypatch.setenv("FAKE_MODE", "happy")
        bridge = LLMBridge(FAKE_LLM, timeout=10, retries=0)
        result = bridge.ask("hello")
        assert result.latency_ms > 0


class TestBridgeCommandNotFound:
    def test_immediate_fail_no_retry(self):
        bridge = LLMBridge(["nonexistent_command_xyz"], timeout=5, retries=2)
        result = bridge.ask("hello")
        assert result.ok is False
        assert "not found" in result.error.lower()
        assert result.attempts == 1


class TestBridgeExitCode:
    def test_retry_then_succeed(self, monkeypatch, tmp_path):
        counter = tmp_path / "counter"
        monkeypatch.setenv("FAKE_COUNTER_FILE", str(counter))
        monkeypatch.setenv("FAKE_FAILURES", "2")
        bridge = LLMBridge(FAKE_LLM_RETRY, timeout=10, retries=3)
        result = bridge.ask("hello")
        assert result.ok is True
        assert result.attempts == 3

    def test_all_retries_exhausted(self, monkeypatch, tmp_path):
        counter = tmp_path / "counter"
        monkeypatch.setenv("FAKE_COUNTER_FILE", str(counter))
        monkeypatch.setenv("FAKE_FAILURES", "10")
        bridge = LLMBridge(FAKE_LLM_RETRY, timeout=10, retries=2)
        result = bridge.ask("hello")
        assert result.ok is False
        assert result.attempts == 3
        assert "Exit code" in result.error


class TestBridgeTimeout:
    def test_timeout_returns_failure(self, monkeypatch):
        monkeypatch.setenv("FAKE_MODE", "hang")
        bridge = LLMBridge(FAKE_LLM, timeout=1, retries=0)
        result = bridge.ask("hello")
        assert result.ok is False
        assert "Timed out" in result.error


class TestBridgeEmptyOutput:
    def test_empty_retried_then_fails(self, monkeypatch):
        monkeypatch.setenv("FAKE_MODE", "empty")
        bridge = LLMBridge(FAKE_LLM, timeout=10, retries=1)
        result = bridge.ask("hello")
        assert result.ok is False
        assert "Empty" in result.error
        assert result.attempts == 2


class TestBridgeGarbageOutput:
    def test_garbage_is_ok(self, monkeypatch):
        monkeypatch.setenv("FAKE_MODE", "garbage")
        bridge = LLMBridge(FAKE_LLM, timeout=10, retries=0)
        result = bridge.ask("hello")
        assert result.ok is True
        assert "not json" in result.raw


# --- HTTPBridge tests (BUG-009-adjacent: native HTTP provider mode) ---


def _fake_response(body: dict):
    """A context-manager fake for urllib.request.urlopen returning JSON bytes."""
    raw = json.dumps(body).encode()

    class _Resp:
        def read(self):
            return raw

        def __enter__(selfself):
            return selfself

        def __exit__(selfself, *a):
            return False

    return _Resp()


def _http_error(status: int):
    return urllib.error.HTTPError(
        url="https://example.test/v1/chat/completions",
        code=status,
        msg="boom",
        hdrs={},
        fp=io.BytesIO(b""),
    )


class TestHTTPBridge:
    """T1-T6: HTTPBridge.ask retry/fail-fast/latency behavior."""

    def test_t1_success(self):
        from dm.bridge import HTTPBridge

        bridge = HTTPBridge(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout=10,
            retries=2,
        )
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_response({"choices": [{"message": {"content": "You see a door."}}]}),
        ):
            result = bridge.ask("look around")
        assert result.ok is True
        assert result.raw == "You see a door."
        assert result.attempts == 1
        assert result.latency_ms >= 0

    def test_t2_retry_then_success(self):
        from dm.bridge import HTTPBridge

        bridge = HTTPBridge(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout=10,
            retries=2,
        )
        responses = [_http_error(503), _http_error(503)]
        success = _fake_response({"choices": [{"message": {"content": "ok"}}]})

        def side_effect(*a, **k):
            if responses:
                raise responses.pop(0)
            return success

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = bridge.ask("go")
        assert result.ok is True
        assert result.attempts == 3

    def test_t3_retry_exhausted(self):
        from dm.bridge import HTTPBridge

        bridge = HTTPBridge(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout=10,
            retries=1,
        )
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.attempts == 2
        assert "500" in result.error

    def test_t4_fail_fast_401(self):
        from dm.bridge import HTTPBridge

        bridge = HTTPBridge(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout=10,
            retries=2,
        )
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.attempts == 1
        assert "401" in result.error

    def test_t5_fail_fast_malformed(self):
        from dm.bridge import HTTPBridge

        bridge = HTTPBridge(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout=10,
            retries=2,
        )
        with patch("urllib.request.urlopen", return_value=_fake_response({"choices": []})):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.attempts == 1

    def test_t6_timeout_retried(self):
        from dm.bridge import HTTPBridge

        bridge = HTTPBridge(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-test",
            timeout=10,
            retries=1,
        )
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.attempts == 2


class TestMakeBridgeDispatch:
    """T7-T9: make_bridge selects the right bridge and resolves the api key."""

    def test_t7_dispatch_http(self):
        from dm.bridge import HTTPBridge

        config = {
            "llm": {
                "provider": "http",
                "model": "gpt-test",
                "timeout": 10,
                "retries": 1,
                "http": {"base_url": "https://example.test/v1", "api_key": "sk-test"},
            }
        }
        import cli

        bridge = cli.make_bridge(config)
        assert isinstance(bridge, HTTPBridge)

    def test_t8_dispatch_subprocess_default(self):
        from dm.bridge import LLMBridge

        config = {"llm": {"argv": ["llm"], "timeout": 10, "retries": 1}}
        import cli

        bridge = cli.make_bridge(config)
        assert isinstance(bridge, LLMBridge)

    def test_t9_env_api_key_fallback(self, monkeypatch):
        from dm.bridge import HTTPBridge

        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
        config = {
            "llm": {
                "provider": "http",
                "model": "gpt-test",
                "timeout": 10,
                "retries": 1,
                "http": {"base_url": "https://example.test/v1"},
            }
        }
        import cli

        bridge = cli.make_bridge(config)
        assert isinstance(bridge, HTTPBridge)
        assert bridge.api_key == "sk-from-env"


# --- sampling params, system role, custom headers ---


def _bridge(**kwargs):
    from dm.bridge import HTTPBridge

    base = {
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-test",
        "timeout": 10,
        "retries": 2,
    }
    base.update(kwargs)
    return HTTPBridge(**base)


class TestSamplingParams:
    def test_each_known_key_lands_in_payload(self):
        bridge = _bridge(
            sampling={"temperature": 0.9, "max_tokens": 800, "top_p": 0.95, "seed": 42}
        )
        payload = bridge._build_payload("hello")
        assert payload["temperature"] == 0.9
        assert payload["max_tokens"] == 800
        assert payload["top_p"] == 0.95
        assert payload["seed"] == 42

    def test_unset_keys_are_omitted_not_null(self):
        """Absent keys must not be sent as null — some providers reject that."""
        payload = _bridge()._build_payload("hello")
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            assert key not in payload

    def test_partial_sampling_only_sends_what_was_set(self):
        payload = _bridge(sampling={"temperature": 0.1})._build_payload("hello")
        assert payload["temperature"] == 0.1
        assert "max_tokens" not in payload

    def test_wrong_type_raises_naming_the_key(self):
        with pytest.raises(ValueError, match="temperature"):
            _bridge(sampling={"temperature": "hot"})
        with pytest.raises(ValueError, match="max_tokens"):
            _bridge(sampling={"max_tokens": 12.5})

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError, match="top_p"):
            _bridge(sampling={"top_p": 1.5})
        with pytest.raises(ValueError, match="max_tokens"):
            _bridge(sampling={"max_tokens": 0})
        with pytest.raises(ValueError, match="temperature"):
            _bridge(sampling={"temperature": 3.0})

    def test_bool_rejected_for_numeric_keys(self):
        """bool is a subclass of int, so seed=True would slip through a naive check."""
        with pytest.raises(ValueError, match="seed"):
            _bridge(sampling={"seed": True})
        with pytest.raises(ValueError, match="temperature"):
            _bridge(sampling={"temperature": True})

    def test_unknown_key_passes_through_unvalidated(self):
        """Provider-specific params must work before we know about them."""
        payload = _bridge(sampling={"repetition_penalty": 1.1})._build_payload("hi")
        assert payload["repetition_penalty"] == 1.1

    def test_int_accepted_where_float_expected(self):
        """TOML `temperature = 1` and `top_p = 0` are legal and must not be rejected."""
        payload = _bridge(sampling={"temperature": 1, "top_p": 0})._build_payload("hi")
        assert payload["temperature"] == 1
        assert payload["top_p"] == 0


class TestSystemRole:
    def test_default_sends_single_user_message(self):
        payload = _bridge()._build_payload("hello", "You are the DM.")
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "hello"

    def test_system_role_true_splits_messages(self):
        bridge = _bridge(system_role=True)
        payload = bridge._build_payload("=== WORLD ===\nx", "You are the DM.")
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        assert payload["messages"][0]["content"] == "You are the DM."
        assert payload["messages"][1]["content"] == "=== WORLD ===\nx"

    def test_system_role_true_but_no_system_stays_single_message(self):
        bridge = _bridge(system_role=True)
        payload = bridge._build_payload("hello", None)
        assert len(payload["messages"]) == 1


class TestSplitSystem:
    def test_splits_system_from_remainder(self):
        from dm.prompt import split_system

        prompt = "=== SYSTEM ===\nBe a DM.\n\n=== WORLD ===\nDark.\n\n=== PLAYER ACTION ===\nlook"
        system, remainder = split_system(prompt)
        assert system == "Be a DM."
        assert remainder == "=== WORLD ===\nDark.\n\n=== PLAYER ACTION ===\nlook"
        assert "=== SYSTEM ===" not in remainder

    def test_system_only_prompt_falls_back_to_single_message(self):
        from dm.prompt import split_system

        system, remainder = split_system("=== SYSTEM ===\nBe a DM.")
        assert system == ""
        assert remainder == "=== SYSTEM ===\nBe a DM."

    def test_headerless_prompt_falls_back_to_single_message(self):
        from dm.prompt import split_system

        system, remainder = split_system("just a bare prompt")
        assert system == ""
        assert remainder == "just a bare prompt"

    def test_empty_prompt(self):
        from dm.prompt import split_system

        assert split_system("") == ("", "")

    def test_roundtrips_a_real_build_turn_prompt(self):
        from pathlib import Path

        from dm.prompt import PromptContext, build_turn, split_system
        from engine.campaign import build_initial_state, load_campaign
        from ui.character_creation import _build_context

        campaign = load_campaign(Path("content/station_nine.json"))
        state = build_initial_state(campaign, campaign.archetypes[0], "Tester")
        context = _build_context(campaign, "Tester", campaign.archetypes[0])
        prompt = build_turn("look around", state, context, 8000, 5)
        system, remainder = split_system(prompt)
        assert "Dungeon Master" in system
        assert "=== WORLD ===" in remainder
        assert "=== SYSTEM ===" not in remainder


class TestCustomHeaders:
    def test_headers_merged_into_request(self):
        bridge = _bridge(headers={"HTTP-Referer": "https://my.game", "X-Title": "dungeon-cli"})
        headers = bridge._build_headers()
        assert headers["HTTP-Referer"] == "https://my.game"
        assert headers["X-Title"] == "dungeon-cli"
        assert headers["Authorization"] == "Bearer sk-test"

    def test_explicit_api_key_header_suppresses_bearer(self):
        """Azure authenticates with an api-key header, not Bearer."""
        bridge = _bridge(headers={"api-key": "azure-secret"})
        headers = bridge._build_headers()
        assert headers["api-key"] == "azure-secret"
        assert "Authorization" not in headers

    def test_explicit_authorization_header_suppresses_bearer(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        bridge = _bridge(api_key="", headers={"Authorization": "Bearer custom"})
        assert bridge._build_headers()["Authorization"] == "Bearer custom"

    def test_no_api_key_means_no_authorization_header(self, monkeypatch):
        """Today we always send 'Bearer ' with an empty value, which is wrong."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        bridge = _bridge(api_key="")
        assert "Authorization" not in bridge._build_headers()

    def test_content_type_always_set(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        bridge = _bridge(api_key="", headers={"X-Title": "dungeon-cli"})
        assert bridge._build_headers()["Content-Type"] == "application/json"


class TestEmptyContentGuard:
    """Regression: a provider content filter returns 200 with content: null.

    Previously _post returned BridgeResult(ok=True, raw=None), which raised
    TypeError downstream instead of taking the repair -> FALLBACK path.
    """

    def test_null_content_fails_fast_without_retry(self):
        bridge = _bridge(retries=3)
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_response({"choices": [{"message": {"content": None}}]}),
        ):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.attempts == 1
        assert "null" in result.error.lower()

    def test_empty_string_content_fails_fast(self):
        bridge = _bridge(retries=3)
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_response({"choices": [{"message": {"content": "   "}}]}),
        ):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.attempts == 1

    def test_non_string_content_fails_fast(self):
        bridge = _bridge(retries=1)
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_response({"choices": [{"message": {"content": {"text": "hi"}}}]}),
        ):
            result = bridge.ask("go")
        assert result.ok is False
        assert result.raw == ""

    def test_null_content_does_not_raise_typeerror(self):
        """The whole point: no TypeError escapes, the bridge reports failure."""
        bridge = _bridge(retries=1)
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_response({"choices": [{"message": {"content": None}}]}),
        ):
            result = bridge.ask("go")
        assert result.raw == ""
        assert isinstance(result.raw, str)


class TestNullContentFallsBackThroughRepair:
    def test_null_content_ends_in_fallback_not_crash(self):
        """A real endpoint content-filtering us must land on FALLBACK."""
        from dm.bridge import BridgeResult
        from dm.repair import FALLBACK, repair

        class NullContentBridge(LLMBridge):
            def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
                return BridgeResult(
                    ok=False, raw="", error="Empty or null message content", attempts=1, latency_ms=5
                )

        result = repair("some raw", "Invalid JSON", NullContentBridge(["fake"], 1, 0), max_attempts=2)
        assert result is FALLBACK


class TestLLMBridgeSystemArg:
    def test_system_prepended_to_stdin(self, monkeypatch):
        """Subprocess mode has no message structure, so system goes into the blob."""
        captured = {}

        class FakeProc:
            returncode = 0
            pid = 1

            def communicate(self, input=None, timeout=None):
                captured["stdin"] = input
                return "OK", ""

        bridge = LLMBridge(FAKE_LLM, timeout=10, retries=0)
        monkeypatch.setattr(bridge, "_spawn", lambda: FakeProc())
        result = bridge.ask("go north", "You are the DM.")
        assert result.ok is True
        assert captured["stdin"] == "You are the DM.\n\ngo north"

    def test_no_system_leaves_prompt_unchanged(self, monkeypatch):
        captured = {}

        class FakeProc:
            returncode = 0
            pid = 1

            def communicate(self, input=None, timeout=None):
                captured["stdin"] = input
                return "OK", ""

        bridge = LLMBridge(FAKE_LLM, timeout=10, retries=0)
        monkeypatch.setattr(bridge, "_spawn", lambda: FakeProc())
        bridge.ask("go north")
        assert captured["stdin"] == "go north"


class TestMakeBridgeWiring:
    def test_forwards_sampling_headers_and_system_role(self):
        from dm.bridge import HTTPBridge

        config = {
            "llm": {
                "provider": "http",
                "model": "gpt-test",
                "system_role": True,
                "timeout": 10,
                "retries": 1,
                "http": {
                    "base_url": "https://example.test/v1",
                    "api_key": "sk-test",
                    "temperature": 0.7,
                    "max_tokens": 500,
                    "headers": {"X-Title": "dungeon-cli"},
                },
            }
        }
        import cli

        bridge = cli.make_bridge(config)
        assert isinstance(bridge, HTTPBridge)
        assert bridge.system_role is True
        assert bridge.sampling == {"temperature": 0.7, "max_tokens": 500}
        assert bridge.headers == {"X-Title": "dungeon-cli"}
        assert bridge._build_headers()["X-Title"] == "dungeon-cli"

    def test_default_config_sends_no_sampling_keys(self):
        from dm.bridge import HTTPBridge

        config = {
            "llm": {
                "provider": "http",
                "model": "gpt-test",
                "http": {"base_url": "https://example.test/v1"},
            }
        }
        import cli

        bridge = cli.make_bridge(config)
        assert bridge.sampling == {}
        assert bridge.system_role is False
        assert "Authorization" not in bridge._build_headers()

    def test_invalid_sampling_raises_at_construction(self):
        """Bad config should fail at startup, not at the first turn."""
        config = {
            "llm": {
                "provider": "http",
                "model": "gpt-test",
                "http": {"base_url": "https://example.test/v1", "temperature": 99},
            }
        }
        import cli

        with pytest.raises(ValueError, match="temperature"):
            cli.make_bridge(config)
