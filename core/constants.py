"""Domain constants for poker_assistant."""

TOTAL_CHIPS: int = 900
STARTING_STACK: int = 300
BLIND_LEVELS: list[tuple[int, int]] = [
    (10, 20),
    (15, 30),
    (20, 40),
    (30, 60),
    (40, 80),
    (50, 100),
    (60, 120),
]
CARD_MATCH_THRESHOLD: float = 0.92
EV_LOSS_THRESHOLD_BB: float = 0.08
RANKS: str = "23456789TJQKA"
SUITS: str = "cdhs"
VALID_STREETS: tuple[str, ...] = (
    "PREFLOP",
    "FLOP",
    "TURN",
    "RIVER",
    "WAITING_FOR_TURN",
)
VALID_ACTIONS: tuple[str, ...] = (
    "FOLD",
    "CHECK",
    "CALL",
    "MIN_RAISE",
    "BET_30",
    "ALL_IN",
    "WAIT",
)
VALID_PROFILES: tuple[str, ...] = (
    "LOOSE_CALLERS",
    "STANDARD_EXPLOIT",
    "HIGH_STEAL",
)
