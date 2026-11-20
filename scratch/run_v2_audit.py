"""Run comprehensive V2 audit on the first 3 minutes (~5400 frames, 30 FPS)."""

import sys
sys.path.insert(0, ".")

import json
import os
import time
import cv2
import numpy as np

from vision.pipeline import VisionPipeline
from state.validator import StateValidator
from state.tracker import TableTracker
from strategy.decision_maker import DecisionMaker
from engine.preflop_nash import PreflopNashEngine
from engine.flop_db import FlopDatabase
from engine.monte_carlo import MonteCarloCalculator
from main import evaluate_candidates

def main():
    video_path = "nagrania testowe/Nagrywanie 2026-11-18 224127.mp4"
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error opening {video_path}")
        return

    os.makedirs("raport/v2/screens", exist_ok=True)

    pipeline = VisionPipeline()
    validator = StateValidator()
    tracker = TableTracker(table_id="table_1")
    decision_maker = DecisionMaker(buy_in=2)

    preflop_engine = None
    try:
        preflop_engine = PreflopNashEngine()
    except Exception as e:
        print("PreflopNashEngine init error:", e)

    flop_db = None
    try:
        flop_db = FlopDatabase()
    except Exception as e:
        print("FlopDatabase init error:", e)

    mc_calc = None
    try:
        mc_calc = MonteCarloCalculator()
    except Exception as e:
        print("MonteCarloCalculator init error:", e)

    sample_step = 15
    max_frame = 5400
    fps = 30.0

    records = []
    latencies = []
    valid_count = 0
    invalid_reasons = {}
    hero_turns = []

    target_screens = [0, 765, 960, 1560, 1620, 2190, 2280, 2370, 4950, 5190]
    saved_screens = {}

    print(f"Starting V2 audit on {max_frame} frames (sample_step={sample_step})...")
    start_total_time = time.perf_counter()

    for fn in range(0, max_frame, sample_step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fn)
        ret, frame = cap.read()
        if not ret:
            print(f"End of stream or failed read at frame {fn}")
            break

        sec = fn / fps
        time_str = f"{int(sec // 60):02d}:{int(sec % 60):02d}"

        t0 = time.perf_counter()
        # 1. Vision pipeline
        state = pipeline.process_frame(frame, timestamp_ms=int(sec * 1000))

        # 2. State validator
        is_valid, val_errors = validator.validate(state)
        state.is_valid = is_valid

        # 3. Table tracker
        track_res = tracker.update(state)

        # 4. Strategy & Decision
        candidates, spot = evaluate_candidates(state, preflop_engine, flop_db, mc_calc)
        decision = decision_maker.decide(state, candidates, spot=spot)

        t1 = time.perf_counter()
        lat_ms = (t1 - t0) * 1000.0
        latencies.append(lat_ms)

        # Record validation
        if state.is_valid:
            valid_count += 1
        else:
            for r in val_errors:
                invalid_reasons[r] = invalid_reasons.get(r, 0) + 1

        # Check hero turn
        if state.is_hero_turn:
            hero_turns.append(fn)

        # Structure record
        rec = {
            "frame_idx": fn,
            "time_str": time_str,
            "latency_ms": round(lat_ms, 2),
            "is_valid": state.is_valid,
            "validation_errors": val_errors,
            "validation_warnings": [],
            "is_hero_turn": state.is_hero_turn,
            "available_actions": state.available_actions,
            "street": state.street,
            "blinds": [state.small_blind, state.big_blind],
            "prize_pool": state.prize_pool,
            "pot": state.pot,
            "hero_cards": state.hero_cards,
            "board_cards": state.board_cards,
            "spot": spot,
            "decision": {
                "action": decision.action,
                "ev_bb": decision.ev_bb,
                "confidence": decision.confidence,
                "profile_used": decision.profile_used,
                "reason": decision.reason,
            },
            "players": {
                s: {
                    "stack": state.players[s].stack,
                    "bet": state.players[s].current_bet,
                    "is_dealer": state.players[s].is_dealer,
                    "status_text": state.players[s].status_text,
                }
                for s in (0, 1, 2)
            },
        }
        records.append(rec)

        # Save annotated screenshot for representative frames
        if fn in target_screens:
            disp = frame.copy()
            # Draw semi-transparent HUD banner at top-left
            overlay = disp.copy()
            cv2.rectangle(overlay, (20, 20), (520, 190), (18, 22, 32), -1)
            cv2.addWeighted(overlay, 0.90, disp, 0.10, 0, disp)
            cv2.rectangle(disp, (20, 20), (520, 190), (140, 100, 255) if state.is_hero_turn else (80, 80, 90), 2)

            font = cv2.FONT_HERSHEY_SIMPLEX
            # Header
            status_txt = f"FRAME {fn:04d} ({time_str}) | V2 AUDIT"
            cv2.putText(disp, status_txt, (35, 48), font, 0.65, (255, 255, 255), 2)

            # Details
            dealer_seat = [s for s in (0, 1, 2) if state.players[s].is_dealer]
            d_str = f"Seat {dealer_seat[0]}" if dealer_seat else "None"
            line1 = f"Prize: ${state.prize_pool} | Blinds: {state.small_blind}/{state.big_blind} | Dealer: {d_str}"
            cv2.putText(disp, line1, (35, 75), font, 0.50, (200, 200, 200), 1)

            cards_str = f"Hero: {' '.join(state.hero_cards) or '--'} | Board: {' '.join(state.board_cards) or '--'}"
            cv2.putText(disp, cards_str, (35, 100), font, 0.50, (100, 230, 255), 1)

            turn_str = f"Hero Turn: {'YES' if state.is_hero_turn else 'NO (Waiting)'} | Street: {state.street}"
            cv2.putText(disp, turn_str, (35, 125), font, 0.50, (120, 255, 120) if state.is_hero_turn else (180, 180, 180), 1)

            ev_str = f"{decision.ev_bb:+.2f} BB" if decision.ev_bb is not None else "--"
            dec_str = f"ACTION: {decision.action} ({ev_str}) | {decision.profile_used}"
            cv2.putText(disp, dec_str, (35, 155), font, 0.60, (50, 255, 120) if decision.action != "WAIT" else (220, 220, 220), 2)

            res_str = f"Reason: {decision.reason}"
            cv2.putText(disp, res_str, (35, 180), font, 0.42, (170, 170, 170), 1)

            screen_path = f"raport/v2/screens/frame_{fn:04d}.png"
            cv2.imwrite(screen_path, disp)
            saved_screens[fn] = screen_path

    total_wall_time = time.perf_counter() - start_total_time
    total_frames = len(records)
    avg_lat = float(np.mean(latencies)) if latencies else 0.0
    p95_lat = float(np.percentile(latencies, 95)) if latencies else 0.0

    print(f"Audit completed in {total_wall_time:.2f}s.")
    print(f"Total processed: {total_frames}")
    print(f"Valid frames: {valid_count}/{total_frames} ({valid_count/total_frames*100:.1f}%)")
    print(f"Hero turns detected: {len(hero_turns)}")
    print(f"Avg latency: {avg_lat:.2f} ms | P95 latency: {p95_lat:.2f} ms")
    print("Invalid breakdown:", invalid_reasons)
    print("Saved screens count:", len(saved_screens))

    # Save JSON records
    with open("raport/v2/audit_records.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print("Saved raport/v2/audit_records.json")

if __name__ == "__main__":
    main()
