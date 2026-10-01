"""Tests for campaigns and character creation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dm.bridge import BridgeResult, LLMBridge
from dm.prompt import build_turn
from engine.campaign import (
    Archetype,
    Campaign,
    build_initial_state,
    list_campaigns,
    load_campaign,
    make_victory_condition,
    validate_campaign,
)
from engine.state import GameState, Room
from ui import character_creation


def _valid_campaign_data():
    return {
        "id": "test_campaign",
        "title": "Test Campaign",
        "genre": "fantasy",
        "world_seed": "A test world.",
        "goal": "Reach the end.",
        "victory_room": "end",
        "starting_room": "start",
        "rooms": [
            {"id": "start", "name": "Start", "description": "The beginning."},
            {"id": "end", "name": "End", "description": "The end."},
        ],
        "archetypes": [
            {"name": "Warrior", "hp": 20, "items": ["sword"], "flavor": "Strong."},
        ],
        "dm_style": "Test style.",
        "opening_narration": "You begin.",
    }


class TestValidateCampaign:
    def test_valid(self):
        errors = validate_campaign(_valid_campaign_data())
        assert errors == []

    def test_missing_key(self):
        data = _valid_campaign_data()
        del data["title"]
        errors = validate_campaign(data)
        assert any("title" in e for e in errors)

    def test_missing_rooms(self):
        data = _valid_campaign_data()
        data["rooms"] = []
        errors = validate_campaign(data)
        assert any("rooms" in e for e in errors)

    def test_victory_room_not_in_rooms(self):
        data = _valid_campaign_data()
        data["victory_room"] = "nonexistent"
        errors = validate_campaign(data)
        assert any("victory_room" in e for e in errors)

    def test_starting_room_not_in_rooms(self):
        data = _valid_campaign_data()
        data["starting_room"] = "nonexistent"
        errors = validate_campaign(data)
        assert any("starting_room" in e for e in errors)

    def test_room_missing_id(self):
        data = _valid_campaign_data()
        data["rooms"][0] = {"name": "No ID"}
        errors = validate_campaign(data)
        assert any("'id'" in e for e in errors)

    def test_archetype_missing_name(self):
        data = _valid_campaign_data()
        data["archetypes"][0] = {"hp": 10}
        errors = validate_campaign(data)
        assert any("'name'" in e for e in errors)


class TestLoadCampaign:
    def test_load(self, tmp_path):
        path = tmp_path / "campaign.json"
        path.write_text(json.dumps(_valid_campaign_data()))
        campaign = load_campaign(path)
        assert campaign.id == "test_campaign"
        assert campaign.title == "Test Campaign"
        assert len(campaign.rooms) == 2
        assert len(campaign.archetypes) == 1

    def test_load_invalid_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"id": "bad"}))
        with pytest.raises(ValueError):
            load_campaign(path)


class TestListCampaigns:
    def test_list_from_content(self):
        campaigns = list_campaigns()
        assert len(campaigns) >= 2
        ids = [c.id for c in campaigns]
        assert "sunken_vault" in ids
        assert "station_nine" in ids


class TestVictoryCondition:
    def test_victory_in_room(self):
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", ""), "end": Room("end", "End", "")},
            archetypes=[], dm_style="", opening_narration="",
        )
        cond = make_victory_condition(campaign)
        state = GameState(player=type("P", (), {"location": "end"})(), rooms=campaign.rooms)
        assert cond(state) is True

    def test_not_victory_elsewhere(self):
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", ""), "end": Room("end", "End", "")},
            archetypes=[], dm_style="", opening_narration="",
        )
        cond = make_victory_condition(campaign)
        state = GameState(player=type("P", (), {"location": "start"})(), rooms=campaign.rooms)
        assert cond(state) is False


class TestBuildInitialState:
    def test_state_from_campaign(self):
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", "")},
            archetypes=[Archetype("Warrior", 25, ["sword"], "Strong")],
            dm_style="", opening_narration="",
        )
        archetype = campaign.archetypes[0]
        state = build_initial_state(campaign, archetype, "Hero")
        assert state.player.name == "Hero"
        assert state.player.hp == 25
        assert state.player.max_hp == 25
        assert "sword" in state.player.inventory
        assert state.player.location == "start"


class TestCharacterCreation:
    def test_character_sheet_in_prompt(self):
        campaign = Campaign(
            id="test", title="Test", genre="fantasy", world_seed="A world", goal="Win",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", "")},
            archetypes=[Archetype("Mage", 18, ["staff"], "Wise")],
            dm_style="Mysterious", opening_narration="Begin.",
        )
        context = character_creation._build_context(campaign, "Gandalf", campaign.archetypes[0])
        prompt = build_turn("look", build_initial_state(campaign, campaign.archetypes[0], "Gandalf"), context, 8000, 5)
        assert "Gandalf" in prompt
        assert "fantasy" in prompt

    def test_create_character_flow(self):
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", "")},
            archetypes=[Archetype("Warrior", 20, ["sword"], "")],
            dm_style="", opening_narration="",
        )
        with patch("ui.character_creation.input", side_effect=["1", "Hero", "y"]):
            state, context = character_creation.create_character(campaign)
        assert state.player.name == "Hero"
        assert state.player.hp == 20

    def test_build_initial_state_stamps_archetype(self):
        """BUG-007 regression: new characters record their archetype name."""
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", "")},
            archetypes=[Archetype("Warrior", 20, ["sword"], ""), Archetype("Mage", 18, ["staff"], "")],
            dm_style="", opening_narration="",
        )
        state = build_initial_state(campaign, campaign.archetypes[1], "Hero")
        assert state.player.archetype == "Mage"

    def test_pick_archetype_eof_propagates(self):
        """BUG-002 regression: EOF at the archetype picker must propagate, not loop forever."""
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", "")},
            archetypes=[Archetype("Warrior", 20, ["sword"], "")],
            dm_style="", opening_narration="",
        )
        with patch("ui.character_creation.input", side_effect=EOFError):
            with pytest.raises(EOFError):
                character_creation._pick_archetype(campaign)

    def test_create_character_eof_propagates(self):
        """EOF during archetype selection flows out of create_character to main's handler."""
        campaign = Campaign(
            id="test", title="Test", genre="", world_seed="", goal="",
            victory_room="end", starting_room="start",
            rooms={"start": Room("start", "Start", "")},
            archetypes=[Archetype("Warrior", 20, ["sword"], "")],
            dm_style="", opening_narration="",
        )
        with patch("ui.character_creation.input", side_effect=EOFError):
            with pytest.raises(EOFError):
                character_creation.create_character(campaign)


class TestCampaignVictoryRun:
    def _make_bridge(self, responses):
        class FakeBridge(LLMBridge):
            def __init__(self, responses):
                self.responses = responses
                self.call_count = 0

            def ask(self, prompt, system=None):
                result = self.responses[self.call_count % len(self.responses)]
                self.call_count += 1
                return result

        return FakeBridge(responses)

    def test_sunken_vault_victory(self):
        campaign = load_campaign(Path("content/sunken_vault.json"))
        bridge = self._make_bridge([
            BridgeResult(ok=True, raw=json.dumps({
                "narration": "You move forward. The passage opens ahead.",
                "choices": ["Continue", "Wait"],
                "state_requests": [{"op": "move", "to": "hall"}],
                "status": "ok",
            }), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=json.dumps({
                "narration": "You press on. The vault chamber looms ahead.",
                "choices": ["Enter", "Wait"],
                "state_requests": [{"op": "move", "to": "vault_chamber"}],
                "status": "victory",
            }), error=None, attempts=1, latency_ms=10),
        ])
        archetype = campaign.archetypes[0]
        state = build_initial_state(campaign, archetype, "Hero")
        context = character_creation._build_context(campaign, "Hero", archetype)
        victory_cond = make_victory_condition(campaign)

        # Simulate turns
        from dm.contract import parse
        from engine.adjudicate import apply_requests, check_status
        from engine.rules import Dice

        dice = Dice(seed=42)
        for _ in range(3):
            prompt = build_turn("go forward", state, context, 8000, 5)
            result = bridge.ask(prompt)
            dm_resp = parse(result.raw)
            state = apply_requests(state, dm_resp.state_requests, dice)
            status = check_status(state, dm_resp.status, victory_cond)
            if status == "victory":
                break

        assert state.player.location == "vault_chamber"
        assert victory_cond(state) is True

    def test_station_nine_victory(self):
        campaign = load_campaign(Path("content/station_nine.json"))
        bridge = self._make_bridge([
            BridgeResult(ok=True, raw=json.dumps({
                "narration": "You move through the corridor. Sparks fly.",
                "choices": ["Continue"],
                "state_requests": [{"op": "move", "to": "corridor"}],
                "status": "ok",
            }), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=json.dumps({
                "narration": "You reach the control deck. Power surges.",
                "choices": ["Activate"],
                "state_requests": [{"op": "move", "to": "control_deck"}],
                "status": "victory",
            }), error=None, attempts=1, latency_ms=10),
        ])
        archetype = campaign.archetypes[0]
        state = build_initial_state(campaign, archetype, "Hero")
        context = character_creation._build_context(campaign, "Hero", archetype)
        victory_cond = make_victory_condition(campaign)

        from dm.contract import parse
        from engine.adjudicate import apply_requests, check_status
        from engine.rules import Dice

        dice = Dice(seed=42)
        for _ in range(3):
            prompt = build_turn("go forward", state, context, 8000, 5)
            result = bridge.ask(prompt)
            dm_resp = parse(result.raw)
            state = apply_requests(state, dm_resp.state_requests, dice)
            status = check_status(state, dm_resp.status, victory_cond)
            if status == "victory":
                break

        assert state.player.location == "control_deck"
        assert victory_cond(state) is True
