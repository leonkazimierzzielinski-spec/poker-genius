"""GTOpen range importer and schema adapter for poker_assistant preflop and flop databases.

Usage:
    python tools/import_gtopen.py --range "AA,KK,QQ,AKs,A5s-A2s,KQs:0.5" --stack 12 --spot BTN_OPEN --action MIN_RAISE
    python tools/import_gtopen.py --input gtopen_export.json --target data/preflop_tables/nash_3max.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

RANKS = "23456789TJQKA"
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}


def expand_range_token(token: str) -> list[tuple[str, float]]:
    """Parse a single range token like 'AA', '77+', 'A5s-A2s', 'KQs:0.5' into a list of (hand, weight)."""
    token = token.strip()
    if not token:
        return []

    weight = 1.0
    if ":" in token:
        parts = token.split(":")
        token = parts[0].strip()
        try:
            weight = float(parts[1])
        except ValueError:
            weight = 1.0

    # Dash range, e.g. A5s-A2s, TT-77, KJo-K8o
    if "-" in token:
        m = re.match(r"^([2-9TJQKA]{2}[so]?)-([2-9TJQKA]{2}[so]?)$", token)
        if m:
            h1, h2 = m.group(1), m.group(2)
            if len(h1) == 2 and len(h2) == 2 and h1[0] == h1[1] and h2[0] == h2[1]:
                # Pairs dash: TT-77
                r1_idx, r2_idx = RANK_INDEX[h1[0]], RANK_INDEX[h2[0]]
                lo, hi = min(r1_idx, r2_idx), max(r1_idx, r2_idx)
                return [(f"{RANKS[i]}{RANKS[i]}", weight) for i in range(hi, lo - 1, -1)]
            elif len(h1) == 3 and len(h2) == 3 and h1[0] == h2[0] and h1[2] == h2[2]:
                # Suited/offsuit fixed high card: A5s-A2s
                hi_card = h1[0]
                typ = h1[2]
                r1_idx, r2_idx = RANK_INDEX[h1[1]], RANK_INDEX[h2[1]]
                lo, hi = min(r1_idx, r2_idx), max(r1_idx, r2_idx)
                return [(f"{hi_card}{RANKS[i]}{typ}", weight) for i in range(hi, lo - 1, -1)]

    # Plus range, e.g. 77+, ATs+, KJo+
    if token.endswith("+"):
        base = token[:-1]
        if len(base) == 2 and base[0] == base[1]:
            # Pairs 77+
            idx = RANK_INDEX[base[0]]
            return [(f"{RANKS[i]}{RANKS[i]}", weight) for i in range(idx, len(RANKS))]
        elif len(base) == 3:
            hi_card = base[0]
            lo_card = base[1]
            typ = base[2]
            hi_idx = RANK_INDEX[hi_card]
            lo_idx = RANK_INDEX[lo_card]
            return [(f"{hi_card}{RANKS[i]}{typ}", weight) for i in range(lo_idx, hi_idx)]

    return [(token, weight)]


def parse_range_string(range_str: str, min_weight: float = 0.40) -> list[str]:
    """Expand a full GTOpen comma-separated range string into canonical hands."""
    tokens = [t.strip() for t in range_str.split(",") if t.strip()]
    res = []
    seen = set()
    for t in tokens:
        expanded = expand_range_token(t)
        for hand, w in expanded:
            if w >= min_weight and hand not in seen:
                seen.add(hand)
                res.append(hand)
    return res


def import_gtopen_to_preflop_json(
    range_input: str | Path,
    target_json: str | Path = "data/preflop_tables/nash_3max.json",
    stack_depth: str = "12",
    spot_name: str = "BTN_OPEN",
    action_name: str = "MIN_RAISE",
) -> Path:
    """Import range from string or json file into the preflop Nash database."""
    target_p = Path(target_json)
    if target_p.exists():
        with open(target_p, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    in_path = Path(str(range_input))
    if in_path.exists() and in_path.is_file():
        text = in_path.read_text(encoding="utf-8")
        try:
            parsed = json.load(open(in_path, "r", encoding="utf-8"))
            if isinstance(parsed, dict) and "ranges" in parsed:
                # GTOpen multi-range export format
                for sp, act_dict in parsed["ranges"].items():
                    data.setdefault(stack_depth, {}).setdefault(sp, {})
                    for act, r_str in act_dict.items():
                        hands = parse_range_string(r_str)
                        data[stack_depth][sp][act] = hands
                target_p.parent.mkdir(parents=True, exist_ok=True)
                with open(target_p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return target_p
        except Exception:
            pass
        hands = parse_range_string(text)
    else:
        hands = parse_range_string(str(range_input))

    data.setdefault(str(stack_depth), {}).setdefault(str(spot_name), {})
    data[str(stack_depth)][str(spot_name)][str(action_name)] = hands

    target_p.parent.mkdir(parents=True, exist_ok=True)
    with open(target_p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return target_p


def main() -> None:
    parser = argparse.ArgumentParser(description="Import GTOpen ranges into poker_assistant tables.")
    parser.add_argument("--range", dest="range_str", default="", help="Comma separated range string.")
    parser.add_argument("--input", dest="input_file", default="", help="Path to input file.")
    parser.add_argument("--target", default="data/preflop_tables/nash_3max.json", help="Target JSON file.")
    parser.add_argument("--stack", default="12", help="Stack depth (e.g. 15, 12, 10, 8, 6, 4).")
    parser.add_argument("--spot", default="BTN_OPEN", help="Spot name (e.g. BTN_OPEN, BB_ISO_VS_LIMP).")
    parser.add_argument("--action", default="MIN_RAISE", help="Action name (e.g. MIN_RAISE, ALL_IN, CALL).")

    args = parser.parse_args()

    source = args.input_file if args.input_file else args.range_str
    if not source:
        print("Please provide --range or --input")
        return

    out = import_gtopen_to_preflop_json(
        range_input=source,
        target_json=args.target,
        stack_depth=args.stack,
        spot_name=args.spot,
        action_name=args.action,
    )
    print(f"Successfully imported GTOpen range into: {out}")


if __name__ == "__main__":
    main()
