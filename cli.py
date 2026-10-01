"""dungeon-cli entrypoint and game loop."""

import tomllib
from collections.abc import Callable
from pathlib import Path

from dm.bridge import HTTPBridge, LLMBridge
from dm.contract import ContractError, parse
from dm.prompt import PromptContext, TurnRecord, build_turn, compact, split_system
from dm.repair import FALLBACK, repair
from engine.adjudicate import apply_requests, check_status
from engine.campaign import list_campaigns, make_victory_condition
from engine.rules import Dice
from engine.state import GameState
from ui import character_creation, menu
from ui.input import get_input, parse_input
from ui.render import (
    render_choices,
    render_epilogue,
    render_message,
    render_narration,
    render_status,
)
from ui.export import default_export_path, export_transcript
from ui.spinner import Spinner
from ui.telemetry import Telemetry


def load_config() -> dict:
    """Load dungeon-cli.toml config."""
    config_path = Path("dungeon-cli.toml")
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def make_bridge(config: dict) -> LLMBridge:
    """Create LLM bridge from config (subprocess or direct HTTP)."""
    llm = config["llm"]
    if llm.get("provider") == "http":
        http = llm.get("http", {}) or {}
        if "base_url" not in http:
            raise ValueError("llm.http.base_url is required when provider = 'http'")
        if "model" not in llm:
            raise ValueError("llm.model is required when provider = 'http'")
        return HTTPBridge(
            base_url=http["base_url"],
            api_key=http.get("api_key", ""),
            model=llm["model"],
            timeout=llm.get("timeout", 30),
            retries=llm.get("retries", 2),
            sampling={k: http[k] for k in ("temperature", "max_tokens", "top_p", "seed") if k in http},
            headers=http.get("headers"),
            system_role=bool(llm.get("system_role", False)),
        )
    if "argv" not in llm:
        raise ValueError("llm.argv is required for the default subprocess provider")
    return LLMBridge(
        argv=llm["argv"],
        timeout=llm.get("timeout", 30),
        retries=llm.get("retries", 2),
    )


def handle_command(cmd: str, state: GameState, save_path: Path, telemetry: Telemetry | None = None) -> str:
    """Handle a slash command. Returns action to take."""
    command = cmd.lower().split()[0]

    if command == "/quit":
        state.save(save_path)
        render_message("Game saved. Goodbye!", style="bold yellow")
        return "quit"

    elif command == "/save":
        state.save(save_path)
        render_message("Game saved.", style="green")
        return "continue"

    elif command == "/load":
        if save_path.exists():
            try:
                loaded = GameState.load(save_path)
            except (OSError, ValueError, KeyError, TypeError) as e:
                render_message(f"Save file could not be loaded ({type(e).__name__}).", style="red")
                return "continue"
            state.update_from(loaded)
            render_message("Game loaded.", style="green")
            return "load"
        else:
            render_message("No save file found.", style="red")
            return "continue"

    elif command == "/help":
        render_message(
            "Commands: /help, /save, /load, /quit, /stats, /retry",
            style="dim",
        )
        return "continue"

    elif command == "/stats":
        stats = (
            f"Name: {state.player.name} | HP: {state.player.hp}/{state.player.max_hp} | "
            f"Location: {state.player.location} | Inventory: {', '.join(state.player.inventory) or 'empty'}"
        )
        render_message(stats)
        if telemetry:
            render_message(telemetry.summary(), style="dim")
        return "continue"

    elif command == "/retry":
        return "retry"

    else:
        render_message(f"Unknown command: {command}", style="red")
        return "continue"


def _safe_save(state: GameState, save_path: Path) -> None:
    """Save state, converting OS-level save failures into a message instead of a crash."""
    try:
        state.save(save_path)
    except OSError as e:
        render_message(f"Save failed: {e}", style="red")


def game_loop(
    state: GameState,
    context: PromptContext,
    bridge: LLMBridge,
    config: dict,
    save_path: Path,
    victory_condition: Callable[[GameState], bool],
    campaign_title: str = "Campaign",
) -> None:
    """Core game loop."""
    prompt_config = config.get("prompt", {})
    budget = prompt_config.get("budget", 8000)
    recent_limit = prompt_config.get("recent_turns", 5)
    compact_after = prompt_config.get("compact_after", recent_limit * 2)
    ui_config = config.get("ui", {})
    typewriter = ui_config.get("typewriter", False)
    typewriter_delay = ui_config.get("typewriter_delay", 0.02)
    use_spinner = ui_config.get("spinner", True)

    telemetry = Telemetry()
    history: list[TurnRecord] = []
    last_action = None
    last_state = None
    last_record: TurnRecord | None = None
    choices = []

    while True:
        render_status(state)
        render_choices(choices)

        try:
            user_input = parse_input(get_input(choices), choices)
        except (KeyboardInterrupt, EOFError):
            _safe_save(state, save_path)
            render_message("\nGame saved. Goodbye!", style="bold yellow")
            return

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, state, save_path, telemetry)
            if result == "quit":
                return
            if result == "load":
                choices = []
                # BUG-006: drop all session context from the discarded timeline
                context.recent_turns = []
                context.story_so_far = ""
                history.clear()
                last_state = None
                last_action = None
                last_record = None
                continue
            if result == "retry":
                if last_state is not None and last_action is not None:
                    # BUG-005: replace the previous attempt's record instead of duplicating it
                    if last_record is not None:
                        if context.recent_turns and context.recent_turns[-1] is last_record:
                            context.recent_turns.pop()
                            telemetry.retract_turn()
                        if history and history[-1] is last_record:
                            history.pop()
                        last_record = None
                    state.update_from(last_state)
                    user_input = last_action
                    choices = []
                else:
                    render_message("Nothing to retry.", style="dim")
                    continue
            else:
                continue

        # Store for retry
        last_state = state.clone()
        last_action = user_input

        # Build prompt and call bridge
        prompt = build_turn(user_input, state, context, budget, recent_limit)
        if getattr(bridge, "system_role", False):
            system, prompt = split_system(prompt)
        else:
            system = None
        if use_spinner:
            with Spinner("The DM is thinking..."):
                result = bridge.ask(prompt, system)
        else:
            result = bridge.ask(prompt, system)

        # Parse/repair
        if result.ok:
            try:
                dm_resp = parse(result.raw)
            except ContractError as e:
                dm_resp = repair(result.raw, str(e), bridge, telemetry=telemetry)
        else:
            telemetry.record_bridge_failure()
            dm_resp = FALLBACK

        if dm_resp is FALLBACK:
            # No usable DM response: render-only, the turn is not consumed or counted.
            telemetry.record_failed_turn()
            last_record = None
            render_narration(FALLBACK.narration, typewriter=typewriter, delay=typewriter_delay)
            render_message(
                "— the DM could not respond. Your action was not processed and the "
                "turn was not counted. Type it again, or use /retry.",
                style="dim",
            )
            continue

        telemetry.record_turn()

        # Adjudicate
        dice = Dice()
        new_state = apply_requests(state, dm_resp.state_requests, dice)
        status = check_status(new_state, dm_resp.status, victory_condition)

        # Update state and history
        state.update_from(new_state)
        turn_record = TurnRecord(
            turn=state.turn,
            action=user_input,
            narration=dm_resp.narration,
            state_summary=f"HP: {state.player.hp}/{state.player.max_hp} | Location: {state.player.location}",
        )
        context.recent_turns.append(turn_record)
        history.append(turn_record)
        last_record = turn_record

        # Render
        render_narration(dm_resp.narration, typewriter=typewriter, delay=typewriter_delay)
        choices = dm_resp.choices

        # Check for death/victory
        if status in ("dead", "victory"):
            render_epilogue(status, dm_resp.narration)
            _offer_export(state, history, campaign_title, save_path.parent)
            return

        # Compact old turns into story_so_far, keeping the last recent_limit verbatim
        if len(context.recent_turns) >= compact_after:
            if use_spinner:
                with Spinner("The DM is summarizing..."):
                    new_ctx = compact(context, bridge, keep=recent_limit)
            else:
                new_ctx = compact(context, bridge, keep=recent_limit)
            if new_ctx is not context:
                # Mutate in place so the caller's context object stays live
                context.story_so_far = new_ctx.story_so_far
                context.recent_turns = new_ctx.recent_turns
                telemetry.record_compaction()


def _offer_export(
    state: GameState,
    history: list[TurnRecord],
    campaign_title: str,
    save_dir: Path,
) -> None:
    """Offer to export transcript on game end."""
    render_message("\nExport transcript? (y/n)", style="dim")
    try:
        choice = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice == "y":
        path = default_export_path(state, save_dir)
        export_transcript(state, history, campaign_title, path)
        render_message(f"Transcript saved to {path}", style="green")


def main() -> None:
    """Entrypoint."""
    config = load_config()
    bridge = make_bridge(config)

    save_dir = Path(config["llm"].get("save_dir", "./saves"))
    save_dir.mkdir(parents=True, exist_ok=True)

    campaigns = list_campaigns()
    if not campaigns:
        render_message("No campaigns found in content/ directory.", style="red")
        return

    while True:
        try:
            choice = menu.main_menu()
            if choice == "quit":
                return
            campaign = menu.pick_campaign(campaigns)
        except (EOFError, KeyboardInterrupt):
            render_message("\nGoodbye!", style="bold yellow")
            return

        campaign_save_dir = save_dir / campaign.id
        campaign_save_dir.mkdir(parents=True, exist_ok=True)
        save_path = campaign_save_dir / "game.json"

        try:
            if choice == "continue":
                loaded = None
                if save_path.exists():
                    try:
                        loaded = GameState.load(save_path)
                    except (OSError, ValueError, KeyError, TypeError) as e:
                        render_message(
                            f"Save file could not be loaded ({type(e).__name__}). Starting new game.",
                            style="yellow",
                        )
                if loaded is not None:
                    state = loaded
                    # BUG-007: resolve the saved character's actual archetype
                    archetype = next(
                        (a for a in campaign.archetypes if a.name == state.player.archetype),
                        campaign.archetypes[0],
                    )
                    context = character_creation._build_context(campaign, state.player.name, archetype)
                else:
                    if not save_path.exists():
                        render_message("No save file found. Starting new game.", style="yellow")
                    state, context = character_creation.create_character(campaign)
            else:
                state, context = character_creation.create_character(campaign)
        except (EOFError, KeyboardInterrupt):
            render_message("\nGoodbye!", style="bold yellow")
            return

        victory_cond = make_victory_condition(campaign)

        try:
            game_loop(state, context, bridge, config, save_path, victory_cond, campaign.title)
        except (KeyboardInterrupt, EOFError):
            _safe_save(state, save_path)
            render_message("\nGame saved. Goodbye!", style="bold yellow")


if __name__ == "__main__":
    main()
