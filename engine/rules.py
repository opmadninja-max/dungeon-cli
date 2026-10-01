"""Dice and damage rules with injectable RNG."""

import random

SEVERITY_DAMAGE: dict[str, str] = {
    "minor": "1d4",
    "major": "1d8",
    "critical": "2d10",
}


class Dice:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def roll(self, sides: int) -> int:
        return self._rng.randint(1, sides)

    def roll_die(self, notation: str) -> int:
        """Parse 'XdY' notation and return the sum of rolls."""
        notation = notation.strip().lower()
        if "d" not in notation:
            raise ValueError(f"Invalid dice notation: {notation!r}")
        parts = notation.split("d")
        if len(parts) != 2:
            raise ValueError(f"Invalid dice notation: {notation!r}")
        count = int(parts[0]) if parts[0] else 1
        sides = int(parts[1])
        return sum(self.roll(sides) for _ in range(count))


def damage_for(severity: str, dice: Dice) -> int:
    """Calculate damage for a severity tier."""
    notation = SEVERITY_DAMAGE.get(severity, "1d4")
    return dice.roll_die(notation)
