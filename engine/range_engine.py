"""Range-vs-Range postflop engine with MDA transition matrices and fast exact/MC equity."""

from __future__ import annotations

import random
import time
import zlib
from typing import Any

try:
    from phevaluator import evaluate_cards
except ImportError:
    evaluate_cards = None  # type: ignore[assignment]

RANKS = "23456789TJQKA"
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
FULL_DECK = [f"{r}{s}" for r in RANKS for s in "cdhs"]


def _norm_card(c: str) -> str:
    return f"{c[0].upper()}{c[1].lower()}"


def classify_combo(c1: str, c2: str, board_cards: list[str]) -> str:
    """Classify a 2-card combo on a given board into 5 strength categories:

    MONSTER (two pair or better), STRONG (top pair / overpair),
    MEDIUM (2nd/3rd pair, underpair, Ace-high), DRAW (FD / OESD), AIR (trash).
    """
    if evaluate_cards is None:
        return "MEDIUM"

    norm_board = [_norm_card(c) for c in board_cards]
    n1 = _norm_card(c1)
    n2 = _norm_card(c2)

    if len(norm_board) < 3:
        # Preflop: pocket pairs 88+ or AK are STRONG/MONSTER
        r1, r2 = RANK_INDEX[n1[0]], RANK_INDEX[n2[0]]
        if r1 == r2:
            return "MONSTER" if r1 >= RANK_INDEX["T"] else "STRONG"
        if r1 >= RANK_INDEX["Q"] and r2 >= RANK_INDEX["Q"]:
            return "STRONG"
        if n1[1] == n2[1]:
            return "DRAW"
        return "MEDIUM"

    score = evaluate_cards(n1, n2, *norm_board)

    # Two pair or better: Full house, flush, straight, three-of-a-kind, two-pair
    if score <= 3325:
        return "MONSTER"

    board_ranks = [RANK_INDEX[c[0]] for c in norm_board]
    max_board_rank = max(board_ranks)
    r1, r2 = RANK_INDEX[n1[0]], RANK_INDEX[n2[0]]

    # One pair category:
    if score <= 6185:
        # Overpair (pocket pair higher than highest board card)
        if r1 == r2 and r1 > max_board_rank:
            return "STRONG"
        # Top pair (one hole card matches highest board card)
        if r1 == max_board_rank or r2 == max_board_rank:
            return "STRONG"
        # 2nd pair, 3rd pair, bottom pair, or pocket pair below top card
        return "MEDIUM"

    # High card category: check for flush / straight draws
    all_cards = norm_board + [n1, n2]
    suits = [c[1] for c in all_cards]
    for s in "cdhs":
        if suits.count(s) >= 4:
            return "DRAW"

    # Straight draw (OESD or gutshot)
    distinct_ranks = sorted(set(RANK_INDEX[c[0]] for c in all_cards))
    # Check 4 ranks spanning <= 4 distance (straight draw)
    for i in range(len(distinct_ranks) - 3):
        span = distinct_ranks[i + 3] - distinct_ranks[i]
        if span <= 4:
            return "DRAW"

    # Ace-high
    if r1 == RANK_INDEX["A"] or r2 == RANK_INDEX["A"]:
        return "MEDIUM"

    return "AIR"


def get_preflop_villain_range(
    position: str = "BTN",
    preflop_action: str = "OPEN_RAISE",
    effective_bb: float = 12.0,
    hero_cards: list[str] | None = None,
    board_cards: list[str] | None = None,
) -> dict[tuple[str, str], float]:
    """Generate initial weighted villain range (dict of combo -> weight) based on preflop action."""
    dead = set()
    if hero_cards:
        dead.update(_norm_card(c) for c in hero_cards)
    if board_cards:
        dead.update(_norm_card(c) for c in board_cards)

    # Standard combos
    combos: dict[tuple[str, str], float] = {}

    act = preflop_action.upper()
    pos = position.upper()

    for i in range(len(FULL_DECK)):
        for j in range(i + 1, len(FULL_DECK)):
            c1, c2 = FULL_DECK[i], FULL_DECK[j]
            if c1 in dead or c2 in dead:
                continue

            r1, r2 = c1[0], c2[0]
            s1, s2 = c1[1], c2[1]
            idx1, idx2 = RANK_INDEX[r1], RANK_INDEX[r2]
            hi_r, lo_r = (r1, r2) if idx1 >= idx2 else (r2, r1)
            is_pair = (r1 == r2)
            is_suited = (s1 == s2)

            weight = 0.0

            if act in ("3BET_OR_SHOVE", "ALL_IN", "SHOVE"):
                # Top ~14%
                if is_pair and idx1 >= RANK_INDEX["7"]:
                    weight = 1.0
                elif is_pair and idx1 >= RANK_INDEX["2"]:
                    weight = 0.6 if effective_bb <= 10 else 0.2
                elif is_suited and hi_r == "A" and idx2 >= RANK_INDEX["9"]:
                    weight = 1.0
                elif not is_suited and hi_r == "A" and idx2 >= RANK_INDEX["J"]:
                    weight = 1.0
                elif is_suited and hi_r == "K" and idx2 >= RANK_INDEX["Q"]:
                    weight = 1.0
                elif is_suited and hi_r == "A" and idx2 <= RANK_INDEX["5"]:
                    weight = 0.5  # A2s-A5s wheel bluffs

            elif act in ("OPEN_RAISE", "MIN_RAISE", "RAISE"):
                # ~42% open range
                if is_pair:
                    weight = 1.0
                elif is_suited:
                    if hi_r in ("A", "K", "Q"):
                        weight = 1.0
                    elif idx1 >= RANK_INDEX["8"] and idx2 >= RANK_INDEX["6"]:
                        weight = 0.9
                    elif abs(idx1 - idx2) <= 2 and idx1 >= RANK_INDEX["5"]:
                        weight = 0.8
                    else:
                        weight = 0.3
                else:
                    if hi_r == "A" and idx2 >= RANK_INDEX["7"]:
                        weight = 1.0
                    elif hi_r == "K" and idx2 >= RANK_INDEX["9"]:
                        weight = 0.8
                    elif hi_r == "Q" and idx2 >= RANK_INDEX["9"]:
                        weight = 0.7
                    elif idx1 >= RANK_INDEX["J"] and idx2 >= RANK_INDEX["9"]:
                        weight = 0.6
                    elif abs(idx1 - idx2) == 1 and idx1 >= RANK_INDEX["8"]:
                        weight = 0.5
                    else:
                        weight = 0.1

            elif act in ("LIMP", "CALL_OPEN", "CALL", "CHECK"):
                # ~55% range: medium strength, speculativeness, capped
                if is_pair:
                    weight = 0.4 if idx1 >= RANK_INDEX["T"] else 0.9
                elif is_suited:
                    if hi_r == "A":
                        weight = 0.5 if idx2 >= RANK_INDEX["T"] else 0.95
                    elif hi_r in ("K", "Q", "J", "T"):
                        weight = 0.9
                    else:
                        weight = 0.75
                else:
                    if hi_r == "A" and idx2 >= RANK_INDEX["T"]:
                        weight = 0.5
                    elif hi_r == "A":
                        weight = 0.85
                    elif hi_r in ("K", "Q") and idx2 >= RANK_INDEX["7"]:
                        weight = 0.75
                    elif idx1 >= RANK_INDEX["9"] and idx2 >= RANK_INDEX["7"]:
                        weight = 0.8
                    else:
                        weight = 0.35
            else:
                weight = 0.5

            if weight > 0.0:
                combo_key = (min(c1, c2), max(c1, c2))
                combos[combo_key] = weight

    return combos


def narrow_range_by_postflop_action(
    villain_range: dict[tuple[str, str], float],
    board_cards: list[str],
    action_type: str,
    bet_to_pot: float,
    street: str,
) -> dict[tuple[str, str], float]:
    """Narrow villain's range using deterministic Microstakes MDA transition matrix."""
    act = action_type.upper()
    strt = street.upper()

    if act == "CHECK":
        multipliers = {
            "MONSTER": 0.35,
            "STRONG": 0.50,
            "MEDIUM": 1.20,
            "DRAW": 1.00,
            "AIR": 1.30,
        }
    elif act in ("BET", "RAISE", "ALL_IN", "BET_30", "BET_SMALL", "BET_MED"):
        if bet_to_pot <= 0.35 or act == "BET_SMALL":
            # Small bet: merged wide range
            multipliers = {
                "MONSTER": 1.10,
                "STRONG": 1.30,
                "MEDIUM": 1.10,
                "DRAW": 1.20,
                "AIR": 0.80,
            }
        elif bet_to_pot <= 0.70 or act in ("BET_30", "BET_MED"):
            # Medium bet: strong value + draws + moderate bluffs
            multipliers = {
                "MONSTER": 1.50,
                "STRONG": 1.40,
                "MEDIUM": 0.60,
                "DRAW": 1.30,
                "AIR": 0.40,
            }
        else:
            # Big bet / All-in / Raise: heavy value, very low air
            air_mult = 0.05 if strt == "RIVER" else 0.10
            draw_mult = 0.20 if strt == "RIVER" else 0.90
            multipliers = {
                "MONSTER": 2.50,
                "STRONG": 2.00,
                "MEDIUM": 0.20,
                "DRAW": draw_mult,
                "AIR": air_mult,
            }
    elif act == "CALL":
        # Call: capped range (mostly MEDIUM + STRONG + DRAW, few MONSTER, low AIR)
        multipliers = {
            "MONSTER": 0.70,
            "STRONG": 1.40,
            "MEDIUM": 1.40,
            "DRAW": 1.30,
            "AIR": 0.15,
        }
    else:
        multipliers = {"MONSTER": 1.0, "STRONG": 1.0, "MEDIUM": 1.0, "DRAW": 1.0, "AIR": 1.0}

    narrowed: dict[tuple[str, str], float] = {}
    for combo, old_w in villain_range.items():
        if old_w <= 0.0:
            continue
        c1, c2 = combo
        cat = classify_combo(c1, c2, board_cards)
        m = multipliers.get(cat, 1.0)
        new_w = old_w * m
        if new_w > 1e-4:
            narrowed[combo] = new_w

    return narrowed


def compute_range_vs_hand_equity(
    hero_cards: list[str],
    board_cards: list[str],
    villain_range: dict[tuple[str, str], float],
    time_budget_ms: float = 400.0,
    seed: int | None = None,
) -> float:
    """Calculate Hero equity against Villain's weighted range.

    - River (5 cards): exact enumeration over all valid villain combos (< 5 ms, 0% error).
    - Turn (4 cards): exact or sampled 44-card river runouts.
    - Flop (3 cards): weighted sampling with deterministic RNG within time budget.
    """
    if evaluate_cards is None or not villain_range or len(hero_cards) != 2:
        return 0.50

    h1, h2 = _norm_card(hero_cards[0]), _norm_card(hero_cards[1])
    board_norm = [_norm_card(c) for c in board_cards]
    dead = {h1, h2} | set(board_norm)

    valid_combos = [
        (c, w)
        for c, w in villain_range.items()
        if w > 0.0 and c[0] not in dead and c[1] not in dead and c[0] != c[1]
    ]

    if not valid_combos:
        return 0.50

    # 1. RIVER (5 board cards): Exact Enumeration (< 5 ms)
    if len(board_norm) == 5:
        h_score = evaluate_cards(h1, h2, *board_norm)
        win_weight = 0.0
        tie_weight = 0.0
        tot_weight = 0.0

        for (v1, v2), w in valid_combos:
            v_score = evaluate_cards(v1, v2, *board_norm)
            tot_weight += w
            if h_score < v_score:
                win_weight += w
            elif h_score == v_score:
                tie_weight += w

        if tot_weight <= 0.0:
            return 0.50
        return round((win_weight + 0.5 * tie_weight) / tot_weight, 4)

    # Deterministic RNG setup
    if seed is None:
        key_str = f"{sorted([h1, h2])}|{board_norm}|{len(valid_combos)}"
        seed = zlib.crc32(key_str.encode("utf-8")) & 0xFFFFFFFF
    rng = random.Random(seed)

    remaining_deck = [c for c in FULL_DECK if c not in dead]

    # 2. TURN (4 board cards): Exact or high-speed enumeration over 44 river cards
    if len(board_norm) == 4:
        t0 = time.perf_counter()
        win_weight = 0.0
        tie_weight = 0.0
        tot_weight = 0.0

        for (v1, v2), w in valid_combos:
            deck_for_combo = [c for c in remaining_deck if c != v1 and c != v2]
            for r_card in deck_for_combo:
                full_b = board_norm + [r_card]
                h_score = evaluate_cards(h1, h2, *full_b)
                v_score = evaluate_cards(v1, v2, *full_b)
                tot_weight += w
                if h_score < v_score:
                    win_weight += w
                elif h_score == v_score:
                    tie_weight += w

            # Time safeguard
            if (time.perf_counter() - t0) * 1000.0 >= time_budget_ms:
                break

        if tot_weight <= 0.0:
            return 0.50
        return round((win_weight + 0.5 * tie_weight) / tot_weight, 4)

    # 3. FLOP (3 board cards): Weighted Monte Carlo sampling within budget
    t0 = time.perf_counter()
    combos_list = [c for c, _ in valid_combos]
    weights_list = [w for _, w in valid_combos]

    win_count = 0.0
    tie_count = 0.0
    total_iters = 0

    max_iters = 2500
    while total_iters < max_iters:
        # Sample combo proportional to weights
        (v1, v2) = rng.choices(combos_list, weights=weights_list, k=1)[0]
        # Deal turn + river from remaining deck without v1, v2
        deck_avail = [c for c in remaining_deck if c != v1 and c != v2]
        turn, river = rng.sample(deck_avail, 2)

        full_b = board_norm + [turn, river]
        h_score = evaluate_cards(h1, h2, *full_b)
        v_score = evaluate_cards(v1, v2, *full_b)

        total_iters += 1
        if h_score < v_score:
            win_count += 1.0
        elif h_score == v_score:
            tie_count += 1.0

        if (time.perf_counter() - t0) * 1000.0 >= time_budget_ms:
            break

    if total_iters == 0:
        return 0.50
    return round((win_count + 0.5 * tie_count) / total_iters, 4)


class RangeTracker:
    """Maintains and updates Villain's range throughout the hand."""

    def __init__(self) -> None:
        self.villain_range: dict[tuple[str, str], float] = {}
        self.history: list[str] = []

    def init_preflop(
        self,
        position: str,
        preflop_action: str,
        effective_bb: float,
        hero_cards: list[str] | None = None,
        board_cards: list[str] | None = None,
    ) -> None:
        self.villain_range = get_preflop_villain_range(
            position=position,
            preflop_action=preflop_action,
            effective_bb=effective_bb,
            hero_cards=hero_cards,
            board_cards=board_cards,
        )
        self.history = [f"PREFLOP:{position}:{preflop_action}"]

    def on_action(
        self,
        action_type: str,
        bet_to_pot: float,
        street: str,
        board_cards: list[str],
    ) -> None:
        if not self.villain_range:
            return
        self.villain_range = narrow_range_by_postflop_action(
            villain_range=self.villain_range,
            board_cards=board_cards,
            action_type=action_type,
            bet_to_pot=bet_to_pot,
            street=street,
        )
        self.history.append(f"{street}:{action_type}:{bet_to_pot:.2f}")

    def get_equity(
        self,
        hero_cards: list[str],
        board_cards: list[str],
        time_budget_ms: float = 400.0,
    ) -> float:
        return compute_range_vs_hand_equity(
            hero_cards=hero_cards,
            board_cards=board_cards,
            villain_range=self.villain_range,
            time_budget_ms=time_budget_ms,
        )

    def get_air_ratio(self, board_cards: list[str]) -> float:
        """Compute the ratio of AIR in villain's range for fold-equity estimation."""
        if not self.villain_range:
            return 0.25
        air_weight = 0.0
        tot_weight = 0.0
        for (c1, c2), w in self.villain_range.items():
            tot_weight += w
            if classify_combo(c1, c2, board_cards) == "AIR":
                air_weight += w
        if tot_weight <= 0.0:
            return 0.25
        return round(air_weight / tot_weight, 4)


def infer_villain_position(
    state: Any,
    hand_summary: dict[str, Any] | None,
    villain_seat: int,
) -> str:
    """Infer villain's position ('BTN', 'SB', 'BB') based on dealer button and player count."""
    dealer_seat: int | None = None
    if hand_summary and isinstance(hand_summary.get("players"), dict):
        for sid, pinfo in hand_summary["players"].items():
            if isinstance(pinfo, dict) and pinfo.get("is_dealer"):
                dealer_seat = int(sid)
                break

    if dealer_seat is None:
        players = getattr(state, "players", {}) or {}
        for sid, p in (players.items() if isinstance(players, dict) else enumerate(players)):
            if getattr(p, "is_dealer", False):
                dealer_seat = int(sid)
                break

    if dealer_seat is not None and villain_seat == dealer_seat:
        return "BTN"

    eliminated: set[int] = set()
    if hand_summary and isinstance(hand_summary.get("players"), dict):
        for sid, pinfo in hand_summary["players"].items():
            if isinstance(pinfo, dict) and pinfo.get("eliminated"):
                eliminated.add(int(sid))
    else:
        players = getattr(state, "players", {}) or {}
        for sid in (0, 1, 2):
            if sid in players:
                p = players[sid]
                if getattr(p, "stack", None) is None and not getattr(p, "is_active", True):
                    eliminated.add(sid)

    num_active = max(2, 3 - len(eliminated))
    if num_active == 2:
        # Heads-Up: non-dealer is BB
        return "BB"

    # 3-max: gracz po dealerze to SB, kolejny to BB
    if dealer_seat is not None:
        sb_seat = (dealer_seat + 1) % 3
        if villain_seat == sb_seat:
            return "SB"
        return "BB"

    return "BTN"


def build_villain_range_from_history(
    hand_summary: dict[str, Any] | None,
    state: Any,
    villain_seat: int,
    effective_bb: float,
) -> dict[tuple[str, str], float]:
    """Build villain's weighted range cumulatively from preflop to the current postflop action."""
    hero_cards = list(getattr(state, "hero_cards", []) or [])
    board_cards = list(getattr(state, "board_cards", []) or [])
    bb_val = max(1, int(getattr(state, "big_blind", 20) or 20))
    pot_val = max(bb_val, int(getattr(state, "pot", 40) or 40))

    v_pos = infer_villain_position(state, hand_summary, villain_seat)

    action_log: list[dict[str, Any]] = []
    if hand_summary and isinstance(hand_summary.get("action_log"), list):
        action_log = hand_summary["action_log"]

    preflop_acts = [
        a for a in action_log
        if a.get("seat_id") == villain_seat
        and a.get("street") == "PREFLOP"
        and a.get("action") not in ("BLIND", "FOLD")
    ]
    postflop_acts = [
        a for a in action_log
        if a.get("seat_id") == villain_seat
        and a.get("street") in ("FLOP", "TURN", "RIVER")
        and a.get("action") not in ("BLIND", "FOLD")
    ]

    has_allin = any(str(a.get("action", "")).upper() in ("ALL-IN", "ALL_IN", "SHOVE") for a in preflop_acts)
    num_raises = sum(
        1 for a in preflop_acts
        if str(a.get("action", "")).upper() == "RAISE"
        or (str(a.get("action", "")).upper() == "BET" and float(a.get("amount", 0) or 0) > bb_val)
    )

    if has_allin or num_raises >= 2:
        preflop_act = "3BET_OR_SHOVE"
    elif any(
        str(a.get("action", "")).upper() == "RAISE"
        or (str(a.get("action", "")).upper() == "BET" and float(a.get("amount", 0) or 0) > bb_val)
        for a in preflop_acts
    ):
        preflop_act = "OPEN_RAISE"
    elif any(str(a.get("action", "")).upper() == "CALL" for a in preflop_acts):
        had_other_raise = any(
            entry.get("street") == "PREFLOP"
            and str(entry.get("action", "")).upper() in ("RAISE", "ALL-IN", "ALL_IN")
            for entry in action_log
        )
        if had_other_raise or pot_val >= 3.5 * bb_val:
            preflop_act = "CALL_OPEN"
        else:
            preflop_act = "LIMP"
    else:
        if pot_val >= 3.5 * bb_val:
            preflop_act = "OPEN_RAISE" if v_pos in ("BTN", "SB") else "CALL_OPEN"
        else:
            preflop_act = "LIMP"

    v_range = get_preflop_villain_range(
        position=v_pos,
        preflop_action=preflop_act,
        effective_bb=effective_bb,
        hero_cards=hero_cards,
        board_cards=board_cards,
    )

    running_pot = max(float(bb_val * 2), float(pot_val) * 0.5)
    for entry in postflop_acts:
        act_street = str(entry.get("street", "FLOP")).upper()
        if act_street == "FLOP":
            if len(board_cards) < 3:
                continue
            street_board = board_cards[:3]
        elif act_street == "TURN":
            if len(board_cards) < 4:
                continue
            street_board = board_cards[:4]
        elif act_street == "RIVER":
            if len(board_cards) < 5:
                continue
            street_board = board_cards[:5]
        else:
            continue

        raw_act = str(entry.get("action", "")).upper()
        if raw_act in ("ALL-IN", "ALL_IN", "RAISE"):
            act_type = "RAISE"
        elif raw_act in ("BET", "BET_30", "BET_SMALL", "BET_MED"):
            act_type = "BET"
        elif raw_act in ("CHECK", "CALL"):
            act_type = "CHECK"
        else:
            act_type = "CHECK"

        amt = float(entry.get("amount", 0) or 0)
        b_to_p = (amt / max(float(bb_val), running_pot)) if act_type in ("BET", "RAISE") else 0.0

        narrowed = narrow_range_by_postflop_action(
            villain_range=v_range,
            board_cards=street_board,
            action_type=act_type,
            bet_to_pot=b_to_p,
            street=act_street,
        )
        if narrowed and sum(narrowed.values()) > 1e-6:
            v_range = narrowed
        if amt > 0:
            running_pot += amt

    # Account for current bet on the active street
    players = getattr(state, "players", {}) or {}
    curr_p = (
        players.get(villain_seat)
        if isinstance(players, dict)
        else (players[villain_seat] if len(players) > villain_seat else None)
    )
    curr_bet = 0
    if curr_p is not None:
        val = getattr(curr_p, "current_bet", None)
        if val is None:
            val = getattr(curr_p, "bet", 0)
        curr_bet = int(val or 0)

    curr_street = str(getattr(state, "street", "FLOP") or "FLOP").upper()

    if curr_bet > 0 and len(board_cards) >= 3:
        already_logged = False
        if postflop_acts:
            last_act = postflop_acts[-1]
            if str(last_act.get("street", "")).upper() == curr_street:
                last_amt = float(last_act.get("amount", 0) or 0)
                if abs(last_amt - curr_bet) <= 1:
                    already_logged = True
        if not already_logged:
            b_to_p = curr_bet / max(float(bb_val), float(pot_val - curr_bet))
            narrowed = narrow_range_by_postflop_action(
                villain_range=v_range,
                board_cards=board_cards,
                action_type="BET",
                bet_to_pot=b_to_p,
                street=curr_street,
            )
            if narrowed and sum(narrowed.values()) > 1e-6:
                v_range = narrowed
    elif curr_bet == 0 and len(board_cards) >= 3:
        has_act_on_curr_street = any(
            str(a.get("street", "")).upper() == curr_street for a in postflop_acts
        )
        if not has_act_on_curr_street and v_pos != "BTN":
            narrowed = narrow_range_by_postflop_action(
                villain_range=v_range,
                board_cards=board_cards,
                action_type="CHECK",
                bet_to_pot=0.0,
                street=curr_street,
            )
            if narrowed and sum(narrowed.values()) > 1e-6:
                v_range = narrowed

    return v_range
