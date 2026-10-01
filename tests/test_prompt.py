"""Tests for prompt assembly and context management."""

import pytest

from dm.bridge import BridgeResult, LLMBridge
from dm.prompt import PromptContext, TurnRecord, build_turn, compact
from engine.state import GameState, Player, Room


def _make_state(**overrides) -> GameState:
    player = Player(name="Hero", hp=15, max_hp=20, inventory=["torch", "key"], location="crypt")
    return GameState(player=player, turn=5, **overrides)


def _make_context(**overrides) -> PromptContext:
    defaults = {
        "system": "You are the Dungeon Master.",
        "world_seed": "A dark fantasy dungeon filled with ancient traps.",
        "story_so_far": "You entered the dungeon and fought a skeleton.",
        "recent_turns": [
            TurnRecord(turn=3, action="open door", narration="The door creaks open.", state_summary="HP: 18/20 | Location: hall"),
            TurnRecord(turn=4, action="fight skeleton", narration="You defeat it.", state_summary="HP: 15/20 | Location: hall"),
        ],
    }
    defaults.update(overrides)
    return PromptContext(**defaults)


class FakeBridge(LLMBridge):
    def __init__(self, response: str = "Summary of the adventure.", ok: bool = True):
        self._response = response
        self._ok = ok
        self.call_count = 0
        self.prompts: list[str] = []

    def ask(self, prompt: str, system: str | None = None) -> BridgeResult:
        self.call_count += 1
        self.prompts.append(prompt)
        if self._ok:
            return BridgeResult(ok=True, raw=self._response, error=None, attempts=1, latency_ms=10)
        return BridgeResult(ok=False, raw="", error="timeout", attempts=1, latency_ms=0)


class TestSectionOrder:
    def test_sections_in_order(self):
        state = _make_state()
        ctx = _make_context()
        prompt = build_turn("look around", state, ctx, budget=8000, recent_limit=5)
        system_pos = prompt.index("=== SYSTEM ===")
        world_pos = prompt.index("=== WORLD ===")
        character_pos = prompt.index("=== CHARACTER ===")
        story_pos = prompt.index("=== STORY SO FAR ===")
        recent_pos = prompt.index("=== RECENT TURNS ===")
        action_pos = prompt.index("=== PLAYER ACTION ===")
        assert system_pos < world_pos < character_pos < story_pos < recent_pos < action_pos

    def test_all_sections_present(self):
        state = _make_state()
        ctx = _make_context()
        prompt = build_turn("look around", state, ctx, budget=8000, recent_limit=5)
        assert "=== SYSTEM ===" in prompt
        assert "=== WORLD ===" in prompt
        assert "=== CHARACTER ===" in prompt
        assert "=== STORY SO FAR ===" in prompt
        assert "=== RECENT TURNS ===" in prompt
        assert "=== PLAYER ACTION ===" in prompt


class TestBudgetEnforcement:
    def test_budget_not_exceeded(self):
        state = _make_state()
        ctx = _make_context()
        budget = 500
        prompt = build_turn("look around", state, ctx, budget=budget, recent_limit=5)
        assert len(prompt) <= budget

    def test_system_always_present(self):
        state = _make_state()
        ctx = _make_context()
        prompt = build_turn("look around", state, ctx, budget=200, recent_limit=5)
        assert "=== SYSTEM ===" in prompt
        assert "You are the Dungeon Master." in prompt

    def test_character_always_present(self):
        state = _make_state()
        ctx = _make_context()
        prompt = build_turn("look around", state, ctx, budget=200, recent_limit=5)
        assert "=== CHARACTER ===" in prompt
        assert "HP: 15/20" in prompt

    def test_trim_oldest_turns_first(self):
        ctx = _make_context(
            recent_turns=[
                TurnRecord(turn=1, action="a1", narration="n1", state_summary="s1"),
                TurnRecord(turn=2, action="a2", narration="n2", state_summary="s2"),
                TurnRecord(turn=3, action="a3", narration="n3", state_summary="s3"),
            ]
        )
        state = _make_state()
        # Small budget that forces trimming
        prompt = build_turn("act", state, ctx, budget=400, recent_limit=5)
        # Should keep the most recent turns
        assert "Turn 3" in prompt
        # Oldest may be trimmed


class TestCompaction:
    def test_compaction_reduces_size(self):
        ctx = _make_context(
            story_so_far="You entered the dungeon. You fought a skeleton. You found a key.",
            recent_turns=[
                TurnRecord(turn=1, action="enter", narration="You enter the dungeon. It is dark and cold. You hear dripping.", state_summary="HP: 20/20"),
                TurnRecord(turn=2, action="fight", narration="A skeleton attacks. You defeat it with your sword. It crumbles.", state_summary="HP: 18/20"),
            ],
        )
        bridge = FakeBridge(response="You explored a dungeon, fought undead, and found treasure.")
        new_ctx = compact(ctx, bridge)
        assert len(new_ctx.story_so_far) < len(ctx.story_so_far) + sum(len(t.narration) for t in ctx.recent_turns)
        assert new_ctx.recent_turns == []

    def test_compaction_uses_bridge(self):
        ctx = _make_context()
        bridge = FakeBridge(response="A brief summary.")
        compact(ctx, bridge)
        assert bridge.call_count == 1

    def test_compaction_failure_graceful(self):
        ctx = _make_context()
        bridge = FakeBridge(ok=False)
        new_ctx = compact(ctx, bridge)
        assert new_ctx.story_so_far == ctx.story_so_far
        assert new_ctx.recent_turns == ctx.recent_turns

    def test_compaction_empty_turns(self):
        ctx = _make_context(recent_turns=[])
        bridge = FakeBridge()
        new_ctx = compact(ctx, bridge)
        assert bridge.call_count == 0
        assert new_ctx.story_so_far == ctx.story_so_far

    def test_compaction_keeps_last_k(self):
        turns = [
            TurnRecord(turn=i, action=f"action {i}", narration=f"Result {i}. Extra sentence.", state_summary="s")
            for i in range(1, 5)
        ]
        ctx = _make_context(recent_turns=turns)
        bridge = FakeBridge(response="You explored and fought.")
        new_ctx = compact(ctx, bridge, keep=2)
        assert bridge.call_count == 1
        assert [t.turn for t in new_ctx.recent_turns] == [3, 4]
        assert new_ctx.story_so_far == "You explored and fought."
        # Oldest turns were folded into the summarizer prompt
        assert "action 1" in bridge.prompts[0]
        assert "action 2" in bridge.prompts[0]
        assert "action 3" not in bridge.prompts[0]

    def test_compaction_below_keep_noop(self):
        ctx = _make_context()  # 2 recent turns
        bridge = FakeBridge()
        new_ctx = compact(ctx, bridge, keep=5)
        assert bridge.call_count == 0
        assert new_ctx is ctx


class TestEdgeCases:
    def test_empty_history(self):
        state = _make_state()
        ctx = _make_context(recent_turns=[], story_so_far="")
        prompt = build_turn("look around", state, ctx, budget=8000, recent_limit=5)
        assert "=== SYSTEM ===" in prompt
        assert "=== PLAYER ACTION ===" in prompt
        assert "look around" in prompt

    def test_10_turn_run_under_budget(self):
        state = _make_state()
        ctx = _make_context(recent_turns=[], story_so_far="")
        budget = 1000

        for i in range(10):
            prompt = build_turn(f"action {i}", state, ctx, budget=budget, recent_limit=3)
            assert len(prompt) <= budget, f"Turn {i}: prompt {len(prompt)} > budget {budget}"
            # Simulate adding a turn record
            ctx.recent_turns.append(
                TurnRecord(
                    turn=i + 1,
                    action=f"action {i}",
                    narration=f"You do action {i}. Something happens.",
                    state_summary=f"HP: {state.player.hp}/{state.player.max_hp} | Location: {state.player.location}",
                )
            )
