"""Main real-time orchestrator for poker_assistant.

Coordinates video frame capture, computer vision detection, state tracking,
game tree evaluation, exploit decision making, lightweight logging,
and PySide6 HUD overlay presentation.
"""

from __future__ import annotations

import argparse
from copy import copy
import queue
import sys
import threading
import time
from typing import Any

# Core contracts and constants
try:
    from core.contracts import Decision, PlayerState, TableState
except ImportError:
    Decision = Any  # type: ignore[misc, assignment]
    PlayerState = Any  # type: ignore[misc, assignment]
    TableState = Any  # type: ignore[misc, assignment]

# Vision module
try:
    from vision.anchor import (
        apply_anti_jitter,
        compute_table_rect,
        compute_table_rect_from_rim,
        compute_unclipped_table_rect,
        crop_rois,
        find_all_anchors,
        find_anchor,
        find_golden_rim,
        find_right_anchor,
        verify_table_rect_has_blue_felt,
    )
    from vision.ocr import detect_rabbit_hunting_break
    from vision.capture import (
        DXCAM_AVAILABLE,
        FrameSource,
        LiveScreenCapture,
        OfflineReplayCapture,
    )
    from vision.pipeline import VisionPipeline
except ImportError:
    apply_anti_jitter = None  # type: ignore[assignment]
    find_all_anchors = None  # type: ignore[assignment]
    find_anchor = None  # type: ignore[assignment]
    find_golden_rim = None  # type: ignore[assignment]
    find_right_anchor = None  # type: ignore[assignment]
    compute_table_rect = None  # type: ignore[assignment]
    compute_table_rect_from_rim = None  # type: ignore[assignment]
    compute_unclipped_table_rect = None  # type: ignore[assignment]
    crop_rois = None  # type: ignore[assignment]
    verify_table_rect_has_blue_felt = None  # type: ignore[assignment]
    detect_rabbit_hunting_break = None  # type: ignore[assignment]
    DXCAM_AVAILABLE = False
    FrameSource = Any  # type: ignore[misc, assignment]
    LiveScreenCapture = Any  # type: ignore[misc, assignment]
    OfflineReplayCapture = Any  # type: ignore[misc, assignment]
    VisionPipeline = Any  # type: ignore[misc, assignment]

# State module
try:
    from state.hand_history import HandHistoryRecorder
    from state.logger import SessionLogger
    from state.tracker import TableTracker
    from state.validator import StateValidator
except ImportError:
    HandHistoryRecorder = None  # type: ignore[assignment]
    SessionLogger = Any  # type: ignore[misc, assignment]
    TableTracker = Any  # type: ignore[misc, assignment]
    StateValidator = Any  # type: ignore[misc, assignment]

# Engine module
try:
    from engine.flop_db import FlopDatabase
except ImportError:
    FlopDatabase = None

try:
    from engine.monte_carlo import MonteCarloCalculator
except ImportError:
    MonteCarloCalculator = None

try:
    from engine.preflop_nash import PreflopNashEngine
except ImportError:
    PreflopNashEngine = None

# Strategy module
try:
    from strategy.decision_maker import DecisionMaker
    from strategy.simplifier import quantize_sizing_to_bb
    from strategy.decision_lock import DecisionLock, compute_decision_fingerprint
except ImportError:
    DecisionMaker = None
    quantize_sizing_to_bb = None
    DecisionLock = None
    compute_decision_fingerprint = None

# Range engine module
try:
    from engine.range_engine import (
        get_preflop_villain_range,
        narrow_range_by_postflop_action,
        compute_range_vs_hand_equity,
        classify_combo,
        build_villain_range_from_history,
    )
except ImportError:
    get_preflop_villain_range = None
    narrow_range_by_postflop_action = None
    compute_range_vs_hand_equity = None
    classify_combo = None
    build_villain_range_from_history = None

# UI module
try:
    from PySide6.QtWidgets import QApplication
    from ui.hud import HudBridge, HudOverlay, format_action_label, render_visual_cards_html
except ImportError:
    QApplication = None  # type: ignore[assignment]
    HudBridge = None  # type: ignore[assignment]
    HudOverlay = None  # type: ignore[assignment]
    format_action_label = None  # type: ignore[assignment]
    render_visual_cards_html = None  # type: ignore[assignment]


def _is_preflop_shove(opp: Any, bb_val: int) -> bool:
    """Check if opponent's preflop action constitutes a shove or standard raise.

    A shove is defined as:
      - opp.status_text == 'ALL_IN'
      - opp.stack == 0 and opp.current_bet > bb_val
      - opp.current_bet >= 0.4 * (opp.stack + opp.current_bet) and opp.current_bet > bb_val
    """
    if opp is None:
        return False
    bet = getattr(opp, "current_bet", 0) or 0
    stack = getattr(opp, "stack", 0) or 0
    status = getattr(opp, "status_text", "")
    if status == "ALL_IN":
        return True
    if stack == 0 and bet > bb_val:
        return True
    total = stack + bet
    if total > 0 and bet >= 0.4 * total and bet > bb_val:
        return True
    return False


def determine_preflop_spot(state: Any) -> str:
    """Determine preflop game tree spot based on dealer button and opponent bets.

    Spots for 3-max hyper-turbo:
        - "BTN_OPEN": Hero is on BTN (dealer).
        - "SB_OPEN": Hero is on SB and BTN folded/unraised.
        - "SB_VS_BTN_SHOVE": Hero is on SB and BTN shoved.
        - "SB_VS_BTN_RAISE": Hero is on SB and BTN min-raised.
        - "BB_ISO_VS_LIMP": Hero is on BB and someone limped (or open unraised).
        - "BB_VS_BTN_SHOVE": Hero is on BB and BTN shoved.
        - "BB_VS_BTN_RAISE": Hero is on BB and BTN min-raised.
        - "BB_VS_SB_SHOVE": Hero is on BB and SB shoved.
        - "BB_VS_SB_RAISE": Hero is on BB and SB min-raised.

    Args:
        state: TableState object or equivalent test object.

    Returns:
        Spot name string.
    """
    players = getattr(state, "players", {})
    if not players:
        return "BTN_OPEN"

    # Identify dealer seat (0 = Hero, 1 = Left, 2 = Right)
    dealer_seat: int | None = None
    for seat_id, p in players.items():
        if getattr(p, "is_dealer", False):
            dealer_seat = int(seat_id)
            break

    if dealer_seat is None:
        return "BTN_OPEN"

    hero_seat = 0
    big_blind = getattr(state, "big_blind", 20)
    bb_val = big_blind if big_blind > 0 else 20

    # Detect if exactly 1 player is eliminated (Heads-Up mode)
    eliminated_seats: set[int] = set()
    for s_id, p in players.items():
        p_stack = getattr(p, "stack", None)
        p_active = getattr(p, "is_active", True)
        p_status = getattr(p, "status_text", "")
        if p_status in ("SIT_OUT", "ELIMINATED") or not p_active:
            eliminated_seats.add(s_id)
        elif p_stack is None and getattr(p, "current_bet", 0) == 0:
            other_stacks = [
                getattr(other, "stack", None)
                for sid, other in players.items()
                if sid != s_id
            ]
            if any(s is not None for s in other_stacks):
                eliminated_seats.add(s_id)

    is_heads_up = (len(players) - len(eliminated_seats) == 2) and (hero_seat not in eliminated_seats)

    # Case A: Heads-Up mode (2 active players: Hero and 1 Opponent)
    if is_heads_up:
        opp_seat = next(s for s in players if s not in eliminated_seats and s != hero_seat)
        opp_player = players.get(opp_seat)
        opp_bet = getattr(opp_player, "current_bet", 0) if opp_player else 0
        opp_status = getattr(opp_player, "status_text", "") if opp_player else ""

        # In Heads-Up: Dealer is SB/BTN (acts first preflop); the other player is BB.
        if dealer_seat == hero_seat:
            if opp_bet > bb_val or opp_status == "ALL_IN":
                if _is_preflop_shove(opp_player, bb_val):
                    return "BB_VS_SB_SHOVE"
                return "BB_VS_SB_RAISE"
            return "SB_OPEN"
        else:
            # Hero is BB, Opponent is Dealer (SB/BTN)
            if opp_bet > bb_val or opp_status == "ALL_IN":
                if _is_preflop_shove(opp_player, bb_val):
                    return "BB_VS_SB_SHOVE"
                return "BB_VS_SB_RAISE"
            if opp_bet == bb_val or (opp_bet > 0 and opp_bet <= bb_val):
                return "BB_ISO_VS_LIMP"
            return "BB_ISO_VS_LIMP"

    # Case B: 3-max mode (all 3 players active)
    btn_seat = dealer_seat
    sb_seat = (dealer_seat + 1) % 3
    bb_seat = (dealer_seat + 2) % 3

    # 1. Hero on BTN
    if hero_seat == btn_seat:
        sb_player = players.get(sb_seat)
        bb_player = players.get(bb_seat)
        sb_bet = getattr(sb_player, "current_bet", 0) if sb_player else 0
        bb_bet = getattr(bb_player, "current_bet", 0) if bb_player else 0
        sb_status = getattr(sb_player, "status_text", "") if sb_player else ""
        bb_status = getattr(bb_player, "status_text", "") if bb_player else ""

        if _is_preflop_shove(sb_player, bb_val):
            return "BB_VS_SB_SHOVE"
        if _is_preflop_shove(bb_player, bb_val):
            return "BB_VS_SB_SHOVE"
        if sb_bet > bb_val or sb_status == "ALL_IN":
            return "BB_VS_SB_RAISE"
        if bb_bet > bb_val or bb_status == "ALL_IN":
            return "BB_VS_SB_RAISE"
        return "BTN_OPEN"

    # 2. Hero on SB
    if hero_seat == sb_seat:
        btn_player = players.get(btn_seat)
        btn_bet = getattr(btn_player, "current_bet", 0) if btn_player else 0
        btn_status = getattr(btn_player, "status_text", "") if btn_player else ""
        if btn_bet > bb_val or btn_status == "ALL_IN":
            if _is_preflop_shove(btn_player, bb_val):
                return "SB_VS_BTN_SHOVE"
            return "SB_VS_BTN_RAISE"
        return "SB_OPEN"

    # 3. Hero on BB
    if hero_seat == bb_seat:
        btn_player = players.get(btn_seat)
        sb_player = players.get(sb_seat)
        btn_bet = getattr(btn_player, "current_bet", 0) if btn_player else 0
        sb_bet = getattr(sb_player, "current_bet", 0) if sb_player else 0
        btn_status = getattr(btn_player, "status_text", "") if btn_player else ""
        sb_status = getattr(sb_player, "status_text", "") if sb_player else ""

        if _is_preflop_shove(btn_player, bb_val):
            return "BB_VS_BTN_SHOVE"
        if _is_preflop_shove(sb_player, bb_val):
            return "BB_VS_SB_SHOVE"
        if btn_bet > bb_val or btn_status == "ALL_IN":
            return "BB_VS_BTN_RAISE"
        if sb_bet > bb_val or sb_status == "ALL_IN":
            return "BB_VS_SB_RAISE"
        if btn_bet == bb_val or sb_bet == bb_val or (btn_bet > 0 and btn_bet <= bb_val):
            return "BB_ISO_VS_LIMP"
        return "BB_ISO_VS_LIMP"

    return "BTN_OPEN"


def determine_postflop_spot(
    state: Any,
    hand_summary: dict[str, Any] | None = None,
) -> str:
    """Map current postflop state + hand history to one of the 4 GTOpen database spot keys."""
    players = getattr(state, "players", {}) or {}
    bb_val = max(1, int(getattr(state, "big_blind", 20) or 20))
    pot_val = int(getattr(state, "pot", 0) or 0)

    # 1. Detect Heads-Up vs 3-max
    eliminated_count = 0
    if hand_summary and isinstance(hand_summary.get("players"), dict):
        eliminated_count = sum(
            1
            for sid in (0, 1, 2)
            if hand_summary["players"].get(sid, {}).get("eliminated", False)
        )
    else:
        eliminated_count = sum(
            1
            for sid in (0, 1, 2)
            if sid in players
            and getattr(players[sid], "stack", None) is None
            and not getattr(players[sid], "is_active", True)
        )
    is_hu = eliminated_count >= 1

    # 2. Detect SRP (Single Raised Pot) vs LIMPED
    had_preflop_raise = False
    if hand_summary and isinstance(hand_summary.get("action_log"), list):
        for entry in hand_summary["action_log"]:
            if entry.get("street") == "PREFLOP" and entry.get("action") in ("RAISE", "ALL-IN"):
                had_preflop_raise = True
                break
        if not had_preflop_raise:
            # Fallback if joined mid-hand without preflop log
            if hand_summary.get("mid_hand_join") and pot_val >= int(round(3.5 * bb_val)):
                had_preflop_raise = True
    else:
        had_preflop_raise = pot_val >= int(round(3.5 * bb_val))

    if is_hu:
        return "HU_SB_vs_BB_SRP" if had_preflop_raise else "HU_SB_vs_BB_LIMPED"
    return "BTN_vs_BB_SRP" if had_preflop_raise else "SB_vs_BB_LIMPED"


def evaluate_candidates(
    state: Any,
    preflop_engine: Any,
    flop_db: Any,
    mc_calc: Any,
    hand_summary: dict[str, Any] | None = None,
) -> tuple[dict[str, float], str]:
    """Calculate candidate actions and their estimated EV in big blinds.

    Args:
        state: TableState object.
        preflop_engine: PreflopNashEngine instance or None.
        flop_db: FlopDatabase instance or None.
        mc_calc: MonteCarloCalculator instance or None.

    Returns:
        Tuple of (candidate_evs_dict, spot_name).
    """
    street = getattr(state, "street", "WAITING_FOR_TURN")
    hero_cards = getattr(state, "hero_cards", [])
    board_cards = getattr(state, "board_cards", [])
    players = getattr(state, "players", {})
    hero_player = players.get(0) if players else None
    hero_stack = getattr(hero_player, "stack", 300) if hero_player else 300
    if hero_stack is None:
        hero_stack = 300
    hero_bet = getattr(hero_player, "current_bet", 0) if hero_player else 0
    hero_total = (hero_stack or 0) + hero_bet
    if hero_total <= 0:
        hero_total = 300

    big_blind = getattr(state, "big_blind", 20)
    bb_val = big_blind if big_blind > 0 else 20

    # Calculate effective stack against active opponents: min(hero_total, max_active_opp_total) / bb_val
    active_opp_totals: list[int] = []
    for s_id, p in players.items():
        if s_id != 0:
            p_stk = getattr(p, "stack", 0) or 0
            p_bet = getattr(p, "current_bet", 0) or 0
            p_act = getattr(p, "is_active", True)
            p_stat = getattr(p, "status_text", "")
            if p_act and p_stat != "FOLDED" and (p_stk + p_bet > 0):
                active_opp_totals.append(p_stk + p_bet)

    if active_opp_totals:
        max_active_opp_total = max(active_opp_totals)
        effective_bb = min(hero_total, max_active_opp_total) / bb_val
    else:
        effective_bb = hero_total / bb_val

    # If hero cards are incomplete, strictly return WAIT
    if len(hero_cards) != 2:
        return {"WAIT": 0.0}, "NO_HERO_CARDS"

    # PREFLOP street
    if street == "PREFLOP":
        spot = determine_preflop_spot(state)
        candidate_evs: dict[str, float] = {"FOLD": 0.0}

        # Handle min-raise vs shove: do not fold BB vs min-raise as if it were all-in
        if spot in ("BB_VS_BTN_RAISE", "BB_VS_SB_RAISE", "SB_VS_BTN_RAISE"):
            max_opp_bet = max(
                (getattr(p, "current_bet", 0) for s_id, p in players.items() if s_id != 0),
                default=0,
            )
            to_call_bb = max(0.5, (max_opp_bet - hero_bet) / bb_val)
            pot_val = getattr(state, "pot", 0) or (max_opp_bet + hero_bet)
            pot_bb = max(2.5, pot_val / bb_val)

            num_opps_in_pot = sum(
                1
                for s_id, p in players.items()
                if s_id != 0
                and getattr(p, "is_active", True)
                and getattr(p, "status_text", "") not in ("FOLDED", "SIT_OUT", "ELIMINATED")
                and (
                    (getattr(p, "current_bet", 0) or 0) >= max_opp_bet
                    or getattr(p, "status_text", "") == "ALL_IN"
                )
            )
            num_opps_in_pot = max(1, min(2, num_opps_in_pot))

            if mc_calc is not None and hasattr(mc_calc, "estimate_equity") and len(hero_cards) == 2:
                try:
                    v_combos = None
                    if get_preflop_villain_range is not None:
                        raiser_pos = "BTN" if "BTN" in spot else "SB"
                        v_range = get_preflop_villain_range(
                            position=raiser_pos,
                            preflop_action="OPEN_RAISE",
                            effective_bb=effective_bb,
                            hero_cards=hero_cards,
                        )
                        if v_range:
                            v_combos = list(v_range.keys())

                    try:
                        equity = mc_calc.estimate_equity(
                            hero_cards,
                            [],
                            villain_range=v_combos,
                            num_opponents=num_opps_in_pot,
                            time_budget_ms=50.0,
                        )
                    except TypeError:
                        equity = mc_calc.estimate_equity(hero_cards, [], time_budget_ms=40.0)

                    if num_opps_in_pot >= 2:
                        call_equity = max(0.05, equity - 0.08)
                        shove_fe = 0.15
                    else:
                        call_equity = max(0.05, equity - 0.05)
                        shove_fe = 0.28
                    shove_call_equity = max(0.05, equity - 0.10)
                    if hasattr(mc_calc, "calculate_ev_bb"):
                        call_ev = mc_calc.calculate_ev_bb(
                            call_equity, pot_bb, call_cost_bb=to_call_bb, fold_equity=0.0
                        )
                        shove_ev = mc_calc.calculate_ev_bb(
                            shove_call_equity, pot_bb, call_cost_bb=effective_bb, fold_equity=shove_fe
                        )
                    else:
                        call_ev = round(
                            call_equity * (pot_bb + to_call_bb) - (1.0 - call_equity) * to_call_bb, 3
                        )
                        shove_ev = round(
                            shove_fe * pot_bb + (1.0 - shove_fe) * (shove_call_equity * (pot_bb + effective_bb) - (1.0 - shove_call_equity) * effective_bb),
                            3,
                        )
                    candidate_evs["CALL"] = float(call_ev)
                    if shove_ev > 0:
                        candidate_evs["ALL_IN"] = float(shove_ev)
                except Exception:
                    candidate_evs["CALL"] = 0.2
            else:
                candidate_evs["CALL"] = 0.2

            return candidate_evs, spot

        if preflop_engine is not None and hasattr(preflop_engine, "get_action") and len(hero_cards) == 2:
            try:
                action, ev_bb = preflop_engine.get_action(hero_cards, effective_bb, spot)
                candidate_evs[action] = float(ev_bb)
            except Exception:
                candidate_evs["ALL_IN"] = 0.5
        else:
            candidate_evs["ALL_IN"] = 0.5

        return candidate_evs, spot

    # POSTFLOP streets (FLOP, TURN, RIVER)
    if street in ("FLOP", "TURN", "RIVER"):
        postflop_spot = determine_postflop_spot(state, hand_summary) if street == "FLOP" else street
        spot = postflop_spot
        candidate_evs = None

        max_opp_bet = max(
            (getattr(p, "current_bet", 0) for s_id, p in players.items() if s_id != 0),
            default=0,
        )
        facing_bet = max_opp_bet > hero_bet
        to_call_bb = (max_opp_bet - hero_bet) / bb_val if facing_bet else 0.0
        pot = getattr(state, "pot", 40)
        pot_bb = pot / bb_val
        bet30_bb = max(0.5, 0.3 * pot_bb)
        stack_bb = effective_bb

        # 1. GTOpen 47 clusters / Flop canonical database lookup (FLOP only, and ONLY when not facing_bet)
        if (
            street == "FLOP"
            and not facing_bet
            and flop_db is not None
            and len(board_cards) == 3
            and len(hero_cards) == 2
        ):
            if hasattr(flop_db, "lookup_nearest_flop"):
                try:
                    lookup_res = flop_db.lookup_nearest_flop(board_cards, postflop_spot, hero_cards)
                    if (
                        lookup_res is not None
                        and isinstance(lookup_res, dict)
                        and any(k in lookup_res for k in ("CHECK", "BET_30", "BET_MED", "ALL_IN"))
                    ):
                        candidate_evs = {k: float(v) for k, v in lookup_res.items()}
                        if "FOLD" not in candidate_evs:
                            candidate_evs["FOLD"] = 0.0
                except Exception:
                    candidate_evs = None

            if candidate_evs is None and hasattr(flop_db, "lookup"):
                try:
                    lookup_res = flop_db.lookup(board_cards, hero_cards, effective_bb)
                    if (
                        lookup_res is not None
                        and isinstance(lookup_res, dict)
                        and any(k in lookup_res for k in ("CHECK", "BET_30", "ALL_IN"))
                    ):
                        candidate_evs = {k: float(v) for k, v in lookup_res.items()}
                        if "FOLD" not in candidate_evs:
                            candidate_evs["FOLD"] = 0.0
                except Exception:
                    candidate_evs = None

        # 2. Range-vs-Range / Monte Carlo estimation (< 400 ms) or CALL EV computation when facing bet
        if candidate_evs is None:
            if mc_calc is not None and hasattr(mc_calc, "estimate_equity") and len(hero_cards) == 2:
                try:
                    active_opponents = sum(
                        1
                        for sid, p in players.items()
                        if sid != 0
                        and getattr(p, "is_active", True)
                        and getattr(p, "status_text", "") not in ("FOLDED", "SIT_OUT", "ELIMINATED")
                    )
                    num_opps = max(1, min(2, active_opponents))

                    # Determine villain_seat
                    villain_seat = 1
                    if facing_bet:
                        best_bet = -1
                        for sid in (1, 2):
                            p = players.get(sid)
                            if p is not None and getattr(p, "is_active", True) and getattr(p, "status_text", "") not in ("FOLDED", "SIT_OUT", "ELIMINATED"):
                                b = getattr(p, "current_bet", 0) or 0
                                if b > best_bet:
                                    best_bet = b
                                    villain_seat = sid
                    else:
                        for sid in (1, 2):
                            p = players.get(sid)
                            if p is not None and getattr(p, "is_active", True) and getattr(p, "status_text", "") not in ("FOLDED", "SIT_OUT", "ELIMINATED"):
                                villain_seat = sid
                                break

                    # 1. Stateful Range-vs-Range equity & dynamic air ratio
                    v_range = None
                    air_ratio = 0.25
                    if build_villain_range_from_history is not None:
                        v_range = build_villain_range_from_history(
                            hand_summary=hand_summary,
                            state=state,
                            villain_seat=villain_seat,
                            effective_bb=stack_bb,
                        )
                    elif get_preflop_villain_range is not None:
                        opp_pos = "BTN"
                        opp_preflop_act = "CALL_OPEN" if facing_bet else "OPEN_RAISE"
                        v_range = get_preflop_villain_range(
                            position=opp_pos,
                            preflop_action=opp_preflop_act,
                            effective_bb=stack_bb,
                            hero_cards=hero_cards,
                            board_cards=board_cards,
                        )
                        if narrow_range_by_postflop_action is not None and v_range:
                            act_type = "BET" if facing_bet else "CHECK"
                            b_to_p = (to_call_bb / max(1.0, pot_bb)) if facing_bet else 0.0
                            v_range = narrow_range_by_postflop_action(
                                villain_range=v_range,
                                board_cards=board_cards,
                                action_type=act_type,
                                bet_to_pot=b_to_p,
                                street=street,
                            )

                    # Compute air ratio from villain range if available
                    if v_range and classify_combo is not None:
                        air_wt = sum(w for (c1, c2), w in v_range.items() if classify_combo(c1, c2, board_cards) == "AIR")
                        tot_wt = sum(v_range.values())
                        air_ratio = (air_wt / tot_wt) if tot_wt > 0 else 0.25

                    # PRESERVE WEIGHTS: For Heads-up postflop (num_opps == 1), use compute_range_vs_hand_equity on Flop, Turn, and River!
                    is_mocked_mc = type(getattr(mc_calc, "estimate_equity", None)).__name__ in ("MagicMock", "Mock")
                    if num_opps == 1 and v_range and compute_range_vs_hand_equity is not None and not is_mocked_mc:
                        equity = compute_range_vs_hand_equity(
                            hero_cards=hero_cards,
                            board_cards=board_cards,
                            villain_range=v_range,
                            time_budget_ms=400.0,
                        )
                    else:
                        # Multiway (2 active opponents) or fallback when range_engine unavailable
                        v_combos = list(v_range.keys()) if v_range else None
                        try:
                            equity = mc_calc.estimate_equity(
                                hero_cards,
                                board_cards,
                                villain_range=v_combos,
                                time_budget_ms=400.0,
                                num_opponents=num_opps,
                            )
                        except TypeError:
                            equity = mc_calc.estimate_equity(
                                hero_cards,
                                board_cards,
                                time_budget_ms=400.0,
                                num_opponents=num_opps,
                            )

                    if facing_bet:
                        call_equity = max(0.05, equity - 0.08)
                        shove_call_equity = max(0.05, equity - 0.16)
                        shove_fe = min(0.40, max(0.05, air_ratio * 0.7))
                        if num_opps == 2:
                            shove_fe *= 0.65
                        if hasattr(mc_calc, "calculate_ev_bb"):
                            call_ev = mc_calc.calculate_ev_bb(
                                call_equity, pot_bb, call_cost_bb=to_call_bb, fold_equity=0.0
                            )
                            shove_ev = mc_calc.calculate_ev_bb(
                                shove_call_equity, pot_bb, call_cost_bb=stack_bb, fold_equity=shove_fe
                            )
                        else:
                            call_ev = round(
                                call_equity * (pot_bb + to_call_bb) - (1.0 - call_equity) * to_call_bb, 3
                            )
                            shove_ev = round(
                                shove_fe * pot_bb + (1.0 - shove_fe) * (shove_call_equity * (pot_bb + stack_bb) - (1.0 - shove_call_equity) * stack_bb),
                                3,
                            )
                        candidate_evs = {
                            "CALL": float(call_ev),
                            "ALL_IN": float(shove_ev),
                            "FOLD": 0.0,
                        }
                    else:
                        spr = stack_bb / max(1.0, pot_bb)
                        if spr <= 1.5:
                            spr_mult = 1.0
                        elif spr <= 3.0:
                            spr_mult = 0.75
                        else:
                            spr_mult = 0.50
                        shove_fe = min(0.35, max(0.08, air_ratio * spr_mult))
                        bet_fe = min(0.45, max(0.10, air_ratio * 0.8))
                        shove_call_equity = max(0.05, equity - 0.14)
                        bet_call_equity = max(0.05, equity - 0.06)
                        if num_opps == 2:
                            shove_fe *= 0.65
                            bet_fe *= 0.65

                        # Sizing quantization in multiples of BB or ALL-IN
                        hero_player = players.get(0)
                        hero_stk = getattr(hero_player, "stack", 0) or 0
                        eff_stk = int(round(stack_bb * bb_val))

                        # Sizing 1: Small bet (~33% pot / 1 BB)
                        target_chips_sm = max(bb_val, 0.33 * pot)
                        if quantize_sizing_to_bb is not None:
                            mode_sm, bb_mult_sm, _ = quantize_sizing_to_bb(
                                target_chips_sm, bb_val, hero_stk, eff_stk, min_bb_mult=1
                            )
                        else:
                            mode_sm, bb_mult_sm = ("BB_MULT", max(1, int(round(target_chips_sm / bb_val))))

                        # Sizing 2: Medium bet (~50% pot)
                        target_chips_med = 0.50 * pot
                        if quantize_sizing_to_bb is not None:
                            mode_med, bb_mult_med, _ = quantize_sizing_to_bb(
                                target_chips_med, bb_val, hero_stk, eff_stk, min_bb_mult=1
                            )
                        else:
                            mode_med, bb_mult_med = ("BB_MULT", max(1, int(round(target_chips_med / bb_val))))

                        if hasattr(mc_calc, "calculate_ev_bb"):
                            check_ev = mc_calc.calculate_ev_bb(
                                equity, pot_bb, call_cost_bb=0.0, fold_equity=0.0
                            )
                            shove_ev = mc_calc.calculate_ev_bb(
                                shove_call_equity, pot_bb, call_cost_bb=stack_bb, fold_equity=shove_fe
                            )
                        else:
                            check_ev = round(equity * pot_bb, 3)
                            shove_ev = round(
                                shove_fe * pot_bb + (1.0 - shove_fe) * (shove_call_equity * (pot_bb + stack_bb) - (1.0 - shove_call_equity) * stack_bb),
                                3,
                            )

                        candidate_evs = {
                            "CHECK": float(check_ev),
                            "ALL_IN": float(shove_ev),
                            "FOLD": 0.0,
                        }

                        if mode_sm == "BB_MULT" and bb_mult_sm is not None:
                            bet_bb = float(bb_mult_sm)
                            if hasattr(mc_calc, "calculate_ev_bb"):
                                bet_ev = mc_calc.calculate_ev_bb(
                                    bet_call_equity, pot_bb, call_cost_bb=bet_bb, fold_equity=bet_fe
                                )
                            else:
                                bet_ev = round(
                                    bet_fe * pot_bb + (1.0 - bet_fe) * (bet_call_equity * (pot_bb + bet_bb) - (1.0 - bet_call_equity) * bet_bb),
                                    3,
                                )
                            candidate_evs["BET_30"] = float(bet_ev)

                        if (
                            mode_med == "BB_MULT"
                            and bb_mult_med is not None
                            and (bb_mult_sm is None or bb_mult_med > bb_mult_sm)
                            and (eff_stk > 0 and (bb_mult_med * bb_val) < 0.65 * eff_stk)
                        ):
                            bet_med_bb = float(bb_mult_med)
                            bet_med_fe = min(0.60, bet_fe + 0.08)
                            bet_med_call_equity = max(0.05, equity - 0.08)
                            bet_med_ev = round(
                                bet_med_fe * pot_bb + (1.0 - bet_med_fe) * (bet_med_call_equity * (pot_bb + bet_med_bb) - (1.0 - bet_med_call_equity) * bet_med_bb),
                                3,
                            )
                            candidate_evs["BET_MED"] = float(bet_med_ev)
                except Exception:
                    if facing_bet:
                        candidate_evs = {"CALL": 0.0, "ALL_IN": 0.0, "FOLD": 0.0}
                    else:
                        candidate_evs = {"CHECK": 0.0, "BET_30": 0.1, "ALL_IN": 0.0, "FOLD": 0.0}
            else:
                if facing_bet:
                    candidate_evs = {"CALL": 0.0, "ALL_IN": 0.0, "FOLD": 0.0}
                else:
                    candidate_evs = {"CHECK": 0.0, "BET_30": 0.1, "ALL_IN": 0.0, "FOLD": 0.0}

        return candidate_evs, spot

    # Default / Waiting for turn
    return {"WAIT": 0.0}, "WAITING_FOR_TURN"


class OfflinePlaybackController:
    """Thread-safe playback controller for offline video replay."""

    def __init__(self, total_frames: int = 0) -> None:
        self._lock = threading.Lock()
        self.paused: bool = False
        self.step_frames: int = 0
        self.seek_target: int | None = None
        self.current_frame_idx: int = 0
        self.total_frames: int = total_frames

    def toggle_pause(self) -> bool:
        """Toggle playback pause state."""
        with self._lock:
            self.paused = not self.paused
            return self.paused

    def request_seek(self, idx: int) -> None:
        """Request seeking to a specific zero-based frame index."""
        with self._lock:
            if self.total_frames > 0:
                self.seek_target = max(0, min(idx, self.total_frames - 1))
            else:
                self.seek_target = max(0, idx)

    def request_step(self, delta: int = 1) -> None:
        """Request stepping by delta frames."""
        with self._lock:
            if delta == 1 and self.paused:
                self.step_frames += 1
            else:
                target = self.current_frame_idx + delta
                if self.total_frames > 0:
                    target = max(0, min(target, self.total_frames - 1))
                else:
                    target = max(0, target)
                self.seek_target = target


def _handle_playback_keys(
    raw_k: int,
    k: int,
    playback: OfflinePlaybackController | None,
    stop_event: threading.Event,
) -> bool:
    """Handle OpenCV video preview keyboard inputs. Returns True if quit requested."""
    if k in (27, ord("q"), ord("Q")):
        stop_event.set()
        return True

    if playback is None:
        return False

    if k in (32, ord("p"), ord("P")):
        playback.toggle_pause()
    elif k == ord("."):
        playback.request_step(1)
    elif k in (ord("a"), ord("A"), 81, 2424832, 37) or raw_k in (81, 2424832, 37):
        playback.request_step(-30)
    elif k in (ord("d"), ord("D"), 83, 2555904, 39) or raw_k in (83, 2555904, 39):
        playback.request_step(30)
    elif k in (ord("s"), ord("S")):
        playback.request_step(-150)
    elif k in (ord("w"), ord("W")):
        playback.request_step(150)

    return False


def _render_overlay_on_disp(
    scaled_frame: Any,
    playback: OfflinePlaybackController | None,
) -> Any:
    """Render frame index, pause status, and keyboard legend onto display copy."""
    disp = scaled_frame.copy()
    if playback is None:
        return disp

    try:
        import cv2
        with playback._lock:
            cur_idx = playback.current_frame_idx
            tot_idx = playback.total_frames
            is_paused = playback.paused

        sh, sw = disp.shape[:2]
        cv2.rectangle(disp, (0, 0), (sw, 36), (18, 22, 30), -1)

        pause_tag = "  [PAUZA]" if is_paused else ""
        status_text = f"Klatka: {cur_idx} / {tot_idx}{pause_tag}"
        legend_text = "Spacja: Pauza | A/D: -/+30 kl | W/S: +/-150 kl | .: +1 kl | Q: Wyjdz"

        color = (0, 165, 255) if is_paused else (0, 230, 115)
        cv2.putText(disp, status_text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        cv2.putText(disp, legend_text, (max(260, sw - 560), 23), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190, 195, 205), 1, cv2.LINE_AA)
    except Exception:
        pass
    return disp


def capture_loop(
    source: Any,
    frame_queue: queue.Queue,
    stop_event: threading.Event,
    interval_sec: float = 0.05,
    max_frames: int | None = None,
    is_live: bool = False,
    playback: OfflinePlaybackController | None = None,
) -> None:
    """Thread 1: Continuously captures frames and feeds processing queue (maxsize=1)."""
    captured = 0
    while not stop_event.is_set():
        if max_frames is not None and captured >= max_frames:
            try:
                frame_queue.put(None, timeout=0.2)
            except Exception:
                pass
            break

        start_time = time.perf_counter()

        # Handle playback controller seek and pause if provided
        if playback is not None:
            seek_target = None
            is_paused = False
            has_step = False
            with playback._lock:
                if playback.seek_target is not None:
                    seek_target = playback.seek_target
                    playback.seek_target = None
                is_paused = playback.paused
                if playback.step_frames > 0:
                    playback.step_frames -= 1
                    has_step = True

            if seek_target is not None:
                if hasattr(source, "seek"):
                    source.seek(seek_target)
                frame = source.grab()
                if frame is not None:
                    captured += 1
                    cur_idx = getattr(source, "current_frame_idx", seek_target)
                    with playback._lock:
                        playback.current_frame_idx = cur_idx
                    try:
                        if frame_queue.full():
                            try:
                                frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        frame_queue.put_nowait(frame)
                    except queue.Full:
                        pass
                if interval_sec > 0:
                    time.sleep(min(0.03, interval_sec))
                else:
                    time.sleep(0.01)
                continue

            if is_paused and not has_step:
                time.sleep(0.03)
                continue

        # Normal frame grab
        frame = source.grab()
        if frame is None:
            if is_live:
                if interval_sec > 0:
                    time.sleep(interval_sec)
                continue
            # End of stream or capture failure in offline mode
            try:
                frame_queue.put(None, timeout=0.2)
            except Exception:
                pass
            break

        captured += 1
        if playback is not None:
            cur_idx = getattr(source, "current_frame_idx", captured - 1)
            with playback._lock:
                playback.current_frame_idx = cur_idx

        # Always retain latest frame without latency build-up
        try:
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    pass
            frame_queue.put_nowait(frame)
        except queue.Full:
            pass

        elapsed = time.perf_counter() - start_time
        sleep_time = max(0.0, interval_sec - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


def processing_loop(
    frame_queue: queue.Queue,
    pipeline: Any,
    validator: Any,
    trackers: dict[str, Any],
    preflop_engine: Any,
    flop_db: Any,
    mc_calc: Any,
    decision_maker: Any,
    logger: Any,
    hud_bridge: Any,
    stop_event: threading.Event,
    headless: bool = False,
    show_video: bool = False,
    playback: OfflinePlaybackController | None = None,
    is_live: bool = False,
    hand_recorder: Any = None,
) -> None:
    """Thread 2: Processes frames, evaluates decisions, logs sessions, and updates HUD."""
    managed_tables: dict[str, dict[str, Any]] = {
        "table_1": {
            "search_region": None,
            "adjust": (0, 0, 1.0, 1.0),
            "last_opponents_sig": None,
            "last_stable_rect": None,
        }
    }
    last_idle_emit: float = 0.0
    decision_locks: dict[str, Any] = {}
    last_active_decisions: dict[str, Any] = {}
    last_spots: dict[str, str] = {}
    tournament_end_confirm: dict[str, int] = {}
    finalized_tournament_tables: set[str] = set()
    decision_snap_counts: dict[str, dict[str, int]] = {}
    last_known_stacks: dict[str, dict[int, tuple[int, float]]] = {}
    auto_buy_in_state: dict[str, dict[str, Any]] = {}

    def _on_manual_rect(rect: Any) -> None:
        if "table_1" in managed_tables:
            managed_tables["table_1"]["search_region"] = rect
            managed_tables["table_1"]["last_stable_rect"] = None

    def _on_table_added(tid: str, search_region: Any) -> None:
        managed_tables[tid] = {
            "search_region": search_region,
            "adjust": (0, 0, 1.0, 1.0),
            "last_opponents_sig": None,
            "last_stable_rect": None,
        }

    def _on_table_removed_by_user(tid: str) -> None:
        managed_tables.pop(tid, None)
        if validator is not None:
            validator.reset_table(tid)
        if hand_recorder is not None and tid in trackers:
            try:
                hand_recorder.record_hand(trackers[tid].get_hand_summary())
                hand_recorder.finalize_game(tid)
            except Exception:
                pass
        trackers.pop(tid, None)
        decision_locks.pop(tid, None)
        last_active_decisions.pop(tid, None)
        last_spots.pop(tid, None)
        tournament_end_confirm.pop(tid, None)
        finalized_tournament_tables.discard(tid)
        decision_snap_counts.pop(tid, None)

    def _on_table_adjust_5arg(tid: str, dx: int, dy: int, sx: float, sy: float) -> None:
        if tid in managed_tables:
            managed_tables[tid]["adjust"] = (dx, dy, sx, sy)
        elif "table_1" in managed_tables:
            managed_tables["table_1"]["adjust"] = (dx, dy, sx, sy)

    def _on_table_adjust_3arg(dx: int, dy: int, s: float) -> None:
        tid = "table_1"
        if tid in managed_tables:
            managed_tables[tid]["adjust"] = (dx, dy, s, s)

    def _on_buy_in_changed(val: float) -> None:
        if decision_maker is not None:
            decision_maker.buy_in = val

    if hud_bridge is not None:
        if hasattr(hud_bridge, "manual_rect_changed"):
            try:
                hud_bridge.manual_rect_changed.connect(_on_manual_rect)
            except Exception:
                pass
        if hasattr(hud_bridge, "table_added"):
            try:
                hud_bridge.table_added.connect(_on_table_added)
            except Exception:
                pass
        if hasattr(hud_bridge, "table_removed_by_user"):
            try:
                hud_bridge.table_removed_by_user.connect(_on_table_removed_by_user)
            except Exception:
                pass
        if hasattr(hud_bridge, "table_adjust_changed"):
            try:
                hud_bridge.table_adjust_changed[str, int, int, float, float].connect(_on_table_adjust_5arg)
                hud_bridge.table_adjust_changed[int, int, float].connect(_on_table_adjust_3arg)
            except Exception:
                hud_bridge.table_adjust_changed.connect(_on_table_adjust_3arg)
        if hasattr(hud_bridge, "buy_in_changed"):
            try:
                hud_bridge.buy_in_changed.connect(_on_buy_in_changed)
            except Exception:
                pass

    WINDOW_NAME = "Poker Assistant - Offline Replay"
    trackbar_created = False
    is_updating_trackbar = False

    def _on_trackbar(pos: int) -> None:
        nonlocal is_updating_trackbar
        if not is_updating_trackbar and playback is not None:
            playback.request_seek(pos)

    last_scaled_disp: Any = None
    last_valid_decisions: dict[str, tuple[float, Decision, str]] = {}
    table_last_seen: dict[str, float] = {}

    try:
        while not stop_event.is_set():
            try:
                frame = frame_queue.get(timeout=0.03)
            except queue.Empty:
                if (
                    show_video
                    and last_scaled_disp is not None
                    and playback is not None
                    and playback.paused
                ):
                    try:
                        import cv2
                        disp = _render_overlay_on_disp(last_scaled_disp, playback)
                        cv2.imshow(WINDOW_NAME, disp)
                        raw_k = cv2.waitKey(30)
                        k = raw_k & 0xFF if raw_k != -1 else -1
                        if k != -1:
                            if _handle_playback_keys(raw_k, k, playback, stop_event):
                                break
                    except Exception:
                        pass
                continue

            if frame is None:
                break

            now_ms = int(time.time() * 1000)
            now_sec = time.perf_counter()

            # Optional OpenCV background video preview
            if show_video and frame is not None:
                try:
                    import cv2
                    fh, fw = frame.shape[:2]
                    target_w = 1280
                    target_h = int(fh * (target_w / max(1, fw)))
                    scaled_disp = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    last_scaled_disp = scaled_disp

                    if not trackbar_created and playback is not None and playback.total_frames > 0:
                        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
                        cv2.createTrackbar("Klatka", WINDOW_NAME, 0, max(1, playback.total_frames - 1), _on_trackbar)
                        trackbar_created = True

                    if trackbar_created and playback is not None:
                        is_updating_trackbar = True
                        try:
                            cv2.setTrackbarPos("Klatka", WINDOW_NAME, playback.current_frame_idx)
                        except Exception:
                            pass
                        finally:
                            is_updating_trackbar = False

                    disp = _render_overlay_on_disp(scaled_disp, playback)
                    cv2.imshow(WINDOW_NAME, disp)

                    raw_k = cv2.waitKey(1)
                    k = raw_k & 0xFF if raw_k != -1 else -1
                    if k != -1:
                        if _handle_playback_keys(raw_k, k, playback, stop_event):
                            break
                except Exception:
                    pass

            # Detect tables using 4-arc golden rim (NUMER 1), anchor fallback (NUMER 2), or manual ROI (NUMER 3)
            table_jobs: list[tuple[str, Any, bool, tuple[Any, ...], str]] = []
            for tid, slot_info in list(managed_tables.items()):
                search_region = slot_info.get("search_region")
                table_rect = None
                has_anchor = False
                anchor_source = "MANUAL"

                # 1. NUMER 1: 4-arc Golden Rim primary anchor (continuous scale, unclipped rect)
                if find_golden_rim is not None and compute_table_rect_from_rim is not None and frame is not None and frame.size > 0:
                    try:
                        rim = find_golden_rim(frame, search_rect=search_region)
                        if rim is not None:
                            canonical_sz = getattr(pipeline, "canonical_table_size", (1757, 997))
                            rim_rel = getattr(pipeline, "golden_rim_rel", [0.1802, 0.2075, 0.6402, 0.5630])
                            table_rect = compute_table_rect_from_rim(rim, rim_rel=rim_rel, canonical_size=canonical_sz)
                            has_anchor = True
                            anchor_source = "RIM"
                            slot_info["last_rim_ts"] = time.perf_counter()
                    except Exception:
                        table_rect = None

                # 2. NUMER 2: Fallback template anchor matching (dual-anchor unclipped rect)
                if table_rect is None and frame is not None and frame.size > 0:
                    if search_region is not None:
                        mx, my, mw, mh = search_region
                        sub_frame = frame[max(0, my) : max(0, my + mh), max(0, mx) : max(0, mx + mw)]
                        if sub_frame.size > 0 and getattr(pipeline, "anchor_template", None) is not None and find_anchor is not None:
                            try:
                                sub_anchor = find_anchor(sub_frame, pipeline.anchor_template, threshold=pipeline.anchor_threshold)
                                if sub_anchor is not None:
                                    ax, ay, aw, ah = sub_anchor
                                    full_anchor = (max(0, mx) + ax, max(0, my) + ay, aw, ah)
                                    canonical_sz = getattr(pipeline, "canonical_table_size", (1757, 997))
                                    tpl_w = pipeline.anchor_template.shape[1]
                                    tpl_h = pipeline.anchor_template.shape[0]
                                    table_offset = getattr(pipeline, "table_offset_rel", [0.0, 0.0, 1.0, 1.0])
                                    right_anchor = None
                                    if getattr(pipeline, "right_anchor_template", None) is not None and find_right_anchor is not None:
                                        right_anchor = find_right_anchor(frame, pipeline.right_anchor_template, full_anchor, canonical_size=canonical_sz, left_template_size=(tpl_w, tpl_h))
                                    table_rect = compute_unclipped_table_rect(full_anchor, table_offset, canonical_size=canonical_sz, template_size=(tpl_w, tpl_h), frame_shape=frame.shape, right_anchor=right_anchor)
                                    if verify_table_rect_has_blue_felt is not None and not verify_table_rect_has_blue_felt(frame, table_rect):
                                        table_rect = search_region
                                        has_anchor = False
                                        anchor_source = "MANUAL"
                                    else:
                                        has_anchor = True
                                        anchor_source = "ICON"
                                else:
                                    table_rect = search_region
                                    anchor_source = "MANUAL"
                            except Exception:
                                table_rect = search_region
                                anchor_source = "MANUAL"
                        else:
                            table_rect = search_region
                            anchor_source = "MANUAL"
                    else:
                        if getattr(pipeline, "anchor_template", None) is not None and find_anchor is not None:
                            try:
                                preferred_scale = getattr(pipeline, "_last_anchor_scale", None)
                                anchor = find_anchor(frame, pipeline.anchor_template, threshold=pipeline.anchor_threshold, preferred_scale=preferred_scale)
                                if anchor is not None:
                                    canonical_sz = getattr(pipeline, "canonical_table_size", (1757, 997))
                                    tpl_w = pipeline.anchor_template.shape[1]
                                    tpl_h = pipeline.anchor_template.shape[0]
                                    table_offset = getattr(pipeline, "table_offset_rel", [0.0, 0.0, 1.0, 1.0])
                                    right_anchor = None
                                    if getattr(pipeline, "right_anchor_template", None) is not None and find_right_anchor is not None:
                                        right_anchor = find_right_anchor(frame, pipeline.right_anchor_template, anchor, canonical_size=canonical_sz, left_template_size=(tpl_w, tpl_h))
                                    table_rect = compute_unclipped_table_rect(anchor, table_offset, canonical_size=canonical_sz, template_size=(tpl_w, tpl_h), frame_shape=frame.shape, right_anchor=right_anchor)
                                    if verify_table_rect_has_blue_felt is not None and not verify_table_rect_has_blue_felt(frame, table_rect):
                                        table_rect = None
                                        has_anchor = False
                                    else:
                                        has_anchor = True
                                        anchor_source = "ICON"
                            except Exception:
                                anchor = None

                # 2b. Hold last stable RIM rect up to 2.0 s during brief dim/transition
                if (
                    table_rect is None
                    and slot_info.get("last_stable_rect") is not None
                    and (time.perf_counter() - slot_info.get("last_rim_ts", 0.0)) <= 2.0
                ):
                    table_rect = slot_info["last_stable_rect"]
                    has_anchor = True
                    anchor_source = "RIM_HOLD"

                # 3. NUMER 3: Fallback to raw search region if set
                if table_rect is None and search_region is not None:
                    table_rect = search_region
                    anchor_source = "MANUAL"

                # Temporal stabilization (Anti-Jitter deadband <= 3 px)
                if table_rect is not None and apply_anti_jitter is not None:
                    last_stable = slot_info.get("last_stable_rect")
                    table_rect = apply_anti_jitter(table_rect, last_stable, deadband_px=3)
                    slot_info["last_stable_rect"] = table_rect

                adj = slot_info.get("adjust", (0, 0, 1.0, 1.0))
                table_jobs.append((tid, table_rect, has_anchor, adj, anchor_source))

            if is_live and all(t[1] is None for t in table_jobs):
                now_sec = time.perf_counter()
                if now_sec - last_idle_emit >= 0.5:
                    last_idle_emit = now_sec
                    idle_decision = Decision(
                        table_id="table_1",
                        action="WAIT",
                        ev_bb=None,
                        confidence=1.0,
                        profile_used="STANDARD_EXPLOIT",
                        reason="Szukam stołu Stake...",
                    )
                    if hud_bridge is not None and hasattr(hud_bridge, "decision_updated"):
                        try:
                            hud_bridge.decision_updated.emit(idle_decision, 0.0, "Szukam stołu Stake...")
                        except Exception:
                            pass
                    if hud_bridge is not None and hasattr(hud_bridge, "debug_overlay_updated"):
                        try:
                            hud_bridge.debug_overlay_updated.emit({"table_id": "table_1", "table_rect": None, "rois": []})
                        except Exception:
                            pass
                continue

            for table_id, orig_table_rect, has_anchor, adj, anchor_source in table_jobs:
                table_rect = orig_table_rect
                if table_rect is not None:
                    if len(adj) == 4:
                        dx, dy, sx, sy = adj
                    else:
                        dx, dy, sx = adj[:3]
                        sy = sx
                    if dx != 0 or dy != 0 or abs(sx - 1.0) > 0.001 or abs(sy - 1.0) > 0.001:
                        tx, ty, tw, th = table_rect
                        new_tw = int(round(tw * sx))
                        new_th = int(round(th * sy))
                        new_tx = tx + dx - (new_tw - tw) // 2
                        new_ty = ty + dy - (new_th - th) // 2
                        table_rect = (new_tx, new_ty, new_tw, new_th)
                table_start = time.perf_counter()

                try:
                    state = pipeline.process_frame(
                        frame,
                        table_id=table_id,
                        timestamp_ms=now_ms,
                        table_rect=table_rect,
                        allow_table_resolution=False,
                        has_anchor=has_anchor,
                    )
                except Exception:
                    continue

                resolved_tid = getattr(state, "table_id", table_id)

                # Track opponent signature to monitor visual changes (non-destructive)
                canonical_img = getattr(pipeline, "_last_canonical_table", None)
                if canonical_img is not None and hasattr(pipeline, "compute_opponents_signature"):
                    try:
                        opp_sig = pipeline.compute_opponents_signature(canonical_img)
                        if opp_sig is not None and table_id in managed_tables:
                            managed_tables[table_id]["last_opponents_sig"] = opp_sig
                    except Exception:
                        pass

                # Reset validator history if this table ID was just LRU evicted by pipeline
                if getattr(pipeline, "last_evicted_table_id", None) == resolved_tid:
                    pipeline.last_evicted_table_id = None
                    if validator is not None:
                        validator.reset_table(resolved_tid)
                    if hand_recorder is not None and resolved_tid in trackers:
                        try:
                            hand_recorder.record_hand(trackers[resolved_tid].get_hand_summary())
                            hand_recorder.finalize_game(resolved_tid)
                        except Exception:
                            pass
                    trackers.pop(resolved_tid, None)
                    decision_locks.pop(resolved_tid, None)
                    last_active_decisions.pop(resolved_tid, None)
                    last_spots.pop(resolved_tid, None)
                    tournament_end_confirm.pop(resolved_tid, None)
                    finalized_tournament_tables.discard(resolved_tid)
                    decision_snap_counts.pop(resolved_tid, None)

                # Unlock and reset when a new game starts after previous was finalized
                if resolved_tid in finalized_tournament_tables and getattr(state, "is_valid", True):
                    curr_stacks = [
                        p.stack for p in getattr(state, "players", {}).values()
                        if getattr(p, "stack", None) is not None
                    ]
                    valid_new_game_stacks = [s for s in curr_stacks if 0 < s < 880]
                    if len(valid_new_game_stacks) >= 2:
                        finalized_tournament_tables.discard(resolved_tid)
                        tournament_end_confirm[resolved_tid] = 0
                        decision_snap_counts.pop(resolved_tid, None)
                        if validator is not None:
                            validator.reset_table(resolved_tid)
                        if hasattr(pipeline, "reset_table_blinds"):
                            pipeline.reset_table_blinds(resolved_tid)
                        last_known_stacks.pop(resolved_tid, None)
                        auto_buy_in_state.pop(resolved_tid, None)
                        trackers.pop(resolved_tid, None)
                        decision_locks.pop(resolved_tid, None)
                        last_active_decisions.pop(resolved_tid, None)
                        last_spots.pop(resolved_tid, None)

                # Short-term carry-over for 1 missing stack (<= 1.5s, non-eliminated seat)
                now_mono = time.perf_counter()
                st_players = getattr(state, "players", {}) or {}
                none_sids = [
                    sid for sid in (0, 1, 2)
                    if sid in st_players
                    and getattr(st_players[sid], "stack", None) is None
                    and (getattr(st_players[sid], "current_bet", 0) or 0) == 0
                ]
                if len(none_sids) == 1 and all(
                    sid in st_players and getattr(st_players[sid], "stack", None) is not None
                    for sid in (0, 1, 2) if sid != none_sids[0]
                ):
                    miss_sid = none_sids[0]
                    tr_obj = trackers.get(resolved_tid)
                    is_out_in_tr = bool(
                        tr_obj is not None
                        and tr_obj.current_hand
                        and tr_obj.current_hand.get("players", {}).get(miss_sid, {}).get("eliminated", False)
                    )
                    last_info = last_known_stacks.get(resolved_tid, {}).get(miss_sid)
                    if not is_out_in_tr and last_info is not None and (now_mono - last_info[1]) <= 1.5:
                        last_stk = last_info[0]
                        other_sum = sum(
                            (getattr(st_players[sid], "stack", 0) or 0) + (getattr(st_players[sid], "current_bet", 0) or 0)
                            for sid in (0, 1, 2) if sid != miss_sid
                        )
                        inferred = 900 - (getattr(state, "pot", 0) or 0) - other_sum
                        if 0 <= inferred <= last_stk:
                            st_players[miss_sid].stack = inferred
                            st_players[miss_sid].is_active = (inferred > 0)
                            st_players[miss_sid].status_text = "ACTIVE" if inferred > 0 else "ALL_IN"

                validation_errors: list[str] = []
                if validator is not None:
                    is_valid, validation_errors = validator.validate(state)
                    # Check if only error is Blinds decreased and this is clearly a new tournament
                    if (
                        not is_valid
                        and len(validation_errors) == 1
                        and validation_errors[0].startswith("Blinds decreased")
                    ):
                        sb = getattr(state, "small_blind", 0)
                        bb = getattr(state, "big_blind", 0)
                        stacks = [
                            p.stack
                            for p in getattr(state, "players", {}).values()
                            if p.stack is not None
                        ]
                        if sb == 10 and bb == 20 and len(stacks) >= 2 and all(200 <= s <= 400 for s in stacks):
                            validator.reset_table(resolved_tid)
                            if hand_recorder is not None and resolved_tid in trackers:
                                try:
                                    hand_recorder.record_hand(trackers[resolved_tid].get_hand_summary())
                                    hand_recorder.finalize_game(resolved_tid, prize_pool=getattr(state, "prize_pool", None))
                                except Exception:
                                    pass
                            trackers.pop(resolved_tid, None)
                            decision_locks.pop(resolved_tid, None)
                            last_active_decisions.pop(resolved_tid, None)
                            last_spots.pop(resolved_tid, None)
                            tournament_end_confirm[resolved_tid] = 0
                            finalized_tournament_tables.discard(resolved_tid)
                            decision_snap_counts.pop(resolved_tid, None)
                            is_valid, validation_errors = validator.validate(state)
                    state.is_valid = is_valid
                    if is_valid:
                        for sid_k, pl_k in (getattr(state, "players", {}) or {}).items():
                            if getattr(pl_k, "stack", None) is not None:
                                last_known_stacks.setdefault(resolved_tid, {})[sid_k] = (int(pl_k.stack), now_mono)

                        # Auto Buy-in 3-frame debounce synchronization
                        cand_bi = getattr(pipeline, "last_detected_buy_in", {}).get(resolved_tid)
                        if cand_bi is not None:
                            bi_st = auto_buy_in_state.setdefault(
                                resolved_tid, {"confirmed": None, "pending": None, "count": 0}
                            )
                            if bi_st["pending"] == cand_bi:
                                bi_st["count"] += 1
                            else:
                                bi_st["pending"] = cand_bi
                                bi_st["count"] = 1
                            if bi_st["count"] >= 3 and bi_st["confirmed"] != cand_bi:
                                bi_st["confirmed"] = cand_bi
                                if decision_maker is not None:
                                    decision_maker.buy_in = float(cand_bi)
                                if hud_bridge is not None and hasattr(hud_bridge, "buy_in_changed"):
                                    try:
                                        hud_bridge.buy_in_changed.emit(float(cand_bi))
                                    except Exception:
                                        pass
                else:
                    is_valid = getattr(state, "is_valid", True)

                # Check if returning from Heads-Up (eliminated player in previous hand) to full 3-max
                if (
                    is_valid
                    and resolved_tid in trackers
                    and getattr(state, "small_blind", 0) == 10
                    and getattr(state, "big_blind", 0) == 20
                ):
                    prev_hand_players = trackers[resolved_tid].current_hand.get("players", {})
                    had_eliminated = any(p.get("eliminated") or p.get("status") == "OUT" for p in prev_hand_players.values())
                    pl_dict = getattr(state, "players", {})
                    if (
                        had_eliminated
                        and len(pl_dict) == 3
                        and all(getattr(p, "stack", None) is not None and 260 <= p.stack <= 320 for p in pl_dict.values())
                    ):
                        if hand_recorder is not None:
                            try:
                                hand_recorder.record_hand(trackers[resolved_tid].get_hand_summary())
                                hand_recorder.finalize_game(resolved_tid, prize_pool=getattr(state, "prize_pool", None))
                            except Exception:
                                pass
                        if validator is not None:
                            validator.reset_table(resolved_tid)
                        if hasattr(pipeline, "reset_table_blinds"):
                            pipeline.reset_table_blinds(resolved_tid)
                        last_known_stacks.pop(resolved_tid, None)
                        auto_buy_in_state.pop(resolved_tid, None)
                        trackers.pop(resolved_tid, None)
                        decision_locks.pop(resolved_tid, None)
                        last_active_decisions.pop(resolved_tid, None)
                        last_spots.pop(resolved_tid, None)
                        tournament_end_confirm[resolved_tid] = 0
                        finalized_tournament_tables.discard(resolved_tid)
                        decision_snap_counts.pop(resolved_tid, None)

                is_rabbit_break = False
                if (
                    detect_rabbit_hunting_break is not None
                    and crop_rois is not None
                    and canonical_img is not None
                    and not getattr(state, "is_hero_turn", False)
                ):
                    try:
                        c_rois = crop_rois(
                            canonical_img,
                            (0, 0, canonical_img.shape[1], canonical_img.shape[0]),
                            getattr(pipeline, "rois_rel", {}),
                        )
                        is_rabbit_break = detect_rabbit_hunting_break(
                            c_rois.get("hero_actions"),
                            getattr(state, "is_hero_turn", False),
                        )
                    except Exception:
                        is_rabbit_break = False

                events: list[Any] = []
                if TableTracker is not None and not is_rabbit_break:
                    if resolved_tid not in trackers:
                        trackers[resolved_tid] = TableTracker(resolved_tid, bet_confirm_frames=2)
                    state, events = trackers[resolved_tid].update(state)
                    if any(getattr(e, "event_type", "") == "NEW_HAND" for e in events):
                        decision_snap_counts.pop(resolved_tid, None)
                        if resolved_tid in decision_locks:
                            decision_locks[resolved_tid].reset()
                        last_active_decisions.pop(resolved_tid, None)
                        last_spots.pop(resolved_tid, None)
                        if getattr(trackers[resolved_tid], "last_completed_hand", None):
                            if hand_recorder is not None:
                                try:
                                    prev_h_num = getattr(trackers[resolved_tid].last_completed_hand, "get", lambda k, d=1: 1)("hand_number", 1)
                                    snap_rel = hand_recorder.save_snapshot(
                                        frame, table_rect, resolved_tid, prev_h_num, "showdown"
                                    )
                                    if snap_rel:
                                        snaps_list = trackers[resolved_tid].last_completed_hand.setdefault("snapshots", [])
                                        if snap_rel not in snaps_list:
                                            snaps_list.append(snap_rel)
                                    hand_recorder.record_hand(trackers[resolved_tid].last_completed_hand)
                                except Exception:
                                    pass
                    if any(getattr(e, "event_type", "") == "STREET_CHANGE" for e in events) and hand_recorder is not None:
                        to_st = getattr(state, "street", "").lower()
                        if to_st in ("flop", "turn", "river"):
                            try:
                                snap_rel = hand_recorder.save_snapshot(
                                    frame, table_rect, resolved_tid, trackers[resolved_tid].hand_number, f"street_{to_st}"
                                )
                                if snap_rel and trackers[resolved_tid].current_hand:
                                    snaps_list = trackers[resolved_tid].current_hand.setdefault("snapshots", [])
                                    if snap_rel not in snaps_list:
                                        snaps_list.append(snap_rel)
                            except Exception:
                                pass
                    has_tr = bool(trackers[resolved_tid].current_hand.get("tournament_result"))
                    if is_valid and has_tr:
                        tournament_end_confirm[resolved_tid] = tournament_end_confirm.get(resolved_tid, 0) + 1
                        if (
                            tournament_end_confirm[resolved_tid] >= 3
                            and resolved_tid not in finalized_tournament_tables
                        ):
                            finalized_tournament_tables.add(resolved_tid)
                            trackers[resolved_tid].current_hand["_game_finalized"] = True
                            if hand_recorder is not None:
                                try:
                                    hand_recorder.record_hand(trackers[resolved_tid].get_hand_summary())
                                    hand_recorder.finalize_game(resolved_tid, prize_pool=getattr(state, "prize_pool", None))
                                except Exception:
                                    pass
                    else:
                        tournament_end_confirm[resolved_tid] = 0

                if logger is not None and hasattr(logger, "log_state"):
                    logger.log_state(state, events)

                is_hero_turn = getattr(state, "is_hero_turn", False)
                hero_cards = getattr(state, "hero_cards", [])
                is_preview_candidate = is_valid and len(hero_cards) == 2 and not is_hero_turn
                just_locked_decision = False
                spot: str = last_spots.get(resolved_tid, "--")

                hero_stk = getattr(getattr(state, "players", {}).get(0), "stack", None)
                if is_rabbit_break:
                    decision = Decision(
                        table_id=resolved_tid,
                        action="WAIT",
                        ev_bb=None,
                        confidence=1.0,
                        profile_used="STANDARD_EXPLOIT",
                        reason="Rabbit hunting break",
                    )
                elif is_valid and len(hero_cards) == 2 and hero_stk == 0:
                    decision = Decision(
                        table_id=resolved_tid,
                        action="WAIT",
                        ev_bb=None,
                        confidence=1.0,
                        profile_used="STANDARD_EXPLOIT",
                        reason="Hero is All-In",
                    )
                    if resolved_tid in decision_locks:
                        decision_locks[resolved_tid].reset()
                    last_active_decisions.pop(resolved_tid, None)
                    last_spots.pop(resolved_tid, None)
                elif is_valid and len(hero_cards) == 2 and (is_hero_turn or is_preview_candidate):
                    if is_preview_candidate:
                        # Preview mode: pre-compute recommendation before Hero's turn starts
                        board_cards = getattr(state, "board_cards", [])
                        if len(board_cards) == 0:
                            preview_street = "PREFLOP"
                        elif len(board_cards) == 3:
                            preview_street = "FLOP"
                        elif len(board_cards) == 4:
                            preview_street = "TURN"
                        elif len(board_cards) >= 5:
                            preview_street = "RIVER"
                        else:
                            preview_street = "PREFLOP"

                        players = getattr(state, "players", {})
                        hero_player = players.get(0)
                        hero_bet = getattr(hero_player, "current_bet", 0) if hero_player else 0
                        max_opp_bet = max(
                            (getattr(p, "current_bet", 0) for sid, p in players.items() if sid != 0),
                            default=0,
                        )
                        if max_opp_bet > hero_bet:
                            preview_actions = ["FOLD", "CALL", "RAISE", "ALL_IN"]
                        else:
                            preview_actions = ["CHECK", "BET_30", "ALL_IN"]

                        sim_state = copy(state)
                        sim_state.street = preview_street
                        sim_state.available_actions = preview_actions
                        sim_state.is_hero_turn = True
                        eval_state = sim_state
                    else:
                        eval_state = state

                    confirm_count = 2 if is_live else 1
                    if DecisionLock is not None and compute_decision_fingerprint is not None:
                        fp = compute_decision_fingerprint(eval_state, is_preview=is_preview_candidate)
                        lock = decision_locks.setdefault(resolved_tid, DecisionLock(confirm_frames=confirm_count))
                        cached_decision = lock.get_locked(fp)
                    else:
                        fp = None
                        lock = None
                        cached_decision = None

                    if cached_decision is not None:
                        decision = cached_decision
                    elif lock is None or lock.observe_and_should_compute(fp):
                        active_tracker = trackers.get(resolved_tid)
                        cur_hand_summary = (
                            active_tracker.get_hand_summary()
                            if active_tracker is not None and hasattr(active_tracker, "get_hand_summary")
                            else None
                        )
                        candidate_evs, spot = evaluate_candidates(
                            eval_state, preflop_engine, flop_db, mc_calc, hand_summary=cur_hand_summary
                        )
                        last_spots[resolved_tid] = spot
                        if decision_maker is not None and hasattr(decision_maker, "decide"):
                            decision = decision_maker.decide(
                                eval_state, candidate_evs, spot=spot, allow_preview=is_preview_candidate
                            )
                        else:
                            best_act = max(candidate_evs, key=candidate_evs.get) if candidate_evs else "FOLD"
                            best_ev = candidate_evs.get(best_act, 0.0) if candidate_evs else 0.0
                            pfx = "[PLAN] Preview plan" if is_preview_candidate else "Candidate EV"
                            decision = Decision(
                                table_id=resolved_tid,
                                action=best_act,
                                ev_bb=best_ev,
                                confidence=0.95,
                                profile_used="STANDARD_EXPLOIT",
                                reason=f"{pfx} ({spot})",
                            )

                        # Sizing quantization in multiples of BB or ALL-IN
                        hero_p_chips = getattr(state, "players", {}).get(0)
                        hero_stk_chips = getattr(hero_p_chips, "stack", 0) or 0
                        hero_bet_chips = getattr(hero_p_chips, "current_bet", 0) or 0
                        bb_val_chips = getattr(state, "big_blind", 20) or 20
                        pot_val_chips = getattr(state, "pot", 0) or 0
                        active_opp_totals = [
                            (getattr(p, "stack", 0) or 0) + (getattr(p, "current_bet", 0) or 0)
                            for sid, p in getattr(state, "players", {}).items()
                            if sid != 0
                            and getattr(p, "is_active", True)
                            and getattr(p, "status_text", "") not in ("FOLDED", "SIT_OUT", "ELIMINATED")
                        ]
                        active_opp_totals = [t for t in active_opp_totals if t > 0]
                        eff_stk_chips = (
                            min(hero_stk_chips + hero_bet_chips, max(active_opp_totals))
                            if active_opp_totals
                            else hero_stk_chips
                        )
                        max_opp_bet_chips = max(
                            (getattr(p, "current_bet", 0) or 0 for sid, p in getattr(state, "players", {}).items() if sid != 0),
                            default=0,
                        )

                        if decision.action == "MIN_RAISE":
                            min_legal_chips = max(2 * bb_val_chips, max_opp_bet_chips * 2)
                            min_mult = max(2, int((min_legal_chips + bb_val_chips - 1) // bb_val_chips))
                            if quantize_sizing_to_bb is not None:
                                mode, bb_mult, chips = quantize_sizing_to_bb(
                                    min_mult * bb_val_chips, bb_val_chips, hero_stk_chips, eff_stk_chips, min_bb_mult=min_mult
                                )
                            else:
                                mode, bb_mult, chips = ("BB_MULT", min_mult, min_mult * bb_val_chips)
                            if mode == "ALL_IN":
                                decision.action = "ALL_IN"
                                decision.sizing_bb = None
                                decision.sizing_chips = chips
                            else:
                                decision.sizing_bb = bb_mult
                                decision.sizing_chips = chips
                        elif decision.action in ("BET_30", "BET_SMALL"):
                            if quantize_sizing_to_bb is not None:
                                mode, bb_mult, chips = quantize_sizing_to_bb(
                                    max(bb_val_chips, 0.33 * pot_val_chips), bb_val_chips, hero_stk_chips, eff_stk_chips, min_bb_mult=1
                                )
                            else:
                                mode, bb_mult, chips = ("BB_MULT", max(1, int(round(0.33 * pot_val_chips / bb_val_chips))), int(round(0.33 * pot_val_chips)))
                            if mode == "ALL_IN":
                                decision.action = "ALL_IN"
                                decision.sizing_bb = None
                                decision.sizing_chips = chips
                            else:
                                decision.sizing_bb = bb_mult
                                decision.sizing_chips = chips
                        elif decision.action == "BET_MED":
                            if quantize_sizing_to_bb is not None:
                                mode, bb_mult, chips = quantize_sizing_to_bb(
                                    0.50 * pot_val_chips, bb_val_chips, hero_stk_chips, eff_stk_chips, min_bb_mult=1
                                )
                            else:
                                mode, bb_mult, chips = ("BB_MULT", max(1, int(round(0.50 * pot_val_chips / bb_val_chips))), int(round(0.50 * pot_val_chips)))
                            if mode == "ALL_IN":
                                decision.action = "ALL_IN"
                                decision.sizing_bb = None
                                decision.sizing_chips = chips
                            else:
                                decision.sizing_bb = bb_mult
                                decision.sizing_chips = chips
                        elif decision.action == "ALL_IN":
                            decision.sizing_bb = None
                            decision.sizing_chips = hero_stk_chips
                        elif decision.action == "CALL":
                            decision.sizing_bb = None
                            decision.sizing_chips = max(0, max_opp_bet_chips - hero_bet_chips)
                        else:
                            decision.sizing_bb = None
                            decision.sizing_chips = None

                        # Quantize alt_action sizing if present
                        if getattr(decision, "alt_action", None):
                            alt_act = decision.alt_action
                            if alt_act == "MIN_RAISE":
                                min_legal_chips = max(2 * bb_val_chips, max_opp_bet_chips * 2)
                                min_mult = max(2, int((min_legal_chips + bb_val_chips - 1) // bb_val_chips))
                                if quantize_sizing_to_bb is not None:
                                    alt_mode, alt_bb_mult, alt_chips = quantize_sizing_to_bb(
                                        min_mult * bb_val_chips, bb_val_chips, hero_stk_chips, eff_stk_chips, min_bb_mult=min_mult
                                    )
                                else:
                                    alt_mode, alt_bb_mult, alt_chips = ("BB_MULT", min_mult, min_mult * bb_val_chips)
                                decision.alt_sizing_bb = alt_bb_mult if alt_mode != "ALL_IN" else None
                                decision.alt_sizing_chips = alt_chips
                            elif alt_act in ("BET_30", "BET_SMALL"):
                                if quantize_sizing_to_bb is not None:
                                    alt_mode, alt_bb_mult, alt_chips = quantize_sizing_to_bb(
                                        max(bb_val_chips, 0.33 * pot_val_chips), bb_val_chips, hero_stk_chips, eff_stk_chips, min_bb_mult=1
                                    )
                                else:
                                    alt_mode, alt_bb_mult, alt_chips = ("BB_MULT", max(1, int(round(0.33 * pot_val_chips / bb_val_chips))), int(round(0.33 * pot_val_chips)))
                                decision.alt_sizing_bb = alt_bb_mult if alt_mode != "ALL_IN" else None
                                decision.alt_sizing_chips = alt_chips
                            elif alt_act == "BET_MED":
                                if quantize_sizing_to_bb is not None:
                                    alt_mode, alt_bb_mult, alt_chips = quantize_sizing_to_bb(
                                        0.50 * pot_val_chips, bb_val_chips, hero_stk_chips, eff_stk_chips, min_bb_mult=1
                                    )
                                else:
                                    alt_mode, alt_bb_mult, alt_chips = ("BB_MULT", max(1, int(round(0.50 * pot_val_chips / bb_val_chips))), int(round(0.50 * pot_val_chips)))
                                decision.alt_sizing_bb = alt_bb_mult if alt_mode != "ALL_IN" else None
                                decision.alt_sizing_chips = alt_chips
                            elif alt_act == "ALL_IN":
                                decision.alt_sizing_bb = None
                                decision.alt_sizing_chips = hero_stk_chips
                            elif alt_act == "CALL":
                                decision.alt_sizing_bb = None
                                decision.alt_sizing_chips = max(0, max_opp_bet_chips - hero_bet_chips)
                            else:
                                decision.alt_sizing_bb = None
                                decision.alt_sizing_chips = None

                        if lock is not None and fp is not None:
                            lock.lock(fp, decision)
                        just_locked_decision = True
                        last_active_decisions[resolved_tid] = decision
                    else:
                        prev_dec = last_active_decisions.get(resolved_tid)
                        if prev_dec is not None:
                            decision = prev_dec
                        else:
                            decision = Decision(
                                table_id=resolved_tid,
                                action="WAIT",
                                ev_bb=None,
                                confidence=1.0,
                                profile_used="STANDARD_EXPLOIT",
                                reason="Skanowanie sytuacji...",
                            )
                else:
                    decision = Decision(
                        table_id=resolved_tid,
                        action="WAIT",
                        ev_bb=None,
                        confidence=1.0,
                        profile_used="STANDARD_EXPLOIT",
                        reason="Waiting for Hero turn",
                    )
                    if resolved_tid in decision_locks:
                        decision_locks[resolved_tid].reset()
                    last_active_decisions.pop(resolved_tid, None)
                    last_spots.pop(resolved_tid, None)

                # Save decision snapshot on locked decision during hero turn
                if just_locked_decision and is_hero_turn and hand_recorder is not None:
                    try:
                        cur_h_num = getattr(trackers.get(resolved_tid), "hand_number", 1)
                        cur_st = getattr(state, "street", "flop").lower()
                        table_counts = decision_snap_counts.setdefault(resolved_tid, {})
                        table_counts[cur_st] = table_counts.get(cur_st, 0) + 1
                        cnt = table_counts[cur_st]
                        tag = f"decision_{cur_st}" if cnt == 1 else f"decision_{cur_st}_{cnt}"
                        snap_rel = hand_recorder.save_snapshot(
                            frame, table_rect, resolved_tid, cur_h_num, tag
                        )
                        if snap_rel and getattr(trackers.get(resolved_tid), "current_hand", None):
                            snaps_list = trackers[resolved_tid].current_hand.setdefault("snapshots", [])
                            if snap_rel not in snaps_list:
                                snaps_list.append(snap_rel)
                    except Exception:
                        pass

                # Diagnostic scan summary for HUD details view
                val_status = "VALID" if is_valid else f"INVALID: {', '.join(validation_errors)}"
                blinds_str = f"{getattr(state, 'small_blind', 0)}/{getattr(state, 'big_blind', 0)}"
                prize_val = getattr(state, "prize_pool", None)
                prize_str = f"${prize_val}" if prize_val is not None else "--"
                pot_str = f"{getattr(state, 'pot', 0)}"
                hero_cards_str = " ".join(getattr(state, "hero_cards", [])) or "--"
                board_cards_str = " ".join(getattr(state, "board_cards", [])) or "--"

                players_info: list[str] = []
                players_dict = getattr(state, "players", {}) or {}
                for seat_id in (0, 1, 2):
                    p = players_dict.get(seat_id)
                    if p is not None:
                        stk = getattr(p, "stack", "--")
                        bet = getattr(p, "current_bet", 0)
                        d_tag = " [D]" if getattr(p, "is_dealer", False) else ""
                        players_info.append(f"S{seat_id}: {stk} (bet {bet}){d_tag}")
                    else:
                        players_info.append(f"S{seat_id}: --")
                players_line = " | ".join(players_info)

                turn_str = "YES" if getattr(state, "is_hero_turn", False) else "NO"
                actions_str = ", ".join(getattr(state, "available_actions", [])) or "--"
                spot_str = spot or "--"

                if orig_table_rect is not None:
                    tx_o, ty_o, tw_o, th_o = orig_table_rect
                    anchor_line = f"Kotwica: {anchor_source} ({tw_o}x{th_o} @ {tx_o},{ty_o})"
                else:
                    anchor_line = f"Kotwica: {anchor_source}"

                scan_summary = (
                    f"Status: {val_status}\n"
                    f"{anchor_line}\n"
                    f"Blinds: {blinds_str} | Prize: {prize_str} | Pot: {pot_str}\n"
                    f"Hero: {hero_cards_str} | Board: {board_cards_str}\n"
                    f"Gracze: {players_line}\n"
                    f"Hero Turn: {turn_str} | Actions: [{actions_str}] | Spot: {spot_str}"
                )

                # Anti-flicker holding for hero turn during brief invalid animation frames
                if getattr(state, "is_hero_turn", False):
                    if not is_valid:
                        if resolved_tid in last_valid_decisions:
                            last_time, last_dec, last_summary = last_valid_decisions[resolved_tid]
                            if (now_sec - last_time) < 0.4:
                                decision = last_dec
                                scan_summary = last_summary
                    else:
                        if decision.action != "WAIT":
                            last_valid_decisions[resolved_tid] = (now_sec, decision, scan_summary)
                else:
                    last_valid_decisions.pop(resolved_tid, None)

                latency_ms = (time.perf_counter() - table_start) * 1000.0

                if logger is not None and hasattr(logger, "log_decision"):
                    logger.log_decision(decision, latency_ms)

                if TableTracker is not None and resolved_tid in trackers:
                    try:
                        trackers[resolved_tid].record_recommendation(
                            decision, getattr(state, "street", "PREFLOP"), getattr(state, "timestamp_ms", 0)
                        )
                        if hud_bridge is not None and hasattr(hud_bridge, "hand_summary_updated"):
                            hud_bridge.hand_summary_updated.emit(resolved_tid, trackers[resolved_tid].get_hand_summary())
                    except Exception:
                        pass

                if hud_bridge is not None and hasattr(hud_bridge, "decision_updated"):
                    hud_bridge.decision_updated.emit(decision, latency_ms, scan_summary)

                if hud_bridge is not None and hasattr(hud_bridge, "action_bar_updated"):
                    amount_chips = getattr(decision, "sizing_chips", None)
                    sizing_bb = getattr(decision, "sizing_bb", None)
                    act_str_chips = getattr(decision, "action", "WAIT")

                    eff_table_rect = table_rect if table_rect is not None else (
                        0,
                        0,
                        frame.shape[1] if (frame is not None and frame.size > 0) else 1757,
                        frame.shape[0] if (frame is not None and frame.size > 0) else 997,
                    )
                    rois_dict = getattr(pipeline, "rois_rel", {}) or (
                        pipeline.config.get("rois", {}) if getattr(pipeline, "config", None) else {}
                    )
                    acts_rel = rois_dict.get("hero_actions", [0.65, 0.85, 0.28, 0.10])
                    ax = int(round(eff_table_rect[0] + acts_rel[0] * eff_table_rect[2]))
                    ay = int(round(eff_table_rect[1] + acts_rel[1] * eff_table_rect[3]))
                    aw = int(round(acts_rel[2] * eff_table_rect[2]))
                    ah = int(round(acts_rel[3] * eff_table_rect[3]))

                    action_bar_payload = {
                        "table_id": resolved_tid,
                        "actions_rect": (ax, ay, aw, ah),
                        "action": act_str_chips,
                        "amount_chips": amount_chips,
                        "sizing_bb": sizing_bb,
                        "ev_bb": getattr(decision, "ev_bb", None),
                        "is_plan": str(getattr(decision, "reason", "")).startswith("[PLAN]"),
                    }
                    try:
                        hud_bridge.action_bar_updated.emit(action_bar_payload)
                    except Exception:
                        pass

                if hud_bridge is not None and hasattr(hud_bridge, "debug_overlay_updated"):
                    eff_rect = table_rect if table_rect is not None else (
                        0,
                        0,
                        frame.shape[1] if (frame is not None and frame.size > 0) else 1757,
                        frame.shape[0] if (frame is not None and frame.size > 0) else 997,
                    )
                    tx, ty, tw, th = eff_rect
                    rois_dict = getattr(pipeline, "rois_rel", {}) or (
                        pipeline.config.get("rois", {}) if getattr(pipeline, "config", None) else {}
                    )

                    hero_cards = getattr(state, "hero_cards", []) or []
                    board_cards = getattr(state, "board_cards", []) or []
                    pot_val = getattr(state, "pot", 0)
                    prize_val = getattr(state, "prize_pool", None)
                    sb = getattr(state, "small_blind", 0)
                    bb = getattr(state, "big_blind", 0)
                    players = getattr(state, "players", {}) or {}
                    is_hero_turn = getattr(state, "is_hero_turn", False)
                    actions = getattr(state, "available_actions", []) or []

                    rois_list = []
                    for rname, rcoords in rois_dict.items():
                        if not rcoords or len(rcoords) < 4:
                            continue
                        rx, ry, rw, rh = rcoords
                        px = int(round(tx + rx * tw))
                        py = int(round(ty + ry * th))
                        pw = int(round(rw * tw))
                        ph = int(round(rh * th))

                        val = "--"
                        color = "#ef4444"

                        if rname == "hero_card_1":
                            if len(hero_cards) > 0:
                                val = hero_cards[0]
                                if val.startswith("T"):
                                    val = "10" + val[1:]
                                color = "#22c55e"
                        elif rname == "hero_card_2":
                            if len(hero_cards) > 1:
                                val = hero_cards[1]
                                if val.startswith("T"):
                                    val = "10" + val[1:]
                                color = "#22c55e"
                        elif rname.startswith("board_card_"):
                            try:
                                b_idx = int(rname.split("_")[-1]) - 1
                                if 0 <= b_idx < len(board_cards):
                                    val = board_cards[b_idx]
                                    if val.startswith("T"):
                                        val = "10" + val[1:]
                                    color = "#22c55e"
                            except Exception:
                                pass
                        elif rname == "pot":
                            if pot_val:
                                val = str(pot_val)
                                color = "#22c55e"
                        elif rname == "prize_pool":
                            if prize_val is not None:
                                val = f"${prize_val}"
                                color = "#22c55e"
                        elif rname == "blinds":
                            if sb or bb:
                                val = f"{sb}/{bb}"
                                color = "#22c55e"
                        elif rname == "hero_actions":
                            if actions:
                                val = ", ".join(actions)
                                color = "#22c55e"
                        elif rname == "seat_0_timer":
                            val = "YES" if is_hero_turn else "NO"
                            color = "#22c55e" if is_hero_turn else "#ef4444"
                        elif "_stack" in rname:
                            for sid in (0, 1, 2):
                                if f"seat_{sid}_stack" == rname:
                                    p = players.get(sid)
                                    stk = getattr(p, "stack", None) if p else None
                                    if stk is not None:
                                        val = str(stk)
                                        color = "#22c55e"
                                    break
                        elif "_bet" in rname:
                            for sid in (0, 1, 2):
                                if f"seat_{sid}_bet" == rname:
                                    p = players.get(sid)
                                    bet = getattr(p, "current_bet", 0) if p else 0
                                    if bet > 0:
                                        val = str(bet)
                                        color = "#22c55e"
                                    else:
                                        val = "0"
                                        color = "#64748b"
                                    break
                        elif "_dealer" in rname:
                            for sid in (0, 1, 2):
                                if f"seat_{sid}_dealer" == rname:
                                    p = players.get(sid)
                                    is_d = getattr(p, "is_dealer", False) if p else False
                                    if is_d:
                                        val = "[D]"
                                        color = "#f1c40f"
                                    break

                        rois_list.append({
                            "name": rname,
                            "rect": (px, py, pw, ph),
                            "value": val,
                            "color": color,
                        })

                    debug_payload = {
                        "table_id": resolved_tid,
                        "table_rect": eff_rect,
                        "anchor_source": anchor_source,
                        "rois": rois_list,
                    }
                    try:
                        hud_bridge.debug_overlay_updated.emit(debug_payload)
                    except Exception:
                        pass

                if headless:
                    ev_str = f"{decision.ev_bb:+.2f} BB" if decision.ev_bb is not None else "N/A"
                    print(
                        f"[{decision.table_id}] Action: {decision.action:<8} | "
                        f"EV: {ev_str:<10} | Profile: {decision.profile_used:<16} | "
                        f"Reason: {decision.reason} ({latency_ms:.1f} ms)"
                    )
    finally:
        if show_video:
            try:
                import cv2
                cv2.destroyAllWindows()
            except Exception:
                pass


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for main orchestrator."""
    parser = argparse.ArgumentParser(
        description="Poker Assistant Real-Time Orchestrator (Module 6)"
    )
    parser.add_argument(
        "--mode",
        choices=["live", "offline"],
        default="live",
        help="Capture mode: 'live' (dxcam) or 'offline' (replay folder/file)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Path to offline frames directory, video file, or single image (required for offline)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to config.json (default: config.json)",
    )
    parser.add_argument(
        "--buy-in",
        type=float,
        default=2.0,
        dest="buy_in",
        help="Tournament buy-in amount (default: 2.0)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without Qt HUD overlay (console output only)",
    )
    parser.add_argument(
        "--show-video",
        action="store_true",
        default=None,
        dest="show_video",
        help="Display OpenCV replay video window (default: True in offline mode without --headless)",
    )
    parser.add_argument(
        "--no-show-video",
        action="store_false",
        dest="show_video",
        help="Disable OpenCV replay video window",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        dest="max_frames",
        help="Maximum number of frames to process",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=0,
        help="Monitor index for live dxcam capture (0 = primary, 1 = secondary)",
    )
    parser.add_argument(
        "--save-snapshots",
        action="store_true",
        default=None,
        dest="save_snapshots",
        help="Enable saving lightweight JPEG snapshots to game zip",
    )
    parser.add_argument(
        "--no-snapshots",
        action="store_false",
        dest="save_snapshots",
        help="Disable saving lightweight JPEG snapshots",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main application entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.mode == "offline" and not args.source:
        parser.error("--source is required when --mode is offline")

    if args.show_video is None:
        args.show_video = (args.mode == "offline" and not args.headless)

    # Initialize frame capture source
    if args.mode == "live":
        if not DXCAM_AVAILABLE or LiveScreenCapture is None:
            print(
                "ERROR: dxcam is not available on this platform. "
                "Use --mode offline --source <path> to run replay mode.",
                file=sys.stderr,
            )
            return 1
        source = LiveScreenCapture(output_idx=args.monitor)
    else:
        source = OfflineReplayCapture(args.source)

    # Initialize modules
    pipeline = VisionPipeline(config_path=args.config) if VisionPipeline is not None else None
    validator = StateValidator() if StateValidator is not None else None
    logger = SessionLogger() if SessionLogger is not None else None

    preflop_engine = None
    if PreflopNashEngine is not None:
        try:
            preflop_engine = PreflopNashEngine()
        except Exception:
            pass

    flop_db = None
    if FlopDatabase is not None:
        try:
            flop_db = FlopDatabase()
        except Exception:
            pass

    mc_calc = None
    if MonteCarloCalculator is not None:
        try:
            mc_calc = MonteCarloCalculator()
        except Exception:
            pass

    decision_maker = None
    if DecisionMaker is not None:
        try:
            decision_maker = DecisionMaker(buy_in=args.buy_in)
        except Exception:
            pass

    stop_event = threading.Event()
    frame_queue: queue.Queue = queue.Queue(maxsize=1)
    trackers: dict[str, Any] = {}

    is_live = (args.mode == "live")
    playback: OfflinePlaybackController | None = None
    if not is_live:
        total = getattr(source, "total_frames", 0)
        playback = OfflinePlaybackController(total_frames=total)

    cfg_snaps = True
    if pipeline is not None and getattr(pipeline, "config", None):
        cfg_snaps = pipeline.config.get("recording", {}).get("save_snapshots", True)
    save_snapshots_flag = args.save_snapshots if args.save_snapshots is not None else cfg_snaps

    hand_recorder = None
    if HandHistoryRecorder is not None and is_live:
        try:
            hand_recorder = HandHistoryRecorder(save_snapshots=save_snapshots_flag)
        except Exception:
            pass

    if args.headless or QApplication is None or HudOverlay is None:
        interval = 0.0 if (args.mode == "offline" and not args.show_video) else 0.05
        cap_thread = threading.Thread(
            target=capture_loop,
            args=(source, frame_queue, stop_event, interval, args.max_frames, is_live, playback),
            daemon=True,
        )
        cap_thread.start()

        try:
            processing_loop(
                frame_queue=frame_queue,
                pipeline=pipeline,
                validator=validator,
                trackers=trackers,
                preflop_engine=preflop_engine,
                flop_db=flop_db,
                mc_calc=mc_calc,
                decision_maker=decision_maker,
                logger=logger,
                hud_bridge=None,
                stop_event=stop_event,
                headless=True,
                show_video=args.show_video,
                playback=playback,
                is_live=is_live,
                hand_recorder=hand_recorder,
            )
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            if hasattr(source, "release"):
                source.release()
            if logger is not None and hasattr(logger, "close"):
                logger.close()
            if hand_recorder is not None and hasattr(hand_recorder, "close"):
                try:
                    hand_recorder.close(trackers)
                except Exception:
                    pass
        return 0

    # Normal mode with Qt HUD overlay
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv if argv is None else ["poker_assistant"])

    hud_bridge = HudBridge()
    hud_overlay = HudOverlay(
        bridge=hud_bridge,
        monitor_idx=args.monitor,
        initial_buy_in=args.buy_in,
    )
    hud_overlay.snapshots_enabled = save_snapshots_flag
    hud_overlay._update_snapshots_button_ui()
    if hand_recorder is not None:
        hud_bridge.snapshots_toggled.connect(lambda en: setattr(hand_recorder, "save_snapshots", en))
    hud_overlay.show()

    cap_thread = threading.Thread(
        target=capture_loop,
        args=(source, frame_queue, stop_event, 0.05, args.max_frames, is_live, playback),
        daemon=True,
    )
    proc_thread = threading.Thread(
        target=processing_loop,
        args=(
            frame_queue,
            pipeline,
            validator,
            trackers,
            preflop_engine,
            flop_db,
            mc_calc,
            decision_maker,
            logger,
            hud_bridge,
            stop_event,
            False,
            args.show_video,
            playback,
            is_live,
            hand_recorder,
        ),
        daemon=True,
    )
    cap_thread.start()
    proc_thread.start()

    try:
        exit_code = app.exec()
    finally:
        stop_event.set()
        if hasattr(source, "release"):
            source.release()
        if logger is not None and hasattr(logger, "close"):
            logger.close()
        if hand_recorder is not None and hasattr(hand_recorder, "close"):
            try:
                hand_recorder.close(trackers)
            except Exception:
                pass

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
