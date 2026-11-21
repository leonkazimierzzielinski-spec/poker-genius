"""Data contracts (inter-module interfaces) for poker_assistant."""

from dataclasses import asdict, dataclass


@dataclass
class PlayerState:
    seat_id: int
    stack: int | None = None
    current_bet: int = 0
    is_dealer: bool = False
    is_active: bool = True
    status_text: str = "ACTIVE"
    last_reaction_ms: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TableState:
    table_id: str
    timestamp_ms: int
    prize_pool: float | int
    small_blind: int
    big_blind: int
    pot: int
    hero_cards: list[str]
    board_cards: list[str]
    street: str
    is_hero_turn: bool
    available_actions: list[str]
    players: dict[int, PlayerState]
    is_valid: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    table_id: str
    action: str
    ev_bb: float | None
    confidence: float
    profile_used: str
    reason: str
    sizing_chips: int | None = None
    sizing_bb: int | None = None
    alt_action: str | None = None
    alt_ev_bb: float | None = None
    alt_sizing_bb: int | None = None
    alt_sizing_chips: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)
