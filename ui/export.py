"""Story export: dump completed run to Markdown transcript."""

from datetime import datetime
from pathlib import Path

from dm.prompt import TurnRecord
from engine.state import GameState


def export_transcript(
    state: GameState,
    history: list[TurnRecord],
    campaign_title: str,
    path: Path,
) -> None:
    """Export completed run to Markdown file."""
    content = _format_transcript(state, history, campaign_title)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _format_transcript(
    state: GameState,
    history: list[TurnRecord],
    campaign_title: str,
) -> str:
    """Format game state and history as Markdown."""
    lines = []

    # Header
    lines.append(f"# Campaign: {campaign_title}")
    lines.append("")

    # Character section
    lines.append("## Character")
    lines.append("")
    lines.append(f"- **Name**: {state.player.name}")
    lines.append(f"- **Final HP**: {state.player.hp}/{state.player.max_hp}")
    lines.append(f"- **Location**: {state.player.location}")
    items = ", ".join(state.player.inventory) if state.player.inventory else "empty"
    lines.append(f"- **Inventory**: {items}")
    lines.append("")

    # Story section
    lines.append("## Story")
    lines.append("")

    for record in history:
        lines.append(f"### Turn {record.turn}")
        lines.append("")
        lines.append(f"**You**: {record.action}")
        lines.append("")
        lines.append(record.narration)
        lines.append("")

    # Footer
    status = "Victory" if state.player.hp > 0 else "Death"
    lines.append("---")
    lines.append("")
    lines.append(f"## Final Status: {status}")
    lines.append("")
    lines.append(f"**Turns**: {len(history)}")
    lines.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    return "\n".join(lines)


def default_export_path(state: GameState, save_dir: Path) -> Path:
    """Generate default export path with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return save_dir / f"transcript_{timestamp}.md"
