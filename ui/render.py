"""Rendering: status line, narration, choices, epilogue."""

import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from engine.state import GameState

console = Console()


def _hp_color(hp: int, max_hp: int) -> str:
    if max_hp == 0:
        return "red"
    ratio = hp / max_hp
    if ratio > 0.5:
        return "green"
    elif ratio > 0.25:
        return "yellow"
    return "red"


def render_status(state: GameState) -> None:
    """Print status line with colored HP."""
    color = _hp_color(state.player.hp, state.player.max_hp)
    text = Text()
    text.append("HP: ", style="bold")
    text.append(f"{state.player.hp}/{state.player.max_hp}", style=f"bold {color}")
    text.append(" | ")
    text.append(f"Location: {state.player.location}", style="bold")
    text.append(" | ")
    text.append(f"Turn: {state.turn + 1}", style="bold")
    console.print(text)


def render_narration(text: str, typewriter: bool = False, delay: float = 0.02) -> None:
    """Print narration in a panel with optional typewriter effect."""
    if not typewriter:
        console.print(Panel(text, title="Narrative", border_style="blue"))
        return

    # Typewriter effect: build up the text character by character
    console.print("[bold blue]Narrative[/bold blue]")
    sys.stdout.write(" ")
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n\n")


def render_choices(choices: list[str]) -> None:
    """Print numbered choices menu."""
    if not choices:
        return
    console.print("[bold]What do you do?[/bold]")
    for i, choice in enumerate(choices, 1):
        console.print(f"  [cyan]{i}.[/cyan] {choice}")
    console.print("  [dim]Type your own action or a command (/)[/dim]")


def render_epilogue(status: str, narration: str) -> None:
    """Print death/victory epilogue."""
    if status == "dead":
        console.print(Panel(narration, title="YOU DIED", border_style="red"))
    elif status == "victory":
        console.print(Panel(narration, title="VICTORY", border_style="green"))


def render_message(text: str, style: str = "") -> None:
    """Print a styled message."""
    console.print(text, style=style)
