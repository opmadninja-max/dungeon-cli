"""Character creation flow."""

from dm.prompt import PromptContext
from engine.campaign import Archetype, Campaign, build_initial_state
from engine.state import GameState
from ui.render import console


def create_character(campaign: Campaign) -> tuple[GameState, PromptContext]:
    """Run character creation flow. Returns (state, context)."""
    console.print(f"\n[bold]{campaign.title}[/bold]")
    console.print(f"[dim]Goal: {campaign.goal}[/dim]\n")

    archetype = _pick_archetype(campaign)
    name = _pick_name(archetype)
    _confirm(name, archetype)

    state = build_initial_state(campaign, archetype, name)
    context = _build_context(campaign, name, archetype)
    return state, context


def _pick_archetype(campaign: Campaign) -> Archetype:
    """Display archetypes and let player pick one."""
    console.print("[bold]Choose your archetype:[/bold]")
    for i, arch in enumerate(campaign.archetypes, 1):
        console.print(f"  [cyan]{i}.[/cyan] [bold]{arch.name}[/bold] (HP: {arch.hp})")
        console.print(f"     Items: {', '.join(arch.items)}")
        if arch.flavor:
            console.print(f"     [dim]{arch.flavor}[/dim]")
        console.print()

    while True:
        try:
            choice = input("> ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(campaign.archetypes):
                return campaign.archetypes[idx]
        except ValueError:
            pass
        console.print("[red]Invalid choice. Enter a number.[/red]")


def _pick_name(archetype: Archetype) -> str:
    """Get character name from player."""
    console.print(f"\nEnter your name (default: {archetype.name}):")
    try:
        name = input("> ").strip()
    except EOFError:
        name = ""
    return name if name else archetype.name


def _confirm(name: str, archetype: Archetype) -> None:
    """Show confirmation screen."""
    console.print(f"\nYou are [bold]{name}[/bold], the [bold]{archetype.name}[/bold].")
    console.print(f"HP: {archetype.hp} | Items: {', '.join(archetype.items)}")
    console.print("\nBegin? (y/n)")
    try:
        choice = input("> ").strip().lower()
    except EOFError:
        choice = "y"
    if choice == "n":
        console.print("Aborted.")
        raise SystemExit(0)


def _build_context(campaign: Campaign, name: str, archetype: Archetype) -> PromptContext:
    """Build prompt context including character sheet and the response schema.

    The op vocabulary must be spelled out here. Without it the model invents
    plausible-sounding ops (set_location, discover, ...) that the strict parser
    rejects, and every such turn is discarded as a failed turn.
    """
    room_names = ", ".join(f"{r.id} ({r.name})" for r in campaign.rooms.values())
    starting_items = ", ".join(archetype.items) or "nothing"

    system = f"""You are the Dungeon Master of a {campaign.genre} text adventure.
Campaign: {campaign.title}
Goal: {campaign.goal}
Style: {campaign.dm_style}
The player is {name}, the {archetype.name}, carrying: {starting_items}.

RULES
- Respond with ONLY a JSON object. No markdown, no commentary, no code fences.
- You narrate; the engine referees. Propose outcomes via state_requests; never claim a change happened.
- Never state the player's HP or inventory. Describe the world, not the HUD.
- Narration: 2-6 sentences, second person, present tense, ending on tension or a hook.
- Accept any freeform action. Clever play succeeds; reckless play has consequences.
- "choices" are 0-3 short suggested actions. Never railroad.
- Absurd or impossible actions fail entertainingly.
- Only set "status":"dead" when the damage you request would plausibly drop HP to 0.
  "status":"victory" only in the victory room.

RESPONSE SCHEMA — return exactly these four keys
{{
  "narration": "2-6 sentences, second person, present tense",
  "choices": ["up to 3 short suggested actions"],
  "state_requests": [ ...see below... ],
  "status": "ok | dead | victory"
}}

state_requests — every element MUST be an object with an "op" key, and "op" MUST
be one of exactly these five. Any other op is rejected and the whole turn is discarded.
  {{"op": "move",       "to": "<room_id>"}}
  {{"op": "give_item",  "item": "<item name>"}}
  {{"op": "take_item",  "item": "<item name>"}}
  {{"op": "hp_delta",   "severity": "minor|major|critical", "reason": "<why>"}}
  {{"op": "set_flag",   "key": "<short_snake_case_key>", "value": true}}

Rules for state_requests:
- Use "move" to change rooms. Valid room ids: {room_names}.
  The engine rejects unknown room ids, so use these ids verbatim.
- Use "hp_delta" for harm. The engine rolls the dice, so NEVER invent a damage
  number — only the severity tier. minor/major/critical map to 1d4/1d8/2d10.
- There is no op to set HP directly, by design. Never try to invent one.
- Do not use "type" instead of "op". Do not invent ops like "set_location" or
  "discover"; there is no such thing. Express discoveries with "set_flag".
- Omit "state_requests" entirely, or use [], if nothing changed this turn.
"""
    return PromptContext(
        system=system,
        world_seed=campaign.world_seed,
    )
