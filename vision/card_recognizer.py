"""Card corner template matching for 52 cards using full BGR color comparison."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class CardRecognizer:
    """Recognizes playing cards from ROI patches using 3-channel template matching."""

    def __init__(
        self,
        templates_dir: str | Path = "data/templates/cards",
        threshold: float = 0.92,
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.threshold = float(threshold)
        self.templates: dict[str, np.ndarray] = {}
        self.template_items: list[tuple[str, np.ndarray]] = []
        self._load_templates()

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

    def recognize_candidates(
        self, card_roi: np.ndarray, top_k: int = 3
    ) -> list[tuple[str, float]]:
        """Return top_k card candidates above threshold sorted descending by score.

        Aggregates multiple template variations (e.g. 5s and 5s_board) taking the
        maximum score for each unique card code.
        """
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

    def recognize(self, card_roi: np.ndarray) -> tuple[str | None, float]:
        """Recognize card rank and suit from card corner ROI.

        Returns (best_card_code, confidence_score). If confidence < threshold or
        roi is empty, returns (None, confidence_score).
        """
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

        # Cache resized variations if templates have same dimensions
        resized_cache: dict[tuple[int, int], np.ndarray] = {}

        for card_name, template in self.template_items:
            th, tw = template.shape[:2]

            # Direct match if roi is large enough, otherwise scale roi to template size
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
