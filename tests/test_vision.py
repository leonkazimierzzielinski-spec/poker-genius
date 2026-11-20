"""Unit tests for vision module: capture, anchor, card recognition, OCR, pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from vision.anchor import (
    compute_table_rect,
    compute_unclipped_table_rect,
    crop_rois,
    find_all_anchors,
    find_anchor,
)
from vision.capture import OfflineReplayCapture
from vision.card_recognizer import CardRecognizer
from vision.ocr import DigitOCR, detect_hero_actions
from vision.pipeline import VisionPipeline


def test_offline_replay_capture_folder(tmp_path: Path) -> None:
    """Verify OfflineReplayCapture reads sequentially from folder and ends with None."""
    frames_dir = tmp_path / "replay_frames"
    frames_dir.mkdir()

    for idx in range(3):
        img = np.full((50, 50, 3), (idx + 1) * 60, dtype=np.uint8)
        cv2.imwrite(str(frames_dir / f"frame_{idx:03d}.png"), img)

    capture = OfflineReplayCapture(frames_dir, loop=False)

    f0 = capture.grab()
    assert f0 is not None
    assert f0.shape == (50, 50, 3)

    f1 = capture.grab()
    assert f1 is not None

    f2 = capture.grab()
    assert f2 is not None

    f3 = capture.grab()
    assert f3 is None

    capture.release()


def test_offline_replay_capture_single_image(tmp_path: Path) -> None:
    """Verify OfflineReplayCapture works with single image file."""
    img_path = tmp_path / "single.png"
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    cv2.imwrite(str(img_path), img)

    capture = OfflineReplayCapture(img_path, loop=False)
    assert capture.grab() is not None
    assert capture.grab() is None
    capture.release()


def test_find_all_anchors_multi_table() -> None:
    """Verify finding multiple anchor instances with non-maximum suppression."""
    frame = np.zeros((600, 1000, 3), dtype=np.uint8)

    # Distinct template pattern
    template = np.zeros((20, 40, 3), dtype=np.uint8)
    template[:, :] = (180, 120, 60)
    cv2.circle(template, (20, 10), 6, (255, 255, 255), -1)

    # Paste into 2 separate positions on screen
    frame[100:120, 100:140] = template
    frame[300:320, 600:640] = template

    anchors = find_all_anchors(
        frame, template, threshold=0.85, min_distance_px=100
    )

    assert len(anchors) == 2
    # Verify detected rectangles match dimensions and approximate positions
    a1, a2 = anchors
    assert a1[2] == 40 and a1[3] == 20
    assert a2[2] == 40 and a2[3] == 20
    assert abs(a1[0] - 100) <= 2 and abs(a1[1] - 100) <= 2
    assert abs(a2[0] - 600) <= 2 and abs(a2[1] - 300) <= 2


def test_find_anchor_single() -> None:
    """Verify find_anchor returns single best match or None."""
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    template = np.full((20, 30, 3), 200, dtype=np.uint8)
    cv2.circle(template, (15, 10), 5, (50, 50, 50), -1)

    # Test before pasting
    assert find_anchor(frame, template, threshold=0.85) is None

    # Test after pasting
    frame[50:70, 80:110] = template
    match = find_anchor(frame, template, threshold=0.85)
    assert match is not None
    assert match == (80, 50, 30, 20)


def test_compute_table_rect() -> None:
    """Verify calculation and clipping of table rect from anchor and relative offset."""
    frame_shape = (600, 800, 3)

    # 1. Default [0.0, 0.0, 1.0, 1.0] -> table matches anchor
    anchor = (100, 100, 400, 300)
    rect = compute_table_rect(anchor, [0.0, 0.0, 1.0, 1.0], frame_shape)
    assert rect == (100, 100, 400, 300)

    # 2. Offset: anchor at relative [0.1, 0.2, 0.5, 0.5] inside table
    anchor = (100, 100, 200, 100)
    # table_w = 200 / 0.5 = 400, table_h = 100 / 0.5 = 200
    # table_x = 100 - 0.1 * 400 = 60, table_y = 100 - 0.2 * 200 = 60
    rect = compute_table_rect(anchor, [0.1, 0.2, 0.5, 0.5], frame_shape)
    assert rect == (60, 60, 400, 200)

    # 3. Clipping at frame boundary
    anchor = (700, 500, 200, 200)
    rect = compute_table_rect(anchor, [0.0, 0.0, 1.0, 1.0], frame_shape)
    assert rect[0] + rect[2] <= 800
    assert rect[1] + rect[3] <= 600


def test_crop_rois_bounds() -> None:
    """Verify relative ROI cropping and safe boundary clipping."""
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    table_rect = (100, 100, 600, 400)

    rois_rel = {
        "pot": [0.4, 0.4, 0.2, 0.1],
        "edge_crop": [0.8, 0.8, 0.5, 0.5],
        "empty": [0.0, 0.0, 0.0, 0.0],
    }

    crops = crop_rois(frame, table_rect, rois_rel)

    assert "pot" in crops
    assert crops["pot"].shape == (40, 120, 3)

    assert "edge_crop" in crops
    # Must be safely clipped to frame boundaries
    eh, ew = crops["edge_crop"].shape[:2]
    assert ew <= 800 and eh <= 600
    assert ew > 0 and eh > 0

    assert "empty" not in crops


def test_card_recognizer_match_and_threshold(tmp_path: Path) -> None:
    """Verify card recognizer with template matching and thresholding."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()

    # Synthetic card template Qh
    qh_tpl = np.zeros((40, 30, 3), dtype=np.uint8)
    qh_tpl[:, :] = (30, 30, 200)
    cv2.putText(
        qh_tpl, "Q", (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    cv2.imwrite(str(cards_dir / "Qh.png"), qh_tpl)

    rec = CardRecognizer(templates_dir=cards_dir, threshold=0.92)

    # 1. Matching identical image
    card, score = rec.recognize(qh_tpl)
    assert card == "Qh"
    assert score >= 0.92

    # 2. Smaller roi scaled up (roi smaller than template)
    resized_qh = cv2.resize(qh_tpl, (25, 35))
    card_r, score_r = rec.recognize(resized_qh)
    assert card_r == "Qh"
    assert score_r >= 0.90

    # 2b. Larger roi containing template (direct match without resizing)
    larger_qh = np.zeros((50, 40, 3), dtype=np.uint8)
    larger_qh[5:45, 5:35] = qh_tpl
    card_l, score_l = rec.recognize(larger_qh)
    assert card_l == "Qh"
    assert score_l >= 0.92

    # 3. Random noise
    np.random.seed(42)
    noise = np.random.randint(0, 255, (40, 30, 3), dtype=np.uint8)
    card_n, score_n = rec.recognize(noise)
    assert card_n is None
    assert score_n < 0.92

    # 4. Empty image
    empty_card, empty_score = rec.recognize(np.array([]))
    assert empty_card is None
    assert empty_score == 0.0


def test_digit_ocr_empty_returns_none(tmp_path: Path) -> None:
    """Verify empty/uniform gray image (simulating 'Sit out') returns None safely."""
    digits_dir = tmp_path / "digits"
    digits_dir.mkdir()

    # Create dummy template '0'
    t0 = np.zeros((20, 15), dtype=np.uint8)
    cv2.putText(t0, "0", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 255, 1)
    cv2.imwrite(str(digits_dir / "0.png"), t0)

    ocr = DigitOCR(templates_dir=digits_dir, threshold=0.80)

    # Uniform gray image (e.g. Sit out or blank background)
    gray_roi = np.full((25, 60, 3), 128, dtype=np.uint8)
    assert ocr.read_int(gray_roi) is None
    assert ocr.read_blinds(gray_roi) is None


def test_digit_ocr_read_int_and_blinds(tmp_path: Path) -> None:
    """Verify digit OCR reading int and blinds with synthetic templates."""
    digits_dir = tmp_path / "digits"
    digits_dir.mkdir()

    # Generate templates for 0, 1, 2
    for d in (0, 1, 2):
        raw = np.zeros((30, 30, 3), dtype=np.uint8)
        cv2.putText(
            raw, str(d), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
        )
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        res = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0)
        _th, th = cv2.threshold(res, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        c, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        x, y, w, h = cv2.boundingRect(c[0])
        cv2.imwrite(str(digits_dir / f"{d}.png"), th[y : y + h, x : x + w])

    ocr = DigitOCR(templates_dir=digits_dir, threshold=0.75)

    # 1. Create image with '10'
    roi_10 = np.zeros((30, 60, 3), dtype=np.uint8)
    cv2.putText(
        roi_10, "1", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    cv2.putText(
        roi_10, "0", (30, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )

    val = ocr.read_int(roi_10)
    assert val == 10

    # 2. Create image with blinds '10/20'
    roi_blinds = np.zeros((30, 120, 3), dtype=np.uint8)
    cv2.putText(
        roi_blinds, "1", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    cv2.putText(
        roi_blinds, "0", (30, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    cv2.line(roi_blinds, (52, 24), (64, 8), (255, 255, 255), 2)
    cv2.putText(
        roi_blinds, "2", (75, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    cv2.putText(
        roi_blinds, "0", (95, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )

    blinds = ocr.read_blinds(roi_blinds)
    assert blinds == (10, 20)


def test_digit_ocr_higher_blinds_touching_slash(tmp_path: Path) -> None:
    """Verify higher blinds (15/30, 20/40, 30/60) with touching slash character."""
    digits_dir = tmp_path / "digits"
    digits_dir.mkdir()

    for d in range(10):
        raw = np.zeros((30, 30, 3), dtype=np.uint8)
        cv2.putText(
            raw, str(d), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
        )
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        res = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0)
        _th, th = cv2.threshold(res, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        c, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        x, y, w, h = cv2.boundingRect(c[0])
        cv2.imwrite(str(digits_dir / f"{d}.png"), th[y : y + h, x : x + w])

    ocr = DigitOCR(templates_dir=digits_dir, threshold=0.75)

    # Test 15/30 where slash is adjacent to '3'
    roi_15_30 = np.zeros((30, 130, 3), dtype=np.uint8)
    cv2.putText(roi_15_30, "1", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_15_30, "5", (30, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.line(roi_15_30, (52, 24), (64, 8), (255, 255, 255), 2)
    cv2.putText(roi_15_30, "3", (66, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_15_30, "0", (88, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    assert ocr.read_blinds(roi_15_30) == (15, 30)


def test_detect_hero_actions() -> None:
    """Verify HSV color detection of Hero action buttons."""
    # 1. Image with Red (Fold), Green (Check), Orange (Bet)
    actions_roi = np.zeros((60, 180, 3), dtype=np.uint8)
    # Fold (red BGR: 0, 0, 230)
    actions_roi[15:45, 10:50] = (0, 0, 230)
    # Check (green BGR: 0, 230, 0)
    actions_roi[15:45, 70:110] = (0, 230, 0)
    # Bet (orange BGR: 0, 140, 240)
    actions_roi[15:45, 130:170] = (0, 140, 240)

    is_turn, actions = detect_hero_actions(actions_roi)
    assert is_turn is True
    assert "FOLD" in actions
    assert "CHECK" in actions
    assert "BET" in actions

    # 2. Inactive / dark table
    dark_roi = np.zeros((60, 180, 3), dtype=np.uint8)
    is_turn_dark, actions_dark = detect_hero_actions(dark_roi)
    assert is_turn_dark is False
    assert actions_dark == []


def test_vision_pipeline_synthetic(tmp_path: Path) -> None:
    """Verify VisionPipeline runs end-to-end and returns TableState."""
    pytest.importorskip("core.contracts")

    cfg_file = tmp_path / "test_config.json"
    cfg = {
        "anchor": {
            "template_path": "non_existent.png",
            "match_threshold": 0.85,
            "table_offset_rel": [0.0, 0.0, 1.0, 1.0],
        },
        "rois": {
            "pot": [0.4, 0.4, 0.2, 0.1],
            "hero_actions": [0.7, 0.7, 0.25, 0.25],
        },
    }
    with cfg_file.open("w", encoding="utf-8") as f:
        json.dump(cfg, f)

    pipeline = VisionPipeline(config_path=cfg_file)

    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    state = pipeline.process_frame(frame, table_id="test_table_1")

    assert state.table_id == "test_table_1"
    assert state.is_valid is False
    assert len(state.players) == 3
    assert state.street == "WAITING_FOR_TURN"
    assert state.is_hero_turn is False


def test_resolve_table_id_two_games(tmp_path: Path) -> None:
    """Verify VisionPipeline resolves distinct table IDs for two alternating games in one window."""
    cfg_file = tmp_path / "cfg.json"
    with cfg_file.open("w", encoding="utf-8") as f:
        json.dump({"rois": {}}, f)

    pipeline = VisionPipeline(config_path=cfg_file)

    table_rect = (0, 0, 1000, 600)
    # Frame with Game 1 header pattern
    frame_game_1 = np.zeros((600, 1000, 3), dtype=np.uint8)
    cv2.putText(frame_game_1, "#105522643", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Frame with Game 2 header pattern
    frame_game_2 = np.zeros((600, 1000, 3), dtype=np.uint8)
    cv2.putText(frame_game_2, "#998877665", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    t1_first = pipeline.resolve_table_id(frame_game_1, table_rect)
    assert t1_first == "table_1"

    t2_first = pipeline.resolve_table_id(frame_game_2, table_rect)
    assert t2_first == "table_2"

    # Switching back to Game 1 resolves table_1
    t1_second = pipeline.resolve_table_id(frame_game_1, table_rect)
    assert t1_second == "table_1"

    # Switching back to Game 2 resolves table_2
    t2_second = pipeline.resolve_table_id(frame_game_2, table_rect)
    assert t2_second == "table_2"


def test_detect_hero_actions_with_purple_timer() -> None:
    """Verify hero turn detection requires purple timer bar when provided."""
    actions_roi = np.zeros((50, 150, 3), dtype=np.uint8)
    actions_roi[:, :50] = (30, 30, 220)      # Red / Fold
    actions_roi[:, 50:100] = (30, 200, 30)   # Green / Call
    actions_roi[:, 100:] = (30, 150, 230)    # Orange / Bet

    # Active timer ROI: saturated purple (H=145, S=200, V=200)
    timer_active = np.zeros((40, 60, 3), dtype=np.uint8)
    hsv_purple = np.zeros((40, 60, 3), dtype=np.uint8)
    hsv_purple[:] = (145, 200, 200)
    timer_active = cv2.cvtColor(hsv_purple, cv2.COLOR_HSV2BGR)

    # Inactive timer ROI: dark grey / felt
    timer_inactive = np.zeros((40, 60, 3), dtype=np.uint8)
    timer_inactive[:] = (40, 40, 40)

    # When active timer is present: hero turn detected
    is_turn, acts = detect_hero_actions(actions_roi, hero_timer_roi=timer_active)
    assert is_turn is True
    assert "FOLD" in acts and "CHECK" in acts and "BET" in acts

    # When timer is inactive (e.g. opponent turn with pre-actions or rabbit hunting): hero turn False
    is_turn_inact, acts_inact = detect_hero_actions(actions_roi, hero_timer_roi=timer_inactive)
    assert is_turn_inact is False
    assert acts_inact == []


def test_digit_ocr_read_int_currency_prefix(tmp_path: Path) -> None:
    """Verify DigitOCR successfully recognizes integers preceded by currency symbols (e.g. $4)."""
    digits_dir = tmp_path / "digits"
    digits_dir.mkdir()

    # Create dummy template '4'
    raw_4 = np.zeros((30, 30, 3), dtype=np.uint8)
    cv2.putText(raw_4, "4", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    gray = cv2.cvtColor(raw_4, cv2.COLOR_BGR2GRAY)
    res = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0)
    _th, th = cv2.threshold(res, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    c, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    x, y, w, h = cv2.boundingRect(c[0])
    cv2.imwrite(str(digits_dir / "4.png"), th[y : y + h, x : x + w])

    ocr = DigitOCR(templates_dir=digits_dir, threshold=0.75)

    # Image with '$4'
    roi_dollar_4 = np.zeros((35, 70, 3), dtype=np.uint8)
    cv2.putText(roi_dollar_4, "$", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_dollar_4, "4", (38, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    val = ocr.read_int(roi_dollar_4)
    assert val == 4


def test_offline_replay_capture_seek(tmp_path: Path) -> None:
    """Verify OfflineReplayCapture.seek() moves frame pointer and updates index."""
    frames_dir = tmp_path / "seek_frames"
    frames_dir.mkdir()

    for idx in range(5):
        img = np.full((30, 30, 3), idx * 50, dtype=np.uint8)
        cv2.imwrite(str(frames_dir / f"frame_{idx:03d}.png"), img)

    capture = OfflineReplayCapture(frames_dir, loop=False)
    assert capture.total_frames == 5
    assert capture.current_frame_idx == 0

    # Grab initial frame 0
    f0 = capture.grab()
    assert f0 is not None
    assert int(f0[0, 0, 0]) == 0
    assert capture.current_frame_idx == 0

    # Seek forward to frame 3
    capture.seek(3)
    assert capture.current_frame_idx == 3
    f3 = capture.grab()
    assert f3 is not None
    assert int(f3[0, 0, 0]) == 150  # 3 * 50
    assert capture.current_frame_idx == 3

    # Seek backward to frame 1
    capture.seek(1)
    assert capture.current_frame_idx == 1
    f1 = capture.grab()
    assert f1 is not None
    assert int(f1[0, 0, 0]) == 50   # 1 * 50
    assert capture.current_frame_idx == 1

    # Seek beyond upper boundary (clamped to 4)
    capture.seek(100)
    assert capture.current_frame_idx == 4
    f4 = capture.grab()
    assert f4 is not None
    assert int(f4[0, 0, 0]) == 200  # 4 * 50

    # Seek below zero (clamped to 0)
    capture.seek(-10)
    assert capture.current_frame_idx == 0
    f0_again = capture.grab()
    assert f0_again is not None
    assert int(f0_again[0, 0, 0]) == 0

    capture.release()


def test_digit_ocr_read_float_and_wide_box_splitting(tmp_path: Path) -> None:
    """Verify DigitOCR read_float detects decimal dots and splits wide boxes."""
    digits_dir = tmp_path / "digits"
    digits_dir.mkdir()

    # Create dummy templates '0', '1', '4', '5'
    for d_val in ("0", "1", "4", "5"):
        raw = np.zeros((30, 30, 3), dtype=np.uint8)
        cv2.putText(raw, d_val, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        res = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0)
        _th, th = cv2.threshold(res, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        c, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        x, y, w, h = cv2.boundingRect(c[0])
        cv2.imwrite(str(digits_dir / f"{d_val}.png"), th[y : y + h, x : x + w])

    ocr = DigitOCR(templates_dir=digits_dir, threshold=0.75)

    # 1. Decimal float '$1.50'
    roi_float = np.zeros((35, 100, 3), dtype=np.uint8)
    cv2.putText(roi_float, "$", (5, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_float, "1", (25, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.circle(roi_float, (45, 24), 2, (255, 255, 255), -1)  # decimal dot
    cv2.putText(roi_float, "5", (55, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_float, "0", (75, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    val_f = ocr.read_float(roi_float)
    assert val_f == 1.50

    # 2. Integer with touching '440' (wide box)
    roi_wide = np.zeros((35, 90, 3), dtype=np.uint8)
    cv2.putText(roi_wide, "4", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_wide, "4", (26, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(roi_wide, "0", (55, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    val_int = ocr.read_int(roi_wide)
    assert val_int == 440


def test_resolve_table_id_ghost_table_prevention() -> None:
    """Verify resolve_table_id rejects dark/empty frames and has_anchor=False."""
    pipeline = VisionPipeline()
    table_rect = (0, 0, 1000, 600)

    # All black frame
    black_frame = np.zeros((600, 1000, 3), dtype=np.uint8)
    tid_black = pipeline.resolve_table_id(black_frame, table_rect, default_table_id="table_1", has_anchor=True)
    assert tid_black == "table_1"
    assert len(pipeline._table_signatures) == 0

    # Frame with text but has_anchor=False
    frame_with_id = np.zeros((600, 1000, 3), dtype=np.uint8)
    cv2.putText(frame_with_id, "#105522643", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    tid_no_anchor = pipeline.resolve_table_id(frame_with_id, table_rect, default_table_id="table_1", has_anchor=False)
    assert tid_no_anchor == "table_1"
    assert len(pipeline._table_signatures) == 0


def test_find_all_anchors_multiscale() -> None:
    """Verify find_all_anchors detects anchor scaled by 1.3x and returns scaled (x, y, w, h)."""
    frame = np.zeros((800, 1200, 3), dtype=np.uint8)
    template = np.zeros((30, 90, 3), dtype=np.uint8)
    template[:, :] = (120, 180, 240)
    cv2.circle(template, (45, 15), 10, (255, 255, 255), -1)

    # Scale template by 1.3x
    scaled_w = int(round(90 * 1.3))
    scaled_h = int(round(30 * 1.3))
    scaled_tpl = cv2.resize(template, (scaled_w, scaled_h), interpolation=cv2.INTER_LINEAR)

    # Paste into frame at (150, 200)
    frame[200 : 200 + scaled_h, 150 : 150 + scaled_w] = scaled_tpl

    anchors = find_all_anchors(frame, template, threshold=0.85)
    assert len(anchors) == 1
    ax, ay, aw, ah = anchors[0]
    assert abs(ax - 150) <= 2
    assert abs(ay - 200) <= 2
    assert aw == scaled_w
    assert ah == scaled_h


def test_compute_unclipped_table_rect_negative_offsets() -> None:
    """Verify compute_unclipped_table_rect retains negative tx, ty without clipping to 0."""
    anchor_rect = (20, 15, 93, 31)
    table_offset_rel = [0.030, 0.040, 0.0529, 0.031]
    canonical_size = (1757, 997)

    rect = compute_unclipped_table_rect(
        anchor_rect,
        table_offset_rel,
        canonical_size=canonical_size,
        template_size=(93, 31),
    )
    tx, ty, tw, th = rect
    assert tx < 0
    assert ty < 0
    assert tw == 1757
    assert th == 997
    assert tx == int(round(20 - 0.030 * 1757))
    assert ty == int(round(15 - 0.040 * 997))


def test_card_recognizer_collision_resolution(tmp_path: Path) -> None:
    """Verify VisionPipeline resolves duplicate card candidates by picking next best non-conflicting card."""
    pytest.importorskip("core.contracts")

    cfg_file = tmp_path / "test_cfg.json"
    cfg = {
        "rois": {
            "board_card_1": [0.1, 0.1, 0.05, 0.05],
            "board_card_2": [0.2, 0.1, 0.05, 0.05],
        },
    }
    with cfg_file.open("w", encoding="utf-8") as f:
        json.dump(cfg, f)

    pipeline = VisionPipeline(config_path=cfg_file)

    # Slot 1 has [('5s', 0.99)]
    # Slot 2 has [('5s', 0.93), ('8c', 0.91)]
    # Greedy assignment should assign 5s to slot 1 and 8c to slot 2
    call_count = [0]

    def mock_candidates(roi: np.ndarray, top_k: int = 3) -> list[tuple[str, float]]:
        call_count[0] += 1
        if call_count[0] == 1:
            return [("5s", 0.99)]
        else:
            return [("5s", 0.93), ("8c", 0.91)]

    pipeline.card_recognizer.recognize_candidates = mock_candidates  # type: ignore[assignment]

    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    state = pipeline.process_frame(frame)

    assert state.board_cards == ["5s", "8c"]


def test_resolve_table_id_more_than_two_tables(tmp_path: Path) -> None:
    """Verify resolve_table_id dynamically assigns table_1, table_2, table_3 for 3 distinct tournaments."""
    cfg_file = tmp_path / "cfg.json"
    with cfg_file.open("w", encoding="utf-8") as f:
        json.dump({"rois": {}}, f)

    pipeline = VisionPipeline(config_path=cfg_file)
    table_rect = (0, 0, 1000, 600)

    # Frame 1: Tournament 1
    f1 = np.zeros((600, 1000, 3), dtype=np.uint8)
    cv2.putText(f1, "#105522643", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Frame 2: Tournament 2
    f2 = np.zeros((600, 1000, 3), dtype=np.uint8)
    cv2.putText(f2, "#998877665", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Frame 3: Tournament 3
    f3 = np.zeros((600, 1000, 3), dtype=np.uint8)
    cv2.putText(f3, "#105540008", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    t1 = pipeline.resolve_table_id(f1, table_rect)
    t2 = pipeline.resolve_table_id(f2, table_rect)
    t3 = pipeline.resolve_table_id(f3, table_rect)

    assert t1 == "table_1"
    assert t2 == "table_2"
    assert t3 == "table_3"

    # Recurring frames keep their assigned IDs
    assert pipeline.resolve_table_id(f1, table_rect) == "table_1"
    assert pipeline.resolve_table_id(f2, table_rect) == "table_2"
    assert pipeline.resolve_table_id(f3, table_rect) == "table_3"


def test_find_all_anchors_preferred_scale_fast_path() -> None:
    """Verify that preferred_scale prioritizes the cached scale and finds scaled anchors immediately."""
    from vision.anchor import find_all_anchors, find_anchor

    # Template 40x20 with distinctive pattern
    tpl = np.zeros((20, 40, 3), dtype=np.uint8)
    tpl[5:15, 10:30] = [0, 255, 0]

    # Synthesize scaled anchor at scale 1.28
    tw_128 = int(round(40 * 1.28))
    th_128 = int(round(20 * 1.28))
    tpl_scaled = cv2.resize(tpl, (tw_128, th_128), interpolation=cv2.INTER_LINEAR)

    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    frame[50:50 + th_128, 60:60 + tw_128] = tpl_scaled

    # 1. find_all_anchors with preferred_scale=1.28
    anchors = find_all_anchors(frame, tpl, threshold=0.85, preferred_scale=1.28)
    assert len(anchors) == 1
    assert anchors[0][2] == tw_128
    assert anchors[0][3] == th_128
    assert abs(anchors[0][0] - 60) <= 2
    assert abs(anchors[0][1] - 50) <= 2

    # 2. find_anchor with preferred_scale=1.28
    anchor_single = find_anchor(frame, tpl, threshold=0.85, preferred_scale=1.28)
    assert anchor_single is not None
    assert anchor_single[2] == tw_128

    # 3. Fallback when preferred_scale is wrong (e.g. 1.0 or 1.15)
    anchors_fallback = find_all_anchors(frame, tpl, threshold=0.85, preferred_scale=1.0)
    assert len(anchors_fallback) == 1
    assert anchors_fallback[0][2] == tw_128


def test_card_recognizer_rank_suit_mode(tmp_path: Path) -> None:
    """Verify hybrid Rank+Suit decomposition mode in CardRecognizer."""
    from vision.card_recognizer import CardRecognizer

    # 1. Default instance uses rank+suit if templates exist
    rec = CardRecognizer()
    if Path("data/templates/ranks").is_dir() and Path("data/templates/suits").is_dir():
        assert rec._use_rank_suit is True
        assert len(rec.ranks) == 13
        assert len(rec.suits) == 4

        # Empty/blue table felt ROI is rejected
        blue_felt = np.full((60, 40, 3), (120, 50, 20), dtype=np.uint8)
        assert rec.recognize_candidates(blue_felt) == []
        card, score = rec.recognize(blue_felt)
        assert card is None
        assert score == 0.0

        # Construct a synthetic card with K rank and d suit
        card_img = np.full((70, 50, 3), 245, dtype=np.uint8)
        k_tpl = rec.ranks["K"]
        kh, kw = k_tpl.shape
        # paste K in red
        for y in range(kh):
            for x in range(kw):
                if k_tpl[y, x] > 128:
                    card_img[8 + y, 5 + x] = (20, 20, 220)

        d_tpl = rec.suits["d"]
        dh, dw = d_tpl.shape
        for y in range(dh):
            for x in range(dw):
                if d_tpl[y, x] > 128:
                    card_img[8 + kh + 6 + y, 5 + x] = (20, 20, 220)

        cands = rec.recognize_candidates(card_img)
        assert len(cands) > 0
        assert cands[0][0] == "Kd"
        assert cands[0][1] >= 0.70

        best_card, best_score = rec.recognize(card_img)
        assert best_card == "Kd"
        assert best_score >= 0.70

    # 2. Custom templates_dir disables rank+suit mode for backward compatibility
    custom_dir = tmp_path / "custom_cards"
    custom_dir.mkdir()
    rec_custom = CardRecognizer(templates_dir=custom_dir)
    assert rec_custom._use_rank_suit is False


