"""DecisionLock mechanism to prevent rapid decision flickering across frames."""

from __future__ import annotations

from typing import Any

from core.contracts import Decision, TableState


def compute_decision_fingerprint(state: TableState, is_preview: bool = False) -> tuple:
    """Zwraca niezmienną krotkę opisującą konkretną sytuację decyzyjną na stole."""
    players = getattr(state, "players", {}) or {}
    players_sig = tuple(
        (
            sid,
            getattr(players[sid], "current_bet", 0) if sid in players else 0,
            getattr(players[sid], "stack", None) if sid in players else None,
            bool(getattr(players[sid], "is_active", True)) if sid in players else False,
            bool(getattr(players[sid], "is_dealer", False)) if sid in players else False,
        )
        for sid in (0, 1, 2)
    )
    return (
        tuple(sorted(getattr(state, "hero_cards", []) or [])),
        tuple(getattr(state, "board_cards", []) or []),
        getattr(state, "street", ""),
        bool(getattr(state, "is_hero_turn", False)),
        bool(is_preview),
        tuple(sorted(getattr(state, "available_actions", []) or [])),
        int(getattr(state, "pot", 0) or 0),
        int(getattr(state, "big_blind", 20) or 20),
        players_sig,
    )


class DecisionLock:
    """Stabilizes decisions across consecutive frames to prevent jitter."""

    def __init__(self, confirm_frames: int = 2) -> None:
        self.confirm_frames = max(1, confirm_frames)
        self._pending_fp: tuple | None = None
        self._pending_count: int = 0
        self._locked_fp: tuple | None = None
        self._locked_decision: Decision | None = None

    def get_locked(self, fp: tuple) -> Decision | None:
        """Returns the locked decision if the fingerprint matches the locked state."""
        if self._locked_fp is not None and fp == self._locked_fp:
            return self._locked_decision
        return None

    def observe_and_should_compute(self, fp: tuple) -> bool:
        """Observes a frame fingerprint. Returns True only when confirmed over confirm_frames."""
        if self._locked_fp is not None and fp == self._locked_fp:
            return False

        if fp == self._pending_fp:
            self._pending_count += 1
        else:
            self._pending_fp = fp
            self._pending_count = 1

        return self._pending_count >= self.confirm_frames

    def lock(self, fp: tuple, decision: Decision) -> None:
        """Locks a decision for the given fingerprint."""
        self._locked_fp = fp
        self._locked_decision = decision
        self._pending_fp = None
        self._pending_count = 0

    def reset(self) -> None:
        """Resets pending and locked states."""
        self._pending_fp = None
        self._pending_count = 0
        self._locked_fp = None
        self._locked_decision = None
