"""Lightweight session logging to JSONL format."""

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.contracts import Decision, TableState
from state.tracker import GameEvent


class SessionLogger:
    """Lightweight session event and decision logger writing to .jsonl."""

    def __init__(self, log_dir: str | Path = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / f"session_{timestamp}.jsonl"
        self.file_path = self.log_path
        self.log_file = self.log_path
        self._file = open(self.log_path, mode="a", encoding="utf-8")

    @staticmethod
    def _to_dict(obj: Any) -> Any:
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return obj.to_dict()
        return obj

    def log_state(self, state: TableState, events: list[GameEvent] | None = None) -> None:
        """Logs table state and associated game events as a single json line."""
        events_list = events or []
        payload = {
            "type": "state",
            "data": self._to_dict(state),
            "events": [self._to_dict(e) for e in events_list],
        }
        self._file.write(json.dumps(payload) + "\n")
        self._file.flush()

    def log_decision(self, decision: Decision, latency_ms: float) -> None:
        """Logs a calculated decision and execution latency as a single json line."""
        payload = {
            "type": "decision",
            "latency_ms": round(latency_ms, 2),
            "data": self._to_dict(decision),
        }
        self._file.write(json.dumps(payload) + "\n")
        self._file.flush()

    def close(self) -> None:
        """Closes the underlying log file."""
        if self._file is not None and not self._file.closed:
            self._file.close()

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
