"""Prompt assembly and context management."""

from dataclasses import dataclass, field

from dm.bridge import LLMBridge
from engine.state import GameState

SUMMARIZER_PROMPT = """Summarize the following adventure story so far in 3-5 sentences.
Preserve key events, discoveries, and the current situation.
Return only the summary text, no commentary.

{context}"""


@dataclass
class TurnRecord:
    turn: int
    action: str
    narration: str
    state_summary: str


@dataclass
class PromptContext:
    system: str
    world_seed: str
    story_so_far: str = ""
    recent_turns: list[TurnRecord] = field(default_factory=list)


def _state_summary(state: GameState) -> str:
    items = ", ".join(state.player.inventory) if state.player.inventory else "empty"
    return (
        f"HP: {state.player.hp}/{state.player.max_hp} | "
        f"Location: {state.player.location} | "
        f"Inventory: {items}"
    )


def _format_recent_turns(turns: list[TurnRecord]) -> str:
    if not turns:
        return ""
    lines = []
    for t in turns:
        lines.append(f"--- Turn {t.turn} ---")
        lines.append(f"Action: {t.action}")
        lines.append(f"Result: {t.narration}")
        lines.append(f"State: {t.state_summary}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _section(name: str, content: str) -> str:
    return f"=== {name} ===\n{content}"


_SYSTEM_HEADER = "=== SYSTEM ===\n"


def split_system(prompt: str) -> tuple[str, str]:
    """Split an assembled prompt into (system, remainder).

    Returns ("", prompt) when the header is absent, empty, or SYSTEM is the only
    section, so the caller can always fall back to the single-message shape.
    """
    if not prompt.startswith(_SYSTEM_HEADER):
        return "", prompt
    system, separator, remainder = prompt[len(_SYSTEM_HEADER):].partition("\n\n")
    if not separator or not remainder.strip():
        return "", prompt
    return system, remainder


def build_turn(
    action: str,
    state: GameState,
    context: PromptContext,
    budget: int,
    recent_limit: int,
) -> str:
    """Build a turn prompt within the character budget.

    Section order: SYSTEM, WORLD, CHARACTER, STORY SO FAR, RECENT TURNS, PLAYER ACTION.
    SYSTEM and CHARACTER are never dropped or truncated.
    Trimming order: story_so_far → oldest recent_turns → world_seed.
    """
    # Build all sections in order
    sections = [
        ("SYSTEM", context.system),
        ("WORLD", context.world_seed),
        ("CHARACTER", _state_summary(state)),
        ("STORY SO FAR", context.story_so_far),
        ("RECENT TURNS", _format_recent_turns(context.recent_turns[-recent_limit:])),
        ("PLAYER ACTION", action),
    ]

    # Always include SYSTEM (0), CHARACTER (2), and PLAYER ACTION (5)
    protected_indices = {0, 2, 5}

    # Calculate fixed size (protected sections + delimiters)
    fixed_size = sum(len(_section(name, content)) for i, (name, content) in enumerate(sections) if i in protected_indices)
    fixed_size += len("\n\n") * (len(protected_indices) - 1)  # delimiters between them

    if fixed_size >= budget:
        # Can only fit protected sections
        return "\n\n".join(_section(name, content) for i, (name, content) in enumerate(sections) if i in protected_indices)

    # Determine which optional sections to include
    # Priority (lowest first for removal): STORY SO FAR, RECENT TURNS, WORLD
    include = [True] * 6
    include[3] = bool(context.story_so_far)  # STORY SO FAR
    include[4] = bool(context.recent_turns)  # RECENT TURNS

    # Try to fit everything first
    result = _assemble(sections, include)
    if len(result) <= budget:
        return result

    # Trim in order: story_so_far, recent_turns, world_seed
    # 1. Drop story_so_far
    include[3] = False
    result = _assemble(sections, include)
    if len(result) <= budget:
        return result

    # 2. Trim recent_turns (oldest first)
    recent = context.recent_turns[-recent_limit:]
    while len(recent) > 0:
        sections[4] = ("RECENT TURNS", _format_recent_turns(recent))
        result = _assemble(sections, include)
        if len(result) <= budget:
            return result
        recent = recent[1:]  # drop oldest

    # Can't fit any recent turns
    include[4] = False
    result = _assemble(sections, include)
    if len(result) <= budget:
        return result

    # 3. Truncate world_seed
    world = context.world_seed
    while len(world) > 10:
        sections[1] = ("WORLD", world + "...")
        result = _assemble(sections, include)
        if len(result) <= budget:
            return result
        world = world[:-1]

    # Last resort: drop world entirely
    include[1] = False
    return _assemble(sections, include)


def _assemble(sections: list[tuple[str, str]], include: list[bool]) -> str:
    """Assemble included sections into a single string."""
    parts = [_section(name, content) for i, (name, content) in enumerate(sections) if include[i] and content]
    return "\n\n".join(parts)


def compact(context: PromptContext, bridge: LLMBridge, keep: int = 0) -> PromptContext:
    """Compact old turns into story_so_far via summarization.

    Folds all but the last `keep` recent turns into story_so_far, keeping the
    last `keep` turns verbatim. Returns updated context. If bridge fails,
    returns context unchanged.
    """
    if len(context.recent_turns) <= keep:
        return context

    # Build context to summarize: existing story + turns being folded
    parts = []
    if context.story_so_far:
        parts.append(context.story_so_far)
    for t in context.recent_turns[:-keep] if keep else context.recent_turns:
        parts.append(f"Turn {t.turn}: {t.action}\n{t.narration}")

    full_context = "\n\n".join(parts)
    prompt = SUMMARIZER_PROMPT.format(context=full_context)

    result = bridge.ask(prompt)
    if not result.ok:
        return context

    summary = result.raw.strip()
    if not summary:
        return context

    return PromptContext(
        system=context.system,
        world_seed=context.world_seed,
        story_so_far=summary,
        recent_turns=context.recent_turns[-keep:] if keep else [],
    )
