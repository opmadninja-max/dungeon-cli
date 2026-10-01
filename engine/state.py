"""Game state: player, world, flags, turn counter, event log."""

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Room:
    id: str
    name: str
    description: str


@dataclass
class Player:
    name: str
    hp: int
    max_hp: int
    inventory: list[str] = field(default_factory=list)
    location: str = ""
    archetype: str = ""


@dataclass
class Event:
    turn: int
    type: str
    detail: str


@dataclass
class GameState:
    player: Player
    rooms: dict[str, Room] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    turn: int = 0
    log: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "player": asdict(self.player),
            "rooms": {k: asdict(v) for k, v in self.rooms.items()},
            "flags": self.flags,
            "turn": self.turn,
            "log": [asdict(e) for e in self.log],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        # Tolerant load: ignore unknown player keys so older/newer saves still load
        player_data = {k: v for k, v in data["player"].items() if k in Player.__dataclass_fields__}
        player = Player(**player_data)
        rooms = {k: Room(**v) for k, v in data.get("rooms", {}).items()}
        log = [Event(**e) for e in data.get("log", [])]
        return cls(
            player=player,
            rooms=rooms,
            flags=data.get("flags", {}),
            turn=data.get("turn", 0),
            log=log,
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp_path, path)

    @classmethod
    def load(cls, path: Path) -> "GameState":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def clone(self) -> "GameState":
        return copy.deepcopy(self)

    def update_from(self, other: "GameState") -> None:
        """Copy all mutable fields from other into self (in place)."""
        self.player = other.player
        self.rooms = other.rooms
        self.flags = other.flags
        self.turn = other.turn
        self.log = other.log
