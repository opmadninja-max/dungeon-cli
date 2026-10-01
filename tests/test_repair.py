"""Tests for the DM response repair loop."""

import json
import pytest

from dm.bridge import BridgeResult, LLMBridge
from dm.contract import DMResponse, ContractError, parse
from dm.repair import FALLBACK, repair


def _valid_raw() -> str:
    return json.dumps({
        "narration": "A torch flickers on the wall. You hear dripping ahead.",
        "choices": ["Go left"],
        "state_requests": [],
        "status": "ok",
    })


class FakeBridge(LLMBridge):
    """A bridge that records calls and returns scripted responses."""

    def __init__(self, responses: list[BridgeResult]):
        self.responses = responses
        self.call_count = 0
        self.prompts: list[str] = []

    def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
        self.prompts.append(prompt)
        if self.call_count < len(self.responses):
            result = self.responses[self.call_count]
        else:
            result = BridgeResult(ok=False, raw="", error="No more scripted responses", attempts=1, latency_ms=0)
        self.call_count += 1
        return result


class TestRepairSucceeds:
    def test_repair_succeeds_second_attempt(self):
        invalid_raw = "{bad json"
        valid_raw = _valid_raw()
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=valid_raw, error=None, attempts=1, latency_ms=10),
        ])
        result = repair(invalid_raw, "Invalid JSON", bridge, max_attempts=2)
        assert isinstance(result, DMResponse)
        assert result is not FALLBACK
        assert result.status == "ok"
        assert bridge.call_count == 1

    def test_repair_succeeds_after_two_failures(self):
        invalid1 = "{bad"
        invalid2 = "{still bad"
        valid_raw = _valid_raw()
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=invalid1, error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=valid_raw, error=None, attempts=1, latency_ms=10),
        ])
        result = repair("{original error}", "error", bridge, max_attempts=2)
        assert isinstance(result, DMResponse)
        assert result.status == "ok"
        assert bridge.call_count == 2


class TestRepairFallback:
    def test_fallback_after_max_attempts(self):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw="{bad", error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw="{still bad", error=None, attempts=1, latency_ms=10),
        ])
        result = repair("{original}", "error", bridge, max_attempts=2)
        assert result is FALLBACK
        assert result.state_requests == []
        assert bridge.call_count == 2

    def test_fallback_on_bridge_failure(self):
        bridge = FakeBridge([
            BridgeResult(ok=False, raw="", error="timeout", attempts=1, latency_ms=0),
            BridgeResult(ok=False, raw="", error="timeout", attempts=1, latency_ms=0),
        ])
        result = repair("{original}", "error", bridge, max_attempts=2)
        assert result is FALLBACK


class TestRepairBridgeCalls:
    def test_total_calls_bounded(self):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw="{bad", error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw="{bad", error=None, attempts=1, latency_ms=10),
        ])
        result = repair("{original}", "error", bridge, max_attempts=2)
        assert bridge.call_count == 2
        assert result is FALLBACK

    def test_repair_prompt_includes_error(self):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=_valid_raw(), error=None, attempts=1, latency_ms=10),
        ])
        repair("{original}", "Invalid JSON: unexpected token", bridge, max_attempts=1)
        assert "Invalid JSON: unexpected token" in bridge.prompts[0]
