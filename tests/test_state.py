"""Unit tests for Module 3: State machine, validation, and session logging."""

import json
from pathlib import Path
import pytest

from core.contracts import Decision, PlayerState, TableState
from state.logger import SessionLogger
from state.tracker import GameEvent, TableTracker
from state.validator import StateValidator


def create_dummy_table_state(
    table_id: str = "table_1",
    timestamp_ms: int = 1000,
    pot: int = 60,
    stacks: tuple[int, int, int] = (300, 280, 260),
    bets: tuple[int, int, int] = (0, 0, 0),
    hero_cards: list[str] | None = None,
    board_cards: list[str] | None = None,
    street: str = "PREFLOP",
    blinds: tuple[int, int] = (10, 20),
    is_hero_turn: bool = False,
    is_valid: bool = False,
    dealer_seat: int = 0,
) -> TableState:
    """Helper to generate consistent TableState objects for tests."""
    return TableState(
        table_id=table_id,
        timestamp_ms=timestamp_ms,
        prize_pool=4,
        small_blind=blinds[0],
        big_blind=blinds[1],
        pot=pot,
        hero_cards=hero_cards if hero_cards is not None else ["Ah", "Kd"],
        board_cards=board_cards if board_cards is not None else [],
        street=street,
        is_hero_turn=is_hero_turn,
        available_actions=["FOLD", "CALL", "RAISE"] if is_hero_turn else [],
        players={
            0: PlayerState(
                seat_id=0,
                stack=stacks[0],
                current_bet=bets[0],
                is_dealer=(dealer_seat == 0),
            ),
            1: PlayerState(
                seat_id=1,
                stack=stacks[1],
                current_bet=bets[1],
                is_dealer=(dealer_seat == 1),
            ),
            2: PlayerState(
                seat_id=2,
                stack=stacks[2],
                current_bet=bets[2],
                is_dealer=(dealer_seat == 2),
            ),
        },
        is_valid=is_valid,
    )


def test_validator_valid_sum_900() -> None:
    """Test 1: Check that a valid hand (300 + 280 + 260 + pot 60 == 900) passes validation."""
    validator = StateValidator()
    state = create_dummy_table_state(
        pot=60,
        stacks=(300, 280, 260),
        bets=(0, 0, 0),
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        blinds=(10, 20),
    )

    is_valid, errors = validator.validate(state)
    assert is_valid is True
    assert errors == []

    marked_state = validator.validate_and_mark(state)
    assert marked_state.is_valid is True


def test_validator_invalid_sum() -> None:
    """Test 2: Check rejection of frame when total chips do not sum to 900 (e.g. 880)."""
    validator = StateValidator()
    # 300 + 270 + 250 + pot 60 = 880 != 900
    state = create_dummy_table_state(
        pot=60,
        stacks=(300, 270, 250),
        bets=(0, 0, 0),
    )

    is_valid, errors = validator.validate(state)
    assert is_valid is False
    assert any("Chip conservation failed" in e for e in errors)

    marked_state = validator.validate_and_mark(state)
    assert marked_state.is_valid is False


def test_validator_duplicate_cards() -> None:
    """Test 3: Check rejection of frame with duplicate cards (e.g. Qh in hero and on flop)."""
    validator = StateValidator()
    state = create_dummy_table_state(
        pot=60,
        stacks=(300, 280, 260),
        hero_cards=["Qh", "Kd"],
        board_cards=["Qh", "2c", "7s"],
        street="FLOP",
    )

    is_valid, errors = validator.validate(state)
    assert is_valid is False
    assert "Duplicate cards detected" in errors


def test_validator_blinds_monotonicity() -> None:
    """Test 4: Check rejection when blinds drop from (20, 40) to (10, 20)."""
    validator = StateValidator()

    # Initial frame with higher blinds (20, 40)
    state1 = create_dummy_table_state(
        table_id="table_test",
        pot=60,
        stacks=(300, 280, 260),
        blinds=(20, 40),
    )
    is_valid1, errors1 = validator.validate(state1)
    assert is_valid1 is True
    assert errors1 == []

    # Subsequent frame where blinds decreased to (10, 20)
    state2 = create_dummy_table_state(
        table_id="table_test",
        pot=60,
        stacks=(300, 280, 260),
        blinds=(10, 20),
    )
    is_valid2, errors2 = validator.validate(state2)
    assert is_valid2 is False
    assert any("Blinds decreased" in e for e in errors2)

    # After table reset, (10, 20) should be accepted again
    validator.reset_table("table_test")
    is_valid3, errors3 = validator.validate(state2)
    assert is_valid3 is True
    assert errors3 == []


def test_validator_missing_stack_and_negative_chips() -> None:
    """Check validation failures for missing stacks, negative stacks/bets, or invalid blinds."""
    validator = StateValidator()

    # Missing stack reading (None)
    state_missing = create_dummy_table_state()
    state_missing.players[1].stack = None
    is_valid, errors = validator.validate(state_missing)
    assert is_valid is False
    assert "Missing stack reading" in errors

    # Negative pot / chips
    state_neg = create_dummy_table_state(pot=-10)
    is_valid, errors = validator.validate(state_neg)
    assert is_valid is False
    assert "Negative chip value detected" in errors

    # Invalid blinds (sb <= 0 or bb <= sb)
    state_blinds = create_dummy_table_state(blinds=(0, 20))
    is_valid, errors = validator.validate(state_blinds)
    assert is_valid is False
    assert "Invalid blinds" in errors

    # Invalid card counts (e.g. 1 hero card, 1 board card)
    state_cards = create_dummy_table_state(hero_cards=["Ah"], board_cards=["Kd"])
    is_valid, errors = validator.validate(state_cards)
    assert is_valid is False
    assert "Invalid card count" in errors


def test_tracker_new_hand_street_and_timing() -> None:
    """Test 5: Simulate sequence of 3 frames (t=1000, t=1350, t=2000) and verify events and timing."""
    tracker = TableTracker(table_id="table_1")

    # Frame 1: t=1000, New hand, preflop
    state1 = create_dummy_table_state(
        timestamp_ms=1000,
        pot=30,
        stacks=(300, 290, 280),
        bets=(0, 10, 20),
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_valid=True,
    )
    st1, events1 = tracker.update(state1)
    assert len(events1) == 1
    assert events1[0].event_type == "NEW_HAND"
    assert events1[0].details["hand_number"] == 1
    assert tracker.last_state_change_ms == 1000

    # Frame 2: t=1350, Villain 1 raises (current_bet 10 -> 40), latency = 350 ms
    state2 = create_dummy_table_state(
        timestamp_ms=1350,
        pot=30,
        stacks=(300, 260, 280),
        bets=(0, 40, 20),
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_valid=True,
    )
    st2, events2 = tracker.update(state2)
    assert len(events2) == 1
    assert events2[0].event_type == "VILLAIN_ACTION"
    assert events2[0].details["seat_id"] == 1
    assert events2[0].details["bet_delta"] == 30
    assert events2[0].details["reaction_ms"] == 350
    assert st2.players[1].last_reaction_ms == 350
    assert tracker.last_state_change_ms == 1350

    # Frame 3: t=2000, Flop dealt
    state3 = create_dummy_table_state(
        timestamp_ms=2000,
        pot=90,
        stacks=(300, 260, 250),
        bets=(0, 0, 0),
        hero_cards=["Ah", "Kd"],
        board_cards=["Qc", "Jd", "2s"],
        street="FLOP",
        is_valid=True,
    )
    st3, events3 = tracker.update(state3)
    assert len(events3) == 1
    assert events3[0].event_type == "STREET_CHANGE"
    assert events3[0].details["from_street"] == "PREFLOP"
    assert events3[0].details["to_street"] == "FLOP"
    assert tracker.last_state_change_ms == 2000


def test_tracker_invalid_state_and_hero_turn() -> None:
    """Verify that invalid states are ignored and hero turn transition triggers HERO_TURN event."""
    tracker = TableTracker(table_id="table_turn")

    state1 = create_dummy_table_state(
        timestamp_ms=1000,
        is_hero_turn=False,
        is_valid=True,
    )
    _, events1 = tracker.update(state1)
    assert len(events1) == 1
    assert events1[0].event_type == "NEW_HAND"

    # Frame with is_valid=False should be ignored
    invalid_state = create_dummy_table_state(
        timestamp_ms=1200,
        is_hero_turn=True,
        is_valid=False,
    )
    _, events_invalid = tracker.update(invalid_state)
    assert events_invalid == []
    assert tracker.prev_state is state1  # Previous valid state retained

    # Frame with hero turn active
    hero_turn_state = create_dummy_table_state(
        timestamp_ms=1500,
        is_hero_turn=True,
        is_valid=True,
    )
    _, events_turn = tracker.update(hero_turn_state)
    assert any(e.event_type == "HERO_TURN" for e in events_turn)


def test_session_logger_jsonl(tmp_path: Path) -> None:
    """Test 6: Verify JSONL logging of TableState and Decision, parsing lines with json.loads()."""
    logger = SessionLogger(log_dir=tmp_path)

    state = create_dummy_table_state(is_valid=True)
    events = [
        GameEvent(
            event_type="NEW_HAND",
            table_id="table_1",
            timestamp_ms=1000,
            details={"hand_number": 1},
        )
    ]
    decision = Decision(
        table_id="table_1",
        action="CALL",
        ev_bb=0.45,
        confidence=0.95,
        profile_used="STANDARD_EXPLOIT",
        reason="Good pot odds",
    )

    logger.log_state(state, events=events)
    logger.log_decision(decision, latency_ms=15.42)
    logger.close()

    # Find written file in tmp_path
    log_files = list(tmp_path.glob("session_*.jsonl"))
    assert len(log_files) == 1
    log_file = log_files[0]

    with open(log_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 2

    # Parse and inspect line 1: state
    entry1 = json.loads(lines[0])
    assert entry1["type"] == "state"
    assert entry1["data"]["table_id"] == "table_1"
    assert len(entry1["events"]) == 1
    assert entry1["events"][0]["event_type"] == "NEW_HAND"

    # Parse and inspect line 2: decision
    entry2 = json.loads(lines[1])
    assert entry2["type"] == "decision"
    assert entry2["latency_ms"] == 15.42
    assert entry2["data"]["action"] == "CALL"
    assert entry2["data"]["profile_used"] == "STANDARD_EXPLOIT"


def test_session_logger_context_manager(tmp_path: Path) -> None:
    """Verify that SessionLogger works as a context manager and cleanly closes file."""
    with SessionLogger(log_dir=tmp_path) as logger:
        decision = Decision(
            table_id="table_2",
            action="ALL_IN",
            ev_bb=1.2,
            confidence=0.99,
            profile_used="HIGH_STEAL",
            reason="ICM shove",
        )
        logger.log_decision(decision, latency_ms=4.128)

    assert logger._file.closed is True


# ---------------------------------------------------------------------------
# Test 11: Heads-Up Mode (2 active players, 1 eliminated)
# ---------------------------------------------------------------------------
def test_validator_heads_up_valid_sum_900() -> None:
    """Verify that StateValidator accepts 1 eliminated player in Heads-Up when 2 remaining players sum to 900."""
    validator = StateValidator()

    # Seat 2 is eliminated (stack=None, current_bet=0, status_text='SIT_OUT')
    # Seat 0 (Hero): stack=500, current_bet=0
    # Seat 1: stack=320, current_bet=80
    # Pot: 0 -> Total = 500 + 320 + 80 = 900
    state_hu = TableState(
        table_id="table_hu",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=20,
        big_blind=40,
        pot=0,
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "RAISE"],
        players={
            0: PlayerState(seat_id=0, stack=500, current_bet=0, is_dealer=False, is_active=True),
            1: PlayerState(seat_id=1, stack=320, current_bet=80, is_dealer=True, is_active=True),
            2: PlayerState(seat_id=2, stack=None, current_bet=0, is_dealer=False, is_active=False, status_text="SIT_OUT"),
        },
        is_valid=False,
    )

    is_valid, errors = validator.validate(state_hu)
    assert is_valid is True
    assert errors == []

    # If the 2 remaining players do not sum to 900 (e.g. 500 + 300 = 800 != 900)
    state_hu_invalid = TableState(
        table_id="table_hu",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=20,
        big_blind=40,
        pot=0,
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "RAISE"],
        players={
            0: PlayerState(seat_id=0, stack=500, current_bet=0, is_dealer=False, is_active=True),
            1: PlayerState(seat_id=1, stack=300, current_bet=0, is_dealer=True, is_active=True),
            2: PlayerState(seat_id=2, stack=None, current_bet=0, is_dealer=False, is_active=False, status_text="SIT_OUT"),
        },
        is_valid=False,
    )

    is_valid2, errors2 = validator.validate(state_hu_invalid)
    assert is_valid2 is False
    assert "Missing stack reading" in errors2


def test_validator_all_in_stack_none_valid() -> None:
    """Verify that StateValidator accepts an All-In player with stack=None if total chips sum to 900."""
    validator = StateValidator()

    # Seat 0: stack=424, bet=20 (Hero)
    # Seat 1: stack=None, bet=166 (Villain All-In, OCR saw 'All-In' text)
    # Seat 2: stack=270, bet=20
    # Pot: 206 -> Total = 206 + 444 + 166 + 290 = 900
    state_all_in = TableState(
        table_id="table_allin",
        timestamp_ms=2000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=206,
        hero_cards=["Jc", "4d"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=424, current_bet=20, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=None, current_bet=166, is_dealer=False, is_active=True, status_text="ALL_IN"),
            2: PlayerState(seat_id=2, stack=270, current_bet=20, is_dealer=False, is_active=True),
        },
        is_valid=False,
    )

    is_valid, errors = validator.validate(state_all_in)
    assert is_valid is True
    assert errors == []

    # If chip sum fails to close to 900 (e.g. pot corrupted to 100)
    state_corrupted = TableState(
        table_id="table_allin",
        timestamp_ms=2000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=100,
        hero_cards=["Jc", "4d"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=424, current_bet=20, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=None, current_bet=166, is_dealer=False, is_active=True, status_text="ALL_IN"),
            2: PlayerState(seat_id=2, stack=270, current_bet=20, is_dealer=False, is_active=True),
        },
        is_valid=False,
    )
    is_valid_c, errors_c = validator.validate(state_corrupted)
    assert is_valid_c is False
    assert "Missing stack reading" in errors_c


def test_tracker_waiting_for_turn_to_preflop_no_fake_new_hand() -> None:
    """Verify that transition WAITING_FOR_TURN -> PREFLOP with same cards and dealer does NOT trigger NEW_HAND."""
    tracker = TableTracker(table_id="table_1")
    state_waiting = create_dummy_table_state(
        pot=30,
        stacks=(300, 290, 280),
        bets=(0, 10, 20),
        hero_cards=["Kh", "2s"],
        board_cards=[],
        dealer_seat=2,
        is_valid=True,
    )
    state_waiting.street = "WAITING_FOR_TURN"
    state_waiting.is_hero_turn = False

    _, events1 = tracker.update(state_waiting)
    assert tracker.hand_number == 1
    assert any(e.event_type == "NEW_HAND" for e in events1)

    # Now it becomes Hero's turn in the same hand on PREFLOP
    state_hero_turn = create_dummy_table_state(
        pot=30,
        stacks=(300, 290, 280),
        bets=(0, 10, 20),
        hero_cards=["Kh", "2s"],
        board_cards=[],
        dealer_seat=2,
        is_valid=True,
    )
    state_hero_turn.street = "PREFLOP"
    state_hero_turn.is_hero_turn = True

    _, events2 = tracker.update(state_hero_turn)
    # hand_number must NOT increment and NEW_HAND must NOT be generated
    assert tracker.hand_number == 1
    assert not any(e.event_type == "NEW_HAND" for e in events2)
    assert any(e.event_type == "HERO_TURN" for e in events2)


def test_validator_postflop_pot_missing_board_cards_rejected() -> None:
    """Verify that pot=218 with bets=0 and empty board is flagged as Missing board cards on postflop pot."""
    validator = StateValidator()
    state = create_dummy_table_state(
        pot=218,
        stacks=(232, 230, 220),
        bets=(0, 0, 0),
        hero_cards=["Kh", "2s"],
        board_cards=[],
        blinds=(10, 20),
    )
    is_valid, errors = validator.validate(state)
    assert is_valid is False
    assert "Missing board cards on postflop pot" in errors


def test_validator_two_players_all_in_pot_conservation() -> None:
    """Verify that StateValidator accepts 2 All-In players when chip conservation holds (e.g. frame 4757)."""
    validator = StateValidator()

    # Seat 0 (Hero): stack=218, bet=0
    # Seat 1: stack=None, bet=0, status_text='ALL_IN'
    # Seat 2: stack=0, bet=64, status_text='ALL_IN'
    # Pot: 682 -> Total pot + stacks = 682 + 218 + 0 = 900
    state = TableState(
        table_id="table_4757",
        timestamp_ms=3000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=682,
        hero_cards=["7s", "7d"],
        board_cards=["Qc", "7c", "7h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "BET"],
        players={
            0: PlayerState(seat_id=0, stack=218, current_bet=0, is_dealer=False, is_active=True),
            1: PlayerState(seat_id=1, stack=None, current_bet=0, is_dealer=True, is_active=True, status_text="ALL_IN"),
            2: PlayerState(seat_id=2, stack=0, current_bet=64, is_dealer=False, is_active=True, status_text="ALL_IN"),
        },
        is_valid=False,
    )

    is_valid, errors = validator.validate(state)
    assert is_valid is True
    assert errors == []


def test_tracker_hand_summary_invested_time_and_fold() -> None:
    """Verify TableTracker hand tracking: invested_total accumulation, decision timing, and fold detection."""
    tracker = TableTracker("table_test")

    # Frame 1: Initial Preflop state with blinds posted
    # S1 (SB): bet 10, stack 290
    # S0 (BB / Hero): bet 20, stack 280
    # S2 (BTN): bet 0, stack 300, dealer=True
    st1 = TableState(
        table_id="table_test",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah", "Kh"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=280, current_bet=20, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False),
            2: PlayerState(seat_id=2, stack=300, current_bet=0, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st1)
    summary1 = tracker.get_hand_summary()
    assert summary1["players"][0]["invested_total"] == 20
    assert summary1["players"][1]["invested_total"] == 10
    assert summary1["players"][2]["invested_total"] == 0
    assert summary1["players"][0]["folded"] is False

    # Frame 2: BTN (S2) raises to 40 at t=2800 (reaction 1.8s)
    st2 = TableState(
        table_id="table_test",
        timestamp_ms=2800,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=70,
        hero_cards=["Ah", "Kh"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=280, current_bet=20, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False),
            2: PlayerState(seat_id=2, stack=260, current_bet=40, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st2)
    summary2 = tracker.get_hand_summary()
    assert summary2["players"][2]["invested_total"] == 40
    assert summary2["players"][2]["last_decision_sec"] == 1.8
    assert "RAISE" in summary2["players"][2]["last_action"] or "BET" in summary2["players"][2]["last_action"]

    # Frame 3: SB (S1) folds (Condition A), Hero (S0) turn begins facing bet 40
    st3 = TableState(
        table_id="table_test",
        timestamp_ms=3500,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=70,
        hero_cards=["Ah", "Kh"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "RAISE"],
        players={
            0: PlayerState(seat_id=0, stack=280, current_bet=20, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False, is_active=False, status_text="FOLDED"),
            2: PlayerState(seat_id=2, stack=260, current_bet=40, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st3)
    summary3 = tracker.get_hand_summary()
    assert summary3["players"][1]["folded"] is True
    assert summary3["players"][1]["last_action"] == "FOLD"

    # Frame 4: Hero (S0) calls 40 (bet rises from 20 to 40)
    st4 = TableState(
        table_id="table_test",
        timestamp_ms=4500,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=90,
        hero_cards=["Ah", "Kh"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=40, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False, is_active=False, status_text="FOLDED"),
            2: PlayerState(seat_id=2, stack=260, current_bet=40, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st4)
    summary4 = tracker.get_hand_summary()
    assert summary4["players"][0]["invested_total"] == 40
    assert summary4["players"][0]["folded"] is False

    # Frame 5: Street change to FLOP -> street_bet resets to 0, board cards appear
    st5 = TableState(
        table_id="table_test",
        timestamp_ms=5000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=90,
        hero_cards=["Ah", "Kh"],
        board_cards=["Qc", "Jd", "2s"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CHECK", "BET"],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=0, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=0, is_dealer=False, is_active=False, status_text="FOLDED"),
            2: PlayerState(seat_id=2, stack=260, current_bet=0, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st5)
    summary5 = tracker.get_hand_summary()
    assert summary5["street"] == "FLOP"
    assert summary5["players"][0]["street_bet"] == 0
    assert summary5["players"][2]["street_bet"] == 0
    # Total invested from preflop persists!
    assert summary5["players"][0]["invested_total"] == 40
    assert summary5["players"][2]["invested_total"] == 40

    # Frame 6: S2 bets 60 on Flop at t=6200
    st6 = TableState(
        table_id="table_test",
        timestamp_ms=6200,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=150,
        hero_cards=["Ah", "Kh"],
        board_cards=["Qc", "Jd", "2s"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "RAISE"],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=0, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=0, is_dealer=False, is_active=False, status_text="FOLDED"),
            2: PlayerState(seat_id=2, stack=200, current_bet=60, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st6)
    summary6 = tracker.get_hand_summary()
    # S2 invested_total accumulated: 40 (preflop) + 60 (flop) = 100!
    assert summary6["players"][2]["invested_total"] == 100

    # Frame 7: Hero folds (Condition C: was facing bet 60, hero turn ends without calling)
    st7 = TableState(
        table_id="table_test",
        timestamp_ms=7000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=150,
        hero_cards=["Ah", "Kh"],
        board_cards=["Qc", "Jd", "2s"],
        street="FLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=0, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=0, is_dealer=False, is_active=False, status_text="FOLDED"),
            2: PlayerState(seat_id=2, stack=200, current_bet=60, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st7)
    summary7 = tracker.get_hand_summary()
    assert summary7["players"][0]["folded"] is True
    assert summary7["players"][0]["last_action"] == "FOLD"


def test_hand_history_recorder_jsonl_and_md(tmp_path) -> None:
    """Verify HandHistoryRecorder lazy creation, JSONL line emission, and readable Markdown formatting."""
    from state.hand_history import HandHistoryRecorder

    recorder = HandHistoryRecorder(output_dir=tmp_path / "histories")

    # Empty hand should be safely ignored
    recorder.record_hand({})
    assert len(list((tmp_path / "histories").glob("*.jsonl"))) == 0

    hand_summary = {
        "hand_number": 42,
        "table_id": "table_1",
        "start_ts_ms": 1700000000000,
        "blinds": (50, 100),
        "prize_pool": 6,
        "hero_cards": ["Ad", "Kd"],
        "board_cards": ["7d", "Td", "Th", "2h"],
        "street": "TURN",
        "pot": 665,
        "players": {
            0: {
                "seat_id": 0,
                "name": "Ty (S0)",
                "is_dealer": False,
                "stack": 235,
                "invested_total": 100,
                "street_bet": 0,
                "last_action": "CHECK",
                "last_decision_sec": 1.2,
                "folded": False,
            },
            1: {
                "seat_id": 1,
                "name": "Rywal 1 (S1)",
                "is_dealer": True,
                "stack": 0,
                "invested_total": 50,
                "street_bet": 0,
                "last_action": "FOLD",
                "last_decision_sec": None,
                "folded": True,
            },
            2: {
                "seat_id": 2,
                "name": "Rywal 2 (S2)",
                "is_dealer": False,
                "stack": 0,
                "invested_total": 565,
                "street_bet": 565,
                "last_action": "ALL-IN 565",
                "last_decision_sec": 1.8,
                "folded": False,
            },
        },
        "action_log": [
            {
                "time_str": "19:14:20",
                "street": "PREFLOP",
                "seat_id": 1,
                "player_name": "Rywal 1 (S1)",
                "action": "BLIND",
                "amount": 50,
                "invested_total": 50,
                "decision_sec": None,
            },
            {
                "time_str": "19:14:22",
                "street": "PREFLOP",
                "seat_id": 2,
                "player_name": "Rywal 2 (S2)",
                "action": "ALL-IN",
                "amount": 565,
                "invested_total": 565,
                "decision_sec": 1.8,
            },
        ],
        "recommendations": [
            {
                "street": "PREFLOP",
                "action": "CALL",
                "sizing_bb": None,
                "sizing_chips": 565,
                "ev_bb": 1.45,
                "reason": "Push/Fold +1.45 BB equity vs loose shove",
                "timestamp_ms": 1700000002000,
            }
        ],
    }

    recorder.record_hand(hand_summary)
    recorder.close()

    jsonl_files = list((tmp_path / "histories").glob("*.jsonl"))
    md_files = list((tmp_path / "histories").glob("*.md"))
    assert len(jsonl_files) == 1
    assert len(md_files) == 1

    # Verify JSONL content
    with open(jsonl_files[0], "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    parsed_json = json.loads(lines[0])
    assert parsed_json["hand_number"] == 42
    assert parsed_json["blinds"] == [50, 100]
    assert parsed_json["hero_cards"] == ["Ad", "Kd"]

    # Verify Markdown content
    with open(md_files[0], "r", encoding="utf-8") as f:
        md_text = f.read()
    assert "# Rozdanie #42" in md_text
    assert "Blinds 50/100" in md_text
    assert "Prize $6" in md_text
    assert "Ad Kd" in md_text
    assert "### Gracze" in md_text
    assert "Rywal 2 (S2)" in md_text
    assert "### Przebieg zagrań" in md_text
    assert "ALL-IN" in md_text
    assert "### Rekomendacje HUD" in md_text
    assert "Push/Fold +1.45 BB" in md_text



