# Architecture Decisions

This document records one-line architecture decisions made during development.

## HTTP bridge

- `system_role` defaults to `false`, so the request body is byte-identical to the
  pre-flag format and existing endpoints keep working. Enable it only for models
  that require a real system message (`o1`, `o3`, `gpt-5`).
- Unset sampling keys are **omitted** from the request body, never sent as `null`.
  Some providers reject an explicit null; sending nothing is universally safe.
- `temperature` and `top_p` accept an int where a float is expected, because TOML
  parses `1` as an int and `0` is a legal value for both. `bool` is rejected for
  every numeric key, since `bool` is a subclass of `int` in Python.
- Unknown sampling keys are forwarded verbatim and unvalidated, so provider-specific
  parameters work without a code change.
- Sampling values are validated in `HTTPBridge.__init__`, not at request time, so a
  bad config fails at startup with a message naming the key rather than as a
  confusing HTTP error on turn one.
- `Authorization: Bearer` is omitted entirely when no api_key is available, rather
  than sent with an empty value. Supplying `api-key` or `Authorization` in
  `[llm.http.headers]` suppresses the automatic header.
- An empty or `null` message content is treated as a **non-retryable** error, matching
  the existing malformed-response handling. A provider content filter returns HTTP
  200 with `content: null`; without this guard that surfaced downstream as a
  `TypeError` instead of taking the repair → `FALLBACK` path.
- The system prompt is split with a pure `split_system()` helper rather than by
  changing `build_turn()`'s signature, so the ~14 existing prompt tests stay valid.
- `compact()` calls `ask()` without a system argument — the summarizer prompt is
  self-contained. It inherits the bridge's temperature, which is not ideal for
  summarization but is not worth a per-call override.
- `LLMBridge.ask()` gained an optional `system` argument that is prepended to the
  stdin blob, since subprocess mode has no message structure to put it in.

## Testing

- New bridge behavior is tested against `_build_payload` / `_build_headers`, which are
  pure, rather than through `urllib`. Network plumbing is only exercised where the
  retry and fail-fast logic is the thing under test.
- New `HTTPBridge` constructor parameters are keyword-defaulted so existing test
  constructions keep working unmodified.
