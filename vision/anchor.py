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


def compute_unclipped_table_rect(
    anchor_rect: tuple[int, int, int, int],
    table_offset_rel: list[float],
    canonical_size: tuple[int, int] = (1757, 997),
    template_size: tuple[int, int] | None = None,
    frame_shape: tuple[int, ...] | None = None,
) -> tuple[int, int, int, int]:
    """Compute unclipped table rect from detected anchor and relative offset.

    Preserves negative tx, ty and unclipped tw, th so that warping onto a canonical
    canvas preserves exact pixel alignment without any coordinate drift.
    If frame_shape is provided and the table is centered in a wide browser window,
    automatically accounts for window margin offset.
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
    tx = int(round(ax - ox * tw))
    ty = int(round(ay - oy * th))

    # Center table horizontally if single window has wide margins
    if frame_shape is not None and len(frame_shape) >= 2:
        frame_w = frame_shape[1]
        tx_centered = (frame_w - tw) // 2
        if abs(tx_centered - tx) > 50 and ax < int(tw * 0.15):
            tx = tx_centered

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
