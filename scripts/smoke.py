"""Smoke test: verify the configured LLM provider is reachable."""

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli import make_bridge  # noqa: E402

PROMPT = "Reply with the single word: OK"


def main() -> int:
    config_path = Path(__file__).parent.parent / "dungeon-cli.toml"
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    try:
        bridge = make_bridge(config)
    except (ValueError, KeyError) as e:
        print(f"ERROR: Invalid configuration: {e}")
        return 1

    print(f"Provider: {bridge.__class__.__name__}")
    print(f"Prompt: {PROMPT!r}")

    result = bridge.ask(PROMPT)
    if not result.ok:
        print(f"ERROR: Bridge failed after {result.attempts} attempt(s): {result.error}")
        return 1

    print(f"Response: {result.raw!r}")

    if "OK" in result.raw:
        print("SMOKE TEST PASSED")
        return 0

    print("ERROR: Response did not contain 'OK'")
    return 1


if __name__ == "__main__":
    sys.exit(main())
