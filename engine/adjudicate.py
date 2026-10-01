"""Adjudication: apply validated state requests to game state."""

from collections.abc import Callable

from dm.contract import FlagRequest, HpDeltaRequest, ItemRequest, MoveRequest, StateRequest
from engine.rules import Dice, damage_for
from engine.state import Event, GameState


def apply_requests(
    state: GameState,
    requests: list[StateRequest],
    dice: Dice,
) -> GameState:
    """Apply state requests to a copy of the game state.

    Invalid requests are silently dropped (the engine is the referee).
    Returns a new GameState; the input is not mutated.
    """
    s = state.clone()
    s.turn += 1

    for req in requests:
        if isinstance(req, MoveRequest):
            _apply_move(s, req)
        elif isinstance(req, ItemRequest):
            _apply_item(s, req)
        elif isinstance(req, HpDeltaRequest):
            _apply_hp_delta(s, req, dice)
        elif isinstance(req, FlagRequest):
            _apply_flag(s, req)

    return s


def _apply_move(s: GameState, req: MoveRequest) -> None:
    if req.to in s.rooms:
        s.player.location = req.to
        s.log.append(Event(turn=s.turn, type="move", detail=f"Moved to {req.to}"))
    else:
        s.log.append(Event(turn=s.turn, type="move", detail=f"Dropped: unknown room {req.to!r}"))


def _apply_item(s: GameState, req: ItemRequest) -> None:
    if req.op == "give_item":
        if req.item not in s.player.inventory:
            s.player.inventory.append(req.item)
            s.log.append(Event(turn=s.turn, type="item", detail=f"Received {req.item}"))
        else:
            s.log.append(Event(turn=s.turn, type="item", detail=f"Dropped: already have {req.item}"))
    elif req.op == "take_item":
        if req.item in s.player.inventory:
            s.player.inventory.remove(req.item)
            s.log.append(Event(turn=s.turn, type="item", detail=f"Lost {req.item}"))
        else:
            s.log.append(Event(turn=s.turn, type="item", detail=f"Dropped: don't have {req.item}"))


def _apply_hp_delta(s: GameState, req: HpDeltaRequest, dice: Dice) -> None:
    dmg = damage_for(req.severity, dice)
    s.player.hp = max(0, s.player.hp - dmg)
    s.log.append(Event(turn=s.turn, type="damage", detail=f"{req.reason} (-{dmg} HP)"))
    if s.player.hp <= 0:
        s.log.append(Event(turn=s.turn, type="death", detail="HP reached 0"))


def _apply_flag(s: GameState, req: FlagRequest) -> None:
    s.flags[req.key] = req.value
    s.log.append(Event(turn=s.turn, type="flag", detail=f"Set {req.key}={req.value}"))


def check_status(
    state: GameState,
    proposed: str,
    victory_condition: Callable[[GameState], bool] | None = None,
) -> str:
    """Validate the DM's proposed status.

    - Death is automatic when HP <= 0 (DM cannot prevent it).
    - Victory requires the victory_condition callback to return True.
    - Otherwise, returns 'ok'.
    """
    if state.player.hp <= 0:
        return "dead"
    if proposed == "victory":
        if victory_condition is not None and victory_condition(state):
            return "victory"
    return "ok"
