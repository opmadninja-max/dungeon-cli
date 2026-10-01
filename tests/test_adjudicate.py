"""Tests for the adjudication engine."""

import pytest

from dm.contract import FlagRequest, HpDeltaRequest, ItemRequest, MoveRequest
from engine.adjudicate import apply_requests, check_status
from engine.rules import Dice
from engine.state import GameState, Player, Room


def _make_state(**overrides) -> GameState:
    player = Player(name="Hero", hp=20, max_hp=20, inventory=["torch"], location="hall")
    rooms = {
        "hall": Room(id="hall", name="Great Hall", description="A vast hall"),
        "crypt": Room(id="crypt", name="Crypt", description="Dark and cold"),
    }
    return GameState(
        player=player,
        rooms=rooms,
        flags={},
        turn=0,
        **overrides,
    )


class TestMove:
    def test_valid_move(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [MoveRequest(to="crypt")], dice)
        assert result.player.location == "crypt"
        assert result.log[-1].type == "move"

    def test_invalid_room_dropped(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [MoveRequest(to="nonexistent")], dice)
        assert result.player.location == "hall"
        assert "Dropped" in result.log[-1].detail


class TestItems:
    def test_give_item(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [ItemRequest(op="give_item", item="key")], dice)
        assert "key" in result.player.inventory

    def test_give_duplicate_not_added(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [ItemRequest(op="give_item", item="torch")], dice)
        assert result.player.inventory.count("torch") == 1

    def test_take_item(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [ItemRequest(op="take_item", item="torch")], dice)
        assert "torch" not in result.player.inventory

    def test_take_not_held_dropped(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [ItemRequest(op="take_item", item="key")], dice)
        assert "key" not in result.player.inventory
        assert "Dropped" in result.log[-1].detail


class TestHpDelta:
    def test_minor_damage(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(
            state,
            [HpDeltaRequest(severity="minor", reason="trap")],
            dice,
        )
        assert result.player.hp < 20
        assert result.player.hp >= 16  # max 4 damage

    def test_hp_clamps_at_zero(self):
        state = _make_state()
        state.player.hp = 1
        dice = Dice(seed=1)
        # Apply multiple times to guarantee hitting 0
        for _ in range(5):
            state = apply_requests(
                state,
                [HpDeltaRequest(severity="critical", reason="big hit")],
                dice,
            )
        assert state.player.hp == 0

    def test_death_at_zero(self):
        state = _make_state()
        state.player.hp = 1
        dice = Dice(seed=1)
        result = apply_requests(
            state,
            [HpDeltaRequest(severity="critical", reason="fatal blow")],
            dice,
        )
        assert result.player.hp == 0
        assert any(e.type == "death" for e in result.log)


class TestFlags:
    def test_set_flag(self):
        state = _make_state()
        dice = Dice(seed=1)
        result = apply_requests(state, [FlagRequest(key="door_open", value=True)], dice)
        assert result.flags["door_open"] is True


class TestCheckStatus:
    def test_dead_when_hp_zero(self):
        state = _make_state()
        state.player.hp = 0
        assert check_status(state, "ok") == "dead"

    def test_victory_requires_condition(self):
        state = _make_state()
        assert check_status(state, "victory") == "ok"

    def test_victory_with_condition_met(self):
        state = _make_state()
        state.flags["has_amulet"] = True
        condition = lambda s: s.flags.get("has_amulet", False)
        assert check_status(state, "victory", victory_condition=condition) == "victory"

    def test_death_overrides_dm_ok(self):
        state = _make_state()
        state.player.hp = 0
        assert check_status(state, "ok") == "dead"

    def test_death_overrides_dm_victory(self):
        state = _make_state()
        state.player.hp = 0
        condition = lambda s: True
        assert check_status(state, "victory", victory_condition=condition) == "dead"

    def test_ok_status_normal(self):
        state = _make_state()
        assert check_status(state, "ok") == "ok"


class TestScriptedGame:
    def test_3_turn_game(self):
        state = _make_state()
        dice = Dice(seed=42)

        # Turn 1: move to crypt
        state = apply_requests(state, [MoveRequest(to="crypt")], dice)
        assert state.player.location == "crypt"
        assert state.turn == 1

        # Turn 2: take damage
        state = apply_requests(
            state,
            [HpDeltaRequest(severity="minor", reason="trap")],
            dice,
        )
        assert state.player.hp < 20
        assert state.turn == 2

        # Turn 3: give item
        state = apply_requests(state, [ItemRequest(op="give_item", item="key")], dice)
        assert "key" in state.player.inventory
        assert state.turn == 3
