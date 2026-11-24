"""End-to-end vision pipeline: frame -> ROIs -> CV/OCR -> TableState."""

from __future__ import annotations

import json
from pathlib import Path
import time

import cv2
import numpy as np

try:
    from core.constants import VALID_BLIND_LEVELS, VALID_BUY_INS
    from core.contracts import PlayerState, TableState
except ImportError:
    VALID_BLIND_LEVELS = (  # type: ignore[assignment]
        (10, 20), (15, 30), (20, 40), (30, 60), (40, 80),
        (50, 100), (60, 120), (75, 150), (100, 200),
    )
    VALID_BUY_INS = (0.5, 2.0, 5.0, 10.0, 50.0)  # type: ignore[assignment]
    PlayerState = None  # type: ignore[misc, assignment]
    TableState = None  # type: ignore[misc, assignment]

from vision.anchor import (
    compute_table_rect,
    compute_table_rect_from_rim,
    compute_unclipped_table_rect,
    crop_rois,
    find_anchor,
    find_golden_rim,
    find_right_anchor,
)
from vision.card_recognizer import CardRecognizer
from vision.ocr import DigitOCR, detect_hero_actions


def infer_buy_in(
    raw_ocr_val: float | None,
    prize_pool: float | int | None,
) -> float | None:
    """Infer tournament buy-in from JAQKpot! prize pool and/or OCR buy_in ROI."""
    if prize_pool is not None:
        pp = float(prize_pool)
        if pp in (1.0, 1.5, 2.5):
            return 0.5
        if pp in (4.0, 6.0):
            return 2.0

    if raw_ocr_val is not None:
        closest = min(VALID_BUY_INS, key=lambda b: abs(b - raw_ocr_val))
        if abs(closest - raw_ocr_val) <= 0.15:
            if prize_pool is None or float(prize_pool) <= 0 or (float(prize_pool) / closest) >= 1.9:
                return float(closest)

    if prize_pool is not None and float(prize_pool) > 0:
        pp = float(prize_pool)
        cands_2x = [b for b in VALID_BUY_INS if abs((pp / b) - 2.0) < 0.01]
        if cands_2x:
            return float(max(cands_2x))

        best_b: float | None = None
        best_dist = 999.0
        for b in reversed(VALID_BUY_INS):
            mult = pp / b
            for target_m in (2.0, 3.0, 5.0, 10.0):
                d = abs(mult - target_m)
                if d <= 0.05 and d < best_dist:
                    best_dist = d
                    best_b = float(b)
        if best_b is not None:
            return best_b

    return None


class VisionPipeline:
    """Orchestrates screen detection, template matching, and OCR into TableState."""

    def __init__(self, config_path: str | Path = "config.json") -> None:
        self.config_path = Path(config_path)
        self.config: dict = self._load_config()

        self.anchor_config = self.config.get("anchor", {})
        self.anchor_template: np.ndarray | None = None
        self.right_anchor_template: np.ndarray | None = None
        self._load_anchor_template()

        self.anchor_threshold: float = float(
            self.anchor_config.get("match_threshold", 0.85)
        )
        self.table_offset_rel: list[float] = self.anchor_config.get(
            "table_offset_rel", [0.0, 0.0, 1.0, 1.0]
        )
        self.golden_rim_rel: list[float] = self.anchor_config.get(
            "golden_rim_rel", [0.1802, 0.2075, 0.6402, 0.5630]
        )
        self.canonical_table_size: tuple[int, int] = tuple(
            self.config.get("canonical_table_size", [1757, 997])
        )
        self.rois_rel: dict[str, list[float]] = self.config.get("rois", {})
        ocr_threshold = float(self.config.get("ocr_threshold", 0.75))
        card_threshold = float(self.config.get("card_threshold", 0.90))
        self.dealer_threshold = float(self.config.get("dealer_threshold", 90.0))

        self.card_recognizer = CardRecognizer(threshold=card_threshold)
        self.digit_ocr = DigitOCR(threshold=ocr_threshold)
        self._table_signatures: dict[str, np.ndarray] = {}
        self._table_last_seen: dict[str, int] = {}
        self._table_counter: int = 0
        self._last_anchor_scale: float | None = None
        self.last_evicted_table_id: str | None = None
        self._last_canonical_table: np.ndarray | None = None
        self._last_valid_blinds: dict[str, tuple[int, int]] = {}
        self._pending_blinds: dict[str, tuple[tuple[int, int], int]] = {}
        self.last_detected_buy_in: dict[str, float] = {}

        self.dealer_template: np.ndarray | None = None
        d_path = Path("data/templates/dealer.png")
        if d_path.is_file():
            img_d = cv2.imread(str(d_path), cv2.IMREAD_COLOR)
            if img_d is not None and img_d.size > 0:
                self.dealer_template = img_d

    def reset_table_blinds(self, table_id: str) -> None:
        """Clear cached valid blinds for a table (e.g. on new tournament)."""
        self._last_valid_blinds.pop(table_id, None)
        self._pending_blinds.pop(table_id, None)

    def _normalize_blinds(
        self, raw_blinds: tuple[int, int] | None, table_id: str
    ) -> tuple[int, int]:
        """Normalize OCR blinds against official Stake JAQKpot! blind ladder with 3-frame upward debounce."""
        prev = self._last_valid_blinds.get(table_id)
        is_exact = raw_blinds in VALID_BLIND_LEVELS

        cand: tuple[int, int] | None = None
        if is_exact:
            cand = raw_blinds
        elif raw_blinds is not None:
            raw_sb, raw_bb = raw_blinds
            candidates = [
                (vsb, vbb)
                for vsb, vbb in VALID_BLIND_LEVELS
                if raw_sb == vsb or raw_bb == vbb
            ]
            if candidates:
                if len(candidates) > 1 and prev is not None:
                    ge_prev = [c for c in candidates if c >= prev]
                    if ge_prev:
                        candidates = ge_prev
                cand = candidates[0]

        if cand is None:
            self._pending_blinds.pop(table_id, None)
            return prev if prev is not None else (10, 20)

        if prev is None:
            self._last_valid_blinds[table_id] = cand
            self._pending_blinds.pop(table_id, None)
            return cand

        if cand == prev:
            self._pending_blinds.pop(table_id, None)
            return cand

        if cand > prev:
            # Partial match cannot jump more than 1 step in VALID_BLIND_LEVELS
            if not is_exact and prev in VALID_BLIND_LEVELS and cand in VALID_BLIND_LEVELS:
                if VALID_BLIND_LEVELS.index(cand) > VALID_BLIND_LEVELS.index(prev) + 1:
                    self._pending_blinds.pop(table_id, None)
                    return prev

            pend_val, pend_cnt = self._pending_blinds.get(table_id, (None, 0))
            pend_cnt = pend_cnt + 1 if pend_val == cand else 1
            self._pending_blinds[table_id] = (cand, pend_cnt)
            if pend_cnt >= 3:
                self._last_valid_blinds[table_id] = cand
                self._pending_blinds.pop(table_id, None)
                return cand
            return prev

        # cand < prev: allow exact ladder reads through so StateValidator/main can handle new tournament / self-heal
        self._pending_blinds.pop(table_id, None)
        return cand if is_exact else prev

    @staticmethod
    def _mask_white_bet_text(roi: np.ndarray) -> np.ndarray:
        """Isolate white bet digits from colored chip icons on real colored ROIs."""
        if roi is None or roi.size == 0 or roi.ndim != 3:
            return roi
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        if float(np.mean(hsv[:, :, 1] >= 65)) >= 0.05:
            mask = (hsv[:, :, 1] < 65) & (hsv[:, :, 2] > 170)
            out = np.zeros_like(roi)
            out[mask] = roi[mask]
            return out
        return roi

    def _load_config(self) -> dict:
        if self.config_path.is_file():
            try:
                with self.config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "anchor": {
                "template_path": "data/templates/anchor.png",
                "match_threshold": 0.85,
                "table_offset_rel": [0.0, 0.0, 1.0, 1.0],
            },
            "rois": {},
        }

    def _load_anchor_template(self) -> None:
        tpl_path = self.anchor_config.get(
            "template_path", "data/templates/anchor.png"
        )
        path = Path(tpl_path)
        if path.is_file():
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is not None and img.size > 0:
                self.anchor_template = img

        right_tpl_path = self.anchor_config.get(
            "right_template_path", "data/templates/anchor_right.png"
        )
        r_path = Path(right_tpl_path)
        if r_path.is_file():
            r_img = cv2.imread(str(r_path), cv2.IMREAD_COLOR)
            if r_img is not None and r_img.size > 0:
                self.right_anchor_template = r_img

    def _warp_to_canonical(
        self, frame: np.ndarray, rect: tuple[int, int, int, int]
    ) -> np.ndarray:
        """Warp an arbitrary table rectangle (potentially unclipped/scaled) to canonical size.

        Places the sliced sub-region of frame onto a canvas of size (th, tw, 3),
        correctly handling negative or out-of-frame coordinates, and resizes to
        canonical_table_size if tw != CW or th != CH.
        """
        CW, CH = self.canonical_table_size
        tx, ty, tw, th = rect
        tw = max(1, tw)
        th = max(1, th)

        canvas = np.zeros((th, tw, 3), dtype=np.uint8)
        H, W = frame.shape[:2]

        fx1 = max(0, tx)
        fy1 = max(0, ty)
        fx2 = min(W, tx + tw)
        fy2 = min(H, ty + th)

        cx1 = fx1 - tx
        cy1 = fy1 - ty
        cx2 = cx1 + (fx2 - fx1)
        cy2 = cy1 + (fy2 - fy1)

        if fx2 > fx1 and fy2 > fy1 and cx2 > cx1 and cy2 > cy1:
            canvas[cy1:cy2, cx1:cx2] = frame[fy1:fy2, fx1:fx2]

        if (tw, th) != (CW, CH):
            interp = cv2.INTER_CUBIC if (tw < CW or th < CH) else cv2.INTER_LINEAR
            return cv2.resize(canvas, (CW, CH), interpolation=interp)
        return canvas

    def resolve_table_id(
        self,
        frame: np.ndarray,
        table_rect: tuple[int, int, int, int] | None,
        default_table_id: str = "table_1",
        has_anchor: bool = True,
    ) -> str:
        """Resolve table_id based on top-left game ID region signature.

        Supports dynamic allocation of up to 6 tables (table_1, table_2, ... table_6)
        with LRU eviction, avoiding collision across multiple tournaments in one session.
        """
        if not has_anchor or table_rect is None or frame is None or frame.size == 0:
            return default_table_id

        tx, ty, tw, th = table_rect
        gx1 = max(0, tx + int(tw * 0.045))
        gx2 = min(frame.shape[1], tx + int(tw * 0.185))
        gy1 = max(0, ty + int(th * 0.055))
        gy2 = min(frame.shape[0], ty + int(th * 0.092))

        if gx2 <= gx1 or gy2 <= gy1:
            return default_table_id

        crop = frame[gy1:gy2, gx1:gx2]
        if float(np.std(crop)) < 5.0:
            return default_table_id

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _otsu, bin_h = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        sig = bin_h.astype(np.float32)

        self._table_counter += 1

        best_id = None
        best_score = -1.0
        for tid, saved_sig in self._table_signatures.items():
            if sig.shape != saved_sig.shape:
                cur_sig = cv2.resize(sig, (saved_sig.shape[1], saved_sig.shape[0]))
            else:
                cur_sig = sig
            res = cv2.matchTemplate(cur_sig, saved_sig, cv2.TM_CCOEFF_NORMED)
            score = float(res[0][0])
            if score > best_score:
                best_score = score
                best_id = tid

        if best_id is not None and best_score >= 0.90:
            self._table_last_seen[best_id] = self._table_counter
            return best_id

        # Allocate new table ID if below capacity
        max_tables = 6
        if len(self._table_signatures) < max_tables:
            new_id = f"table_{len(self._table_signatures) + 1}"
            self._table_signatures[new_id] = sig
            self._table_last_seen[new_id] = self._table_counter
            return new_id
        else:
            # Evict least recently seen table
            lru_id = min(self._table_last_seen.items(), key=lambda item: item[1])[0]
            self.last_evicted_table_id = lru_id
            self._table_signatures[lru_id] = sig
            self._table_last_seen[lru_id] = self._table_counter
            return lru_id

    def compute_opponents_signature(
        self, table_image: np.ndarray, effective_rect: tuple[int, int, int, int] | None = None
    ) -> np.ndarray | None:
        """Compute compact binary/grayscale signature of Seat 1 and Seat 2 opponent nickname/avatar areas.

        Used to differentiate tournaments across hands without relying on volatile hand ID headers.
        """
        if table_image is None or table_image.size == 0:
            return None
        CW, CH = self.canonical_table_size
        s1 = table_image[int(0.20 * CH) : int(0.28 * CH), int(0.25 * CW) : int(0.38 * CW)]
        s2 = table_image[int(0.20 * CH) : int(0.28 * CH), int(0.62 * CW) : int(0.75 * CW)]
        if s1.size == 0 or s2.size == 0:
            return None
        combined = np.hstack([s1, s2])
        gray = cv2.cvtColor(combined, cv2.COLOR_BGR2GRAY)
        sig = cv2.resize(gray, (64, 16), interpolation=cv2.INTER_AREA)
        norm_sig = cv2.equalizeHist(sig).astype(np.float32)
        return norm_sig

    def process_frame(
        self,
        frame: np.ndarray,
        table_id: str = "table_1",
        timestamp_ms: int | None = None,
        table_rect: tuple[int, int, int, int] | None = None,
        allow_table_resolution: bool = True,
        has_anchor: bool | None = None,
    ) -> TableState:
        """Process a single frame and return extracted TableState."""
        if TableState is None or PlayerState is None:
            raise ImportError(
                "core.contracts (TableState, PlayerState) is required to run VisionPipeline."
            )

        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)

        CW, CH = self.canonical_table_size
        anchor_found = False

        # Detect table bounds or fallback to full frame
        if table_rect is None:
            # 1. Primary golden rim detection (4 clean arcs, continuous scale, any window aspect)
            rim = find_golden_rim(frame)
            if rim is not None:
                anchor_found = True
                unclipped_rect = compute_table_rect_from_rim(
                    rim,
                    rim_rel=self.golden_rim_rel,
                    canonical_size=self.canonical_table_size,
                )
                table_image = self._warp_to_canonical(frame, unclipped_rect)
                effective_rect = (0, 0, CW, CH)
            elif self.anchor_template is not None:
                # 2. Dual-anchor unclipped rect fallback
                anchor = find_anchor(
                    frame,
                    self.anchor_template,
                    self.anchor_threshold,
                    preferred_scale=self._last_anchor_scale,
                )
                if anchor is not None:
                    anchor_found = True
                    tpl_w = self.anchor_template.shape[1]
                    tpl_h = self.anchor_template.shape[0]
                    self._last_anchor_scale = anchor[2] / tpl_w
                    right_anchor = None
                    if self.right_anchor_template is not None:
                        right_anchor = find_right_anchor(
                            frame,
                            self.right_anchor_template,
                            anchor,
                            canonical_size=self.canonical_table_size,
                            left_template_size=(tpl_w, tpl_h),
                        )
                    unclipped_rect = compute_unclipped_table_rect(
                        anchor,
                        self.table_offset_rel,
                        canonical_size=self.canonical_table_size,
                        template_size=(tpl_w, tpl_h),
                        frame_shape=frame.shape,
                        right_anchor=right_anchor,
                    )
                    table_image = self._warp_to_canonical(frame, unclipped_rect)
                    effective_rect = (0, 0, CW, CH)
                else:
                    table_rect = (0, 0, frame.shape[1], frame.shape[0])
                    table_image = frame
                    effective_rect = table_rect
            else:
                table_rect = (0, 0, frame.shape[1], frame.shape[0])
                table_image = frame
                effective_rect = table_rect
        else:
            # Provided table_rect (from main.py unclipped rect or manual ROI)
            anchor_found = has_anchor if has_anchor is not None else True
            table_image = self._warp_to_canonical(frame, table_rect)
            effective_rect = (0, 0, CW, CH)

        self._last_canonical_table = table_image

        # Resolve table_id based on game ID header if default table_1 and allowed
        if allow_table_resolution and table_id == "table_1":
            table_id = self.resolve_table_id(
                table_image, effective_rect, default_table_id=table_id, has_anchor=anchor_found
            )

        # Crop configured ROIs from normalized table image
        rois = crop_rois(table_image, effective_rect, self.rois_rel)

        # 1. Hero actions & active timer bar (evaluated early to gate board cards recognition)
        is_hero_turn = False
        available_actions: list[str] = []
        hero_timer_roi = rois.get("seat_0_timer")
        if "hero_actions" in rois:
            is_hero_turn, available_actions = detect_hero_actions(
                rois["hero_actions"], hero_timer_roi=hero_timer_roi
            )

        # 2. Hero cards & Board cards candidate collection with duplicate collision resolution
        hero_slots = [k for k in ("hero_card_1", "hero_card_2") if k in rois]
        board_slots = [
            k
            for k in (
                "board_card_1",
                "board_card_2",
                "board_card_3",
                "board_card_4",
                "board_card_5",
            )
            if k in rois
        ]

        # Slightly lower card threshold for resized/interpolated tables
        orig_card_thresh = getattr(self.card_recognizer, "threshold", 0.90)
        is_scaled = (
            abs((self._last_anchor_scale or 1.0) - 1.0) > 0.02
            or (table_rect is not None and len(table_rect) >= 4 and (table_rect[2], table_rect[3]) != (CW, CH))
        )

        if is_scaled and hasattr(self.card_recognizer, "threshold"):
            self.card_recognizer.threshold = min(orig_card_thresh, 0.82)

        slot_candidates: dict[str, list[tuple[str, float]]] = {}
        try:
            for slot in hero_slots + board_slots:
                slot_roi = rois[slot]
                if hasattr(self.card_recognizer, "recognize_candidates"):
                    try:
                        cands = self.card_recognizer.recognize_candidates(
                            slot_roi, top_k=3, slot_hint=slot
                        )
                    except TypeError:
                        cands = self.card_recognizer.recognize_candidates(slot_roi, top_k=3)
                else:
                    try:
                        c, s = self.card_recognizer.recognize(slot_roi, slot_hint=slot)
                    except TypeError:
                        c, s = self.card_recognizer.recognize(slot_roi)
                    cands = [(c, s)] if c is not None else []
                if cands:
                    slot_candidates[slot] = cands
        finally:
            if is_scaled and hasattr(self.card_recognizer, "threshold"):
                self.card_recognizer.threshold = orig_card_thresh

        # Sort slots by their highest candidate score descending for greedy assignment
        sorted_slots = sorted(
            slot_candidates.keys(),
            key=lambda s: slot_candidates[s][0][1],
            reverse=True,
        )

        used_cards: set[str] = set()
        assigned_cards: dict[str, str] = {}
        for slot in sorted_slots:
            for card_code, _conf in slot_candidates[slot]:
                if card_code not in used_cards:
                    used_cards.add(card_code)
                    assigned_cards[slot] = card_code
                    break

        hero_cards: list[str] = [
            assigned_cards[k] for k in ("hero_card_1", "hero_card_2") if k in assigned_cards
        ]
        board_cards: list[str] = [
            assigned_cards[k]
            for k in (
                "board_card_1",
                "board_card_2",
                "board_card_3",
                "board_card_4",
                "board_card_5",
            )
            if k in assigned_cards
        ]

        # 4. Pot
        pot = 0
        if "pot" in rois:
            val = self.digit_ocr.read_int(rois["pot"])
            if val is not None:
                pot = val

        # 4. Prize pool (supports decimal currency like $1.50)
        prize_pool: float | int = 0
        if "prize_pool" in rois:
            f_val = self.digit_ocr.read_float(rois["prize_pool"])
            if f_val is not None:
                prize_pool = int(f_val) if f_val.is_integer() else f_val

        # 5. Blinds (normalized against VALID_BLIND_LEVELS)
        raw_blinds = self.digit_ocr.read_blinds(rois["blinds"]) if "blinds" in rois else None
        small_blind, big_blind = self._normalize_blinds(raw_blinds, table_id)

        # 5b. Auto Buy-in detection
        raw_buy_in: float | None = None
        if "buy_in" in rois:
            raw_buy_in = self.digit_ocr.read_float(rois["buy_in"], min_p98=100.0, min_contrast=25.0)
        detected_bi = infer_buy_in(raw_buy_in, prize_pool)
        if detected_bi is not None:
            self.last_detected_buy_in[table_id] = detected_bi

        # 6. Players (seats 0, 1, 2)
        best_dealer_seat = None
        best_dealer_score = -1.0
        if self.dealer_template is not None:
            for s in (0, 1, 2):
                d_key = f"seat_{s}_dealer"
                if d_key in rois and rois[d_key].size > 0:
                    d_crop = rois[d_key]
                    th_d, tw_d = self.dealer_template.shape[:2]
                    if d_crop.shape[0] >= th_d and d_crop.shape[1] >= tw_d:
                        res_d = cv2.matchTemplate(d_crop, self.dealer_template, cv2.TM_CCOEFF_NORMED)
                        score_d = float(cv2.minMaxLoc(res_d)[1])
                        if score_d > best_dealer_score:
                            best_dealer_score = score_d
                            best_dealer_seat = s

        players: dict[int, PlayerState] = {}
        for seat_id in (0, 1, 2):
            stack_key = f"seat_{seat_id}_stack"
            bet_key = f"seat_{seat_id}_bet"
            dealer_key = f"seat_{seat_id}_dealer"

            stack = None
            is_all_in_badge = False
            if stack_key in rois:
                if self.digit_ocr.is_all_in_label(rois[stack_key]):
                    stack = 0
                    is_all_in_badge = True
                else:
                    stack = self.digit_ocr.read_int(rois[stack_key])

            current_bet = 0
            if bet_key in rois:
                masked_bet_roi = self._mask_white_bet_text(rois[bet_key])
                b_val = self.digit_ocr.read_int(masked_bet_roi)
                if b_val is not None:
                    current_bet = b_val

            is_dealer = False
            if best_dealer_score >= 0.75:
                is_dealer = (seat_id == best_dealer_seat)
            elif dealer_key in rois:
                d_roi = rois[dealer_key]
                if d_roi.size > 0 and float(np.mean(d_roi)) > self.dealer_threshold:
                    is_dealer = True

            is_active = (stack is not None and stack > 0) or (current_bet > 0) or is_all_in_badge
            if is_all_in_badge:
                stack = 0
                status_text = "ALL_IN"
                is_active = True
            elif stack is None and current_bet > 0:
                stack = 0
                status_text = "ALL_IN"
                is_active = True
            elif stack is None and current_bet == 0:
                status_text = "SIT_OUT"
                is_active = False
            elif is_active:
                status_text = "ACTIVE"
            else:
                status_text = "FOLDED"

            players[seat_id] = PlayerState(
                seat_id=seat_id,
                stack=stack,
                current_bet=current_bet,
                is_dealer=is_dealer,
                is_active=is_active,
                status_text=status_text,
            )

        # Physical bet sanitization: bet cannot exceed pot (and pot == 0 implies all bets == 0)
        if pot == 0:
            for p in players.values():
                p.current_bet = 0
        else:
            for p in players.values():
                if p.current_bet > pot:
                    p.current_bet = 0

        # Refine Check vs Call if facing an opponent bet
        if is_hero_turn and available_actions:
            hero_bet = players[0].current_bet if 0 in players and players[0].current_bet is not None else 0
            max_opp_bet = max(
                (players[s].current_bet for s in (1, 2) if s in players and players[s].current_bet is not None),
                default=0,
            )
            if max_opp_bet > hero_bet:
                available_actions = ["CALL" if a == "CHECK" else a for a in available_actions]
            elif max_opp_bet <= hero_bet:
                available_actions = ["CHECK" if a == "CALL" else a for a in available_actions]

        # 8. Street determination
        if not is_hero_turn or len(hero_cards) != 2:
            street = "WAITING_FOR_TURN"
        else:
            nb = len(board_cards)
            if nb == 0:
                street = "PREFLOP"
            elif nb == 3:
                street = "FLOP"
            elif nb == 4:
                street = "TURN"
            elif nb == 5:
                street = "RIVER"
            else:
                street = "PREFLOP"

        return TableState(
            table_id=table_id,
            timestamp_ms=timestamp_ms,
            prize_pool=prize_pool,
            small_blind=small_blind,
            big_blind=big_blind,
            pot=pot,
            hero_cards=hero_cards,
            board_cards=board_cards,
            street=street,
            is_hero_turn=is_hero_turn,
            available_actions=available_actions,
            players=players,
            is_valid=False,
        )
