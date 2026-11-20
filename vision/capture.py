"""Frame capture sources: Live screen capture via dxcam and Offline replay."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import threading
from typing import Sequence

import cv2
import numpy as np

try:
    import dxcam

    DXCAM_AVAILABLE = True
except ImportError:
    dxcam = None
    DXCAM_AVAILABLE = False


class FrameSource(ABC):
    """Abstract base class for all frame capture sources."""

    @abstractmethod
    def grab(self) -> np.ndarray | None:
        """Grab the next BGR frame as a numpy.ndarray.

        Returns None if no frame is available or replay ended.
        """
        raise NotImplementedError

    @abstractmethod
    def release(self) -> None:
        """Release underlying capture resources."""
        raise NotImplementedError


class LiveScreenCapture(FrameSource):
    """Live screen capture on Windows using DirectX Desktop Duplication (dxcam)."""

    def __init__(
        self,
        region: tuple[int, int, int, int] | None = None,
        target_fps: int = 15,
    ) -> None:
        if not DXCAM_AVAILABLE or dxcam is None:
            raise RuntimeError("dxcam is not installed or available on this system.")

        self.region = region
        self.target_fps = target_fps
        self._camera = None
        self._init_camera()

    def _init_camera(self) -> None:
        self._camera = dxcam.create(
            region=self.region,
            max_buffer_len=4,
        )
        if self._camera is None:
            raise RuntimeError("Failed to create dxcam camera instance.")

    def grab(self) -> np.ndarray | None:
        if self._camera is None:
            return None
        frame = self._camera.grab(region=self.region)
        if frame is None:
            return None
        # Convert RGB from dxcam to BGR for OpenCV consistency
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def release(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            del self._camera
            self._camera = None


class OfflineReplayCapture(FrameSource):
    """Replay frames from a folder of images or a single video/image file."""

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"}

    def __init__(self, source_path: str | Path, loop: bool = False) -> None:
        self.source_path = Path(source_path)
        self.loop = loop
        self._lock = threading.Lock()
        self._mode: str = "none"
        self._image_files: list[Path] = []
        self._current_idx: int = 0
        self.current_frame_idx: int = 0
        self.total_frames: int = 0
        self._single_frame: np.ndarray | None = None
        self._cap: cv2.VideoCapture | None = None

        if not self.source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {self.source_path}")

        if self.source_path.is_dir():
            self._mode = "folder"
            self._image_files = sorted(
                [
                    p
                    for p in self.source_path.iterdir()
                    if p.is_file() and p.suffix.lower() in self.IMAGE_EXTENSIONS
                ]
            )
            if not self._image_files:
                raise ValueError(
                    f"No supported image files found in folder: {self.source_path}"
                )
            self.total_frames = len(self._image_files)
        else:
            ext = self.source_path.suffix.lower()
            if ext in self.VIDEO_EXTENSIONS:
                self._mode = "video"
                self._cap = cv2.VideoCapture(str(self.source_path))
                if not self._cap.isOpened():
                    raise ValueError(f"Could not open video file: {self.source_path}")
                count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
                self.total_frames = max(0, count)
            elif ext in self.IMAGE_EXTENSIONS:
                self._mode = "image"
                img = cv2.imread(str(self.source_path))
                if img is None:
                    raise ValueError(f"Could not decode image file: {self.source_path}")
                self._single_frame = img
                self.total_frames = 1
            else:
                raise ValueError(f"Unsupported source format: {self.source_path.suffix}")

    def grab(self) -> np.ndarray | None:
        with self._lock:
            if self._mode == "folder":
                if self._current_idx >= len(self._image_files):
                    if self.loop and self._image_files:
                        self._current_idx = 0
                    else:
                        return None

                self.current_frame_idx = self._current_idx
                img_path = self._image_files[self._current_idx]
                self._current_idx += 1
                frame = cv2.imread(str(img_path))
                return frame

            elif self._mode == "image":
                if self._single_frame is None:
                    return None
                if self._current_idx == 0 or self.loop:
                    self.current_frame_idx = 0
                    self._current_idx += 1
                    return self._single_frame.copy()
                return None

            elif self._mode == "video":
                if self._cap is None or not self._cap.isOpened():
                    return None
                cur_pos = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    if self.loop:
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self.current_frame_idx = 0
                        ret, frame = self._cap.read()
                        if not ret or frame is None:
                            return None
                        return frame
                    return None
                self.current_frame_idx = cur_pos
                return frame

            return None

    def seek(self, frame_idx: int) -> None:
        """Seek replay to a specific zero-based frame index.

        Args:
            frame_idx: Target frame index. Clamped to [0, max(0, total_frames - 1)].
        """
        with self._lock:
            if self.total_frames <= 0:
                return
            clamped = max(0, min(frame_idx, self.total_frames - 1))
            if self._mode == "video":
                if self._cap is not None and self._cap.isOpened():
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, clamped)
                    self.current_frame_idx = clamped
            elif self._mode == "folder":
                self._current_idx = clamped
                self.current_frame_idx = clamped
            elif self._mode == "image":
                self._current_idx = 0
                self.current_frame_idx = 0

    def release(self) -> None:
        with self._lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            self._single_frame = None
            self._image_files = []
