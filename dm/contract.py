"""DM response contract: dataclasses and strict parser."""

import json
import re
from dataclasses import dataclass, field
from typing import Any


class ContractError(Exception):
    pass


@dataclass
class MoveRequest:
    op: str = "move"
    to: str = ""


@dataclass
class ItemRequest:
    op: str = "give_item"
    item: str = ""


@dataclass
class HpDeltaRequest:
    op: str = "hp_delta"
    severity: str = "minor"
    reason: str = ""


@dataclass
class FlagRequest:
    op: str = "set_flag"
    key: str = ""
    value: Any = True


StateRequest = MoveRequest | ItemRequest | HpDeltaRequest | FlagRequest

VALID_OPS = {"move", "give_item", "take_item", "hp_delta", "set_flag"}
VALID_STATUSES = {"ok", "dead", "victory"}
VALID_SEVERITIES = {"minor", "major", "critical"}


@dataclass
class DMResponse:
    narration: str = ""
    choices: list[str] = field(default_factory=list)
    state_requests: list[StateRequest] = field(default_factory=list)
    status: str = "ok"


def _strip_markdown_fences(raw: str) -> str:
    """Strip ```json ... ``` fences if present."""
    pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    match = re.match(pattern, raw.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw.strip()


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on sentence-ending punctuation."""
    sentences = re.split(r'[.!?]+', text)
    return len([s for s in sentences if s.strip()])


def _parse_request(req: dict) -> StateRequest:
    op = req.get("op")
    if op not in VALID_OPS:
        raise ContractError(f"Unknown op: {op!r}")

    if op == "move":
        to = req.get("to")
        if not to or not isinstance(to, str):
            raise ContractError("move request requires non-empty 'to' field")
        return MoveRequest(op=op, to=to)

    if op in ("give_item", "take_item"):
        item = req.get("item")
        if not item or not isinstance(item, str):
            raise ContractError(f"{op} request requires non-empty 'item' field")
        return ItemRequest(op=op, item=item)

    if op == "hp_delta":
        severity = req.get("severity", "minor")
        if severity not in VALID_SEVERITIES:
            raise ContractError(f"Invalid severity: {severity!r}")
        reason = req.get("reason", "")
        if not isinstance(reason, str):
            raise ContractError("hp_delta 'reason' must be a string")
        return HpDeltaRequest(op=op, severity=severity, reason=reason)

    if op == "set_flag":
        key = req.get("key")
        if not key or not isinstance(key, str):
            raise ContractError("set_flag request requires non-empty 'key' field")
        return FlagRequest(op=op, key=key, value=req.get("value", True))

    raise ContractError(f"Unhandled op: {op!r}")


def parse(raw: str) -> DMResponse:
    """Parse raw JSON string into a validated DMResponse."""
    text = _strip_markdown_fences(raw)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ContractError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise ContractError("Expected a JSON object")

    narration = data.get("narration")
    if not isinstance(narration, str):
        raise ContractError("'narration' must be a string")

    sentence_count = _count_sentences(narration)
    if sentence_count < 2:
        raise ContractError(f"Narration too short: {sentence_count} sentences (min 2)")
    if sentence_count > 6:
        raise ContractError(f"Narration too long: {sentence_count} sentences (max 6)")

    choices = data.get("choices", [])
    if not isinstance(choices, list):
        raise ContractError("'choices' must be a list")
    if len(choices) > 3:
        raise ContractError(f"Too many choices: {len(choices)} (max 3)")
    for i, c in enumerate(choices):
        if not isinstance(c, str) or not c.strip():
            raise ContractError(f"Choice {i} must be a non-empty string")

    status = data.get("status", "ok")
    if status not in VALID_STATUSES:
        raise ContractError(f"Invalid status: {status!r}")

    raw_requests = data.get("state_requests", [])
    if not isinstance(raw_requests, list):
        raise ContractError("'state_requests' must be a list")

    state_requests = []
    for i, req in enumerate(raw_requests):
        if not isinstance(req, dict):
            raise ContractError(f"State request {i} must be an object")
        try:
            state_requests.append(_parse_request(req))
        except ContractError as e:
            raise ContractError(f"State request {i}: {e}")

    return DMResponse(
        narration=narration,
        choices=choices,
        state_requests=state_requests,
        status=status,
    )
