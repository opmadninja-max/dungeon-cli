"""Main menu and campaign picker."""

import sys

from engine.campaign import Campaign
from ui.render import console


def main_menu() -> str:
    """Display main menu. Returns 'new' or 'continue'."""
    console.print("\n[bold]=== dungeon-cli ===[/bold]")
    console.print("  [cyan]1.[/cyan] New Game")
    console.print("  [cyan]2.[/cyan] Continue")
    console.print("  [cyan]3.[/cyan] Quit")
    console.print()
    while True:
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        if choice == "1":
            return "new"
        elif choice == "2":
            return "continue"
        elif choice == "3":
            return "quit"
        console.print("[red]Invalid choice. Enter 1, 2, or 3.[/red]")


def pick_campaign(campaigns: list[Campaign]) -> Campaign:
    """Display campaigns and let player pick one."""
    if not campaigns:
        console.print("[red]No campaigns found.[/red]")
        sys.exit(1)

    console.print("\n[bold]=== Choose a Campaign ===[/bold]")
    for i, camp in enumerate(campaigns, 1):
        console.print(f"  [cyan]{i}.[/cyan] [bold]{camp.title}[/bold] ({camp.genre})")
        console.print(f"     [dim]{camp.goal}[/dim]")
    console.print()

    while True:
        try:
            choice = input("> ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(campaigns):
                return campaigns[idx]
        except ValueError:
            pass
        console.print("[red]Invalid choice. Enter a number.[/red]")
