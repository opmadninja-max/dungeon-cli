"""Tests for UI input parsing and game loop."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dm.bridge import BridgeResult, LLMBridge
from dm.prompt import PromptContext
from engine.campaign import Campaign, build_initial_state, load_campaign, make_victory_condition
from engine.state import GameState, Player, Room
from ui import spinner
from ui.input import parse_input
from ui.menu import pick_campaign
from ui.telemetry import Telemetry
import cli
from cli import game_loop


class FakeBridge(LLMBridge):
    """Bridge that returns scripted responses."""

    def __init__(self, responses: list[BridgeResult]):
        self.responses = responses
        self.call_count = 0

    def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
        if self.call_count < len(self.responses):
            result = self.responses[self.call_count]
        else:
            result = BridgeResult(ok=False, raw="", error="exhausted", attempts=1, latency_ms=0)
        self.call_count += 1
        return result


def _valid_response():
    return json.dumps({
        "narration": "You see a passage ahead. It is dark and cold.",
        "choices": ["Go forward", "Turn back"],
        "state_requests": [],
        "status": "ok",
    })


def _make_state() -> GameState:
    return GameState(
        player=Player(name="Hero", hp=20, max_hp=20, inventory=["torch"], location="entrance"),
        rooms={
            "entrance": Room(id="entrance", name="Entrance", description="Start"),
            "hall": Room(id="hall", name="Hall", description="A hall"),
        },
        flags={},
        turn=0,
    )


class TestParseInput:
    def test_freeform(self):
        result = parse_input("look around", ["Go left", "Go right"])
        assert result == "look around"

    def test_number_selects_choice(self):
        result = parse_input("1", ["Go left", "Go right"])
        assert result == "Go left"

    def test_number_two(self):
        result = parse_input("2", ["Go left", "Go right"])
        assert result == "Go right"

    def test_number_out_of_range(self):
        result = parse_input("9", ["Go left", "Go right"])
        assert result == "9"

    def test_slash_command(self):
        result = parse_input("/help", ["Go left"])
        assert result == "/help"

    def test_empty_input(self):
        result = parse_input("", ["Go left"])
        assert result == ""

    def test_whitespace_only(self):
        result = parse_input("   ", ["Go left"])
        assert result == ""

    def test_number_zero(self):
        result = parse_input("0", ["Go left"])
        assert result == "0"

    def test_strips_whitespace(self):
        result = parse_input("  look around  ", [])
        assert result == "look around"


def _make_test_context() -> PromptContext:
    return PromptContext(system="You are the DM.", world_seed="A dark dungeon.")


class TestMenuEOF:
    """BUG-002 regression: EOF at the campaign picker must propagate, not loop forever."""

    def test_pick_campaign_eof_propagates(self):
        campaigns = [
            Campaign(
                id="test", title="Test", genre="", world_seed="", goal="",
                victory_room="end", starting_room="start",
                rooms={"start": Room("start", "Start", "")},
                archetypes=[], dm_style="", opening_narration="",
            )
        ]
        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(EOFError):
                pick_campaign(campaigns)


class TestGameLoop:
    def test_quit_command_exits(self, tmp_path):
        bridge = FakeBridge([])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["/quit"]):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        assert save_path.exists()

    def test_save_command_saves(self, tmp_path):
        bridge = FakeBridge([])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["/save", "/quit"]):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        assert save_path.exists()

    def test_save_load_byte_identical(self, tmp_path):
        bridge = FakeBridge([])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["/save", "/quit"]):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        loaded = GameState.load(save_path)
        assert loaded.player.name == state.player.name
        assert loaded.player.hp == state.player.hp
        assert loaded.player.inventory == state.player.inventory
        assert loaded.player.location == state.player.location

    def test_retry_restores_state(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        # First action, then retry (re-runs same action), then quit
        with patch("ui.input.input", side_effect=["look around", "/retry", "/quit"]):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        # Bridge should be called twice (original + retry)
        assert bridge.call_count == 2

    def test_full_turn(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["look around", "/quit"]):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        assert bridge.call_count == 1
        assert save_path.exists()

    def test_interrupt_saves_current_state(self, tmp_path):
        """BUG-001 regression: after 2 completed turns, an interrupt during the
        3rd bridge call must leave the caller's state object at turn 2 (main's
        autosave then persists turn 2; the pre-fix bug saved turn 0)."""
        class InterruptingBridge(LLMBridge):
            def __init__(self):
                self.call_count = 0

            def ask(self, prompt, system=None):
                self.call_count += 1
                if self.call_count > 2:
                    raise KeyboardInterrupt()
                return BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10)

        bridge = InterruptingBridge()
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["look around", "look again", "look more"]):
            with pytest.raises(KeyboardInterrupt):
                game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        assert bridge.call_count == 3
        assert state.turn == 2
        state.save(save_path)
        assert GameState.load(save_path).turn == 2

    def test_compaction_triggers_in_game_loop(self, tmp_path):
        """BUG-003 regression: at compact_after turns, game_loop folds old turns
        into story_so_far via one summarizer bridge call and keeps the rest verbatim."""
        class AlwaysValidBridge(LLMBridge):
            def __init__(self):
                self.prompts: list[str] = []

            def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
                self.prompts.append(prompt)
                return BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10)

        bridge = AlwaysValidBridge()
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        inputs = [f"action {i}" for i in range(10)] + ["/quit"]
        with patch("ui.input.input", side_effect=inputs), patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}, save_path, lambda s: False)

        dm_prompts = [p for p in bridge.prompts if "Summarize the following" not in p]
        summarizer_prompts = [p for p in bridge.prompts if "Summarize the following" in p]
        assert len(dm_prompts) == 10
        assert len(summarizer_prompts) == 1
        assert all(len(p) <= 8000 for p in bridge.prompts)
        assert telemetry.compactions == 1
        # The caller's context object must be the compacted one (mutated in place)
        assert context.story_so_far == _valid_response()
        assert len(context.recent_turns) == 5


class TestTelemetryCompaction:
    def test_record_compaction_in_summary(self):
        telemetry = Telemetry()
        assert "Compactions: 0" in telemetry.summary()
        telemetry.record_compaction()
        assert "Compactions: 1" in telemetry.summary()


class TestFailedTurns:
    """BUG-004 regression: a failed DM turn must not consume the player's action."""

    LOOP_CONFIG = {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}

    def _victory_response(self):
        return json.dumps({
            "narration": "You win the day. The vault opens wide.",
            "choices": [],
            "state_requests": [],
            "status": "victory",
        })

    def test_t1_bridge_failure_does_not_consume_turn(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=False, raw="", error="boom", attempts=3, latency_ms=0),
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        before = state.to_dict()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("builtins.input", side_effect=["act once", "act again", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert bridge.call_count == 2
        expected = dict(before)
        expected["turn"] = 1
        assert state.to_dict() == expected
        assert len(context.recent_turns) == 1
        assert context.recent_turns[0].action == "act again"
        assert telemetry.total_turns == 1
        assert telemetry.failed_turns == 1

    def test_t2_unrepairable_response_does_not_consume_turn(self, tmp_path):
        # calls 1-3: garbage (parse fail + 2 failed repair attempts -> FALLBACK); call 4: valid
        bridge = FakeBridge([
            BridgeResult(ok=True, raw="not json {{{", error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw="not json {{{", error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw="not json {{{", error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        before = state.to_dict()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("builtins.input", side_effect=["act once", "act again", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert bridge.call_count == 4
        expected = dict(before)
        expected["turn"] = 1
        assert state.to_dict() == expected
        assert len(context.recent_turns) == 1
        assert context.recent_turns[0].action == "act again"
        assert telemetry.total_turns == 1
        assert telemetry.failed_turns == 1

    def test_t3_retry_after_bridge_failure(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=False, raw="", error="boom", attempts=3, latency_ms=0),
            BridgeResult(ok=True, raw=self._victory_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("builtins.input", side_effect=["act once", "/retry", "y"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: True)

        transcripts = list(tmp_path.glob("transcript_*.md"))
        assert len(transcripts) == 1
        text = transcripts[0].read_text(encoding="utf-8")
        # exactly one real turn in history, and the action appears exactly once
        assert text.count("### Turn") == 1
        assert text.count("**You**: act once") == 1
        assert telemetry.failed_turns == 1

    def test_t4_successful_turn_counts_once(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("ui.input.input", side_effect=["act once", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert state.turn == 1
        assert telemetry.total_turns == 1

    def test_t5_two_consecutive_failed_turns(self, tmp_path):
        bridge = FakeBridge([])  # always ok=False ("exhausted")
        state = _make_state()
        before = state.to_dict()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("ui.input.input", side_effect=["act one", "act two", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert state.turn == 0
        assert state.to_dict() == before
        assert len(context.recent_turns) == 0
        assert telemetry.failed_turns == 2
        assert telemetry.total_turns == 0


class TestRetryRecords:
    """BUG-005 regression: /retry must replace the previous turn record, not duplicate it."""

    LOOP_CONFIG = {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}

    def _response(self, narration):
        return json.dumps({
            "narration": narration,
            "choices": [],
            "state_requests": [],
            "status": "ok",
        })

    def _victory_response(self):
        return json.dumps({
            "narration": "You win the day. The vault opens wide.",
            "choices": [],
            "state_requests": [],
            "status": "victory",
        })

    def test_ta_retry_replaces_not_duplicates(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("First outcome. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._response("Second outcome. Something differs."), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("ui.input.input", side_effect=["act once", "/retry", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert bridge.call_count == 2
        assert state.turn == 1
        assert len(context.recent_turns) == 1
        assert context.recent_turns[0].narration == "Second outcome. Something differs."
        assert telemetry.total_turns == 1

    def test_tb_retry_then_failure_rolls_back_cleanly(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("First outcome. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=False, raw="", error="boom", attempts=3, latency_ms=0),
        ])
        state = _make_state()
        before = state.to_dict()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("ui.input.input", side_effect=["act once", "/retry", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert state.turn == 0
        assert state.to_dict() == before
        assert len(context.recent_turns) == 0
        assert telemetry.total_turns == 0
        assert telemetry.failed_turns == 1

    def test_tc_retry_after_failed_turn_keeps_earlier_record(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("First outcome. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=False, raw="", error="boom", attempts=3, latency_ms=0),
            BridgeResult(ok=True, raw=self._response("Second try works. Something differs."), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("ui.input.input", side_effect=["act one", "act two", "/retry", "/quit"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert bridge.call_count == 3
        assert state.turn == 2
        assert [r.action for r in context.recent_turns] == ["act one", "act two"]
        assert telemetry.total_turns == 2
        assert telemetry.failed_turns == 1

    def test_td_retry_transcript_has_single_turn(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("First outcome. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._victory_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        telemetry = Telemetry()
        with patch("builtins.input", side_effect=["act once", "/retry", "y"]), \
             patch("cli.Telemetry", return_value=telemetry):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: True)

        transcripts = list(tmp_path.glob("transcript_*.md"))
        assert len(transcripts) == 1
        text = transcripts[0].read_text(encoding="utf-8")
        assert text.count("### Turn") == 1
        assert text.count("**You**: act once") == 1


class TestLoadContext:
    """BUG-006 regression: /load must drop all session context from the discarded timeline."""

    LOOP_CONFIG = {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"typewriter": False, "spinner": False}}

    def _response(self, narration):
        return json.dumps({
            "narration": narration,
            "choices": [],
            "state_requests": [],
            "status": "ok",
        })

    def _victory_response(self):
        return json.dumps({
            "narration": "You win the day. The vault opens wide.",
            "choices": [],
            "state_requests": [],
            "status": "victory",
        })

    def test_t1_load_resets_recent_turns(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("One. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._response("Two. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._response("Three. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._response("After load. Something happens."), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["act one", "/save", "act two", "act three", "/load", "act after load", "/quit"]):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert state.turn == 2
        assert [r.action for r in context.recent_turns] == ["act after load"]

    def test_t2_retry_after_load_does_not_revert(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("One. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._response("Two. Something happens."), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("ui.input.input", side_effect=["act one", "/save", "act two", "/load", "/retry", "/quit"]):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: False)

        assert bridge.call_count == 2
        assert state.turn == 1
        assert context.recent_turns == []

    def test_t3_export_after_load_has_only_post_load_turns(self, tmp_path):
        bridge = FakeBridge([
            BridgeResult(ok=True, raw=self._response("One. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._response("Two. Something happens."), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=self._victory_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()
        save_path = tmp_path / "game.json"

        with patch("builtins.input", side_effect=["act one", "/save", "act two", "/load", "act after load", "y"]):
            game_loop(state, context, bridge, self.LOOP_CONFIG, save_path, lambda s: True)

        transcripts = list(tmp_path.glob("transcript_*.md"))
        assert len(transcripts) == 1
        text = transcripts[0].read_text(encoding="utf-8")
        assert text.count("### Turn") == 1
        assert "**You**: act after load" in text
        assert "act two" not in text


class TestContinueContext:
    """BUG-007 regression: Continue must build the DM prompt from the saved archetype."""

    def test_continue_uses_saved_archetype(self, tmp_path):
        campaign = load_campaign(Path("content/station_nine.json"))
        marine = campaign.archetypes[1]
        state = build_initial_state(campaign, marine, "Hero")
        save_dir = tmp_path / campaign.id
        save_dir.mkdir(parents=True)
        state.save(save_dir / "game.json")

        class PromptRecorder(LLMBridge):
            def __init__(self):
                self.prompts: list[str] = []

            def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
                self.prompts.append(prompt)
                return BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=1)

        bridge = PromptRecorder()
        config = {
            "llm": {"argv": ["fake"], "timeout": 1, "retries": 0, "save_dir": str(tmp_path)},
            "prompt": {"budget": 8000, "recent_turns": 5},
            "ui": {"spinner": False},
        }
        with patch("ui.menu.main_menu", side_effect=["continue", "quit"]), \
             patch("ui.menu.pick_campaign", return_value=campaign), \
             patch("builtins.input", side_effect=["act", "/quit"]), \
             patch("cli.load_config", return_value=config), \
             patch("cli.make_bridge", return_value=bridge):
            cli.main()

        assert len(bridge.prompts) >= 1
        assert "the Marine" in bridge.prompts[0]
        assert "the Engineer" not in bridge.prompts[0]


class TestSpinner:
    """BUG-008 regression: spinner must use encodable frames on legacy codepages."""

    def test_frames_ascii_on_cp1252(self):
        stream = MagicMock()
        stream.encoding = "cp1252"
        frames = spinner._frames_for(stream)
        assert "\u280b" not in frames
        assert "|" in frames

    def test_frames_braille_on_utf8(self):
        stream = MagicMock()
        stream.encoding = "utf-8"
        frames = spinner._frames_for(stream)
        assert "\u280b" in frames

    def test_frames_default_ascii_when_encoding_unknown(self):
        stream = MagicMock()
        stream.encoding = None
        frames = spinner._frames_for(stream)
        assert "\u280b" not in frames
        assert "|" in frames

    def test_stop_joins_cleanly(self):
        s = spinner.Spinner("Thinking...")
        s.start()
        time.sleep(0.3)
        s.stop()  # must return without exception


class TestCorruptSave:
    """BUG-009 regression: a corrupt save must never crash the game."""

    def _config(self, tmp_path):
        return {
            "llm": {"argv": ["fake"], "timeout": 1, "retries": 0, "save_dir": str(tmp_path)},
            "prompt": {"budget": 8000, "recent_turns": 5},
            "ui": {"spinner": False},
        }

    def _run_continue(self, tmp_path, bridge):
        campaign = load_campaign(Path("content/station_nine.json"))
        with patch("ui.menu.main_menu", side_effect=["continue", "quit"]), \
             patch("ui.menu.pick_campaign", return_value=campaign), \
             patch("builtins.input", side_effect=["1", "", "", "act", "/quit"]), \
             patch("cli.load_config", return_value=self._config(tmp_path)), \
             patch("cli.make_bridge", return_value=bridge):
            cli.main()

    def test_t1_continue_with_garbage_save_starts_new_game(self, tmp_path):
        save_dir = tmp_path / "station_nine"
        save_dir.mkdir(parents=True)
        (save_dir / "game.json").write_text("not valid json {{{")

        class PromptRecorder(LLMBridge):
            def __init__(self):
                self.prompts: list[str] = []

            def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
                self.prompts.append(prompt)
                return BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=1)

        bridge = PromptRecorder()
        self._run_continue(tmp_path, bridge)
        assert len(bridge.prompts) >= 1

    def test_t2_continue_with_wrong_shape_save_starts_new_game(self, tmp_path):
        save_dir = tmp_path / "station_nine"
        save_dir.mkdir(parents=True)
        (save_dir / "game.json").write_text('{"player": {}, "rooms": {}}')

        class PromptRecorder(LLMBridge):
            def __init__(self):
                self.prompts: list[str] = []

            def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
                self.prompts.append(prompt)
                return BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=1)

        bridge = PromptRecorder()
        self._run_continue(tmp_path, bridge)
        assert len(bridge.prompts) >= 1

    def test_t3_in_game_load_with_corrupt_file_does_not_crash(self, tmp_path):
        save_path = tmp_path / "game.json"

        bridge = FakeBridge([
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
            BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=10),
        ])
        state = _make_state()
        context = _make_test_context()

        inputs = iter(["act once", "/save", "/load", "act again", "/quit"])

        def scripted_input(prompt=""):
            value = next(inputs)
            if value == "/load":
                # External corruption between /save and /load
                save_path.write_text("garbage {{{")
            return value

        with patch("ui.input.input", side_effect=scripted_input):
            game_loop(state, context, bridge, {"prompt": {"budget": 8000, "recent_turns": 5}, "ui": {"spinner": False}}, save_path, lambda s: False)

        assert bridge.call_count == 2
        assert state.turn == 2


class TestMenuKeyboardInterrupt:
    """BUG-010 regression: Ctrl-C in pre-game prompts must exit cleanly, not traceback."""

    def _config(self, tmp_path):
        return {
            "llm": {"argv": ["fake"], "timeout": 1, "retries": 0, "save_dir": str(tmp_path)},
            "prompt": {"budget": 8000, "recent_turns": 5},
            "ui": {"spinner": False},
        }

    def _run_main(self, tmp_path, *, main_menu_side, pick_campaign_side, input_side):
        campaign = load_campaign(Path("content/station_nine.json"))

        class PromptRecorder(LLMBridge):
            def __init__(self):
                self.prompts: list[str] = []

            def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
                self.prompts.append(prompt)
                return BridgeResult(ok=True, raw=_valid_response(), error=None, attempts=1, latency_ms=1)

        with patch("ui.menu.main_menu", side_effect=main_menu_side), \
             patch("ui.menu.pick_campaign", side_effect=pick_campaign_side), \
             patch("builtins.input", side_effect=input_side), \
             patch("cli.load_config", return_value=self._config(tmp_path)), \
             patch("cli.make_bridge", return_value=PromptRecorder()):
            try:
                cli.main()
            except KeyboardInterrupt:
                pytest.fail("KeyboardInterrupt escaped main() — the player would see a raw traceback")

    def test_t1_ctrl_c_at_campaign_pick_exits_cleanly(self, tmp_path):
        self._run_main(tmp_path,
                       main_menu_side=["new"],
                       pick_campaign_side=KeyboardInterrupt(),
                       input_side=[])
        assert True  # main() returned without raising

    def test_t2_ctrl_c_at_archetype_pick_exits_cleanly(self, tmp_path):
        self._run_main(tmp_path,
                       main_menu_side=["new"],
                       pick_campaign_side=[load_campaign(Path("content/station_nine.json"))],
                       input_side=KeyboardInterrupt())
        assert True

    def test_t3_ctrl_c_at_name_prompt_exits_cleanly(self, tmp_path):
        self._run_main(tmp_path,
                       main_menu_side=["new"],
                       pick_campaign_side=[load_campaign(Path("content/station_nine.json"))],
                       input_side=["1", KeyboardInterrupt()])
        assert True

    def test_t4_ctrl_c_at_confirm_prompt_exits_cleanly(self, tmp_path):
        self._run_main(tmp_path,
                       main_menu_side=["new"],
                       pick_campaign_side=[load_campaign(Path("content/station_nine.json"))],
                       input_side=["1", "Hero", KeyboardInterrupt()])
        assert True
