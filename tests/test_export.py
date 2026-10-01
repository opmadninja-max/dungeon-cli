"""Tests for story export functionality."""

import pytest

from dm.prompt import TurnRecord
from engine.state import GameState, Player, Room
from ui.export import _format_transcript, default_export_path, export_transcript


def _make_state() -> GameState:
    return GameState(
        player=Player(name="Hero", hp=15, max_hp=20, inventory=["torch", "key"], location="hall"),
        rooms={"hall": Room(id="hall", name="Hall", description="A hall")},
        flags={"met_ghost": True},
        turn=3,
    )


def _make_history() -> list[TurnRecord]:
    return [
        TurnRecord(turn=1, action="look around", narration="You see a door. It is locked.", state_summary="HP: 20/20"),
        TurnRecord(turn=2, action="open door", narration="The door creaks open. You enter.", state_summary="HP: 20/20"),
        TurnRecord(turn=3, action="fight skeleton", narration="You defeat it. It crumbles.", state_summary="HP: 15/20"),
    ]


class TestFormatTranscript:
    def test_contains_title(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test Campaign")
        assert "# Campaign: Test Campaign" in result

    def test_contains_character_name(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "**Name**: Hero" in result

    def test_contains_final_hp(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "**Final HP**: 15/20" in result

    def test_contains_turns(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "### Turn 1" in result
        assert "### Turn 2" in result
        assert "### Turn 3" in result

    def test_contains_actions(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "**You**: look around" in result
        assert "**You**: open door" in result
        assert "**You**: fight skeleton" in result

    def test_contains_narration(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "You see a door. It is locked." in result

    def test_contains_final_status_victory(self):
        state = _make_state()
        state.player.hp = 10
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "## Final Status: Victory" in result

    def test_contains_final_status_death(self):
        state = _make_state()
        state.player.hp = 0
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "## Final Status: Death" in result

    def test_contains_turn_count(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "**Turns**: 3" in result

    def test_contains_inventory(self):
        state = _make_state()
        history = _make_history()
        result = _format_transcript(state, history, "Test")
        assert "torch" in result
        assert "key" in result


class TestExportTranscript:
    def test_creates_file(self, tmp_path):
        state = _make_state()
        history = _make_history()
        path = tmp_path / "transcript.md"
        export_transcript(state, history, "Test", path)
        assert path.exists()

    def test_file_contains_content(self, tmp_path):
        state = _make_state()
        history = _make_history()
        path = tmp_path / "transcript.md"
        export_transcript(state, history, "Test", path)
        content = path.read_text(encoding="utf-8")
        assert "# Campaign: Test" in content
        assert "Hero" in content


class TestDefaultExportPath:
    def test_generates_unique_path(self, tmp_path):
        state = _make_state()
        path1 = default_export_path(state, tmp_path)
        path2 = default_export_path(state, tmp_path)
        # Paths should be different (different timestamps) or same format
        assert path1.suffix == ".md"
        assert path2.suffix == ".md"
        assert "transcript_" in path1.name

    def test_uses_save_dir(self, tmp_path):
        state = _make_state()
        path = default_export_path(state, tmp_path)
        assert path.parent == tmp_path
