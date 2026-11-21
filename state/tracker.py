"""State machine, hand tracking, and timing tells measurement."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import time
from typing import Any

from core.contracts import TableState


@dataclass
class GameEvent:
    event_type: str  # "NEW_HAND", "STREET_CHANGE", "VILLAIN_ACTION", "HERO_TURN"
    table_id: str
    timestamp_ms: int
    details: dict = field(default_factory=dict)


class TableTracker:
    """Tracks state transitions across valid frames, measures reaction times, and produces game events."""

    def __init__(self, table_id: str) -> None:
        self.table_id = table_id
        self.prev_state: TableState | None = None
        self.hand_number: int = 0
        self.last_state_change_ms: int | None = None
        self.current_hand: dict[str, Any] = {}
        self.last_completed_hand: dict[str, Any] | None = None

    def _format_time(self, ts_ms: int) -> str:
        if ts_ms >= 100_000_000_000:
            return time.strftime("%H:%M:%S", time.localtime(ts_ms / 1000.0))
        tot_s = int(ts_ms / 1000.0)
        return f"{tot_s // 60:02d}:{tot_s % 60:02d}"

    def _init_current_hand(self, state: TableState) -> None:
        players_dict: dict[int, dict[str, Any]] = {}
        for sid in (0, 1, 2):
            p = state.players.get(sid)
            cur_bet = getattr(p, "current_bet", 0) if p else 0
            is_dealer = bool(getattr(p, "is_dealer", False)) if p else False
            stack = getattr(p, "stack", None) if p else None
            is_active = getattr(p, "is_active", True) if p else True
            status_text = getattr(p, "status_text", "ACTIVE") if p else "ACTIVE"
            folded = bool((not is_active) or (status_text == "FOLDED"))

            last_action = "—"
            if cur_bet > 0:
                last_action = f"BLIND {cur_bet}"
            elif folded:
                last_action = "FOLD"

            players_dict[sid] = {
                "seat_id": sid,
                "name": "Ty (S0)" if sid == 0 else f"Rywal {sid} (S{sid})",
                "is_dealer": is_dealer,
                "stack": stack,
                "invested_total": cur_bet,
                "street_bet": cur_bet,
                "last_action": last_action,
                "last_decision_sec": None,
                "folded": folded,
            }

        action_log: list[dict[str, Any]] = []
        for sid in (1, 2, 0):
            p_info = players_dict[sid]
            if p_info["invested_total"] > 0:
                action_log.append({
                    "time_str": self._format_time(state.timestamp_ms),
                    "street": "PREFLOP",
                    "seat_id": sid,
                    "player_name": p_info["name"],
                    "action": "BLIND",
                    "amount": p_info["invested_total"],
                    "invested_total": p_info["invested_total"],
                    "decision_sec": None,
                })

        self.current_hand = {
            "hand_number": self.hand_number,
            "table_id": self.table_id,
            "start_ts_ms": state.timestamp_ms,
            "blinds": (getattr(state, "small_blind", 0), getattr(state, "big_blind", 0)),
            "prize_pool": getattr(state, "prize_pool", None),
            "hero_cards": list(getattr(state, "hero_cards", [])),
            "board_cards": list(getattr(state, "board_cards", [])),
            "street": getattr(state, "street", "PREFLOP"),
            "pot": getattr(state, "pot", 0),
            "players": players_dict,
            "action_log": action_log,
            "recommendations": [],
        }

    def record_recommendation(
        self,
        decision: Any,
        street: str,
        timestamp_ms: int,
    ) -> None:
        """Record a HUD decision recommendation for the current hand."""
        if not self.current_hand:
            return
        act = getattr(decision, "action", "WAIT")
        if act == "WAIT":
            return
        recs = self.current_hand.setdefault("recommendations", [])
        if recs:
            last = recs[-1]
            if last.get("street") == street and last.get("action") == act:
                return
        recs.append({
            "street": street,
            "action": act,
            "sizing_bb": getattr(decision, "sizing_bb", None),
            "sizing_chips": getattr(decision, "sizing_chips", None),
            "ev_bb": getattr(decision, "ev_bb", None),
            "reason": getattr(decision, "reason", ""),
            "timestamp_ms": timestamp_ms,
        })

    def get_hand_summary(self) -> dict[str, Any]:
        """Return a copy of the current hand summary for HUD or recording."""
        return copy.deepcopy(self.current_hand)

    def update(self, state: TableState) -> tuple[TableState, list[GameEvent]]:
        """Processes a new TableState frame.

        Returns:
            tuple[TableState, list[GameEvent]]: The updated table state and detected events.
        """
        # If frame failed validation, ignore it and retain previous valid state
        if not state.is_valid:
            return state, []

        events: list[GameEvent] = []

        # First valid frame observed
        if self.prev_state is None:
            self.hand_number = 1
            self.last_state_change_ms = state.timestamp_ms
            self._init_current_hand(state)
            self.prev_state = state
            event = GameEvent(
                event_type="NEW_HAND",
                table_id=self.table_id,
                timestamp_ms=state.timestamp_ms,
                details={"hand_number": self.hand_number},
            )
            return state, [event]

        # Detect NEW_HAND
        hero_cards_changed = (
            bool(state.hero_cards) and state.hero_cards != self.prev_state.hero_cards
        )

        prev_dealer = next(
            (sid for sid, p in self.prev_state.players.items() if p.is_dealer), None
        )
        curr_dealer = next((sid for sid, p in state.players.items() if p.is_dealer), None)
        dealer_changed = (
            prev_dealer is not None and curr_dealer is not None and prev_dealer != curr_dealer
        )

        street_reset = (
            self.prev_state.street in ("FLOP", "TURN", "RIVER")
            and state.street == "PREFLOP"
        )

        is_new_hand = hero_cards_changed or dealer_changed or street_reset

        if is_new_hand:
            self.hand_number += 1
            self.last_state_change_ms = state.timestamp_ms
            if self.current_hand and (self.current_hand.get("hero_cards") or self.current_hand.get("action_log")):
                self.last_completed_hand = copy.deepcopy(self.current_hand)
            self._init_current_hand(state)
            events.append(
                GameEvent(
                    event_type="NEW_HAND",
                    table_id=self.table_id,
                    timestamp_ms=state.timestamp_ms,
                    details={"hand_number": self.hand_number},
                )
            )

        # Sync ongoing hand metadata
        if state.hero_cards:
            self.current_hand["hero_cards"] = list(state.hero_cards)
        if state.board_cards:
            self.current_hand["board_cards"] = list(state.board_cards)
        self.current_hand["pot"] = getattr(state, "pot", self.current_hand.get("pot", 0))
        self.current_hand["street"] = state.street
        if getattr(state, "prize_pool", None) is not None:
            self.current_hand["prize_pool"] = state.prize_pool

        # Detect STREET_CHANGE
        if not is_new_hand and state.street != self.prev_state.street:
            self.last_state_change_ms = state.timestamp_ms
            events.append(
                GameEvent(
                    event_type="STREET_CHANGE",
                    table_id=self.table_id,
                    timestamp_ms=state.timestamp_ms,
                    details={
                        "from_street": self.prev_state.street,
                        "to_street": state.street,
                    },
                )
            )
            # Fold Condition B: Street change with uncalled bet
            max_prev_bet = max((getattr(p, "current_bet", 0) for p in self.prev_state.players.values()), default=0)
            for sid in (0, 1, 2):
                prev_p = self.prev_state.players.get(sid)
                p_dict = self.current_hand["players"].get(sid)
                if prev_p and p_dict and not p_dict["folded"]:
                    if max_prev_bet > 0 and getattr(prev_p, "current_bet", 0) < max_prev_bet and (getattr(prev_p, "stack", 0) or 0) > 0:
                        p_dict["folded"] = True
                        p_dict["last_action"] = "FOLD"
                        self.current_hand["action_log"].append({
                            "time_str": self._format_time(state.timestamp_ms),
                            "street": self.prev_state.street,
                            "seat_id": sid,
                            "player_name": p_dict["name"],
                            "action": "FOLD",
                            "amount": 0,
                            "invested_total": p_dict["invested_total"],
                            "decision_sec": None,
                        })

            # Reset street bets for active players
            for p_dict in self.current_hand["players"].values():
                if not p_dict["folded"]:
                    p_dict["street_bet"] = 0

        # Fold Condition C: Hero fold during street (hero turn ended facing bet without calling)
        if not is_new_hand and self.prev_state.is_hero_turn and not state.is_hero_turn:
            max_opp = max((getattr(p, "current_bet", 0) for sid, p in self.prev_state.players.items() if sid != 0), default=0)
            hero_prev_bet = getattr(self.prev_state.players.get(0), "current_bet", 0)
            hero_curr_bet = getattr(state.players.get(0), "current_bet", 0)
            p0_dict = self.current_hand["players"].get(0)
            if (
                max_opp > hero_prev_bet
                and hero_curr_bet <= hero_prev_bet
                and state.street == self.prev_state.street
                and p0_dict
                and not p0_dict["folded"]
            ):
                p0_dict["folded"] = True
                p0_dict["last_action"] = "FOLD"
                self.current_hand["action_log"].append({
                    "time_str": self._format_time(state.timestamp_ms),
                    "street": state.street,
                    "seat_id": 0,
                    "player_name": p0_dict["name"],
                    "action": "FOLD",
                    "amount": 0,
                    "invested_total": p0_dict["invested_total"],
                    "decision_sec": None,
                })

        # Fold Condition A: Player explicitly folded or inactive
        for sid in (0, 1, 2):
            curr_p = state.players.get(sid)
            p_dict = self.current_hand["players"].get(sid)
            if curr_p and p_dict and not p_dict["folded"]:
                if (not getattr(curr_p, "is_active", True)) or getattr(curr_p, "status_text", "") == "FOLDED":
                    p_dict["folded"] = True
                    p_dict["last_action"] = "FOLD"
                    self.current_hand["action_log"].append({
                        "time_str": self._format_time(state.timestamp_ms),
                        "street": state.street,
                        "seat_id": sid,
                        "player_name": p_dict["name"],
                        "action": "FOLD",
                        "amount": 0,
                        "invested_total": p_dict["invested_total"],
                        "decision_sec": None,
                    })

        # Track mid-street bet increases and measure reaction time (Timing Tells)
        for seat_id in (0, 1, 2):
            if seat_id in state.players and seat_id in self.prev_state.players:
                curr_p = state.players[seat_id]
                prev_p = self.prev_state.players[seat_id]
                p_dict = self.current_hand["players"].get(seat_id)
                if p_dict:
                    if curr_p.stack is not None:
                        p_dict["stack"] = curr_p.stack
                    p_dict["is_dealer"] = curr_p.is_dealer

                    if curr_p.current_bet > p_dict["street_bet"]:
                        delta = curr_p.current_bet - p_dict["street_bet"]
                        p_dict["invested_total"] += delta
                        p_dict["street_bet"] = curr_p.current_bet

                        base_time = (
                            self.last_state_change_ms
                            if self.last_state_change_ms is not None
                            else state.timestamp_ms
                        )
                        reaction_ms = max(0, state.timestamp_ms - base_time)
                        curr_p.last_reaction_ms = reaction_ms
                        self.last_state_change_ms = state.timestamp_ms

                        decision_sec = round(reaction_ms / 1000.0, 1)
                        p_dict["last_decision_sec"] = decision_sec

                        max_other_bet = max(
                            (other["street_bet"] for oid, other in self.current_hand["players"].items() if oid != seat_id),
                            default=0,
                        )
                        if curr_p.stack == 0 or getattr(curr_p, "status_text", "") == "ALL_IN":
                            act_name = "ALL-IN"
                        elif curr_p.current_bet == max_other_bet:
                            act_name = "CALL"
                        elif max_other_bet == 0:
                            act_name = "BET"
                        else:
                            act_name = "RAISE"

                        p_dict["last_action"] = f"{act_name} {curr_p.current_bet}"
                        self.current_hand["action_log"].append({
                            "time_str": self._format_time(state.timestamp_ms),
                            "street": state.street,
                            "seat_id": seat_id,
                            "player_name": p_dict["name"],
                            "action": act_name,
                            "amount": curr_p.current_bet,
                            "invested_total": p_dict["invested_total"],
                            "decision_sec": decision_sec,
                        })

                        if seat_id in (1, 2):
                            events.append(
                                GameEvent(
                                    event_type="VILLAIN_ACTION",
                                    table_id=self.table_id,
                                    timestamp_ms=state.timestamp_ms,
                                    details={
                                        "seat_id": seat_id,
                                        "bet_delta": delta,
                                        "reaction_ms": curr_p.last_reaction_ms,
                                    },
                                )
                            )
                    elif not is_new_hand and curr_p.last_reaction_ms is None and prev_p.last_reaction_ms is not None:
                        curr_p.last_reaction_ms = prev_p.last_reaction_ms

        # Detect HERO_TURN
        if state.is_hero_turn and not self.prev_state.is_hero_turn:
            self.last_state_change_ms = state.timestamp_ms
            events.append(
                GameEvent(
                    event_type="HERO_TURN",
                    table_id=self.table_id,
                    timestamp_ms=state.timestamp_ms,
                    details={"available_actions": list(state.available_actions)},
                )
            )

        self.prev_state = state
        return state, events
