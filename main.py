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
        compute_table_rect,
        compute_unclipped_table_rect,
        find_all_anchors,
        find_anchor,
    )
    from vision.capture import (
        DXCAM_AVAILABLE,
        FrameSource,
        LiveScreenCapture,
        OfflineReplayCapture,
    )
    from vision.pipeline import VisionPipeline
except ImportError:
    find_all_anchors = None  # type: ignore[assignment]
    find_anchor = None  # type: ignore[assignment]
    compute_table_rect = None  # type: ignore[assignment]
    compute_unclipped_table_rect = None  # type: ignore[assignment]
    DXCAM_AVAILABLE = False
    FrameSource = Any  # type: ignore[misc, assignment]
    LiveScreenCapture = Any  # type: ignore[misc, assignment]
    OfflineReplayCapture = Any  # type: ignore[misc, assignment]
    VisionPipeline = Any  # type: ignore[misc, assignment]

# State module
try:
    from state.logger import SessionLogger
    from state.tracker import TableTracker
    from state.validator import StateValidator
except ImportError:
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
except ImportError:
    DecisionMaker = None

# UI module
try:
    from PySide6.QtWidgets import QApplication
    from ui.hud import HudBridge, HudOverlay
except ImportError:
    QApplication = None  # type: ignore[assignment]
    HudBridge = None  # type: ignore[assignment]
    HudOverlay = None  # type: ignore[assignment]


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

        if sb_bet > bb_val or sb_status == "ALL_IN":
            if _is_preflop_shove(sb_player, bb_val):
                return "BB_VS_SB_SHOVE"
            return "BB_VS_SB_RAISE"
        if bb_bet > bb_val or bb_status == "ALL_IN":
            if _is_preflop_shove(bb_player, bb_val):
                return "BB_VS_SB_SHOVE"
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

        if btn_bet > bb_val or btn_status == "ALL_IN":
            if _is_preflop_shove(btn_player, bb_val):
                return "BB_VS_BTN_SHOVE"
            return "BB_VS_BTN_RAISE"
        if sb_bet > bb_val or sb_status == "ALL_IN":
            if _is_preflop_shove(sb_player, bb_val):
                return "BB_VS_SB_SHOVE"
            return "BB_VS_SB_RAISE"
        if btn_bet == bb_val or sb_bet == bb_val or (btn_bet > 0 and btn_bet <= bb_val):
            return "BB_ISO_VS_LIMP"
        return "BB_ISO_VS_LIMP"

    return "BTN_OPEN"


def evaluate_candidates(
    state: Any,
    preflop_engine: Any,
    flop_db: Any,
    mc_calc: Any,
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

            if mc_calc is not None and hasattr(mc_calc, "estimate_equity") and len(hero_cards) == 2:
                try:
                    equity = mc_calc.estimate_equity(hero_cards, [], time_budget_ms=40.0)
                    call_equity = max(0.05, equity - 0.05)
                    shove_call_equity = max(0.05, equity - 0.10)
                    shove_fe = 0.28
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
        spot = street
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

        # 1. Flop canonical database lookup (FLOP only)
        if (
            street == "FLOP"
            and flop_db is not None
            and hasattr(flop_db, "lookup")
            and len(board_cards) == 3
            and len(hero_cards) == 2
        ):
            try:
                lookup_res = flop_db.lookup(board_cards, hero_cards, effective_bb)
                if lookup_res is not None:
                    candidate_evs = {k: float(v) for k, v in lookup_res.items()}
                    if "FOLD" not in candidate_evs:
                        candidate_evs["FOLD"] = 0.0
            except Exception:
                candidate_evs = None

        # 2. Monte Carlo estimation fallback (< 80 ms) or CALL EV computation when facing bet
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

                    equity = mc_calc.estimate_equity(
                        hero_cards,
                        board_cards,
                        time_budget_ms=80.0,
                        num_opponents=num_opps,
                    )

                    if facing_bet:
                        call_equity = max(0.05, equity - 0.08)
                        shove_call_equity = max(0.05, equity - 0.16)
                        shove_fe = 0.18
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
                        shove_fe = 0.30 if spr <= 1.5 else (0.22 if spr <= 3.0 else 0.15)
                        shove_call_equity = max(0.05, equity - 0.14)
                        bet_call_equity = max(0.05, equity - 0.06)
                        bet_fe = 0.25
                        if num_opps == 2:
                            shove_fe *= 0.65
                            bet_fe *= 0.65

                        if hasattr(mc_calc, "calculate_ev_bb"):
                            check_ev = mc_calc.calculate_ev_bb(
                                equity, pot_bb, call_cost_bb=0.0, fold_equity=0.0
                            )
                            bet_ev = mc_calc.calculate_ev_bb(
                                bet_call_equity, pot_bb, call_cost_bb=bet30_bb, fold_equity=bet_fe
                            )
                            shove_ev = mc_calc.calculate_ev_bb(
                                shove_call_equity, pot_bb, call_cost_bb=stack_bb, fold_equity=shove_fe
                            )
                        else:
                            check_ev = round(equity * pot_bb, 3)
                            bet_ev = round(
                                bet_fe * pot_bb + (1.0 - bet_fe) * (bet_call_equity * (pot_bb + bet30_bb) - (1.0 - bet_call_equity) * bet30_bb),
                                3,
                            )
                            shove_ev = round(
                                shove_fe * pot_bb + (1.0 - shove_fe) * (shove_call_equity * (pot_bb + stack_bb) - (1.0 - shove_call_equity) * stack_bb),
                                3,
                            )

                        candidate_evs = {
                            "CHECK": float(check_ev),
                            "BET_30": float(bet_ev),
                            "ALL_IN": float(shove_ev),
                            "FOLD": 0.0,
                        }
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
        else:
            # If candidate_evs was obtained from flop_db and Hero faces bet:
            if facing_bet:
                candidate_evs.pop("CHECK", None)
                if "CALL" not in candidate_evs:
                    if mc_calc is not None and hasattr(mc_calc, "estimate_equity") and len(hero_cards) == 2:
                        try:
                            equity = mc_calc.estimate_equity(hero_cards, board_cards, time_budget_ms=40.0)
                            if hasattr(mc_calc, "calculate_ev_bb"):
                                call_ev = mc_calc.calculate_ev_bb(
                                    equity, pot_bb, call_cost_bb=to_call_bb, fold_equity=0.0
                                )
                            else:
                                call_ev = round(
                                    equity * (pot_bb + to_call_bb) - (1.0 - equity) * to_call_bb, 3
                                )
                            candidate_evs["CALL"] = float(call_ev)
                        except Exception:
                            candidate_evs["CALL"] = 0.0
                    else:
                        candidate_evs["CALL"] = 0.0

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
) -> None:
    """Thread 2: Processes frames, evaluates decisions, logs sessions, and updates HUD."""
    manual_rect_holder: list[tuple[int, int, int, int] | None] = [None]
    last_idle_emit: float = 0.0

    def _on_manual_rect(rect: Any) -> None:
        manual_rect_holder[0] = rect

    if hud_bridge is not None and hasattr(hud_bridge, "manual_rect_changed"):
        try:
            hud_bridge.manual_rect_changed.connect(_on_manual_rect)
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

            # Detect anchors or fallback to single table / manual ROI
            manual_rect = manual_rect_holder[0]
            if manual_rect is not None:
                mx, my, mw, mh = manual_rect
                sub_anchor = None
                if (
                    getattr(pipeline, "anchor_template", None) is not None
                    and find_anchor is not None
                    and frame is not None
                    and frame.size > 0
                ):
                    sub_frame = frame[max(0, my) : max(0, my + mh), max(0, mx) : max(0, mx + mw)]
                    if sub_frame.size > 0:
                        try:
                            preferred_scale = getattr(pipeline, "_last_anchor_scale", None)
                            sub_anchor = find_anchor(
                                sub_frame,
                                pipeline.anchor_template,
                                threshold=pipeline.anchor_threshold,
                                preferred_scale=preferred_scale,
                            )
                        except Exception:
                            sub_anchor = None

                if sub_anchor is not None:
                    ax, ay, aw, ah = sub_anchor
                    full_anchor = (max(0, mx) + ax, max(0, my) + ay, aw, ah)
                    anchors = [full_anchor]
                    if getattr(pipeline, "anchor_template", None) is not None:
                        tpl_w = pipeline.anchor_template.shape[1]
                        if tpl_w > 0:
                            pipeline._last_anchor_scale = aw / tpl_w
                    if compute_unclipped_table_rect is not None:
                        tpl_w = pipeline.anchor_template.shape[1] if getattr(pipeline, "anchor_template", None) is not None else None
                        tpl_h = pipeline.anchor_template.shape[0] if getattr(pipeline, "anchor_template", None) is not None else None
                        template_size = (tpl_w, tpl_h) if tpl_w and tpl_h else None
                        canonical_sz = getattr(pipeline, "canonical_table_size", (1757, 997))
                        table_offset = getattr(pipeline, "table_offset_rel", [0.0, 0.0, 1.0, 1.0])
                        table_rect = compute_unclipped_table_rect(
                            full_anchor,
                            table_offset,
                            canonical_size=canonical_sz,
                            template_size=template_size,
                            frame_shape=frame.shape,
                        )
                    elif compute_table_rect is not None:
                        table_rect = compute_table_rect(full_anchor, pipeline.table_offset_rel, frame.shape)
                    else:
                        table_rect = manual_rect
                    table_jobs = [("table_1", table_rect)]
                else:
                    table_jobs = [("table_1", manual_rect)]
                    anchors = []
            else:
                anchors = []
                if (
                    getattr(pipeline, "anchor_template", None) is not None
                    and find_all_anchors is not None
                ):
                    try:
                        preferred_scale = getattr(pipeline, "_last_anchor_scale", None)
                        anchors = find_all_anchors(
                            frame,
                            pipeline.anchor_template,
                            threshold=pipeline.anchor_threshold,
                            preferred_scale=preferred_scale,
                        )
                        if anchors and getattr(pipeline, "anchor_template", None) is not None:
                            tpl_w = pipeline.anchor_template.shape[1]
                            pipeline._last_anchor_scale = anchors[0][2] / tpl_w
                    except Exception:
                        anchors = []

                if is_live and not anchors:
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
                                hud_bridge.debug_overlay_updated.emit({"table_rect": None, "rois": []})
                            except Exception:
                                pass
                    continue

                table_jobs = []
                if anchors and compute_unclipped_table_rect is not None:
                    tpl_w = pipeline.anchor_template.shape[1] if getattr(pipeline, "anchor_template", None) is not None else None
                    tpl_h = pipeline.anchor_template.shape[0] if getattr(pipeline, "anchor_template", None) is not None else None
                    template_size = (tpl_w, tpl_h) if tpl_w and tpl_h else None
                    canonical_sz = getattr(pipeline, "canonical_table_size", (1757, 997))
                    table_offset = getattr(pipeline, "table_offset_rel", [0.0, 0.0, 1.0, 1.0])
                    for idx, anchor in enumerate(anchors):
                        table_id = f"table_{idx + 1}"
                        table_rect = compute_unclipped_table_rect(
                            anchor,
                            table_offset,
                            canonical_size=canonical_sz,
                            template_size=template_size,
                            frame_shape=frame.shape,
                        )
                        table_jobs.append((table_id, table_rect))
                elif anchors and compute_table_rect is not None:
                    for idx, anchor in enumerate(anchors):
                        table_id = f"table_{idx + 1}"
                        table_rect = compute_table_rect(anchor, pipeline.table_offset_rel, frame.shape)
                        table_jobs.append((table_id, table_rect))
                else:
                    table_jobs.append(("table_1", None))

            for table_id, table_rect in table_jobs:
                table_start = time.perf_counter()

                try:
                    state = pipeline.process_frame(
                        frame,
                        table_id=table_id,
                        timestamp_ms=now_ms,
                        table_rect=table_rect,
                        allow_table_resolution=(len(anchors) <= 1 if (manual_rect is None or len(anchors) > 0) else False),
                        has_anchor=(len(anchors) > 0),
                    )
                except Exception:
                    continue

                resolved_tid = getattr(state, "table_id", table_id)

                now_sec = time.perf_counter()
                if len(anchors) <= 1:
                    table_last_seen[resolved_tid] = now_sec
                    stale_tids = [
                        tid for tid, last_t in table_last_seen.items()
                        if now_sec - last_t > 5.0 and tid != resolved_tid
                    ]
                    for stale_tid in stale_tids:
                        table_last_seen.pop(stale_tid, None)
                        if hud_bridge is not None and hasattr(hud_bridge, "table_removed"):
                            try:
                                hud_bridge.table_removed.emit(stale_tid)
                            except Exception:
                                pass

                # Reset validator history if this table ID was just LRU evicted by pipeline
                if getattr(pipeline, "last_evicted_table_id", None) == resolved_tid:
                    pipeline.last_evicted_table_id = None
                    if validator is not None:
                        validator.reset_table(resolved_tid)
                    trackers.pop(resolved_tid, None)

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
                            trackers.pop(resolved_tid, None)
                            is_valid, validation_errors = validator.validate(state)
                    state.is_valid = is_valid
                else:
                    is_valid = getattr(state, "is_valid", True)

                events: list[Any] = []
                if TableTracker is not None:
                    if resolved_tid not in trackers:
                        trackers[resolved_tid] = TableTracker(resolved_tid)
                    state, events = trackers[resolved_tid].update(state)

                if logger is not None and hasattr(logger, "log_state"):
                    logger.log_state(state, events)

                is_hero_turn = getattr(state, "is_hero_turn", False)
                hero_cards = getattr(state, "hero_cards", [])
                is_preview_candidate = is_valid and len(hero_cards) == 2 and not is_hero_turn

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

                    candidate_evs, spot = evaluate_candidates(
                        sim_state, preflop_engine, flop_db, mc_calc
                    )
                    if decision_maker is not None and hasattr(decision_maker, "decide"):
                        decision = decision_maker.decide(
                            sim_state, candidate_evs, spot=spot, allow_preview=True
                        )
                    else:
                        best_act = max(candidate_evs, key=candidate_evs.get) if candidate_evs else "FOLD"
                        decision = Decision(
                            table_id=resolved_tid,
                            action=best_act,
                            ev_bb=candidate_evs.get(best_act, 0.0),
                            confidence=0.95,
                            profile_used="STANDARD_EXPLOIT",
                            reason=f"[PLAN] Preview plan ({spot})",
                        )
                else:
                    candidate_evs, spot = evaluate_candidates(
                        state, preflop_engine, flop_db, mc_calc
                    )
                    if decision_maker is not None and hasattr(decision_maker, "decide"):
                        decision = decision_maker.decide(
                            state, candidate_evs, spot=spot, allow_preview=False
                        )
                    else:
                        if (
                            not getattr(state, "is_valid", False)
                            or not is_hero_turn
                            or getattr(state, "street", "") == "WAITING_FOR_TURN"
                        ):
                            decision = Decision(
                                table_id=resolved_tid,
                                action="WAIT",
                                ev_bb=None,
                                confidence=1.0,
                                profile_used="STANDARD_EXPLOIT",
                                reason="Waiting for Hero turn",
                            )
                        else:
                            best_act = max(candidate_evs, key=candidate_evs.get) if candidate_evs else "FOLD"
                            best_ev = candidate_evs.get(best_act, 0.0) if candidate_evs else 0.0
                            decision = Decision(
                                table_id=resolved_tid,
                                action=best_act,
                                ev_bb=best_ev,
                                confidence=0.95,
                                profile_used="STANDARD_EXPLOIT",
                                reason=f"Candidate EV ({spot})",
                            )

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

                scan_summary = (
                    f"Status: {val_status}\n"
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

                if hud_bridge is not None and hasattr(hud_bridge, "decision_updated"):
                    hud_bridge.decision_updated.emit(decision, latency_ms, scan_summary)

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
            )
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            if hasattr(source, "release"):
                source.release()
            if logger is not None and hasattr(logger, "close"):
                logger.close()
        return 0

    # Normal mode with Qt HUD overlay
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv if argv is None else ["poker_assistant"])

    hud_bridge = HudBridge()
    hud_overlay = HudOverlay(bridge=hud_bridge)
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

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
