"""Vision module for poker_assistant: frame capture, anchor detection, cards, OCR."""

from __future__ import annotations

from vision.anchor import (
    compute_table_rect,
    crop_rois,
    find_all_anchors,
    find_anchor,
)
from vision.capture import (
    FrameSource,
    LiveScreenCapture,
    OfflineReplayCapture,
)
from vision.card_recognizer import CardRecognizer
from vision.ocr import DigitOCR, detect_hero_actions
from vision.pipeline import VisionPipeline

__all__ = [
    "FrameSource",
    "LiveScreenCapture",
    "OfflineReplayCapture",
    "find_anchor",
    "find_all_anchors",
    "compute_table_rect",
    "crop_rois",
    "CardRecognizer",
    "DigitOCR",
    "detect_hero_actions",
    "VisionPipeline",
]
