"""Generate V3 Audit Report and Annotated Verification Screenshots."""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

from core.contracts import Decision, TableState
from engine.flop_db import FlopDatabase
from engine.monte_carlo import MonteCarloCalculator
from engine.preflop_nash import PreflopNashEngine
from main import evaluate_candidates
from state.tracker import TableTracker
from state.validator import StateValidator
from strategy.decision_maker import DecisionMaker
from vision.pipeline import VisionPipeline


def annotate_frame(
    frame: np.ndarray,
    f_idx: int,
    state: TableState,
    is_valid: bool,
    reasons: list[str],
    spot: str,
    decision: Decision,
    latency_ms: float,
) -> np.ndarray:
    """Annotate frame with HUD inspection boxes and data overlay."""
    out = frame.copy()
    h, w = out.shape[:2]

    # Create top banner
    banner_h = 130
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, banner_h), (18, 22, 32), -1)
    cv2.addWeighted(overlay, 0.88, out, 0.12, 0, out)

    # Format texts
    time_str = f"{int(f_idx / 30 // 60):02d}:{int(f_idx / 30 % 60):02d}.{int((f_idx % 30) / 30 * 100):02d}"
    hero_cards = " ".join(getattr(state, "hero_cards", [])) or "--"
    board_cards = " ".join(getattr(state, "board_cards", [])) or "--"
    
    players = getattr(state, "players", {})
    s0 = players.get(0)
    s1 = players.get(1)
    s2 = players.get(2)
    
    s0_str = f"S0(Hero): {getattr(s0, 'stack', 0)} (Bet: {getattr(s0, 'current_bet', 0)}) {'[D]' if getattr(s0, 'is_dealer', False) else ''}"
    s1_str = f"S1: {getattr(s1, 'stack', 0)} (Bet: {getattr(s1, 'current_bet', 0)}) {'[D]' if getattr(s1, 'is_dealer', False) else ''}"
    s2_str = f"S2: {getattr(s2, 'stack', 0)} (Bet: {getattr(s2, 'current_bet', 0)}) {'[D]' if getattr(s2, 'is_dealer', False) else ''}"
    
    pot_val = getattr(state, "pot", 0)
    bb_val = getattr(state, "big_blind", 20)
    sb_val = getattr(state, "small_blind", 10)
    prize = getattr(state, "prize_pool", 4)
    actions = getattr(state, "available_actions", [])
    act_str = f"[{', '.join(actions)}]" if actions else "[]"
    
    stacks_sum = sum(getattr(p, "stack", 0) or 0 for p in players.values())
    bets_sum = sum(getattr(p, "current_bet", 0) or 0 for p in players.values())
    total_chips = stacks_sum + bets_sum + (pot_val or 0)
    
    # Line 1: Frame info, Validity, Blinds, Prize Pool, Pot, Chips
    val_color = (0, 255, 0) if is_valid else (0, 0, 255)
    val_status = "VALID" if is_valid else f"INVALID ({'; '.join(reasons)})"
    line1 = f"Frame {f_idx:04d} ({time_str}) | Status: {val_status} | Blinds: {sb_val}/{bb_val} | Prize: ${prize} | Pot: {pot_val} | Chips: {total_chips}/900"
    cv2.putText(out, line1, (15, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    
    # Line 2: Cards, Stacks & Bets
    line2 = f"Hero: [{hero_cards}] | Board: [{board_cards}] | {s0_str} | {s1_str} | {s2_str}"
    cv2.putText(out, line2, (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 240, 255), 2, cv2.LINE_AA)
    
    # Line 3: Decision & Strategy info
    ev_str = f"{decision.ev_bb:+.2f} BB" if decision.ev_bb is not None else "--"
    is_hero_str = "YES (Timer Active)" if getattr(state, "is_hero_turn", False) else "NO"
    dec_color = (0, 255, 100) if decision.action in ("CALL", "CHECK", "PUSH", "ALL_IN") else ((100, 100, 255) if decision.action == "FOLD" else (200, 200, 200))
    line3 = f"Hero Turn: {is_hero_str} | Actions: {act_str} | Spot: {spot} | Decision: {decision.action} ({ev_str}) | Profile: {decision.profile_used} | {latency_ms:.1f}ms"
    cv2.putText(out, line3, (15, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.68, dec_color, 2, cv2.LINE_AA)
    
    # Line 4: Reason
    line4 = f"Reason: {decision.reason}"
    cv2.putText(out, line4, (15, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 200, 220), 1, cv2.LINE_AA)
    
    return out


def main():
    video_path = "nagrania testowe/Nagrywanie 2026-11-18 224127.mp4"
    if not os.path.exists(video_path):
        print(f"Error: {video_path} not found")
        return

    os.makedirs("raport/v3/screens", exist_ok=True)
    
    pipeline = VisionPipeline("config.json")
    validator = StateValidator()
    tracker = TableTracker("table_1")
    preflop_engine = PreflopNashEngine()
    flop_db = FlopDatabase()
    mc_calc = MonteCarloCalculator()
    decision_maker = DecisionMaker()

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video loaded: {total_frames} frames @ {fps} FPS")

    # We evaluate 360 frames (first 3 minutes sampled every 15 frames)
    # plus guarantee frames [0, 765, 2370, 4950, 5190] are explicitly captured and annotated.
    target_frames = [0, 765, 2370, 4950, 5190]
    sample_indices = set(range(0, 5400, 15))
    sample_indices.update(target_frames)
    sorted_indices = sorted(sample_indices)
    
    records = []
    latencies = []
    valid_count = 0
    hero_turn_count = 0
    rejection_reasons = {}

    print(f"Processing {len(sorted_indices)} frames...")

    for f_idx in sorted_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        
        t0 = time.perf_counter()
        now_ms = int((f_idx / fps) * 1000)
        
        state = pipeline.process_frame(frame, timestamp_ms=now_ms)
        is_valid, reasons = validator.validate(state)
        state.is_valid = is_valid
        state, events = tracker.update(state)
        
        cand_evs, spot = evaluate_candidates(state, preflop_engine, flop_db, mc_calc)
        decision = decision_maker.decide(state, cand_evs, spot=spot)
        
        latency = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency)
        
        if is_valid:
            valid_count += 1
        else:
            for r in reasons:
                rejection_reasons[r] = rejection_reasons.get(r, 0) + 1
                
        if getattr(state, "is_hero_turn", False):
            hero_turn_count += 1

        rec = {
            "frame_idx": f_idx,
            "timestamp_ms": now_ms,
            "time_str": f"{int(f_idx / fps // 60):02d}:{int(f_idx / fps % 60):02d}",
            "is_valid": is_valid,
            "reasons": reasons,
            "is_hero_turn": getattr(state, "is_hero_turn", False),
            "street": getattr(state, "street", "WAITING_FOR_TURN"),
            "spot": spot,
            "small_blind": getattr(state, "small_blind", 10),
            "big_blind": getattr(state, "big_blind", 20),
            "prize_pool": getattr(state, "prize_pool", 4),
            "pot": getattr(state, "pot", 0),
            "hero_cards": getattr(state, "hero_cards", []),
            "board_cards": getattr(state, "board_cards", []),
            "available_actions": getattr(state, "available_actions", []),
            "players": {
                str(k): {
                    "stack": getattr(p, "stack", 0),
                    "current_bet": getattr(p, "current_bet", 0),
                    "is_dealer": getattr(p, "is_dealer", False),
                }
                for k, p in getattr(state, "players", {}).items()
            },
            "recommended_action": decision.action,
            "ev_bb": decision.ev_bb,
            "profile_used": decision.profile_used,
            "reason": decision.reason,
            "latency_ms": latency,
        }
        records.append(rec)

        # Annotate and save target frames
        if f_idx in target_frames:
            annotated = annotate_frame(
                frame, f_idx, state, is_valid, reasons, spot, decision, latency
            )
            out_img_path = f"raport/v3/screens/frame_{f_idx:04d}.png"
            cv2.imwrite(out_img_path, annotated)
            print(f"Saved annotated screenshot: {out_img_path}")

    cap.release()

    # Save JSON records
    with open("raport/v3/audit_records.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print("Saved raport/v3/audit_records.json")

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p95_lat = np.percentile(latencies, 95) if latencies else 0.0

    print("--- V3 AUDIT SUMMARY ---")
    print(f"Total frames processed: {len(sorted_indices)}")
    print(f"Valid frames: {valid_count} ({valid_count / len(sorted_indices) * 100:.1f}%)")
    print(f"Hero turns: {hero_turn_count}")
    print(f"Average latency: {avg_lat:.2f} ms | P95 latency: {p95_lat:.2f} ms")
    print(f"Rejection reasons: {rejection_reasons}")


if __name__ == "__main__":
    main()
