"""Session telemetry: track repairs, fallbacks, and bridge failures."""

from dataclasses import dataclass


@dataclass
class Telemetry:
    repair_attempts: int = 0
    fallback_activations: int = 0
    total_turns: int = 0
    bridge_failures: int = 0
    compactions: int = 0
    failed_turns: int = 0

    def record_repair(self) -> None:
        self.repair_attempts += 1

    def record_fallback(self) -> None:
        self.fallback_activations += 1

    def record_turn(self) -> None:
        self.total_turns += 1

    def retract_turn(self) -> None:
        self.total_turns -= 1

    def record_bridge_failure(self) -> None:
        self.bridge_failures += 1

    def record_compaction(self) -> None:
        self.compactions += 1

    def record_failed_turn(self) -> None:
        self.failed_turns += 1

    def summary(self) -> str:
        return (
            f"Turns: {self.total_turns} | "
            f"Repairs: {self.repair_attempts} | "
            f"Fallbacks: {self.fallback_activations} | "
            f"Bridge failures: {self.bridge_failures} | "
            f"Compactions: {self.compactions} | "
            f"Failed turns: {self.failed_turns}"
        )
