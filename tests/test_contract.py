"""Tests for the DM response contract parser."""

import json
import pytest

from dm.contract import (
    ContractError,
    DMResponse,
    FlagRequest,
    HpDeltaRequest,
    ItemRequest,
    MoveRequest,
    parse,
)


def _make_raw(**overrides) -> str:
    """Build a valid raw JSON string with optional overrides."""
    data = {
        "narration": "A torch flickers on the wall. You hear dripping ahead.",
        "choices": ["Go left", "Go right"],
        "state_requests": [],
        "status": "ok",
    }
    data.update(overrides)
    return json.dumps(data)


class TestValidResponses:
    def test_valid_complete_json(self):
        raw = _make_raw(
            state_requests=[
                {"op": "move", "to": "hallway"},
                {"op": "give_item", "item": "rusty_key"},
                {"op": "hp_delta", "severity": "minor", "reason": "trap"},
                {"op": "set_flag", "key": "met_ghost", "value": True},
            ]
        )
        resp = parse(raw)
        assert resp.narration == "A torch flickers on the wall. You hear dripping ahead."
        assert resp.choices == ["Go left", "Go right"]
        assert resp.status == "ok"
        assert len(resp.state_requests) == 4
        assert isinstance(resp.state_requests[0], MoveRequest)
        assert resp.state_requests[0].to == "hallway"
        assert isinstance(resp.state_requests[1], ItemRequest)
        assert resp.state_requests[1].item == "rusty_key"
        assert isinstance(resp.state_requests[2], HpDeltaRequest)
        assert resp.state_requests[2].severity == "minor"
        assert isinstance(resp.state_requests[3], FlagRequest)
        assert resp.state_requests[3].key == "met_ghost"

    def test_valid_minimal(self):
        raw = json.dumps({
            "narration": "You see a door. It is locked.",
            "status": "ok",
        })
        resp = parse(raw)
        assert resp.choices == []
        assert resp.state_requests == []

    def test_markdown_wrapped_json(self):
        raw = "```json\n" + _make_raw() + "\n```"
        resp = parse(raw)
        assert resp.status == "ok"

    def test_markdown_wrapped_no_lang(self):
        raw = "```\n" + _make_raw() + "\n```"
        resp = parse(raw)
        assert resp.status == "ok"


class TestMalformedJson:
    def test_invalid_json(self):
        with pytest.raises(ContractError, match="Invalid JSON"):
            parse("{invalid")

    def test_not_an_object(self):
        with pytest.raises(ContractError, match="JSON object"):
            parse("[1, 2, 3]")

    def test_empty_string(self):
        with pytest.raises(ContractError, match="Invalid JSON"):
            parse("")


class TestNarrationValidation:
    def test_wrong_type(self):
        raw = _make_raw(narration=42)
        with pytest.raises(ContractError, match="must be a string"):
            parse(raw)

    def test_too_short(self):
        raw = _make_raw(narration="Just one sentence.")
        with pytest.raises(ContractError, match="too short"):
            parse(raw)

    def test_too_long(self):
        raw = _make_raw(
            narration=(
                "One. Two. Three. Four. Five. Six. Seven."
            )
        )
        with pytest.raises(ContractError, match="too long"):
            parse(raw)


class TestChoicesValidation:
    def test_too_many(self):
        raw = _make_raw(choices=["a", "b", "c", "d"])
        with pytest.raises(ContractError, match="Too many"):
            parse(raw)

    def test_not_strings(self):
        raw = _make_raw(choices=[1, 2, 3])
        with pytest.raises(ContractError, match="non-empty string"):
            parse(raw)

    def test_empty_string_choice(self):
        raw = _make_raw(choices=["valid", ""])
        with pytest.raises(ContractError, match="non-empty string"):
            parse(raw)


class TestStatusValidation:
    def test_invalid_status(self):
        raw = _make_raw(status="win")
        with pytest.raises(ContractError, match="Invalid status"):
            parse(raw)


class TestStateRequestValidation:
    def test_unknown_op(self):
        raw = _make_raw(state_requests=[{"op": "fly"}])
        with pytest.raises(ContractError, match="Unknown op"):
            parse(raw)

    def test_move_missing_to(self):
        raw = _make_raw(state_requests=[{"op": "move"}])
        with pytest.raises(ContractError, match="non-empty 'to'"):
            parse(raw)

    def test_give_item_missing_item(self):
        raw = _make_raw(state_requests=[{"op": "give_item"}])
        with pytest.raises(ContractError, match="non-empty 'item'"):
            parse(raw)

    def test_take_item_missing_item(self):
        raw = _make_raw(state_requests=[{"op": "take_item"}])
        with pytest.raises(ContractError, match="non-empty 'item'"):
            parse(raw)

    def test_hp_delta_invalid_severity(self):
        raw = _make_raw(state_requests=[{"op": "hp_delta", "severity": "extreme"}])
        with pytest.raises(ContractError, match="Invalid severity"):
            parse(raw)

    def test_set_flag_missing_key(self):
        raw = _make_raw(state_requests=[{"op": "set_flag"}])
        with pytest.raises(ContractError, match="non-empty 'key'"):
            parse(raw)

    def test_request_not_object(self):
        raw = _make_raw(state_requests=["not a dict"])
        with pytest.raises(ContractError, match="must be an object"):
            parse(raw)
