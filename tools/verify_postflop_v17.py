"""Verification script for V17 postflop frames."""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
from vision.pipeline import VisionPipeline
from vision.anchor import find_all_anchors, compute_unclipped_table_rect, find_anchor, find_right_anchor
from state.validator import StateValidator
from engine.preflop_nash import PreflopNashEngine
from engine.flop_db import FlopDatabase
from engine.monte_carlo import MonteCarloCalculator
from strategy.decision_maker import DecisionMaker
from main import evaluate_candidates, determine_postflop_spot

def test_frame(video_path: str, frame_num: int):
    print(f"\n==================================================")
    print(f"Testing {Path(video_path).name} at frame {frame_num}")
    print(f"==================================================")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open {video_path}")
        return

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        print(f"Error: Could not read frame {frame_num}")
        return

    pipeline = VisionPipeline(config_path="config.json")
    validator = StateValidator()
    preflop_engine = PreflopNashEngine()
    flop_db = FlopDatabase()
    mc_calc = MonteCarloCalculator()
    decision_maker = DecisionMaker()

    # Find anchor(s)
    anchors = []
    if pipeline.anchor_template is not None:
        anchors = find_all_anchors(frame, pipeline.anchor_template, threshold=pipeline.anchor_threshold)
    if not anchors and pipeline.anchor_template is not None:
        a = find_anchor(frame, pipeline.anchor_template, threshold=pipeline.anchor_threshold)
        if a:
            anchors = [a]

    print(f"Found {len(anchors)} anchor(s) in frame {frame_num}")
    for idx, anchor in enumerate(anchors):
        tpl_w = pipeline.anchor_template.shape[1]
        tpl_h = pipeline.anchor_template.shape[0]
        right_anchor = None
        if pipeline.right_anchor_template is not None:
            right_anchor = find_right_anchor(
                frame,
                pipeline.right_anchor_template,
                anchor,
                canonical_size=pipeline.canonical_table_size,
                left_template_size=(tpl_w, tpl_h),
            )
        table_rect = compute_unclipped_table_rect(
            anchor,
            pipeline.table_offset_rel,
            canonical_size=pipeline.canonical_table_size,
            template_size=(tpl_w, tpl_h),
            frame_shape=frame.shape,
            right_anchor=right_anchor,
        )
        tid = f"table_{idx + 1}"
        state = pipeline.process_frame(
            frame,
            table_id=tid,
            table_rect=table_rect,
            has_anchor=True,
        )
        is_val, errs = validator.validate(state)
        state.is_valid = is_val
        print(f"\nTable {tid}:")
        print(f"  hero_cards: {state.hero_cards}")
        print(f"  board_cards: {state.board_cards}")
        print(f"  street: {state.street}")
        print(f"  pot: {state.pot}, bb: {state.big_blind}")
        print(f"  hero_turn: {state.is_hero_turn}")
        for sid, p in state.players.items():
            print(f"    Seat {sid}: stack={p.stack}, bet={p.current_bet}, status={p.status_text}")

        t0 = time.perf_counter()
        cands, spot = evaluate_candidates(state, preflop_engine, flop_db, mc_calc)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        decision = decision_maker.decide(state, cands, spot=spot)
        print(f"  spot: {spot}")
        print(f"  candidate_evs: {cands}")
        print(f"  decision: {decision.action} ({decision.ev_bb} BB, alt={decision.alt_action} {decision.alt_ev_bb})")
        print(f"  latency: {elapsed_ms:.1f} ms")

if __name__ == "__main__":
    rec1 = "nagrania testowe/Nagrywanie 2 gry na raz , przeskakujące okna.mp4"
    rec2 = "nagrania testowe/Nagrywanie 2026-11-19 211257.mp4"

    test_frame(rec1, 1383)
    test_frame(rec1, 1627)
    test_frame(rec2, 2604)
    test_frame(rec2, 4757)
