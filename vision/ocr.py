"""Lightweight digit OCR and Hero turn action detector using OpenCV."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class DigitOCR:
    """Lightweight template-matching based digit OCR for numbers and blinds."""

    def __init__(
        self,
        templates_dir: str | Path = "data/templates/digits",
        threshold: float = 0.80,
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.threshold = float(threshold)
        self.templates: dict[int, np.ndarray] = {}
        self._load_templates()

    def _trim_to_digit(self, img: np.ndarray) -> np.ndarray:
        """Trim binary/grayscale template to the tight bounding box of the digit."""
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _otsu, bin_t = cv2.threshold(
            img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        corners = [
            int(bin_t[0, 0]),
            int(bin_t[0, -1]),
            int(bin_t[-1, 0]),
            int(bin_t[-1, -1]),
        ]
        if sum(1 for c in corners if c > 127) >= 3:
            bin_t = cv2.bitwise_not(bin_t)

        cnts, _ = cv2.findContours(
            bin_t, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if cnts:
            all_pts = np.vstack(cnts)
            x, y, w, h = cv2.boundingRect(all_pts)
            if w > 2 and h > 2:
                return bin_t[y : y + h, x : x + w]
        return bin_t

    def _load_templates(self) -> None:
        if not self.templates_dir.is_dir():
            return

        for digit in range(10):
            p = self.templates_dir / f"{digit}.png"
            if p.exists():
                img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                if img is not None and img.size > 0:
                    self.templates[digit] = self._trim_to_digit(img)

    def preprocess(self, roi: np.ndarray) -> np.ndarray:
        """Convert to grayscale, upscale 2x, and binarize via Otsu thresholding."""
        if roi.ndim == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi.copy()

        resized = cv2.resize(
            gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC
        )
        _otsu_thresh, thresh = cv2.threshold(
            resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        return thresh

    def _prepare_binary_image(
        self,
        roi: np.ndarray,
        min_p98: float = 140.0,
        min_contrast: float = 40.0,
    ) -> np.ndarray | None:
        if roi is None or roi.size == 0:
            return None

        # Check for near uniform images (e.g. empty or background only)
        if float(np.std(roi)) < 4.0:
            return None

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        p2 = float(np.percentile(gray, 2))
        p50 = float(np.percentile(gray, 50))
        p98 = float(np.percentile(gray, 98))

        if p50 > 180.0:
            if (p50 - p2) < min_contrast:
                return None
        else:
            if p98 < min_p98 or (p98 - p50) < min_contrast:
                return None

        bin_img = self.preprocess(roi)
        # Invert if background appears white/light (check corners)
        corners = [
            int(bin_img[0, 0]),
            int(bin_img[0, -1]),
            int(bin_img[-1, 0]),
            int(bin_img[-1, -1]),
        ]
        if sum(1 for c in corners if c > 127) >= 3:
            bin_img = cv2.bitwise_not(bin_img)

        # 2x2 morphological opening to disconnect touching characters only on larger crops
        if bin_img.shape[0] >= 55:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            bin_img = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, kernel)

        return bin_img

    def _match_digit_crop(self, crop: np.ndarray) -> tuple[int | None, float]:
        """Trim split crop to tight non-zero bbox, resize, pad 2px, and match templates."""
        if crop.size == 0:
            return None, -1.0

        ys, xs = np.where(crop > 0)
        if len(ys) == 0 or len(xs) == 0:
            return None, -1.0

        y_min, y_max = int(ys.min()), int(ys.max())
        x_min, x_max = int(xs.min()), int(xs.max())
        trimmed = crop[y_min : y_max + 1, x_min : x_max + 1]
        if trimmed.size == 0 or trimmed.shape[0] < 2 or trimmed.shape[1] < 1:
            return None, -1.0

        best_digit: int | None = None
        best_score = -1.0

        for d_val, tmpl in self.templates.items():
            th, tw = tmpl.shape[:2]
            resized_crop = cv2.resize(
                trimmed, (tw, th), interpolation=cv2.INTER_AREA
            )
            padded_crop = cv2.copyMakeBorder(
                resized_crop, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0
            )
            res = cv2.matchTemplate(padded_crop, tmpl, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(res)
            score = float(max_val)
            if score > best_score:
                best_score = score
                best_digit = d_val

        return best_digit, best_score

    def _split_wide_box(
        self, box: tuple[int, int, int, int], bin_img: np.ndarray
    ) -> list[tuple[int, int, int, int]]:
        """Split horizontally touching digit bounding boxes based on column density valleys."""
        x, y, w, h = box
        if w <= 1.05 * h:
            return [box]
        crop = bin_img[y : y + h, x : x + w]
        col_sums = np.sum(crop, axis=0)
        mid_start = int(w * 0.25)
        mid_end = int(w * 0.75)
        if mid_end <= mid_start:
            return [box]
        split_x = mid_start + int(np.argmin(col_sums[mid_start:mid_end]))
        left = (x, y, split_x, h)
        right = (x + split_x, y, w - split_x, h)
        res: list[tuple[int, int, int, int]] = []
        res.extend(self._split_wide_box(left, bin_img))
        res.extend(self._split_wide_box(right, bin_img))
        return res

    def read_int(self, roi: np.ndarray) -> int | None:
        """Extract and recognize an integer from the ROI.

        Returns int value or None if digits could not be reliably recognized.
        """
        if not self.templates:
            return None

        bin_img = self._prepare_binary_image(roi, min_p98=100.0, min_contrast=40.0)
        if bin_img is None:
            return None

        bh, bw = bin_img.shape[:2]
        min_h = max(5, int(bh * 0.2))
        max_h = int(bh * 0.98)
        min_w = 2
        max_w = int(bw * 0.95)

        contours, _ = cv2.findContours(
            bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        raw_boxes: list[tuple[int, int, int, int]] = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if min_h <= h <= max_h and min_w <= w <= max_w:
                raw_boxes.append((x, y, w, h))

        if not raw_boxes:
            return None

        valid_boxes: list[tuple[int, int, int, int]] = []
        for b in raw_boxes:
            valid_boxes.extend(self._split_wide_box(b, bin_img))

        # Sort contours horizontally left-to-right
        valid_boxes.sort(key=lambda b: b[0])

        digits: list[str] = []
        for bx, by, bw_b, bh_b in valid_boxes:
            crop = bin_img[by : by + bh_b, bx : bx + bw_b]
            best_digit, best_score = self._match_digit_crop(crop)

            if best_score >= self.threshold and best_digit is not None:
                digits.append(str(best_digit))

        if not digits:
            return None

        try:
            return int("".join(digits))
        except ValueError:
            return None

    def read_float(self, roi: np.ndarray) -> float | None:
        """Extract and recognize a float (e.g. prize pool '$1.50') from the ROI.

        Detects decimal dots between digits. Returns float or None.
        """
        if not self.templates:
            return None

        bin_img = self._prepare_binary_image(roi, min_p98=125.0, min_contrast=35.0)
        if bin_img is None:
            return None

        bh, bw = bin_img.shape[:2]
        min_h = max(5, int(bh * 0.2))
        max_h = int(bh * 0.98)
        min_w = 2
        max_w = int(bw * 0.95)

        contours, _ = cv2.findContours(
            bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        raw_boxes: list[tuple[int, int, int, int]] = []
        dot_boxes: list[tuple[int, int, int, int]] = []

        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if min_h <= h <= max_h and min_w <= w <= max_w:
                raw_boxes.append((x, y, w, h))
            elif 2 <= w <= int(bh * 0.45) and 2 <= h <= int(bh * 0.35) and y >= int(bh * 0.40):
                dot_boxes.append((x, y, w, h))

        if not raw_boxes:
            return None

        valid_boxes: list[tuple[int, int, int, int]] = []
        for b in raw_boxes:
            valid_boxes.extend(self._split_wide_box(b, bin_img))

        valid_boxes.sort(key=lambda b: b[0])

        tokens: list[tuple[int, str]] = []
        for bx, by, bw_b, bh_b in valid_boxes:
            crop = bin_img[by : by + bh_b, bx : bx + bw_b]
            best_digit, best_score = self._match_digit_crop(crop)

            if best_score >= self.threshold and best_digit is not None:
                tokens.append((bx, str(best_digit)))

        if not tokens:
            return None

        # Insert dots between recognized digits
        for dx, _dy, _dw, _dh in dot_boxes:
            if any(t[0] < dx for t in tokens) and any(t[0] > dx for t in tokens):
                tokens.append((dx, "."))

        tokens.sort(key=lambda t: t[0])
        str_val = "".join(t[1] for t in tokens)

        try:
            return float(str_val)
        except ValueError:
            return None

    def read_blinds(self, roi: np.ndarray) -> tuple[int, int] | None:
        """Extract small blind and big blind separated by slash or horizontal gap.

        Returns (small_blind, big_blind) or None if recognition fails.
        """
        if not self.templates:
            return None

        bin_img = self._prepare_binary_image(roi, min_p98=100.0, min_contrast=25.0)
        if bin_img is None:
            return None

        bh, bw = bin_img.shape[:2]
        min_h = max(5, int(bh * 0.15))
        max_h = int(bh * 0.98)
        min_w = 2
        max_w = int(bw * 0.95)

        contours, _ = cv2.findContours(
            bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        raw_boxes: list[tuple[int, int, int, int]] = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if min_h <= h <= max_h and min_w <= w <= max_w:
                raw_boxes.append((x, y, w, h))

        boxes: list[tuple[int, int, int, int]] = []
        for b in raw_boxes:
            boxes.extend(self._split_wide_box(b, bin_img))

        if len(boxes) < 2:
            return None

        boxes.sort(key=lambda b: b[0])

        recognized: list[tuple[tuple[int, int, int, int], str | None]] = []
        for bx, by, bw_b, bh_b in boxes:
            crop = bin_img[by : by + bh_b, bx : bx + bw_b]
            best_digit, best_score = self._match_digit_crop(crop)

            # A '/' separator in blinds can resemble '7' without a top bar; reject if top-left is empty.
            if best_digit == 7 and best_score >= self.threshold:
                ys, xs = np.where(crop > 0)
                if len(ys) > 0 and len(xs) > 0:
                    tr = crop[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1]
                    tl_mean = float(np.mean(tr[: max(1, tr.shape[0] // 4), : max(1, tr.shape[1] // 2)]))
                    if tl_mean < 40.0:
                        best_digit = None

            if best_score >= self.threshold and best_digit is not None:
                recognized.append(((bx, by, bw_b, bh_b), str(best_digit)))
            else:
                recognized.append(((bx, by, bw_b, bh_b), None))

        # Check if an unrecognized contour acts as a slash separator
        digit_indices = [
            i for i, (_box, digit) in enumerate(recognized) if digit is not None
        ]
        if len(digit_indices) < 2:
            return None

        # Look for a divider separator between digits (ignore leading/trailing non-digits)
        split_idx: int | None = None
        first_d = digit_indices[0]
        last_d = digit_indices[-1]

        for i in range(first_d + 1, last_d):
            if recognized[i][1] is None:
                split_idx = i
                break

        if split_idx is not None:
            group1 = [
                d for _box, d in recognized[first_d:split_idx] if d is not None
            ]
            group2 = [
                d for _box, d in recognized[split_idx + 1 : last_d + 1] if d is not None
            ]
        else:
            # Split by largest horizontal gap between consecutive recognized digits
            max_gap = -1
            best_split = -1
            for k in range(len(digit_indices) - 1):
                idx_a = digit_indices[k]
                idx_b = digit_indices[k + 1]
                box_a = recognized[idx_a][0]
                box_b = recognized[idx_b][0]
                gap = box_b[0] - (box_a[0] + box_a[2])
                if gap > max_gap:
                    max_gap = gap
                    best_split = k

            if best_split < 0:
                return None

            group1 = [
                recognized[digit_indices[i]][1]
                for i in range(0, best_split + 1)
            ]
            group2 = [
                recognized[digit_indices[i]][1]
                for i in range(best_split + 1, len(digit_indices))
            ]

        if not group1 or not group2:
            return None

        try:
            sb = int("".join(group1))  # type: ignore[arg-type]
            bb = int("".join(group2))  # type: ignore[arg-type]
            return (sb, bb)
        except ValueError:
            return None


def detect_hero_actions(
    actions_roi: np.ndarray,
    hero_timer_roi: np.ndarray | None = None,
) -> tuple[bool, list[str]]:
    """Detect whether Hero action buttons (Fold, Check/Call, Bet/Raise) are active.

    When hero_timer_roi is provided, requires the bright purple countdown timer bar
    under Hero (Seat 0) to be active (>= 500 purple pixels), preventing false triggers
    from rabbit hunting breaks and opponent turns with grey pre-action checkboxes.

    Uses HSV color heuristics:
    - Red hue: Fold button
    - Green hue: Check / Call button
    - Orange / Gold hue: Bet / Raise / All-in button

    Returns (is_hero_turn, list_of_actions).
    """
    if hero_timer_roi is not None and hero_timer_roi.size > 0:
        hsv_timer = cv2.cvtColor(hero_timer_roi, cv2.COLOR_BGR2HSV)
        mask_purple = cv2.inRange(
            hsv_timer, np.array([125, 80, 100]), np.array([165, 255, 255])
        )
        if int(cv2.countNonZero(mask_purple)) < 500:
            return (False, [])

    if actions_roi is None or actions_roi.size == 0:
        return (False, [])

    hsv = cv2.cvtColor(actions_roi, cv2.COLOR_BGR2HSV)
    h, w = actions_roi.shape[:2]
    total_pixels = h * w
    min_action_pixels = max(20, min(80, int(total_pixels * 0.002)))

    # Red mask (Fold) - wraps around 0/180 in HSV
    mask_red1 = cv2.inRange(hsv, np.array([0, 60, 60]), np.array([10, 255, 255]))
    mask_red2 = cv2.inRange(hsv, np.array([170, 60, 60]), np.array([180, 255, 255]))
    mask_red = cv2.bitwise_or(mask_red1, mask_red2)

    # Green mask (Check / Call)
    mask_green = cv2.inRange(hsv, np.array([35, 60, 60]), np.array([85, 255, 255]))

    # Orange / Gold mask (Bet / Raise / All-in)
    mask_orange = cv2.inRange(hsv, np.array([11, 60, 60]), np.array([34, 255, 255]))

    if w >= 2 * h:
        # Zoned action detection:
        # Fold is located in left zone (0 .. 0.45w)
        has_fold = int(cv2.countNonZero(mask_red[:, : int(w * 0.45)])) >= min_action_pixels
        # Check / Call is located in middle zone (0.15w .. 0.80w)
        has_check = int(cv2.countNonZero(mask_green[:, int(w * 0.15) : int(w * 0.80)])) >= min_action_pixels
        # Bet / Raise is located in right zone (x >= 0.40w) with solid button contour
        right_orange = mask_orange[:, int(w * 0.40) :]
        cnts, _ = cv2.findContours(right_orange, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        has_bet = any(cv2.boundingRect(c)[2] >= 10 and cv2.boundingRect(c)[3] >= 10 for c in cnts)
    else:
        has_fold = int(cv2.countNonZero(mask_red)) >= min_action_pixels
        has_check = int(cv2.countNonZero(mask_green)) >= min_action_pixels
        has_bet = int(cv2.countNonZero(mask_orange)) >= min_action_pixels

    actions: list[str] = []
    if has_fold:
        actions.append("FOLD")
    if has_check:
        actions.append("CHECK")
    if has_bet:
        actions.append("BET")

    if len(actions) >= 2:
        return (True, actions)

    return (False, [])
