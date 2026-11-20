"""Preflop Nash engine for 3-max Hyper-Turbo poker."""

from __future__ import annotations

import json
from pathlib import Path

RANKS = "23456789TJQKA"
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
VALID_SUITS = {"c", "d", "h", "s"}


def hand_to_canonical(cards: list[str]) -> str:
    """Convert two hole cards into canonical preflop notation.

    Examples:
        ["7c", "7d"] -> "77"
        ["Qh", "4h"] -> "Q4s"
        ["3c", "As"] -> "A3o"
        ["Kd", "Qc"] -> "KQo"

    Args:
        cards: List containing exactly 2 card strings (e.g. ["Ah", "Kd"]).

    Returns:
        Canonical hand representation string (e.g. "AA", "AKs", "72o").

    Raises:
        ValueError: If cards does not contain exactly 2 valid card strings.
    """
    if len(cards) != 2:
        raise ValueError(f"Expected exactly 2 cards, got {len(cards)}")

    c1, c2 = cards[0], cards[1]
    if len(c1) < 2 or len(c2) < 2:
        raise ValueError(f"Invalid card format: {cards}")

    r1, s1 = c1[0].upper(), c1[1].lower()
    r2, s2 = c2[0].upper(), c2[1].lower()

    if r1 not in RANK_INDEX or r2 not in RANK_INDEX:
        raise ValueError(f"Invalid card rank in cards: {cards}")

    if s1 not in VALID_SUITS or s2 not in VALID_SUITS:
        raise ValueError(f"Invalid card suit in cards: {cards}")

    # Equal rank -> Pocket Pair
    if r1 == r2:
        return f"{r1}{r2}"

    # Determine higher rank
    idx1, idx2 = RANK_INDEX[r1], RANK_INDEX[r2]
    if idx1 < idx2:
        r1, r2 = r2, r1
        s1, s2 = s2, s1

    # Suited vs Offsuit
    if s1 == s2:
        return f"{r1}{r2}s"
    return f"{r1}{r2}o"


class PreflopNashEngine:
    """Loads and queries preflop Nash equilibrium push/fold & raise tables."""

    def __init__(self, tables_path: str | Path = "data/preflop_tables/nash_3max.json") -> None:
        self.tables_path = Path(tables_path)
        self.tables: dict[str, dict[str, dict[str, set[str] | dict[str, float]]]] = {}
        self.ev_tables: dict[str, dict[str, dict[str, float]]] = {}
        self.available_stacks: list[float] = []

        self._load_tables()

    def _load_tables(self) -> None:
        if not self.tables_path.exists():
            raise FileNotFoundError(f"Nash preflop tables file not found at {self.tables_path}")

        with open(self.tables_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        for stack_str, spots in raw_data.items():
            try:
                stack_float = float(stack_str)
                self.available_stacks.append(stack_float)
            except ValueError:
                continue

            self.tables[stack_str] = {}
            self.ev_tables[stack_str] = {}

            for spot, actions in spots.items():
                self.tables[stack_str][spot] = {}
                self.ev_tables[stack_str][spot] = {}

                for action_key, val in actions.items():
                    if action_key == "ev":
                        if isinstance(val, dict):
                            self.ev_tables[stack_str][spot] = {
                                str(h): float(ev_val) for h, ev_val in val.items()
                            }
                    elif isinstance(val, list):
                        self.tables[stack_str][spot][action_key] = set(val)

        self.available_stacks.sort()

    def get_action(
        self,
        hero_cards: list[str],
        effective_bb: float,
        spot: str,
    ) -> tuple[str, float]:
        """Lookup Nash preflop action and estimated EV.

        Args:
            hero_cards: 2 cards held by Hero (e.g. ["As", "Kh"]).
            effective_bb: Effective stack depth in BB.
            spot: Preflop spot name ("BTN_OPEN", "SB_OPEN", "SB_VS_BTN_SHOVE", etc.).

        Returns:
            Tuple of (action_name, estimated_ev_bb).
        """
        canonical_hand = hand_to_canonical(hero_cards)

        if not self.available_stacks:
            return "FOLD", 0.0

        # Choose closest stack depth from table
        closest_stack = min(self.available_stacks, key=lambda s: abs(s - effective_bb))
        stack_key = str(int(closest_stack)) if closest_stack.is_integer() else str(closest_stack)
        if stack_key not in self.tables:
            # Fallback string representation
            stack_key = f"{closest_stack:.0f}"

        spot_tables = self.tables.get(stack_key, {}).get(spot, {})
        ev_map = self.ev_tables.get(stack_key, {}).get(spot, {})

        # Determine action by spot rules
        action = "FOLD"
        default_ev = 0.0

        if spot in ("BTN_OPEN", "SB_OPEN"):
            all_in_set = spot_tables.get("ALL_IN", set())
            min_raise_set = spot_tables.get("MIN_RAISE", set())

            # Priority: MIN_RAISE if defined and present, otherwise ALL_IN
            if canonical_hand in min_raise_set:
                action = "MIN_RAISE"
                default_ev = 0.50
            elif canonical_hand in all_in_set:
                action = "ALL_IN"
                default_ev = 0.45
            else:
                action = "FOLD"
                default_ev = 0.0

        elif spot in ("SB_VS_BTN_SHOVE", "BB_VS_BTN_SHOVE", "BB_VS_SB_SHOVE"):
            call_set = spot_tables.get("CALL", set())
            if canonical_hand in call_set:
                action = "CALL"
                default_ev = 0.45
            else:
                action = "FOLD"
                default_ev = 0.0

        elif spot == "BB_ISO_VS_LIMP":
            all_in_set = spot_tables.get("ALL_IN", set())
            if canonical_hand in all_in_set:
                action = "ALL_IN"
                default_ev = 0.45
            else:
                action = "CHECK"
                default_ev = 0.05

        else:
            # Generic spot fallback: check actions in order
            for act_name, hand_set in spot_tables.items():
                if canonical_hand in hand_set:
                    action = act_name
                    default_ev = 0.40
                    break

        if action == "FOLD":
            ev = 0.0
        else:
            ev = ev_map.get(canonical_hand, default_ev)

        return action, round(float(ev), 2)
