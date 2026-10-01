"""Campaign loading, validation, and victory conditions."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.state import GameState, Player, Room


@dataclass
class Archetype:
    name: str
    hp: int
    items: list[str]
    flavor: str


@dataclass
class Campaign:
    id: str
    title: str
    genre: str
    world_seed: str
    goal: str
    victory_room: str
    starting_room: str
    rooms: dict[str, Room]
    archetypes: list[Archetype]
    dm_style: str
    opening_narration: str


REQUIRED_KEYS = ["id", "title", "world_seed", "goal", "victory_room", "starting_room", "rooms", "archetypes", "dm_style", "opening_narration"]


def validate_campaign(data: dict) -> list[str]:
    """Validate campaign data. Returns list of error strings."""
    errors = []

    for key in REQUIRED_KEYS:
        if key not in data:
            errors.append(f"Missing required key: {key}")

    if "rooms" in data:
        if not isinstance(data["rooms"], list) or not data["rooms"]:
            errors.append("'rooms' must be a non-empty list")
        else:
            room_ids = []
            for i, room in enumerate(data["rooms"]):
                if "id" not in room:
                    errors.append(f"Room {i} missing 'id'")
                else:
                    room_ids.append(room["id"])
                if "name" not in room:
                    errors.append(f"Room {i} missing 'name'")
                if "description" not in room:
                    errors.append(f"Room {i} missing 'description'")
            if "victory_room" in data and data["victory_room"] not in room_ids:
                errors.append(f"victory_room '{data['victory_room']}' not found in rooms")
            if "starting_room" in data and data["starting_room"] not in room_ids:
                errors.append(f"starting_room '{data['starting_room']}' not found in rooms")

    if "archetypes" in data:
        if not isinstance(data["archetypes"], list) or not data["archetypes"]:
            errors.append("'archetypes' must be a non-empty list")
        else:
            for i, arch in enumerate(data["archetypes"]):
                if "name" not in arch:
                    errors.append(f"Archetype {i} missing 'name'")
                if "hp" not in arch:
                    errors.append(f"Archetype {i} missing 'hp'")
                if "items" not in arch:
                    errors.append(f"Archetype {i} missing 'items'")

    return errors


def load_campaign(path: Path) -> Campaign:
    """Load and validate a campaign from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    errors = validate_campaign(data)
    if errors:
        raise ValueError(f"Invalid campaign: {'; '.join(errors)}")

    rooms = {}
    for r in data["rooms"]:
        rooms[r["id"]] = Room(id=r["id"], name=r["name"], description=r["description"])

    archetypes = [
        Archetype(
            name=a["name"],
            hp=a["hp"],
            items=a.get("items", []),
            flavor=a.get("flavor", ""),
        )
        for a in data["archetypes"]
    ]

    return Campaign(
        id=data["id"],
        title=data["title"],
        genre=data.get("genre", ""),
        world_seed=data["world_seed"],
        goal=data["goal"],
        victory_room=data["victory_room"],
        starting_room=data["starting_room"],
        rooms=rooms,
        archetypes=archetypes,
        dm_style=data.get("dm_style", ""),
        opening_narration=data.get("opening_narration", ""),
    )


def list_campaigns(directory: Path = Path("content")) -> list[Campaign]:
    """Load all campaign JSON files from a directory."""
    campaigns = []
    for path in sorted(directory.glob("*.json")):
        try:
            campaigns.append(load_campaign(path))
        except (ValueError, json.JSONDecodeError):
            continue
    return campaigns


def make_victory_condition(campaign: Campaign) -> Callable[[GameState], bool]:
    """Create a victory condition that checks if player is in the victory room."""
    victory_room = campaign.victory_room
    return lambda state: state.player.location == victory_room


def build_initial_state(campaign: Campaign, archetype: Archetype, name: str) -> GameState:
    """Build initial GameState from campaign + archetype."""
    return GameState(
        player=Player(
            name=name,
            hp=archetype.hp,
            max_hp=archetype.hp,
            inventory=list(archetype.items),
            location=campaign.starting_room,
            archetype=archetype.name,
        ),
        rooms=campaign.rooms,
        flags={},
        turn=0,
    )
