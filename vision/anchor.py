"""Table anchor detection, multi-tabling identification, and ROI scaling."""

from __future__ import annotations

import cv2
import numpy as np


def find_all_anchors(
    frame: np.ndarray,
    anchor_template: np.ndarray,
    threshold: float = 0.85,
    min_distance_px: int = 100,
    scales: tuple[float, ...] = (1.0, 1.25, 1.28, 1.30, 1.15, 0.85, 0.75, 1.40),
    preferred_scale: float | None = None,
) -> list[tuple[int, int, int, int]]:
    """Find all occurrences of anchor template in frame above threshold.

    If preferred_scale is provided, it is checked first for minimum latency.
    Otherwise attempts scale 1.0 for zero-overhead on standard frames.
    If no matches are found, falls back to multiscale matching using provided scales.
    Applies Non-Maximum Suppression (NMS) to eliminate overlapping detections
    within `min_distance_px`. Returns a list of (x, y, w, h) for each detected table.
    """
    if (
        frame is None
        or anchor_template is None
        or frame.size == 0
        or anchor_template.size == 0
    ):
        return []

    fh, fw = frame.shape[:2]
    th, tw = anchor_template.shape[:2]

    def _nms_from_res(res_mat: np.ndarray, t_w: int, t_h: int, min_t: float) -> list[tuple[int, int, int, int]]:
        locs = np.where(res_mat >= min_t)
        if len(locs[0]) == 0:
            return []
        candidates: list[tuple[int, int, float]] = []
        for y, x in zip(locs[0], locs[1]):
            candidates.append((int(x), int(y), float(res_mat[y, x])))
        candidates.sort(key=lambda item: item[2], reverse=True)

        selected: list[tuple[int, int, int, int]] = []
        selected_pts: list[tuple[int, int]] = []
        min_dist_sq = min_distance_px * min_distance_px

        for x, y, _score in candidates:
            suppressed = False
            for sx, sy in selected_pts:
                dist_sq = (x - sx) ** 2 + (y - sy) ** 2
                if dist_sq < min_dist_sq:
                    suppressed = True
                    break
            if not suppressed:
                selected_pts.append((x, y))
                selected.append((x, y, t_w, t_h))
        selected.sort(key=lambda r: (r[1], r[0]))
        return selected

    tested_preferred = False
    if preferred_scale is not None and preferred_scale > 0:
        tested_preferred = True
        s = preferred_scale
        tw_s = int(round(tw * s))
        th_s = int(round(th * s))
        if tw_s <= fw and th_s <= fh and tw_s > 0 and th_s > 0:
            pref_tpl = anchor_template if abs(s - 1.0) < 0.01 else cv2.resize(anchor_template, (tw_s, th_s), interpolation=cv2.INTER_LINEAR)
            res_pref = cv2.matchTemplate(frame, pref_tpl, cv2.TM_CCOEFF_NORMED)
            t_pref = threshold if abs(s - 1.0) < 0.01 else min(threshold, 0.72)
            matches = _nms_from_res(res_pref, tw_s, th_s, t_pref)
            if matches:
                return matches

    # 1. Fast pass at scale 1.0 (if not already tested)
    if not (tested_preferred and abs(preferred_scale - 1.0) < 0.01):
        if tw <= fw and th <= fh:
            res = cv2.matchTemplate(frame, anchor_template, cv2.TM_CCOEFF_NORMED)
            matches = _nms_from_res(res, tw, th, threshold)
            if matches:
                return matches

    # 2. Multiscale fallback (only when scale 1.0 / preferred yields no matches >= threshold)
    fallback_thresh = min(threshold, 0.72)
    best_max_val = -1.0
    best_res = None
    best_tw_s = tw
    best_th_s = th

    for s in scales:
        if s == 1.0 or (tested_preferred and abs(s - preferred_scale) < 0.01):
            continue
        tw_s = int(round(tw * s))
        th_s = int(round(th * s))
        if tw_s > fw or th_s > fh or tw_s <= 0 or th_s <= 0:
            continue
        scaled_tpl = cv2.resize(anchor_template, (tw_s, th_s), interpolation=cv2.INTER_LINEAR)
        res_s = cv2.matchTemplate(frame, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, _max_l = cv2.minMaxLoc(res_s)
        if max_v > best_max_val:
            best_max_val = float(max_v)
            best_res = res_s
            best_tw_s = tw_s
            best_th_s = th_s

    if best_max_val < fallback_thresh or best_res is None:
        return []

    return _nms_from_res(best_res, best_tw_s, best_th_s, fallback_thresh)


def find_anchor(
    frame: np.ndarray,
    anchor_template: np.ndarray,
    threshold: float = 0.85,
    scales: tuple[float, ...] = (1.0, 1.25, 1.28, 1.30, 1.15, 0.85, 0.75, 1.40),
    preferred_scale: float | None = None,
) -> tuple[int, int, int, int] | None:
    """Find the single strongest anchor match in frame.

    First tests preferred_scale (if provided) or scale 1.0. If no match meets threshold, tests multiscale fallback.
    Returns (x, y, w, h) or None if max confidence < threshold.
    """
    if (
        frame is None
        or anchor_template is None
        or frame.size == 0
        or anchor_template.size == 0
    ):
        return None

    fh, fw = frame.shape[:2]
    th, tw = anchor_template.shape[:2]

    tested_preferred = False
    if preferred_scale is not None and preferred_scale > 0:
        tested_preferred = True
        s = preferred_scale
        tw_s = int(round(tw * s))
        th_s = int(round(th * s))
        if tw_s <= fw and th_s <= fh and tw_s > 0 and th_s > 0:
            pref_tpl = anchor_template if abs(s - 1.0) < 0.01 else cv2.resize(anchor_template, (tw_s, th_s), interpolation=cv2.INTER_LINEAR)
            res_pref = cv2.matchTemplate(frame, pref_tpl, cv2.TM_CCOEFF_NORMED)
            _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res_pref)
            t_pref = threshold if abs(s - 1.0) < 0.01 else min(threshold, 0.72)
            if max_v >= t_pref:
                return (int(max_l[0]), int(max_l[1]), int(tw_s), int(th_s))

    # Fast pass at scale 1.0
    if not (tested_preferred and abs(preferred_scale - 1.0) < 0.01):
        if tw <= fw and th <= fh:
            res = cv2.matchTemplate(frame, anchor_template, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val >= threshold:
                return (int(max_loc[0]), int(max_loc[1]), int(tw), int(th))

    # Multiscale fallback
    fallback_thresh = min(threshold, 0.72)
    best_match: tuple[int, int, int, int] | None = None
    best_max_val = -1.0

    for s in scales:
        if s == 1.0 or (tested_preferred and abs(s - preferred_scale) < 0.01):
            continue
        tw_s = int(round(tw * s))
        th_s = int(round(th * s))
        if tw_s > fw or th_s > fh or tw_s <= 0 or th_s <= 0:
            continue
        scaled_tpl = cv2.resize(anchor_template, (tw_s, th_s), interpolation=cv2.INTER_LINEAR)
        res_s = cv2.matchTemplate(frame, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res_s)
        if max_v > best_max_val:
            best_max_val = float(max_v)
            best_match = (int(max_l[0]), int(max_l[1]), int(tw_s), int(th_s))

    if best_match is not None and best_max_val >= fallback_thresh:
        return best_match

    return None


def find_right_anchor(
    frame: np.ndarray,
    right_template: np.ndarray,
    left_anchor: tuple[int, int, int, int],
    threshold: float = 0.72,
    canonical_size: tuple[int, int] = (1757, 997),
    left_template_size: tuple[int, int] = (78, 35),
) -> tuple[int, int, int, int] | None:
    """Find right anchor [⚙][🏆] in a narrow horizontal strip to the right of left_anchor.

    Searches y in [ay - 25, ay + ah + 25] and x in [ax + int(tw * 0.50), min(fw, ax + int(tw * 1.25))].
    Scales right_template by aw / left_template_size[0].
    Returns (x, y, w, h) in full frame coordinates or None if confidence < threshold.
    """
    if (
        frame is None
        or right_template is None
        or frame.size == 0
        or right_template.size == 0
    ):
        return None

    ax, ay, aw, ah = left_anchor
    ltpl_w = left_template_size[0] if left_template_size[0] > 0 else 78
    scale = aw / ltpl_w
    tw = int(round(canonical_size[0] * scale))

    fh, fw = frame.shape[:2]
    y1 = max(0, ay - 25)
    y2 = min(fh, ay + ah + 25)
    x1 = max(0, ax + int(tw * 0.50))
    x2 = min(fw, ax + int(tw * 1.25))
    if x2 <= x1 or y2 <= y1:
        return None

    rw_s = int(round(right_template.shape[1] * scale))
    rh_s = int(round(right_template.shape[0] * scale))
    if rw_s > (x2 - x1) or rh_s > (y2 - y1) or rw_s <= 0 or rh_s <= 0:
        return None

    scaled_tpl = (
        right_template
        if (rw_s, rh_s) == (right_template.shape[1], right_template.shape[0])
        else cv2.resize(right_template, (rw_s, rh_s), interpolation=cv2.INTER_LINEAR)
    )
    strip = frame[y1:y2, x1:x2]
    res = cv2.matchTemplate(strip, scaled_tpl, cv2.TM_CCOEFF_NORMED)
    _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
    if max_v >= threshold:
        return (x1 + int(max_l[0]), y1 + int(max_l[1]), rw_s, rh_s)
    return None


def compute_unclipped_table_rect(
    anchor_rect: tuple[int, int, int, int],
    table_offset_rel: list[float],
    canonical_size: tuple[int, int] = (1757, 997),
    template_size: tuple[int, int] | None = None,
    frame_shape: tuple[int, ...] | None = None,
    right_anchor: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Compute unclipped table rect from detected anchor(s) and relative offset.

    Preserves negative tx, ty and unclipped tw, th so that warping onto a canonical
    canvas preserves exact pixel alignment without any coordinate drift.
    Uses dual-anchor alignment when right_anchor is provided, falling back to pure
    left anchor offset tx = ax - ox * tw without screen-wide centering.
    """
    ax, ay, aw, ah = anchor_rect
    if len(table_offset_rel) < 4 or table_offset_rel[2] <= 0 or table_offset_rel[3] <= 0:
        return (ax, ay, aw, ah)
    if table_offset_rel == [0.0, 0.0, 1.0, 1.0]:
        return (ax, ay, aw, ah)

    scale = aw / template_size[0] if template_size and template_size[0] > 0 else 1.0
    tw = int(round(canonical_size[0] * scale))
    th = int(round(canonical_size[1] * scale))
    ox, oy = table_offset_rel[:2]
    tx_single = int(round(ax - ox * tw))
    ty = int(round(ay - oy * th))

    if right_anchor is not None:
        rx, ry, rw, rh = right_anchor
        container_w = (rx + rw) - ax
        if container_w < tw * 0.85:
            # Narrow responsive Stake container (e.g. 211257 where table is centered in window)
            game_center_x = (ax + (rx + rw)) / 2.0 + 30.0 * (scale / 1.28205)
            tx = int(round(game_center_x - tw / 2.0))
        else:
            # Standard or wide container (e.g. 224127, 2 gry na raz, wide laptop screens)
            game_center_x = (ax + (rx + rw)) / 2.0 + 14.0 * scale
            tx_dual = int(round(game_center_x - tw / 2.0))
            if abs(tx_dual - tx_single) <= 15 * scale:
                tx = tx_dual
            else:
                tx = tx_single
    else:
        tx = tx_single

    return (tx, ty, tw, th)


def compute_table_rect(
    anchor_rect: tuple[int, int, int, int],
    table_offset_rel: list[float],
    frame_shape: tuple[int, ...],
) -> tuple[int, int, int, int]:
    """Compute full table rectangle from detected anchor_rect and relative offset.

    Clips the resulting rectangle safely to frame_shape.
    """
    ax, ay, aw, ah = anchor_rect
    frame_h, frame_w = frame_shape[:2]

    if len(table_offset_rel) < 4 or table_offset_rel[2] <= 0 or table_offset_rel[3] <= 0:
        table_x, table_y, table_w, table_h = ax, ay, aw, ah
    elif table_offset_rel == [0.0, 0.0, 1.0, 1.0]:
        table_x, table_y, table_w, table_h = ax, ay, aw, ah
    else:
        ox, oy, ow, oh = table_offset_rel[:4]
        table_w = int(round(aw / ow))
        table_h = int(round(ah / oh))
        table_x = int(round(ax - ox * table_w))
        table_y = int(round(ay - oy * table_h))

    tx = max(0, min(table_x, frame_w - 1))
    ty = max(0, min(table_y, frame_h - 1))
    tw = max(1, min(table_w, frame_w - tx))
    th = max(1, min(table_h, frame_h - ty))

    return (tx, ty, tw, th)


def crop_rois(
    frame: np.ndarray,
    table_rect: tuple[int, int, int, int],
    rois_rel: dict[str, list[float]],
) -> dict[str, np.ndarray]:
    """Crop all defined ROIs from table_rect according to relative coordinates.

    Skips [0.0, 0.0, 0.0, 0.0] or non-positive sizes. Safely clips coordinates
    to frame boundaries, ensuring no empty or negative crops are returned.
    """
    if frame is None or frame.size == 0:
        return {}

    frame_h, frame_w = frame.shape[:2]
    tx, ty, tw, th = table_rect

    crops: dict[str, np.ndarray] = {}

    for name, rel in rois_rel.items():
        if (
            not isinstance(rel, (list, tuple))
            or len(rel) < 4
            or rel == [0.0, 0.0, 0.0, 0.0]
            or rel[2] <= 0
            or rel[3] <= 0
        ):
            continue

        rx = int(round(tx + rel[0] * tw))
        ry = int(round(ty + rel[1] * th))
        rw = int(round(rel[2] * tw))
        rh = int(round(rel[3] * th))

        x1 = max(0, min(rx, frame_w))
        y1 = max(0, min(ry, frame_h))
        x2 = max(0, min(rx + rw, frame_w))
        y2 = max(0, min(ry + rh, frame_h))

        if x2 <= x1 or y2 <= y1:
            continue

        crops[name] = frame[y1:y2, x1:x2].copy()

    return crops


def find_golden_rim(
    frame: np.ndarray,
    search_rect: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int] | None:
    """Detect the golden/orange elliptical table rim on Stake poker felt.

    Performs strict 4-arc confidence verification:
    1. Finds candidate blue felt interior ellipse (HSV 90..135, area >= 20000, aspect 1.45..2.25).
    2. Detects golden rim boundary (HSV H: 12..35, S: 50..255, V: 90..255) around all 4 sides (left, right, top, bottom).
    3. Strict size (ow >= 300, oh >= 160) and aspect ratio checks (1.55 <= ow/oh <= 2.15).
    4. Verified blue interior felt dominance (>= 50% blue pixels in center).

    Returns (ox, oy, ow, oh) in full frame coordinates or None if not 100% confident.
    """
    if frame is None or frame.size == 0:
        return None

    sx_offset, sy_offset = 0, 0
    work_frame = frame
    if search_rect is not None:
        sx, sy, sw, sh = search_rect
        fh, fw = frame.shape[:2]
        x1 = max(0, min(sx, fw - 1))
        y1 = max(0, min(sy, fh - 1))
        x2 = max(x1 + 1, min(sx + sw, fw))
        y2 = max(y1 + 1, min(sy + sh, fh))
        if x2 - x1 < 150 or y2 - y1 < 100:
            return None
        work_frame = frame[y1:y2, x1:x2]
        sx_offset, sy_offset = x1, y1

    H, W = work_frame.shape[:2]
    if W < 300 or H < 160:
        return None

    hsv = cv2.cvtColor(work_frame, cv2.COLOR_BGR2HSV)

    # 1. Detect blue felt candidate
    blue_mask = cv2.inRange(hsv, (90, 40, 30), (135, 255, 255))
    contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= 20000:
            bx, by, bw, bh = cv2.boundingRect(c)
            if bh > 0:
                asp = bw / bh
                if 1.45 <= asp <= 2.25:
                    candidates.append((area, bx, by, bw, bh))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    _, fx, fy, fw, fh = candidates[0]

    # 2. Golden rim boundary around felt
    golden_mask = cv2.inRange(hsv, (12, 50, 90), (35, 255, 255))

    # Left band:
    left_band = golden_mask[int(fy + 0.25 * fh) : int(fy + 0.75 * fh), max(0, fx - 50) : fx + 50]
    left_pts = np.where(left_band > 0)
    if len(left_pts[1]) < 20:
        return None
    rim_x1 = max(0, fx - 50) + int(np.min(left_pts[1]))

    # Right band:
    right_band = golden_mask[int(fy + 0.25 * fh) : int(fy + 0.75 * fh), fx + fw - 50 : min(W, fx + fw + 50)]
    right_pts = np.where(right_band > 0)
    if len(right_pts[1]) < 20:
        return None
    rim_x2 = (fx + fw - 50) + int(np.max(right_pts[1]))

    # Top band:
    top_band = golden_mask[max(0, fy - 50) : fy + 100, int(fx + 0.25 * fw) : int(fx + 0.75 * fw)]
    top_pts = np.where(top_band > 0)
    if len(top_pts[0]) < 20:
        return None
    rim_y1 = max(0, fy - 50) + int(np.min(top_pts[0]))

    # Bottom band:
    bot_band = golden_mask[fy + fh - 100 : min(H, fy + fh + 50), int(fx + 0.25 * fw) : int(fx + 0.75 * fw)]
    bot_pts = np.where(bot_band > 0)
    if len(bot_pts[0]) < 20:
        return None
    rim_y2 = (fy + fh - 100) + int(np.max(bot_pts[0]))

    rim_w = rim_x2 - rim_x1
    rim_h = rim_y2 - rim_y1

    # 3. Hard size and aspect ratio checks
    if rim_w < 300 or rim_h < 160:
        return None

    aspect = rim_w / rim_h
    if not (1.55 <= aspect <= 2.15):
        return None

    # 4. Verified blue interior felt dominance in center 40% box
    c_y1 = int(rim_y1 + 0.30 * rim_h)
    c_y2 = int(rim_y1 + 0.70 * rim_h)
    c_x1 = int(rim_x1 + 0.30 * rim_w)
    c_x2 = int(rim_x1 + 0.70 * rim_w)
    if c_y2 <= c_y1 or c_x2 <= c_x1:
        return None

    center_roi = hsv[c_y1:c_y2, c_x1:c_x2]
    blue_center_mask = (center_roi[:, :, 0] >= 90) & (center_roi[:, :, 0] <= 135) & (center_roi[:, :, 1] >= 40)
    blue_ratio = np.count_nonzero(blue_center_mask) / (center_roi.shape[0] * center_roi.shape[1])
    if blue_ratio < 0.50:
        return None

    return (rim_x1 + sx_offset, rim_y1 + sy_offset, rim_w, rim_h)


def compute_table_rect_from_rim(
    rim_rect: tuple[int, int, int, int],
    rim_rel: list[float] | None = None,
    canonical_size: tuple[int, int] = (1757, 997),
) -> tuple[int, int, int, int]:
    """Compute table rect (tx, ty, tw, th) from detected golden rim rect and relative offset."""
    if rim_rel is None or len(rim_rel) < 4:
        rim_rel = [0.1816, 0.0963, 0.6460, 0.6780]
    ox, oy, ow, oh = rim_rect
    rx, ry, rw, rh = rim_rel[:4]
    scale = ow / (canonical_size[0] * rw)
    tw = int(round(canonical_size[0] * scale))
    th = int(round(canonical_size[1] * scale))
    tx = int(round(ox - rx * tw))
    ty = int(round(oy - ry * th))
    return (tx, ty, tw, th)
