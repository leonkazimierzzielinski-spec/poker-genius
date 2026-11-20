"""Flop database and isomorphism reducer for 1,755 canonical flops."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}
ALL_SUITS = ("c", "d", "h", "s")


def canonicalize_flop(board_cards: list[str]) -> tuple[str, dict[str, str]]:
    """Convert any 3-card flop into its canonical representation under suit isomorphism.

    Cards are sorted descending by rank. When ranks are equal, cards are sorted
    by suit frequency on the board descending, then by suit letter deterministically.
    Suits are mapped to 'a', 'b', 'c' in order of appearance.

    Example:
        canonicalize_flop(["Qd", "Qs", "8d"]) -> ("QaQb8a", {"d": "a", "s": "b"})

    Args:
        board_cards: List of exactly 3 card strings (e.g. ["Qd", "Qs", "8d"]).

    Returns:
        Tuple of (canonical_flop_key, suit_mapping).

    Raises:
        ValueError: If board_cards does not contain exactly 3 cards.
    """
    if len(board_cards) != 3:
        raise ValueError(f"Flop must contain exactly 3 cards, got {len(board_cards)}")

    # Normalize card representation
    norm_cards = [f"{c[0].upper()}{c[1].lower()}" for c in board_cards]

    # Calculate suit frequencies on the flop
    suits = [c[1] for c in norm_cards]
    suit_counts = {s: suits.count(s) for s in suits}

    # Sort:
    # 1. Higher rank first (-RANK_VAL[c[0]])
    # 2. More frequent suit first (-suit_counts[c[1]])
    # 3. Deterministic suit tie breaker (c[1])
    sorted_cards = sorted(
        norm_cards,
        key=lambda c: (-RANK_VAL[c[0]], -suit_counts[c[1]], c[1]),
    )

    suit_map: dict[str, str] = {}
    letters = "abc"
    idx = 0
    key_parts: list[str] = []

    for c in sorted_cards:
        s = c[1]
        if s not in suit_map:
            suit_map[s] = letters[idx]
            idx += 1
        key_parts.append(f"{c[0]}{suit_map[s]}")

    return "".join(key_parts), suit_map


def generate_all_1755_flops() -> list[str]:
    """Generate all 1,755 canonical flops from the 22,100 possible 3-card combinations.

    Returns:
        Sorted list of exactly 1,755 canonical flop strings.
    """
    deck = [f"{r}{s}" for r in RANKS for s in ALL_SUITS]
    unique_flops: set[str] = set()

    for combo in itertools.combinations(deck, 3):
        key, _ = canonicalize_flop(list(combo))
        unique_flops.add(key)

    return sorted(unique_flops)


class FlopDatabase:
    """In-memory loader and query engine for precomputed 1,755 canonical flops."""

    def __init__(self, db_path: str | Path = "data/postflop_db/flops_1755.json") -> None:
        self.db_path = Path(db_path)
        self.db: dict[str, dict] = {}

        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.db = json.load(f)
            except Exception:
                self.db = {}

    def lookup(
        self,
        board_cards: list[str],
        hero_cards: list[str],
        effective_bb: float,
    ) -> dict[str, float] | None:
        """Query strategy for a specific flop and hero hand.

        Args:
            board_cards: 3 board cards.
            hero_cards: 2 hero hole cards.
            effective_bb: Effective stack depth in BB.

        Returns:
            Dictionary of frequencies/EV for actions (e.g. {"CHECK": 0.4, "BET_30": 0.6, "ALL_IN": 0.0})
            or None if not found or DB empty.
        """
        if not self.db or len(board_cards) != 3 or len(hero_cards) != 2:
            return None

        try:
            flop_key, suit_map = canonicalize_flop(board_cards)
        except Exception:
            return None

        if flop_key not in self.db:
            return None

        flop_entry = self.db[flop_key]

        # Check if flop_entry directly provides action distribution
        if all(k in flop_entry for k in ("CHECK", "BET_30", "ALL_IN")):
            return {k: float(flop_entry[k]) for k in ("CHECK", "BET_30", "ALL_IN")}

        # Map hero cards to canonical suits
        full_map = dict(suit_map)
        assigned_letters = set(suit_map.values())
        avail_letters = [l for l in ("a", "b", "c", "d") if l not in assigned_letters]
        avail_suits = [s for s in ALL_SUITS if s not in suit_map]

        for s, l in zip(avail_suits, avail_letters):
            full_map[s] = l

        h1 = f"{hero_cards[0][0].upper()}{full_map.get(hero_cards[0][1].lower(), 'd')}"
        h2 = f"{hero_cards[1][0].upper()}{full_map.get(hero_cards[1][1].lower(), 'd')}"

        # Sort hero cards by rank
        if RANK_VAL.get(h1[0], 0) < RANK_VAL.get(h2[0], 0):
            h1, h2 = h2, h1
        hero_key = f"{h1}{h2}"

        # Try looking up in nested structures
        # Structure 1: flop_entry[hero_key]
        if hero_key in flop_entry:
            val = flop_entry[hero_key]
            if isinstance(val, dict):
                return {k: float(v) for k, v in val.items()}

        # Structure 2: flop_entry[stack_str][hero_key]
        stack_keys = [k for k in flop_entry.keys() if k.replace(".", "", 1).isdigit()]
        if stack_keys:
            stack_floats = [float(k) for k in stack_keys]
            closest_stack = min(stack_floats, key=lambda s: abs(s - effective_bb))
            closest_key = str(int(closest_stack)) if closest_stack.is_integer() else str(closest_stack)
            if closest_key in flop_entry and hero_key in flop_entry[closest_key]:
                val = flop_entry[closest_key][hero_key]
                if isinstance(val, dict):
                    return {k: float(v) for k, v in val.items()}

        return None
