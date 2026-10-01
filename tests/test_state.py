"""Tests for game state save/load."""

import json
import pytest

from engine.state import GameState, Player, Room


def _make_state() -> GameState:
    return GameState(
        player=Player(name="Hero", hp=20, max_hp=20, inventory=["torch"], location="hall"),
        rooms={
            "hall": Room(id="hall", name="Great Hall", description="A vast hall"),
            "crypt": Room(id="crypt", name="Crypt", description="Dark and cold"),
        },
        flags={"met_ghost": True},
        turn=5,
    )


class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        state = _make_state()
        path = tmp_path / "save.json"
        state.save(path)
        loaded = GameState.load(path)
        assert loaded.player.name == state.player.name
        assert loaded.player.hp == state.player.hp
        assert loaded.player.inventory == state.player.inventory
        assert loaded.player.location == state.player.location
        assert set(loaded.rooms.keys()) == set(state.rooms.keys())
        assert loaded.flags == state.flags
        assert loaded.turn == state.turn

    def test_save_creates_file(self, tmp_path):
        state = _make_state()
        path = tmp_path / "saves" / "game.json"
        state.save(path)
        assert path.exists()

    def test_no_tmp_left_behind(self, tmp_path):
        state = _make_state()
        path = tmp_path / "save.json"
        state.save(path)
        assert not path.with_suffix(".json.tmp").exists()

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GameState.load(tmp_path / "nonexistent.json")

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json")
        with pytest.raises(json.JSONDecodeError):
            GameState.load(path)

    def test_from_dict_missing_key(self):
        with pytest.raises((KeyError, TypeError)):
            GameState.from_dict({"player": {}})


class TestArchetypePersistence:
    """BUG-007 regression: the archetype must survive save/load for the Continue path."""

    def test_player_archetype_roundtrip(self, tmp_path):
        state = _make_state()
        state.player.archetype = "Marine"
        path = tmp_path / "save.json"
        state.save(path)
        loaded = GameState.load(path)
        assert loaded.player.archetype == "Marine"

    def test_legacy_save_without_archetype_loads(self, tmp_path):
        data = {
            "player": {"name": "Hero", "hp": 20, "max_hp": 20, "inventory": ["torch"], "location": "hall"},
            "rooms": {},
            "flags": {},
            "turn": 3,
            "log": [],
        }
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps(data))
        loaded = GameState.load(path)
        assert loaded.player.name == "Hero"
        assert loaded.player.archetype == ""
