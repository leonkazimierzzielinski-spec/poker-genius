"""Offline diagnostic script for V18 on the latest recording (read-only on production code)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from state.tracker import TableTracker
from state.validator import StateValidator
from vision.anchor import (
    compute_table_rect_from_rim,
    compute_unclipped_table_rect,
    crop_rois,
    find_anchor,
    find_golden_rim,
    find_right_anchor,
    verify_table_rect_has_blue_felt,
)
from vision.ocr import detect_hero_actions
from vision.pipeline import VisionPipeline

STANDARD_BLINDS = {
    (10, 20),
    (15, 30),
    (20, 40),
    (30, 60),
    (40, 80),
    (50, 100),
    (60, 120),
    (80, 160),
    (100, 200),
}


def find_latest_mp4() -> Path:
    """Find newest .mp4 in recordings/ or fallback to nagrania testowe/."""
    for folder_name in ("recordings", "nagrania testowe"):
        folder = ROOT / folder_name
        if folder.is_dir():
            mp4s = list(folder.glob("*.mp4"))
            if mp4s:
                mp4s.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return mp4s[0]
    raise FileNotFoundError("No .mp4 file found in recordings/ or nagrania testowe/")


def draw_annotated_table(
    canonical_img: np.ndarray,
    rois_rel: dict[str, list[float]],
    state: Any,
    frame_idx: int,
    anchor_src: str,
    is_valid: bool,
    errs: list[str],
) -> np.ndarray:
    """Draw ROI boxes and summary banner on canonical table and scale to width 880 px."""
    vis = canonical_img.copy()
    H, W = vis.shape[:2]

    for name, rel in rois_rel.items():
        if len(rel) < 4:
            continue
        rx, ry, rw, rh = rel[:4]
        x1 = max(0, int(round(rx * W)))
        y1 = max(0, int(round(ry * H)))
        x2 = min(W, int(round((rx + rw) * W)))
        y2 = min(H, int(round((ry + rh) * H)))
        color = (0, 255, 0) if is_valid else (0, 165, 255)
        if "bet" in name:
            color = (255, 255, 0)
        elif "stack" in name:
            color = (255, 180, 0)
        elif "timer" in name or "actions" in name:
            color = (255, 0, 255)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 1)
        cv2.putText(
            vis,
            name,
            (x1, max(12, y1 - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            color,
            1,
            cv2.LINE_AA,
        )

    banner = (
        f"f={frame_idx} [{anchor_src}] valid={is_valid} st={state.street} "
        f"bl={state.small_blind}/{state.big_blind} pot={state.pot} "
        f"S=[{state.players[0].stack},{state.players[1].stack},{state.players[2].stack}] "
        f"B=[{state.players[0].current_bet},{state.players[1].current_bet},{state.players[2].current_bet}]"
    )
    cv2.rectangle(vis, (0, 0), (W, 28), (15, 15, 15), -1)
    cv2.putText(vis, banner, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    if errs:
        err_txt = "ERR: " + "; ".join(errs[:2])
        cv2.rectangle(vis, (0, 28), (W, 50), (0, 0, 120), -1)
        cv2.putText(vis, err_txt, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    target_w = 880
    scale = target_w / float(W)
    target_h = max(1, int(round(H * scale)))
    return cv2.resize(vis, (target_w, target_h), interpolation=cv2.INTER_AREA)


class BundleSampler:
    """Manage max 4 samples per category with >= 30 frame spacing."""

    def __init__(self, out_dir: Path, max_per_cat: int = 4, min_gap: int = 30) -> None:
        self.out_dir = out_dir
        self.max_per_cat = max_per_cat
        self.min_gap = min_gap
        self.counts: dict[str, int] = defaultdict(int)
        self.last_frame: dict[str, int] = defaultdict(lambda: -9999)

    def can_save(self, cat: str, frame_idx: int) -> bool:
        if self.counts[cat] >= self.max_per_cat:
            return False
        if frame_idx - self.last_frame[cat] < self.min_gap:
            return False
        return True

    def save_table_and_crops(
        self,
        cat: str,
        frame_idx: int,
        annotated_table: np.ndarray,
        crops: dict[str, np.ndarray],
    ) -> None:
        if not self.can_save(cat, frame_idx):
            return
        cat_dir = self.out_dir / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(
            str(cat_dir / f"f{frame_idx:05d}_table.jpg"),
            annotated_table,
            [cv2.IMWRITE_JPEG_QUALITY, 75],
        )
        for cname, cimg in crops.items():
            if cimg is not None and cimg.size > 0:
                cv2.imwrite(str(cat_dir / f"f{frame_idx:05d}_{cname}.png"), cimg)
        self.counts[cat] += 1
        self.last_frame[cat] = frame_idx

    def save_full_frame_fail(self, cat: str, frame_idx: int, frame: np.ndarray) -> None:
        if not self.can_save(cat, frame_idx):
            return
        cat_dir = self.out_dir / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        H, W = frame.shape[:2]
        target_w = 960
        scale = target_w / float(W)
        resized = cv2.resize(frame, (target_w, max(1, int(round(H * scale)))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(
            str(cat_dir / f"f{frame_idx:05d}_full.jpg"),
            resized,
            [cv2.IMWRITE_JPEG_QUALITY, 75],
        )
        self.counts[cat] += 1
        self.last_frame[cat] = frame_idx


def main() -> None:
    t_start = time.perf_counter()
    video_path = find_latest_mp4()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stride = 3 if total_frames >= 3000 else 2

    print(f"Analyzing {video_path.name}: {total_frames} frames @ {fps:.1f} fps ({vid_w}x{vid_h}), stride={stride}")

    out_dir = ROOT / "scratch" / "diag_v18_out"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sampler = BundleSampler(out_dir, max_per_cat=4, min_gap=30)
    pipeline = VisionPipeline(str(ROOT / "config.json"))
    validator = StateValidator()
    tracker = TableTracker("table_1", bet_confirm_frames=2)

    # Metrics accumulators
    sampled_frames = 0
    anchor_counts: Counter[str] = Counter()
    rect_counter: Counter[tuple[int, int, int, int]] = Counter()
    prev_rect: tuple[int, int, int, int] | None = None
    rect_jumps_gt5 = 0

    valid_total = 0
    invalid_total = 0
    valid_hero2 = 0
    invalid_hero2 = 0
    valid_actions_vis = 0
    invalid_actions_vis = 0

    err_counter_all: Counter[str] = Counter()
    err_counter_hero2: Counter[str] = Counter()
    err_counter_actions: Counter[str] = Counter()

    missing_stack_by_seat_3max: Counter[str] = Counter()
    missing_stack_by_seat_hu: Counter[str] = Counter()
    missing_stack_in_turn_frames = 0

    purple_hist: Counter[str] = Counter()
    actions_ge2_with_purple_lt500 = 0
    purple_ge120_no_actions = 0
    purple_ge500_frames = 0
    actions_ok_no_timer_frames = 0

    bet_gt_pot_frames = 0
    bet_gt_900_frames = 0
    weird_bet_examples: list[dict[str, Any]] = []
    bet_hsv_stats: dict[str, list[dict[str, float]]] = {"S0": [], "S1": [], "S2": []}

    blinds_counter: Counter[tuple[int, int]] = Counter()
    blinds_errors: list[dict[str, Any]] = []

    allin_stack_1_frames = 0
    allin_stack_lt5_frames = 0
    allin_none_sum900_frames = 0
    allin_hsv_samples: list[dict[str, Any]] = []

    rabbit_candidates = 0
    rabbit_details: list[dict[str, Any]] = []

    hands_log: list[dict[str, Any]] = []
    hand_start_frame = 0
    prev_hand_num = 0

    frame_idx = -1
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        frame_idx += 1
        if frame_idx % stride != 0:
            continue

        sampled_frames += 1

        # 1. Anchor detection matching main.py
        table_rect: tuple[int, int, int, int] | None = None
        has_anchor = False
        anchor_src = "NONE"

        rim = find_golden_rim(frame)
        if rim is not None:
            table_rect = compute_table_rect_from_rim(rim, pipeline.golden_rim_rel)
            has_anchor = True
            anchor_src = "RIM"
        elif pipeline.anchor_template is not None:
            preferred_scale = getattr(pipeline, "_last_anchor_scale", None)
            anchor = find_anchor(
                frame,
                pipeline.anchor_template,
                threshold=pipeline.anchor_threshold,
                preferred_scale=preferred_scale,
            )
            if anchor is not None:
                canonical_sz = pipeline.canonical_table_size
                tpl_w = pipeline.anchor_template.shape[1]
                tpl_h = pipeline.anchor_template.shape[0]
                right_anchor = None
                if pipeline.right_anchor_template is not None:
                    right_anchor = find_right_anchor(
                        frame,
                        pipeline.right_anchor_template,
                        anchor,
                        canonical_size=canonical_sz,
                        left_template_size=(tpl_w, tpl_h),
                    )
                cand_rect = compute_unclipped_table_rect(
                    anchor,
                    pipeline.table_offset_rel,
                    canonical_size=canonical_sz,
                    template_size=(tpl_w, tpl_h),
                    frame_shape=frame.shape,
                    right_anchor=right_anchor,
                )
                if verify_table_rect_has_blue_felt(frame, cand_rect):
                    table_rect = cand_rect
                    has_anchor = True
                    anchor_src = "ICON"

        anchor_counts[anchor_src] += 1
        if table_rect is not None:
            rect_counter[table_rect] += 1
            if prev_rect is not None:
                dx = abs(table_rect[0] - prev_rect[0])
                dy = abs(table_rect[1] - prev_rect[1])
                dw = abs(table_rect[2] - prev_rect[2])
                dh = abs(table_rect[3] - prev_rect[3])
                if max(dx, dy, dw, dh) > 5:
                    rect_jumps_gt5 += 1
            prev_rect = table_rect
        else:
            sampler.save_full_frame_fail("cat_anchor_fail", frame_idx, frame)
            continue

        # 2. VisionPipeline + StateValidator + TableTracker
        ts_ms = int(frame_idx * 1000.0 / fps)
        state = pipeline.process_frame(
            frame,
            table_id="table_1",
            timestamp_ms=ts_ms,
            table_rect=table_rect,
            has_anchor=has_anchor,
        )
        is_valid, errs = validator.validate(state)
        state.is_valid = is_valid
        state, events = tracker.update(state)

        # Track hand boundaries
        if any(e.event_type == "NEW_HAND" for e in events):
            if tracker.last_completed_hand is not None:
                h_copy = dict(tracker.last_completed_hand)
                h_copy["frame_start"] = hand_start_frame
                h_copy["frame_end"] = frame_idx - stride
                hands_log.append(h_copy)
            hand_start_frame = frame_idx
            prev_hand_num = tracker.hand_number

        ct = pipeline._last_canonical_table
        assert ct is not None
        rois = crop_rois(ct, (0, 0, ct.shape[1], ct.shape[0]), pipeline.rois_rel)

        # 3. Timer & Hero actions analysis
        timer_roi = rois.get("seat_0_timer")
        actions_roi = rois.get("hero_actions")
        purple_px = 0
        if timer_roi is not None and timer_roi.size > 0:
            hsv_t = cv2.cvtColor(timer_roi, cv2.COLOR_BGR2HSV)
            mask_p = cv2.inRange(hsv_t, np.array([125, 80, 100]), np.array([165, 255, 255]))
            purple_px = int(cv2.countNonZero(mask_p))

        if purple_px == 0:
            purple_hist["0"] += 1
        elif purple_px < 120:
            purple_hist["1..119"] += 1
        elif purple_px < 300:
            purple_hist["120..299"] += 1
        elif purple_px < 500:
            purple_hist["300..499"] += 1
        else:
            purple_hist["500+"] += 1
            purple_ge500_frames += 1

        acts_no_timer_ok, acts_no_timer_list = detect_hero_actions(actions_roi, hero_timer_roi=None)
        if acts_no_timer_ok:
            actions_ok_no_timer_frames += 1

        if len(acts_no_timer_list) >= 2 and purple_px < 500:
            actions_ge2_with_purple_lt500 += 1
            ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
            sampler.save_table_and_crops(
                "cat_timer_vs_actions",
                frame_idx,
                ann,
                {"seat_0_timer": timer_roi, "hero_actions": actions_roi},
            )
        elif purple_px >= 120 and not acts_no_timer_ok:
            purple_ge120_no_actions += 1
            ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
            sampler.save_table_and_crops(
                "cat_timer_vs_actions",
                frame_idx,
                ann,
                {"seat_0_timer": timer_roi, "hero_actions": actions_roi},
            )

        # 2. Validation stats
        has_2_hero = len(state.hero_cards) == 2
        if is_valid:
            valid_total += 1
            if has_2_hero:
                valid_hero2 += 1
            if acts_no_timer_ok:
                valid_actions_vis += 1
        else:
            invalid_total += 1
            if has_2_hero:
                invalid_hero2 += 1
            if acts_no_timer_ok:
                invalid_actions_vis += 1

            for e in errs:
                ekey = e.split(":")[0].strip()
                err_counter_all[ekey] += 1
                if has_2_hero:
                    err_counter_hero2[ekey] += 1
                if acts_no_timer_ok:
                    err_counter_actions[ekey] += 1

            if any("Missing stack reading" in e for e in errs):
                # Check which seats are None
                # Determine HU vs 3-max from tracker
                cur_players_meta = tracker.current_hand.get("players", {}) if tracker.current_hand else {}
                elim_cnt = sum(1 for sid in (0, 1, 2) if cur_players_meta.get(sid, {}).get("eliminated", False))
                target_counter = missing_stack_by_seat_hu if elim_cnt >= 1 else missing_stack_by_seat_3max
                for sid in (0, 1, 2):
                    if state.players[sid].stack is None:
                        target_counter[f"S{sid}"] += 1

                if state.is_hero_turn or acts_no_timer_ok:
                    missing_stack_in_turn_frames += 1
                    ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
                    sampler.save_table_and_crops(
                        "cat_missing_stack_turn",
                        frame_idx,
                        ann,
                        {
                            "seat_0_stack": rois.get("seat_0_stack"),
                            "seat_1_stack": rois.get("seat_1_stack"),
                            "seat_2_stack": rois.get("seat_2_stack"),
                        },
                    )

        # 4. Bets & HSV white-text stats
        for sid in (0, 1, 2):
            bet_val = state.players[sid].current_bet or 0
            bet_roi = rois.get(f"seat_{sid}_bet")
            if bet_val > 0 and bet_roi is not None and bet_roi.size > 0:
                hsv_b = cv2.cvtColor(bet_roi, cv2.COLOR_BGR2HSV)
                white_mask = (hsv_b[:, :, 1] < 50) & (hsv_b[:, :, 2] > 180)
                chip_mask = (hsv_b[:, :, 1] >= 80) & (hsv_b[:, :, 2] >= 80)
                tot_px = float(bet_roi.shape[0] * bet_roi.shape[1])
                if len(bet_hsv_stats[f"S{sid}"]) < 300:
                    bet_hsv_stats[f"S{sid}"].append({
                        "white_pct": round(100.0 * float(np.count_nonzero(white_mask)) / tot_px, 2),
                        "chip_pct": round(100.0 * float(np.count_nonzero(chip_mask)) / tot_px, 2),
                        "bet_val": float(bet_val),
                    })

            if bet_val > state.pot and state.pot > 0:
                bet_gt_pot_frames += 1
            if bet_val > 900:
                bet_gt_900_frames += 1

            is_weird_bet = (bet_val > 900) or (state.pot > 0 and bet_val > state.pot and bet_val > 60)
            if is_weird_bet:
                if len(weird_bet_examples) < 30:
                    weird_bet_examples.append({
                        "frame": frame_idx,
                        "seat": f"S{sid}",
                        "bet": bet_val,
                        "pot": state.pot,
                        "valid": is_valid,
                    })
                ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
                sampler.save_table_and_crops(
                    "cat_bet_weird",
                    frame_idx,
                    ann,
                    {
                        "seat_0_bet": rois.get("seat_0_bet"),
                        "seat_1_bet": rois.get("seat_1_bet"),
                        "seat_2_bet": rois.get("seat_2_bet"),
                    },
                )

        # 5. Blinds ladder
        bl_pair = (int(state.small_blind), int(state.big_blind))
        blinds_counter[bl_pair] += 1
        if bl_pair not in STANDARD_BLINDS:
            if len(blinds_errors) < 50:
                blinds_errors.append({"frame": frame_idx, "blinds": list(bl_pair), "pot": state.pot})
            ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
            sampler.save_table_and_crops(
                "cat_blinds_error",
                frame_idx,
                ann,
                {"blinds": rois.get("blinds")},
            )

        # 6. All-In stack field
        other_sum_check_done = False
        for sid in (0, 1, 2):
            stk = state.players[sid].stack
            stk_roi = rois.get(f"seat_{sid}_stack")
            if stk is not None and stk < 5:
                if stk == 1:
                    allin_stack_1_frames += 1
                allin_stack_lt5_frames += 1
                if stk_roi is not None and stk_roi.size > 0 and len(allin_hsv_samples) < 20:
                    hsv_s = cv2.cvtColor(stk_roi, cv2.COLOR_BGR2HSV)
                    allin_hsv_samples.append({
                        "frame": frame_idx,
                        "seat": f"S{sid}",
                        "read": stk,
                        "h_med": float(np.median(hsv_s[:, :, 0])),
                        "s_med": float(np.median(hsv_s[:, :, 1])),
                        "v_med": float(np.median(hsv_s[:, :, 2])),
                        "v_p98": float(np.percentile(hsv_s[:, :, 2], 98)),
                    })
                ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
                sampler.save_table_and_crops(
                    "cat_allin_stack",
                    frame_idx,
                    ann,
                    {f"seat_{sid}_stack": stk_roi},
                )
            elif stk is None:
                rem_sum = state.pot + sum(
                    (state.players[k].stack or 0) + (state.players[k].current_bet or 0)
                    for k in (0, 1, 2)
                    if k != sid
                ) + (state.players[sid].current_bet or 0)
                if rem_sum == 900 and not other_sum_check_done:
                    allin_none_sum900_frames += 1
                    other_sum_check_done = True
                    if stk_roi is not None and stk_roi.size > 0 and len(allin_hsv_samples) < 20:
                        hsv_s = cv2.cvtColor(stk_roi, cv2.COLOR_BGR2HSV)
                        allin_hsv_samples.append({
                            "frame": frame_idx,
                            "seat": f"S{sid}",
                            "read": None,
                            "h_med": float(np.median(hsv_s[:, :, 0])),
                            "s_med": float(np.median(hsv_s[:, :, 1])),
                            "v_med": float(np.median(hsv_s[:, :, 2])),
                            "v_p98": float(np.percentile(hsv_s[:, :, 2], 98)),
                        })
                    ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
                    sampler.save_table_and_crops(
                        "cat_allin_stack",
                        frame_idx,
                        ann,
                        {f"seat_{sid}_stack": stk_roi},
                    )

        # 7. Rabbit Hunting Break detection
        # Zone under board: [0.35..0.65, 0.44..0.52]
        ct_h, ct_w = ct.shape[:2]
        under_board_roi = ct[int(0.44 * ct_h) : int(0.52 * ct_h), int(0.35 * ct_w) : int(0.65 * ct_w)]
        grey_btn_ratio = 0.0
        if actions_roi is not None and actions_roi.size > 0:
            hsv_a = cv2.cvtColor(actions_roi, cv2.COLOR_BGR2HSV)
            grey_mask = (hsv_a[:, :, 1] < 45) & (hsv_a[:, :, 2] >= 50) & (hsv_a[:, :, 2] <= 170)
            grey_btn_ratio = float(np.count_nonzero(grey_mask)) / float(actions_roi.shape[0] * actions_roi.shape[1])

        dark_bar_ratio = 0.0
        if under_board_roi is not None and under_board_roi.size > 0:
            hsv_ub = cv2.cvtColor(under_board_roi, cv2.COLOR_BGR2HSV)
            dark_mask = hsv_ub[:, :, 2] < 60
            dark_bar_ratio = float(np.count_nonzero(dark_mask)) / float(under_board_roi.shape[0] * under_board_roi.shape[1])

        is_rabbit_cand = (
            len(state.board_cards) >= 3
            and not state.is_hero_turn
            and not acts_no_timer_ok
            and (grey_btn_ratio > 0.18 or dark_bar_ratio > 0.45)
            and state.pot == 0
        )
        if is_rabbit_cand:
            rabbit_candidates += 1
            if len(rabbit_details) < 20:
                rabbit_details.append({
                    "frame": frame_idx,
                    "board": list(state.board_cards),
                    "hero_cards": list(state.hero_cards),
                    "street": state.street,
                    "is_valid": is_valid,
                    "grey_btn_ratio": round(grey_btn_ratio, 3),
                    "dark_bar_ratio": round(dark_bar_ratio, 3),
                    "events": [e.event_type for e in events],
                })
            ann = draw_annotated_table(ct, pipeline.rois_rel, state, frame_idx, anchor_src, is_valid, errs)
            sampler.save_table_and_crops(
                "cat_rabbit_hunting",
                frame_idx,
                ann,
                {
                    "hero_actions": actions_roi,
                    "under_board": under_board_roi,
                },
            )

    cap.release()

    # Finalize last hand if any
    if tracker.current_hand:
        h_last = dict(tracker.current_hand)
        h_last["frame_start"] = hand_start_frame
        h_last["frame_end"] = frame_idx
        h_last["in_progress"] = True
        hands_log.append(h_last)

    elapsed_s = time.perf_counter() - t_start

    # Summarize bet HSV stats
    bet_hsv_summary: dict[str, Any] = {}
    for s_key, items in bet_hsv_stats.items():
        if items:
            bet_hsv_summary[s_key] = {
                "samples": len(items),
                "avg_white_pct": round(sum(x["white_pct"] for x in items) / len(items), 2),
                "avg_chip_pct": round(sum(x["chip_pct"] for x in items) / len(items), 2),
            }
        else:
            bet_hsv_summary[s_key] = {"samples": 0}

    metrics = {
        "video_file": video_path.name,
        "total_video_frames": total_frames,
        "fps": fps,
        "resolution": [vid_w, vid_h],
        "stride": stride,
        "sampled_frames": sampled_frames,
        "elapsed_sec": round(elapsed_s, 2),
        "anchor_counts": dict(anchor_counts),
        "rect_jumps_gt5": rect_jumps_gt5,
        "top_table_rects": [{"rect": list(k), "count": v} for k, v in rect_counter.most_common(10)],
        "validation": {
            "all": {"valid": valid_total, "invalid": invalid_total},
            "hero_2_cards": {"valid": valid_hero2, "invalid": invalid_hero2},
            "actions_visible_no_timer": {"valid": valid_actions_vis, "invalid": invalid_actions_vis},
            "error_ranking_all": dict(err_counter_all.most_common()),
            "error_ranking_hero2": dict(err_counter_hero2.most_common()),
            "error_ranking_actions": dict(err_counter_actions.most_common()),
            "missing_stack_3max": dict(missing_stack_by_seat_3max),
            "missing_stack_hu": dict(missing_stack_by_seat_hu),
            "missing_stack_in_turn_frames": missing_stack_in_turn_frames,
        },
        "hero_turn_timer_vs_actions": {
            "purple_px_histogram": dict(purple_hist),
            "purple_ge500_frames": purple_ge500_frames,
            "actions_ok_no_timer_frames": actions_ok_no_timer_frames,
            "actions_ge2_with_purple_lt500": actions_ge2_with_purple_lt500,
            "purple_ge120_no_actions": purple_ge120_no_actions,
        },
        "bets": {
            "bet_gt_pot_frames": bet_gt_pot_frames,
            "bet_gt_900_frames": bet_gt_900_frames,
            "weird_bet_examples": weird_bet_examples,
            "bet_hsv_summary": bet_hsv_summary,
        },
        "blinds_distribution": {f"{k[0]}/{k[1]}": v for k, v in blinds_counter.most_common()},
        "blinds_errors": blinds_errors,
        "allin_stack": {
            "stack_eq_1_frames": allin_stack_1_frames,
            "stack_lt_5_frames": allin_stack_lt5_frames,
            "stack_none_sum900_frames": allin_none_sum900_frames,
            "hsv_samples": allin_hsv_samples,
        },
        "rabbit_hunting": {
            "candidate_frames": rabbit_candidates,
            "samples": rabbit_details,
        },
        "hands_detected_count": len(hands_log),
    }

    with open(out_dir / "diag_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    # Build DIAG_REPORT.md
    lines: list[str] = [
        f"# Raport Diagnostyczny V18 — `{video_path.name}`",
        "",
        f"- **Rozdzielczość / FPS:** `{vid_w}×{vid_h}` @ `{fps:.1f} fps`",
        f"- **Klatki wideo / Przeanalizowane (stride={stride}):** `{total_frames}` / `{sampled_frames}`",
        f"- **Czas analizy:** `{elapsed_s:.2f} s`",
        "",
        "## 1. Geometria i kotwica (`RIM` vs `ICON` vs `NONE`)",
        f"- `RIM`: `{anchor_counts['RIM']}`, `ICON`: `{anchor_counts['ICON']}`, `NONE`: `{anchor_counts['NONE']}`",
        f"- Skoki `table_rect > 5 px`: `{rect_jumps_gt5}`",
        "- Top rozkłady `table_rect`:",
    ]
    for item in metrics["top_table_rects"][:5]:
        lines.append(f"  - `{tuple(item['rect'])}`: `{item['count']}` klatek")

    lines.extend([
        "",
        "## 2. Walidacja i przyczyny `INVALID`",
        f"- Ogółem: `VALID={valid_total}`, `INVALID={invalid_total}`",
        f"- Gdy `len(hero_cards) == 2`: `VALID={valid_hero2}`, `INVALID={invalid_hero2}`",
        f"- Gdy widoczne przyciski akcji: `VALID={valid_actions_vis}`, `INVALID={invalid_actions_vis}`",
        f"- `Missing stack reading` w turze Hero: `{missing_stack_in_turn_frames}`",
        f"- Ranking błędów (ogółem): `{dict(err_counter_all.most_common())}`",
        f"- Ranking błędów (hero_2_cards): `{dict(err_counter_hero2.most_common())}`",
        f"- `Missing stack` 3-max: `{dict(missing_stack_by_seat_3max)}` | HU: `{dict(missing_stack_by_seat_hu)}`",
        "",
        "## 3. Detekcja tury Hero (`seat_0_timer` vs `hero_actions`)",
        f"- Histogram `purple_px`: `{dict(purple_hist)}`",
        f"- Klatki z `>= 2` kolorowymi przyciskami akcji przy `purple_px < 500`: **`{actions_ge2_with_purple_lt500}`**",
        f"- Klatki z `purple_px >= 120` bez wykrytych przycisków akcji: **`{purple_ge120_no_actions}`**",
        "",
        "## 4. Bety i statystyki HSV białego tekstu",
        f"- `current_bet > pot`: `{bet_gt_pot_frames}` | `current_bet > 900`: `{bet_gt_900_frames}`",
        f"- HSV (`S < 50, V > 180` vs kolor żetonu `S >= 80, V >= 80`): `{bet_hsv_summary}`",
        f"- Przykłady dziwnych betów: `{weird_bet_examples[:10]}`",
        "",
        "## 5. Blind ladder (`Blinds` OCR)",
        f"- Rozkład `(sb, bb)`: `{metrics['blinds_distribution']}`",
        f"- Błędne odczyty spoza drabinki: `{len(blinds_errors)}` (przykłady: `{blinds_errors[:10]}`)",
        "",
        "## 6. Etykieta `All-In` w polu stacka",
        f"- `stack == 1`: `{allin_stack_1_frames}` | `stack < 5`: `{allin_stack_lt5_frames}` | `stack is None` przy `sum==900`: `{allin_none_sum900_frames}`",
        f"- Próbki HSV pola `All-In`: `{allin_hsv_samples[:5]}`",
        "",
        "## 7. Rabbit Hunting Break",
        f"- Kandydaci (`len(board)>=3, pot==0, grey/dark bar`): `{rabbit_candidates}`",
        f"- Przykłady: `{rabbit_details[:8]}`",
        "",
        f"## 8. Pełny log rozdań z `TableTracker` (wykryto: {len(hands_log)})",
    ])

    for idx, h in enumerate(hands_log, 1):
        h_num = h.get("hand_number", idx)
        f_s = h.get("frame_start", "?")
        f_e = h.get("frame_end", "?")
        h_cards = h.get("hero_cards", [])
        b_cards = h.get("board_cards", [])
        sb = h.get("small_blind", "?")
        bb = h.get("big_blind", "?")
        res = h.get("tournament_result") or ("IN_PROGRESS" if h.get("in_progress") else "COMPLETED")
        lines.append(
            f"### Rozdanie #{h_num} (f{f_s}–f{f_e}) | Blinds: {sb}/{bb} | Hero: `{h_cards}` | Board: `{b_cards}` | {res}"
        )
        for act in h.get("action_log", []):
            lines.append(
                f"  - [{act.get('street')}] S{act.get('seat_id')} ({act.get('player_name')}): "
                f"`{act.get('action')}` {act.get('amount')} (inv={act.get('invested_total')})"
            )

    with open(out_dir / "DIAG_REPORT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Zip into diag_v18_bundle.zip
    zip_path = ROOT / "diag_v18_bundle.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_p in sorted(out_dir.rglob("*")):
            if file_p.is_file():
                zf.write(file_p, file_p.relative_to(out_dir))

    zip_mb = zip_path.stat().st_size / (1024.0 * 1024.0)
    print(f"\nDONE! Saved {zip_path.name} ({zip_mb:.2f} MB)")
    print(f"Sampler counts: {dict(sampler.counts)}")


if __name__ == "__main__":
    main()
