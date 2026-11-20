"""Card corner template matching and hybrid Rank+Suit recognition engine."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class CardRecognizer:
    """Recognizes playing cards from ROI patches using hybrid Rank+Suit or 3-channel template matching."""

    def __init__(
        self,
        templates_dir: str | Path = "data/templates/cards",
        threshold: float = 0.92,
        ranks_dir: str | Path = "data/templates/ranks",
        suits_dir: str | Path = "data/templates/suits",
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.ranks_dir = Path(ranks_dir)
        self.suits_dir = Path(suits_dir)
        self.threshold = float(threshold)

        self.ranks: dict[str, np.ndarray] = {}
        self.suits: dict[str, np.ndarray] = {}
        self.templates: dict[str, np.ndarray] = {}
        self.template_items: list[tuple[str, np.ndarray]] = []

        # Check if hybrid rank+suit decomposition mode is available
        self._use_rank_suit = False
        default_cards_dir = Path("data/templates/cards")
        is_default_templates = (
            self.templates_dir == default_cards_dir
            or self.templates_dir.resolve() == default_cards_dir.resolve()
        )
        if is_default_templates and self.ranks_dir.is_dir() and self.suits_dir.is_dir():
            self._load_rank_suit_templates()
            if len(self.ranks) >= 13 and len(self.suits) >= 4:
                self._use_rank_suit = True

        # Always load legacy templates if available (fallback or custom dir)
        self._load_templates()

    def _load_rank_suit_templates(self) -> None:
        if not self.ranks_dir.is_dir() or not self.suits_dir.is_dir():
            return
        for p in self.ranks_dir.glob("*.png"):
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None and img.size > 0:
                self.ranks[p.stem] = img
        for p in self.suits_dir.glob("*.png"):
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None and img.size > 0:
                self.suits[p.stem] = img

    def _load_templates(self) -> None:
        if not self.templates_dir.is_dir():
            return

        for p in self.templates_dir.glob("*.png"):
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is not None and img.size > 0:
                card_name = p.stem.split("_")[0]
                if card_name.startswith("10"):
                    card_name = "T" + card_name[2:]
                self.template_items.append((card_name, img))
                if card_name not in self.templates:
                    self.templates[card_name] = img

    def _recognize_rank_suit_candidates(
        self,
        card_roi: np.ndarray,
        top_k: int = 3,
        slot_hint: str | None = None,
    ) -> list[tuple[str, float]]:
        """Recognize card candidates using binary Rank + Suit decomposition with color grouping."""
        if card_roi is None or card_roi.size == 0 or not self.ranks or not self.suits:
            return []

        # Ensure 3-channel BGR input
        if card_roi.ndim == 2:
            roi_bgr = cv2.cvtColor(card_roi, cv2.COLOR_GRAY2BGR)
        elif card_roi.shape[2] == 4:
            roi_bgr = cv2.cvtColor(card_roi, cv2.COLOR_BGRA2BGR)
        else:
            roi_bgr = card_roi

        roi_h, roi_w = roi_bgr.shape[:2]
        # Ignore bottom 32% (action badges like Call/Check overlay on Hero cards)
        badge_cut_h = int(roi_h * 0.68) if roi_h >= 30 else roi_h
        top_roi = roi_bgr[:badge_cut_h, :]

        gray = cv2.cvtColor(top_roi, cv2.COLOR_BGR2GRAY)
        white_fraction = float(np.mean(gray > 170))
        if white_fraction < 0.18:
            return []

        hsv = cv2.cvtColor(top_roi, cv2.COLOR_BGR2HSV)
        red_mask = (
            ((hsv[:, :, 0] <= 18) | (hsv[:, :, 0] >= 160))
            & (hsv[:, :, 1] > 60)
            & (hsv[:, :, 2] > 60)
        )
        red_count = int(np.sum(red_mask))

        b = top_roi[:, :, 0].astype(int)
        r = top_roi[:, :, 2].astype(int)
        black_mask = (gray < 145) & ((b - r) < 60) & (~red_mask)
        black_count = int(np.sum(black_mask))

        if red_count > black_count and red_count >= 30:
            color_group = "RED"
            allowed_suits = ["h", "d"]
            ink_mask = (red_mask.astype(np.uint8)) * 255
        else:
            color_group = "BLACK"
            allowed_suits = ["s", "c"]
            ink_mask = (black_mask.astype(np.uint8)) * 255

        contours, _ = cv2.findContours(
            ink_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        boxes = []
        for c in contours:
            bx, by, bw, bh = cv2.boundingRect(c)
            if by == 0 and bh <= 4:
                continue
            if bx > 28 and by < 5 and bw * bh < 40:
                continue
            if bh >= 12:
                boxes.append((bx, by, bw, bh))

        if not boxes:
            for c in contours:
                bx, by, bw, bh = cv2.boundingRect(c)
                if by == 0 and bh <= 4:
                    continue
                if bh >= 9:
                    boxes.append((bx, by, bw, bh))

        if not boxes:
            return []

        boxes.sort(key=lambda b: (b[1], b[0]))
        rx, ry, rw, rh = boxes[0]
        suit_idx = 1
        if len(boxes) > 1:
            bx1, by1, bw1, bh1 = boxes[1]
            if abs(by1 - ry) <= 8 and bx1 < rx + rw + 15:
                rx_m = min(rx, bx1)
                ry_m = min(ry, by1)
                rw_m = max(rx + rw, bx1 + bw1) - rx_m
                rh_m = max(ry + rh, by1 + bh1) - ry_m
                rx, ry, rw, rh = rx_m, ry_m, rw_m, rh_m
                suit_idx = 2

        rank_crop = ink_mask[ry : ry + rh, rx : rx + rw]
        suit_box = None
        if len(boxes) > suit_idx:
            candidates = [b for b in boxes[suit_idx:] if b[1] >= ry + 8]
            if candidates:
                suit_box = max(candidates, key=lambda b: b[2] * b[3])

        if suit_box is not None:
            sx, sy, sw, sh = suit_box
            suit_crop = ink_mask[sy : sy + sh, sx : sx + sw]
        else:
            below = ink_mask[ry + rh :, :]
            suit_crop = below if (below.size > 0 and np.any(below > 0)) else None

        pad = 3
        rank_scores: dict[str, float] = {}
        for r_name, r_tpl in self.ranks.items():
            th, tw = r_tpl.shape[:2]
            scaled = cv2.resize(rank_crop, (tw, th), interpolation=cv2.INTER_AREA)
            padded = cv2.copyMakeBorder(
                scaled, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0
            )
            res = cv2.matchTemplate(padded, r_tpl, cv2.TM_CCOEFF_NORMED)
            rank_scores[r_name] = float(cv2.minMaxLoc(res)[1])

        suit_scores: dict[str, float] = {}
        mid_ratio = 0.55
        if suit_crop is not None and suit_crop.shape[0] >= 6 and suit_crop.shape[1] >= 6:
            sh, sw = suit_crop.shape
            top_third = suit_crop[: int(sh * 0.35), :]
            mid_sec = suit_crop[int(sh * 0.35) : int(sh * 0.55), :]
            top_w = max([np.sum(row > 128) for row in top_third]) if len(top_third) else 0
            tot_w = max([np.sum(row > 128) for row in suit_crop])
            mid_w = min([np.sum(row > 128) for row in mid_sec]) if len(mid_sec) else top_w
            if tot_w > 0:
                mid_ratio = mid_w / tot_w

        for s_name in allowed_suits:
            s_tpl = self.suits[s_name]
            th, tw = s_tpl.shape[:2]
            if (
                suit_crop is not None
                and suit_crop.shape[0] >= 6
                and suit_crop.shape[1] >= 6
            ):
                scaled = cv2.resize(suit_crop, (tw, th), interpolation=cv2.INTER_AREA)
                padded = cv2.copyMakeBorder(
                    scaled, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0
                )
                res = cv2.matchTemplate(padded, s_tpl, cv2.TM_CCOEFF_NORMED)
                base_score = float(cv2.minMaxLoc(res)[1])
                if color_group == "BLACK":
                    if s_name == "c":
                        base_score += 0.12 if mid_ratio <= 0.50 else -0.10
                    elif s_name == "s":
                        base_score += 0.12 if mid_ratio > 0.50 else -0.10
                suit_scores[s_name] = base_score
            else:
                suit_scores[s_name] = 0.5

        candidates_list: list[tuple[str, float]] = []
        for r_name, r_score in rank_scores.items():
            for s_name, s_score in suit_scores.items():
                comb = 0.65 * r_score + 0.35 * s_score
                candidates_list.append((r_name + s_name, comb))

        candidates_list.sort(key=lambda x: x[1], reverse=True)
        eff_thresh = min(self.threshold, 0.72)
        return [(c, s) for c, s in candidates_list if s >= eff_thresh][:top_k]

    def recognize_candidates(
        self,
        card_roi: np.ndarray,
        top_k: int = 3,
        slot_hint: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return top_k card candidates above threshold sorted descending by score."""
        if self._use_rank_suit:
            return self._recognize_rank_suit_candidates(
                card_roi, top_k=top_k, slot_hint=slot_hint
            )

        if (
            card_roi is None
            or card_roi.size == 0
            or not self.template_items
        ):
            return []

        # Ensure 3-channel BGR input
        if card_roi.ndim == 2:
            roi_bgr = cv2.cvtColor(card_roi, cv2.COLOR_GRAY2BGR)
        elif card_roi.shape[2] == 4:
            roi_bgr = cv2.cvtColor(card_roi, cv2.COLOR_BGRA2BGR)
        else:
            roi_bgr = card_roi

        roi_h, roi_w = roi_bgr.shape[:2]
        card_scores: dict[str, float] = {}
        resized_cache: dict[tuple[int, int], np.ndarray] = {}

        for card_name, template in self.template_items:
            th, tw = template.shape[:2]

            if roi_h >= th and roi_w >= tw:
                res = cv2.matchTemplate(roi_bgr, template, cv2.TM_CCOEFF_NORMED)
            else:
                if (tw, th) in resized_cache:
                    current_roi = resized_cache[(tw, th)]
                elif (roi_w, roi_h) == (tw, th):
                    current_roi = roi_bgr
                    resized_cache[(tw, th)] = roi_bgr
                else:
                    current_roi = cv2.resize(
                        roi_bgr, (tw, th), interpolation=cv2.INTER_AREA
                    )
                    resized_cache[(tw, th)] = current_roi
                res = cv2.matchTemplate(current_roi, template, cv2.TM_CCOEFF_NORMED)

            score = float(cv2.minMaxLoc(res)[1])
            c_code = card_name
            if c_code.startswith("10"):
                c_code = "T" + c_code[2:]

            if c_code not in card_scores or score > card_scores[c_code]:
                card_scores[c_code] = score

        candidates = [
            (c, s) for c, s in card_scores.items() if s >= self.threshold
        ]
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:top_k]

    def recognize(
        self,
        card_roi: np.ndarray,
        slot_hint: str | None = None,
    ) -> tuple[str | None, float]:
        """Recognize card rank and suit from card corner ROI."""
        if self._use_rank_suit:
            cands = self._recognize_rank_suit_candidates(
                card_roi, top_k=1, slot_hint=slot_hint
            )
            if cands:
                return cands[0]
            return (None, 0.0)

        if (
            card_roi is None
            or card_roi.size == 0
            or not self.template_items
        ):
            return (None, 0.0)

        # Ensure 3-channel BGR input
        if card_roi.ndim == 2:
            roi_bgr = cv2.cvtColor(card_roi, cv2.COLOR_GRAY2BGR)
        elif card_roi.shape[2] == 4:
            roi_bgr = cv2.cvtColor(card_roi, cv2.COLOR_BGRA2BGR)
        else:
            roi_bgr = card_roi

        roi_h, roi_w = roi_bgr.shape[:2]
        best_card: str | None = None
        best_score: float = -1.0

        resized_cache: dict[tuple[int, int], np.ndarray] = {}

        for card_name, template in self.template_items:
            th, tw = template.shape[:2]

            if roi_h >= th and roi_w >= tw:
                res = cv2.matchTemplate(roi_bgr, template, cv2.TM_CCOEFF_NORMED)
            else:
                if (tw, th) in resized_cache:
                    current_roi = resized_cache[(tw, th)]
                elif (roi_w, roi_h) == (tw, th):
                    current_roi = roi_bgr
                    resized_cache[(tw, th)] = roi_bgr
                else:
                    current_roi = cv2.resize(
                        roi_bgr, (tw, th), interpolation=cv2.INTER_AREA
                    )
                    resized_cache[(tw, th)] = current_roi
                res = cv2.matchTemplate(current_roi, template, cv2.TM_CCOEFF_NORMED)

            score = float(cv2.minMaxLoc(res)[1])

            if score > best_score:
                best_score = score
                best_card = card_name

        if best_score >= self.threshold and best_card is not None:
            if best_card.startswith("10"):
                best_card = "T" + best_card[2:]
            return (best_card, best_score)

        return (None, max(0.0, best_score))
