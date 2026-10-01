"""Input handling: parse freeform, number selection, slash commands."""


def get_input(choices: list[str]) -> str:
    """Get raw input from player."""
    try:
        return input("> ")
    except (KeyboardInterrupt, EOFError):
        raise


def parse_input(user_input: str, choices: list[str]) -> str:
    """Parse input into slash command, choice selection, or freeform action.

    Rules:
    1. Strip whitespace; empty → return empty (caller re-prompts)
    2. Starts with "/" → return as command
    3. Single digit within choices range → return choice text
    4. Otherwise → return as freeform action
    """
    text = user_input.strip()
    if not text:
        return ""

    if text.startswith("/"):
        return text

    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(choices):
            return choices[idx]

    return text
