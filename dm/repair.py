"""DM response repair loop: self-healing parser with fallback."""

from dm.bridge import LLMBridge
from dm.contract import DMResponse, ContractError, parse
from ui.telemetry import Telemetry

REPAIR_TEMPLATE = """Your previous response was invalid because: {error}

Return a corrected JSON object only. No markdown, no commentary.

The response must be an object with exactly these keys:
  "narration": 2-6 sentences, second person, present tense
  "choices": up to 3 short suggested actions
  "state_requests": list of ops (may be empty)
  "status": "ok" | "dead" | "victory"

Every element of state_requests must be an object with an "op" key, and "op" must
be exactly one of:
  {{"op": "move",      "to": "<room_id>"}}
  {{"op": "give_item", "item": "<item name>"}}
  {{"op": "take_item", "item": "<item name>"}}
  {{"op": "hp_delta",  "severity": "minor|major|critical", "reason": "<why>"}}
  {{"op": "set_flag",  "key": "<short_snake_case_key>", "value": true}}
Use "op", never "type". No other op exists; inventing one invalidates the response.
Never invent a damage number — the engine rolls the dice from the severity.

Your previous (invalid) response was:
{raw}"""

FALLBACK = DMResponse(
    narration=(
        "The shadows swirl and shift. You pause, uncertain what happened. "
        "The adventure continues."
    ),
    choices=["Look around", "Continue forward", "Check your belongings"],
    state_requests=[],
    status="ok",
)


def repair(
    raw: str,
    error: str,
    bridge: LLMBridge,
    max_attempts: int = 2,
    telemetry: Telemetry | None = None,
) -> DMResponse:
    """Attempt to repair an invalid DM response by re-prompting the model.

    Returns a valid DMResponse or the fallback if all repair attempts fail.
    Total bridge calls: max_attempts (not counting the original call).
    """
    current_raw = raw

    for attempt in range(max_attempts):
        if telemetry:
            telemetry.record_repair()
        prompt = REPAIR_TEMPLATE.format(error=error, raw=current_raw)
        result = bridge.ask(prompt)

        if not result.ok:
            error = f"Bridge failure: {result.error}"
            continue

        try:
            return parse(result.raw)
        except ContractError as e:
            error = str(e)
            current_raw = result.raw

    if telemetry:
        telemetry.record_fallback()
    return FALLBACK
