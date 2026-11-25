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


def _flop_texture_vector(cards: list[str]) -> tuple[int, int, int, int, int, int]:
    """Extract a 6-element texture vector for flop clustering."""
    ranks = sorted([RANK_VAL.get(c[0].upper(), 0) for c in cards], reverse=True)
    is_paired = 1 if (ranks[0] == ranks[1] or ranks[1] == ranks[2]) else 0
    suits = [c[1].lower() for c in cards]
    max_suit = max(suits.count(s) for s in suits) if suits else 0
    is_monotone = 1 if max_suit == 3 else 0
    is_two_tone = 1 if max_suit == 2 else 0
    is_connected = 1 if (ranks[0] - ranks[2] <= 4 and len(set(ranks)) == 3) else 0
    return (ranks[0], ranks[1], is_paired, is_monotone, is_two_tone, is_connected)


def _texture_distance(t1: tuple, t2: tuple) -> float:
    """Weighted distance between two flop texture vectors."""
    d_high = abs(t1[0] - t2[0]) * 2.0
    d_mid = abs(t1[1] - t2[1]) * 1.5
    d_pair = abs(t1[2] - t2[2]) * 4.0
    d_mono = abs(t1[3] - t2[3]) * 5.0
    d_two_tone = abs(t1[4] - t2[4]) * 3.0
    d_conn = abs(t1[5] - t2[5]) * 2.0
    return d_high + d_mid + d_pair + d_mono + d_two_tone + d_conn


class FlopDatabase:
    """In-memory loader and query engine for precomputed 1,755 canonical flops and GTOpen 47 clusters."""

    def __init__(
        self,
        db_path: str | Path = "data/postflop_db/flops_1755.json",
        gtopen_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        if gtopen_path is None:
            p49 = Path("data/flop_db/gtopen_49_flops.json")
            p47 = Path("data/flop_db/gtopen_47_flops.json")
            self.gtopen_path = p49 if p49.exists() else p47
        else:
            self.gtopen_path = Path(gtopen_path)
        self.db: dict[str, dict] = {}
        self.gtopen_db: dict[str, dict] = {}

        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.db = json.load(f)
            except Exception:
                self.db = {}

        if self.gtopen_path.exists():
            try:
                with open(self.gtopen_path, "r", encoding="utf-8") as f:
                    self.gtopen_db = json.load(f)
            except Exception:
                self.gtopen_db = {}

    def lookup_nearest_flop(
        self,
        board_cards: list[str],
        spot: str,
        hero_cards: list[str],
        node_type: str | None = None,
    ) -> dict[str, float] | None:
        """Find strategy from GTOpen flop database matching exact or nearest cluster.

        Args:
            board_cards: 3 board cards (e.g. ["Ah", "7d", "2c"]).
            spot: Postflop spot name (e.g. "BTN_vs_BB_SRP", "SB_vs_BB_LIMPED").
            hero_cards: 2 hero hole cards (e.g. ["As", "Kh"]).
            node_type: Optional node key ("oop_root", "ip_after_check", "oop_vs_cbet").

        Returns:
            Dictionary of candidate EVs or action frequencies (e.g. {"CHECK": 0.4, "BET_30": 0.6, "ALL_IN": 0.0})
            or None if database empty or spot not found.
        """
        if not self.gtopen_db or len(board_cards) != 3 or len(hero_cards) != 2:
            return None

        spot_db = self.gtopen_db.get(spot)
        if (not spot_db or not isinstance(spot_db, dict)) and (spot.endswith("_6BB") or spot.endswith("_18BB")):
            base_spot = spot.rsplit("_", 1)[0]
            spot_db = self.gtopen_db.get(base_spot)
        if not spot_db or not isinstance(spot_db, dict):
            return None

        # 1. Exact canonical or direct key match
        exact_entry = None
        try:
            canon_key, _ = canonicalize_flop(board_cards)
            if canon_key in spot_db:
                exact_entry = spot_db[canon_key]
        except Exception:
            pass

        if exact_entry is None:
            raw_key1 = "".join([f"{c[0].upper()}{c[1].lower()}" for c in board_cards])
            raw_key2 = " ".join([f"{c[0].upper()}{c[1].lower()}" for c in board_cards])
            if raw_key1 in spot_db:
                exact_entry = spot_db[raw_key1]
            elif raw_key2 in spot_db:
                exact_entry = spot_db[raw_key2]

        selected_entry = exact_entry
        if selected_entry is None:
            # 2. Nearest cluster by flop texture distance
            target_tex = _flop_texture_vector(board_cards)
            best_dist = float("inf")
            best_key = None
            for f_key in spot_db.keys():
                cards = [p.strip() for p in f_key.replace(",", " ").split() if len(p.strip()) == 2]
                if len(cards) != 3 and len(f_key) == 6:
                    cards = [f_key[0:2], f_key[2:4], f_key[4:6]]
                if len(cards) == 3:
                    cand_tex = _flop_texture_vector(cards)
                    dist = _texture_distance(target_tex, cand_tex)
                    if dist < best_dist:
                        best_dist = dist
                        best_key = f_key
            if best_key is not None:
                selected_entry = spot_db[best_key]

        if not selected_entry or not isinstance(selected_entry, dict):
            return None

        if node_type and isinstance(selected_entry.get("nodes"), dict):
            if node_type in selected_entry["nodes"] and isinstance(selected_entry["nodes"][node_type], dict):
                selected_entry = selected_entry["nodes"][node_type]
            elif node_type in ("ip_after_check", "oop_vs_cbet"):
                return None

        # Direct hero cards lookup (e.g. "AsKh" or "KhAs")
        h1 = f"{hero_cards[0][0].upper()}{hero_cards[0][1].lower()}"
        h2 = f"{hero_cards[1][0].upper()}{hero_cards[1][1].lower()}"
        for dk in (f"{h1}{h2}", f"{h2}{h1}"):
            if dk in selected_entry and isinstance(selected_entry[dk], dict):
                sub = selected_entry[dk]
                if "evs" in sub and isinstance(sub["evs"], dict):
                    return {k: float(v) for k, v in sub["evs"].items()}
                return {k: float(v) for k, v in sub.items() if k in ("CHECK", "BET_30", "BET_MED", "ALL_IN", "CALL", "FOLD")}

        # Hand category classification (MONSTER, STRONG, MEDIUM, DRAW, AIR)
        from engine.range_engine import classify_combo
        cat = classify_combo(hero_cards[0], hero_cards[1], board_cards)
        if cat in selected_entry and isinstance(selected_entry[cat], dict):
            sub = selected_entry[cat]
            if "evs" in sub and isinstance(sub["evs"], dict):
                return {k: float(v) for k, v in sub["evs"].items()}
            return {k: float(v) for k, v in sub.items() if k in ("CHECK", "BET_30", "BET_MED", "ALL_IN", "CALL", "FOLD")}

        if "evs" in selected_entry and isinstance(selected_entry["evs"], dict):
            return {k: float(v) for k, v in selected_entry["evs"].items()}

        if any(k in selected_entry for k in ("CHECK", "BET_30", "ALL_IN", "CALL", "FOLD")):
            return {k: float(selected_entry[k]) for k in ("CHECK", "BET_30", "BET_MED", "ALL_IN", "CALL", "FOLD") if k in selected_entry}

        return None

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
