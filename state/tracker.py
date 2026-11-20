"""State machine, hand tracking, and timing tells measurement."""

from dataclasses import dataclass, field
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
            self.prev_state.street in ("FLOP", "TURN", "RIVER", "WAITING_FOR_TURN")
            and state.street == "PREFLOP"
            and self.prev_state.street != "PREFLOP"
        )

        is_new_hand = hero_cards_changed or dealer_changed or street_reset

        if is_new_hand:
            self.hand_number += 1
            self.last_state_change_ms = state.timestamp_ms
            events.append(
                GameEvent(
                    event_type="NEW_HAND",
                    table_id=self.table_id,
                    timestamp_ms=state.timestamp_ms,
                    details={"hand_number": self.hand_number},
                )
            )

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

        # Detect VILLAIN_ACTION and measure reaction time (Timing Tells)
        for seat_id in (1, 2):
            if seat_id in state.players and seat_id in self.prev_state.players:
                curr_p = state.players[seat_id]
                prev_p = self.prev_state.players[seat_id]

                if curr_p.current_bet > prev_p.current_bet:
                    base_time = (
                        self.last_state_change_ms
                        if self.last_state_change_ms is not None
                        else state.timestamp_ms
                    )
                    reaction_ms = max(0, state.timestamp_ms - base_time)
                    curr_p.last_reaction_ms = reaction_ms
                    self.last_state_change_ms = state.timestamp_ms
                    events.append(
                        GameEvent(
                            event_type="VILLAIN_ACTION",
                            table_id=self.table_id,
                            timestamp_ms=state.timestamp_ms,
                            details={
                                "seat_id": seat_id,
                                "bet_delta": curr_p.current_bet - prev_p.current_bet,
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
