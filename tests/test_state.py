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

    zip_files = list((tmp_path / "histories").glob("*.zip"))
    assert len(zip_files) == 1

    import zipfile

    with zipfile.ZipFile(zip_files[0], "r") as zf:
        namelist = zf.namelist()
        assert "history.jsonl" in namelist
        assert "history.md" in namelist

        jsonl_text = zf.read("history.jsonl").decode("utf-8")
        md_text = zf.read("history.md").decode("utf-8")

    lines = [line.strip() for line in jsonl_text.splitlines() if line.strip()]
    assert len(lines) == 1
    parsed_json = json.loads(lines[0])
    assert parsed_json["hand_number"] == 42
    assert parsed_json["blinds"] == [50, 100]
    assert parsed_json["hero_cards"] == ["Ad", "Kd"]

    # Verify Markdown content
    assert "# Rozdanie #42" in md_text
    assert "Blinds 50/100" in md_text
    assert "Prize $6" in md_text
    assert "Ad Kd" in md_text
    assert "### Gracze" in md_text
    assert "Rywal 2 (S2)" in md_text
    assert "### Przebieg zagrań" in md_text
    assert "ALL-IN" in md_text
    assert "### Rekomendacje HUD" in md_text or "Rekomendacje HUD" in md_text
    assert "Push/Fold +1.45 BB" in md_text


def test_tracker_no_false_new_hand_on_waiting_to_preflop_and_blinds_not_bets() -> None:
    """Verify that appearance of hero cards after WAITING_FOR_TURN does not trigger fake NEW_HAND,

    blinds are recorded as BLIND, and eliminated players become OUT.
    """
    from core.contracts import PlayerState, TableState
    from state.tracker import TableTracker

    tracker = TableTracker(table_id="tbl_live_1")

    # Frame 1: WAITING_FOR_TURN, no hero cards, blinds posted (SB=10, BB=20)
    s1 = TableState(
        table_id="tbl_live_1",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=[],
        board_cards=[],
        street="WAITING_FOR_TURN",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=300, current_bet=0, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=280, current_bet=20, is_dealer=False, is_active=True),
        },
        is_valid=True,
    )
    st, ev1 = tracker.update(s1)
    assert tracker.hand_number == 1
    assert len(ev1) == 1
    assert ev1[0].event_type == "NEW_HAND"

    # Frame 2: PREFLOP, hero cards received (e.g. Ah Kd), street changes or stays, same hand!
    s2 = TableState(
        table_id="tbl_live_1",
        timestamp_ms=1500,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "RAISE", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=300, current_bet=0, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=280, current_bet=20, is_dealer=False, is_active=True),
        },
        is_valid=True,
    )
    st, ev2 = tracker.update(s2)
    # MUST NOT trigger NEW_HAND!
    assert tracker.hand_number == 1
    new_hand_events = [e for e in ev2 if e.event_type == "NEW_HAND"]
    assert len(new_hand_events) == 0
    assert tracker.current_hand["hero_cards"] == ["Ah", "Kd"]

    # Verify actions in log are BLIND with decision_sec is None
    act_log = tracker.current_hand["action_log"]
    blind_acts = [a for a in act_log if a.get("action") == "BLIND"]
    assert len(blind_acts) >= 2
    for b in blind_acts:
        assert b["decision_sec"] is None

    # Frame 3: Player 2 gets eliminated (stack None, is_active False)
    s3 = TableState(
        table_id="tbl_live_1",
        timestamp_ms=2000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CALL", "RAISE", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=300, current_bet=0, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=None, current_bet=0, is_dealer=False, is_active=False),
        },
        is_valid=True,
    )
    st, ev3 = tracker.update(s3)
    p2 = tracker.current_hand["players"][2]
    assert p2["eliminated"] is True
    assert p2["status"] == "OUT"
    assert p2["last_action"] == "OUT"
    # Eliminated player should not add a FOLD action
    fold_acts_p2 = [a for a in tracker.current_hand["action_log"] if a.get("seat_id") == 2 and a.get("action") == "FOLD"]
    assert len(fold_acts_p2) == 0


def test_tracker_winner_delta_and_tournament_winner() -> None:
    """Verify hand winner stack delta calculation and tournament_result when player stack >= 880."""
    from core.contracts import PlayerState, TableState
    from state.tracker import TableTracker

    tracker = TableTracker(table_id="tbl_tourney")

    # Hand 1 start
    s1 = TableState(
        table_id="tbl_tourney",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["As", "Ks"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=290, current_bet=10, is_dealer=False, is_active=True),
            1: PlayerState(seat_id=1, stack=280, current_bet=20, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=300, current_bet=0, is_dealer=True, is_active=True),
        },
        is_valid=True,
    )
    tracker.update(s1)
    assert tracker.hand_number == 1

    # Hand 2 start: dealer moves to S0, Hero won the 30 pot: Hero stack is 320, S1 280, S2 290
    s2 = TableState(
        table_id="tbl_tourney",
        timestamp_ms=5000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["7c", "8c"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=320, current_bet=0, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=270, current_bet=10, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=270, current_bet=20, is_dealer=False, is_active=True),
        },
        is_valid=True,
    )
    tracker.update(s2)
    assert tracker.hand_number == 2
    assert tracker.last_completed_hand is not None
    res = tracker.last_completed_hand.get("result")
    assert res is not None
    assert res["winner_seat"] == 0
    assert "Ty (S0)" in res["winner_name"]
    assert res["net_delta"] == 20  # Hero invested 10, won pot (start_tot=300, end_tot=320 -> +20)

    # In Hand 2, Hero stacks both opponents, reaching stack 890 (>= 880)
    s3 = TableState(
        table_id="tbl_tourney",
        timestamp_ms=8000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=0,
        hero_cards=["7c", "8c"],
        board_cards=["7d", "8h", "2s", "Qc", "Kd"],
        street="RIVER",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=890, current_bet=0, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=10, current_bet=0, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=0, current_bet=0, is_dealer=False, is_active=False),
        },
        is_valid=True,
    )
    tracker.update(s3)
    tr = tracker.current_hand.get("tournament_result")
    assert tr is not None
    assert tr["winner_seat"] == 0
    assert "Ty (S0)" in tr["winner_name"]
    assert tr["final_stack"] == 890
    assert tr["prize_pool"] == 6


def test_hand_history_per_game_zip_with_and_without_snapshots(tmp_path) -> None:
    """Verify that 2 separate games create 2 separate .zip packages,

    one with snapshots and one without, and cleans up working directory.
    """
    import zipfile
    import numpy as np
    from state.hand_history import HandHistoryRecorder

    output_dir = tmp_path / "hh_test"
    recorder = HandHistoryRecorder(output_dir=output_dir, save_snapshots=True, snapshot_width=640)

    # Game 1 on table_1 (with snapshots enabled)
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    rect = (100, 100, 600, 400)

    snap_path = recorder.save_snapshot(
        frame_bgr=dummy_frame,
        table_rect=rect,
        table_id="table_1",
        hand_number=1,
        event_label="decision_flop",
    )
    assert snap_path is not None
    assert snap_path == "snapshots/h001_decision_flop.jpg"

    h1 = {
        "hand_number": 1,
        "table_id": "table_1",
        "start_ts_ms": 1700000000000,
        "blinds": (10, 20),
        "prize_pool": 4,
        "hero_cards": ["Ah", "Kd"],
        "board_cards": ["Jh", "Th", "2c"],
        "street": "FLOP",
        "pot": 60,
        "players": {
            0: {"seat_id": 0, "name": "Ty (S0)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
            1: {"seat_id": 1, "name": "Rywal 1 (S1)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
        },
        "action_log": [{"time_str": "12:00:00", "street": "PREFLOP", "seat_id": 1, "action": "BLIND", "amount": 20}],
        "recommendations": [{"street": "FLOP", "action": "BET_30", "sizing_bb": 1, "ev_bb": 0.8, "reason": "C-bet"}],
        "snapshots": [snap_path],
    }
    recorder.record_hand(h1)

    # Game 2 on table_2 (snapshots disabled)
    recorder.save_snapshots = False
    snap_path2 = recorder.save_snapshot(
        frame_bgr=dummy_frame,
        table_rect=rect,
        table_id="table_2",
        hand_number=1,
        event_label="decision_turn",
    )
    assert snap_path2 is None

    h2 = {
        "hand_number": 1,
        "table_id": "table_2",
        "start_ts_ms": 1700000005000,
        "blinds": (10, 20),
        "prize_pool": 10,
        "hero_cards": ["Qc", "Qd"],
        "board_cards": [],
        "street": "PREFLOP",
        "pot": 40,
        "players": {
            0: {"seat_id": 0, "name": "Ty (S0)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
            1: {"seat_id": 1, "name": "Rywal 1 (S1)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
        },
        "action_log": [{"time_str": "12:00:05", "street": "PREFLOP", "seat_id": 1, "action": "BLIND", "amount": 20}],
    }
    recorder.record_hand(h2)

    # Close and finalize both games into .zip packages
    created_zips = recorder.close()
    assert len(created_zips) == 2

    # Check zip 1 (table_1)
    zip_t1 = next(z for z in created_zips if "table_1" in z.name)
    assert "_prize4" in zip_t1.name
    with zipfile.ZipFile(zip_t1, "r") as zf:
        names = zf.namelist()
        assert "history.jsonl" in names
        assert "history.md" in names
        assert "snapshots/h001_decision_flop.jpg" in names

        # Verify image properties
        img_info = zf.getinfo("snapshots/h001_decision_flop.jpg")
        assert img_info.file_size < 60 * 1024  # Less than 60 KB

        import cv2
        img_bytes = zf.read("snapshots/h001_decision_flop.jpg")
        img_arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        assert img_arr.shape[1] == 640  # Exactly 640px wide

    # Check zip 2 (table_2)
    zip_t2 = next(z for z in created_zips if "table_2" in z.name)
    assert "_prize10" in zip_t2.name
    with zipfile.ZipFile(zip_t2, "r") as zf:
        names = zf.namelist()
        assert "history.jsonl" in names
        assert "history.md" in names
        assert not any("snapshots" in n for n in names)

    # Working _active directory should be cleaned up
    active_dir = output_dir / "_active"
    assert not active_dir.exists()


def test_tracker_no_false_tournament_end_on_two_opponents_all_in() -> None:
    """Verify that when 2 opponents are All-In with stack=0 but pot > 0, tournament_result is NOT triggered."""
    tracker = TableTracker("table_1")

    # S0=100 (Hero), S1=0 (All-in), S2=0 (All-in), pot=800 on Flop
    st1 = TableState(
        table_id="table_1",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=800,
        hero_cards=["Kh", "Qh"],
        board_cards=["Ah", "7c", "2d"],
        street="FLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=100, current_bet=0, is_dealer=True, is_active=True),
            1: PlayerState(seat_id=1, stack=0, current_bet=400, is_dealer=False, is_active=True, status_text="ALL_IN"),
            2: PlayerState(seat_id=2, stack=0, current_bet=400, is_dealer=False, is_active=True, status_text="ALL_IN"),
        },
        is_valid=True,
    )
    tracker.update(st1)

    # pot is 800 > 0: tournament_result MUST be None
    assert tracker.current_hand.get("tournament_result") is None

    # Frame 2: River dealt, showdown resolved, pot collected (pot=0), S2 won stack 900
    st2 = TableState(
        table_id="table_1",
        timestamp_ms=3000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=0,
        hero_cards=["Kh", "Qh"],
        board_cards=["Ah", "7c", "2d", "8s", "Jh"],
        street="RIVER",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=0, current_bet=0, is_dealer=True, is_active=False),
            1: PlayerState(seat_id=1, stack=0, current_bet=0, is_dealer=False, is_active=False),
            2: PlayerState(seat_id=2, stack=900, current_bet=0, is_dealer=False, is_active=True),
        },
        is_valid=True,
    )
    tracker.update(st2)

    # Now pot=0 and S2 has stack >= 880: tournament_result is set
    tr = tracker.current_hand.get("tournament_result")
    assert tr is not None
    assert tr["winner_seat"] == 2
    assert tr["final_stack"] == 900


def test_tracker_waiting_for_turn_does_not_double_invested_or_false_fold() -> None:
    """Verify that street oscillating between WAITING_FOR_TURN and PREFLOP does not reset street_bet or double invested_total."""
    tracker = TableTracker("table_1")

    # Frame 1: Hero posts BB 20
    st1 = TableState(
        table_id="table_1",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ac", "Kd"],
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

    # Frame 2: Opponent raises to 40, Hero calls to 40
    st2 = TableState(
        table_id="table_1",
        timestamp_ms=2000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=90,
        hero_cards=["Ac", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=40, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False),
            2: PlayerState(seat_id=2, stack=260, current_bet=40, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st2)
    assert tracker.current_hand["players"][0]["invested_total"] == 40
    assert tracker.current_hand["players"][0]["folded"] is False

    # Frame 3: Street changes to WAITING_FOR_TURN with same board (empty) and same bets
    st3 = TableState(
        table_id="table_1",
        timestamp_ms=2500,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=90,
        hero_cards=["Ac", "Kd"],
        board_cards=[],
        street="WAITING_FOR_TURN",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=40, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False),
            2: PlayerState(seat_id=2, stack=260, current_bet=40, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st3)
    assert tracker.current_hand["players"][0]["invested_total"] == 40
    assert tracker.current_hand["players"][0]["folded"] is False

    # Frame 4: Street toggles back to PREFLOP
    st4 = TableState(
        table_id="table_1",
        timestamp_ms=3000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=90,
        hero_cards=["Ac", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=260, current_bet=40, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False),
            2: PlayerState(seat_id=2, stack=260, current_bet=40, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st4)

    # Invested total must stay strictly 40 (no double/triple accumulation) and no false fold!
    assert tracker.current_hand["players"][0]["invested_total"] == 40
    assert tracker.current_hand["players"][0]["folded"] is False


def test_tracker_ignores_sub_sb_ocr_glitch_and_stale_pot_sweep() -> None:
    """Verify filtering of sub-small_blind OCR animation glitches and start-of-hand pot sweep artifacts."""
    tracker = TableTracker("table_1")

    # Frame 1: Normal preflop with blinds 10/20
    st1 = TableState(
        table_id="table_1",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ac", "Kd"],
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

    # Frame 2: Seat 2 has OCR glitch current_bet=2 (< small_blind 10) with remaining stack 298
    st2 = TableState(
        table_id="table_1",
        timestamp_ms=1500,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=32,
        hero_cards=["Ac", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=280, current_bet=20, is_dealer=False),
            1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=False),
            2: PlayerState(seat_id=2, stack=298, current_bet=2, is_dealer=True),
        },
        is_valid=True,
    )
    tracker.update(st2)

    # The glitch bet of 2 should be completely ignored in action_log and invested_total
    assert tracker.current_hand["players"][2]["invested_total"] == 0
    assert not any(a.get("seat_id") == 2 for a in tracker.current_hand["action_log"])

    # Test stale pot sweep: new hand starting with no board cards and no hero cards, but bet=740 (> 2*BB)
    tracker2 = TableTracker("table_2")
    st_sweep = TableState(
        table_id="table_2",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=30,
        big_blind=60,
        pot=0,
        hero_cards=[],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=False,
        available_actions=[],
        players={
            0: PlayerState(seat_id=0, stack=160, current_bet=0, is_dealer=False),
            1: PlayerState(seat_id=1, stack=740, current_bet=740, is_dealer=False),
            2: PlayerState(seat_id=2, stack=0, current_bet=0, is_dealer=True),
        },
        is_valid=True,
    )
    tracker2.update(st_sweep)

    # 740 is a stale animation artifact and should be zeroed out
    assert tracker2.current_hand["mid_hand_join"] is False
    assert tracker2.current_hand["players"][1]["invested_total"] == 0
    assert not any("740" in a.get("action", "") or a.get("amount") == 740 for a in tracker2.current_hand["action_log"])


def test_hand_history_saves_both_zip_and_standalone_md_with_summary(tmp_path) -> None:
    """Verify finalize_game writes both .zip and companion .md with summary and deduplicates snapshots."""
    from state.hand_history import HandHistoryRecorder

    out_dir = tmp_path / "hh_dual_test"
    rec = HandHistoryRecorder(output_dir=out_dir, save_snapshots=True)

    hand = {
        "hand_number": 1,
        "table_id": "table_1",
        "start_ts_ms": 1700000000000,
        "blinds": (10, 20),
        "prize_pool": 6,
        "hero_cards": ["Ah", "Kd"],
        "board_cards": ["Jh", "Th", "2c"],
        "street": "FLOP",
        "pot": 60,
        "players": {
            0: {"seat_id": 0, "name": "Ty (S0)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
            1: {"seat_id": 1, "name": "Rywal 1 (S1)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
        },
        "action_log": [{"time_str": "12:00:00", "street": "PREFLOP", "seat_id": 1, "action": "BLIND", "amount": 20}],
        "recommendations": [
            {"street": "FLOP", "action": "CHECK", "sizing_bb": None, "ev_bb": 0.5, "reason": "[PLAN] Preview check"},
            {"street": "FLOP", "action": "BET_30", "sizing_bb": 1, "ev_bb": 1.2, "reason": "Value bet"},
        ],
        "snapshots": ["snapshots/h001_decision_flop.jpg", "snapshots/h001_decision_flop.jpg"],
        "tournament_result": {
            "winner_seat": 0,
            "winner_name": "Ty (S0)",
            "prize_pool": 6,
            "final_stack": 900,
        },
    }
    rec.record_hand(hand)

    zip_path = rec.finalize_game("table_1", prize_pool=6)
    assert zip_path is not None
    assert zip_path.exists()

    # Standalone .md must exist right next to the .zip
    md_path = zip_path.with_suffix(".md")
    assert md_path.exists()

    content = md_path.read_text(encoding="utf-8")
    assert "## 📊 Podsumowanie gry" in content
    assert "- **Liczba rozdań**: 1" in content
    assert "- **Pula nagród**: $6" in content
    assert "- **Zwycięzca turnieju**: Ty (S0) (S0)" in content
    assert "- **Decyzje HUD (Hero)**: 1" in content  # Excludes [PLAN]!

    # Snapshots must be deduplicated (only 1 occurrence)
    assert content.count("![snapshots/h001_decision_flop.jpg](snapshots/h001_decision_flop.jpg)") == 1


def test_tracker_3_frame_debounce_ignores_single_frame_ts_glitch_on_postflop() -> None:
    """Verify that a 1-frame OCR card glitch (e.g. 5h 5d -> 5h Ts -> 5h 5d) on postflop does NOT trigger NEW_HAND."""
    tracker = TableTracker(table_id="t1")

    base_players = {
        0: PlayerState(seat_id=0, stack=280, current_bet=0, is_dealer=False),
        1: PlayerState(seat_id=1, stack=280, current_bet=0, is_dealer=True),
    }

    # Frame 1: Flop with real hero cards [5h, 5d]
    f1 = TableState(
        table_id="t1",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=40,
        hero_cards=["5h", "5d"],
        board_cards=["7c", "8d", "2h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CHECK", "BET_30"],
        players=base_players,
        is_valid=True,
    )
    _, events1 = tracker.update(f1)
    ev_types1 = [e.event_type for e in events1]
    assert "NEW_HAND" in ev_types1
    assert tracker.hand_number == 1
    assert tracker.current_hand["hero_cards"] == ["5h", "5d"]

    # Frame 2: 1-frame glitch: hero cards misread as [5h, Ts] on FLOP (same dealer, same board)
    f2 = TableState(
        table_id="t1",
        timestamp_ms=1200,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=40,
        hero_cards=["5h", "Ts"],
        board_cards=["7c", "8d", "2h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CHECK", "BET_30"],
        players=base_players,
        is_valid=True,
    )
    _, events2 = tracker.update(f2)
    ev_types2 = [e.event_type for e in events2]
    assert "NEW_HAND" not in ev_types2, "1-frame Ts glitch on postflop must NOT trigger NEW_HAND"
    assert tracker.hand_number == 1
    assert tracker.current_hand["hero_cards"] == ["5h", "5d"]

    # Frame 3: Normal frame again with [5h, 5d]
    f3 = TableState(
        table_id="t1",
        timestamp_ms=1400,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=40,
        hero_cards=["5h", "5d"],
        board_cards=["7c", "8d", "2h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CHECK", "BET_30"],
        players=base_players,
        is_valid=True,
    )
    _, events3 = tracker.update(f3)
    ev_types3 = [e.event_type for e in events3]
    assert "NEW_HAND" not in ev_types3
    assert tracker.hand_number == 1


def test_hand_history_preserves_nonzero_prize_pool_on_finalize(tmp_path) -> None:
    """Verify that finalize_game with prize_pool=0 or None preserves existing recorded prize_pool > 0."""
    from state.hand_history import HandHistoryRecorder

    out_dir = tmp_path / "hh_prize_preserve"
    rec = HandHistoryRecorder(output_dir=out_dir, save_snapshots=False)

    hand = {
        "hand_number": 1,
        "table_id": "table_1",
        "start_ts_ms": 1700000000000,
        "blinds": (10, 20),
        "prize_pool": 4,
        "hero_cards": ["Ah", "Kd"],
        "board_cards": ["Jh", "Th", "2c"],
        "street": "FLOP",
        "pot": 60,
        "players": {
            0: {"seat_id": 0, "name": "Ty (S0)", "stack": 280, "invested_total": 20, "is_dealer": False, "folded": False},
        },
        "action_log": [{"time_str": "12:00:00", "street": "PREFLOP", "seat_id": 0, "action": "BLIND", "amount": 20}],
    }
    rec.record_hand(hand)

    # Finalize with prize_pool=0 (e.g. from end of tournament frame where prize was obscured or 0)
    zip_path = rec.finalize_game("table_1", prize_pool=0)
    assert zip_path is not None
    assert "_prize4.zip" in zip_path.name, f"Expected _prize4.zip in filename, got {zip_path.name}"
    assert "_prize0" not in zip_path.name

    md_path = zip_path.with_suffix(".md")
    assert md_path.exists()
    assert "_prize4.md" in md_path.name
    content = md_path.read_text(encoding="utf-8")
    assert "- **Pula nagród**: $4" in content


def test_export_games_md_combines_multiple_games(tmp_path) -> None:
    """Verify that export_all_games_md reads multiple game .md files and produces ALL_GAMES_REPORT.md."""
    from tools.export_games_md import export_all_games_md

    hh_dir = tmp_path / "hand_histories"
    hh_dir.mkdir(parents=True)

    g1_text = """# Rozdanie #1 (12:00:00) — Blinds 10/20 | Prize $4
## 📊 Podsumowanie gry
- **Liczba rozdań**: 5
- **Pula nagród**: $4
- **Zwycięzca turnieju**: Ty (S0)
- **Decyzje HUD (Hero)**: 8
"""
    g2_text = """# Rozdanie #1 (12:10:00) — Blinds 10/20 | Prize $6
## 📊 Podsumowanie gry
- **Liczba rozdań**: 7
- **Pula nagród**: $6
- **Zwycięzca turnieju**: Rywal 1 (S1)
- **Decyzje HUD (Hero)**: 12
"""
    (hh_dir / "game_20261121_120000_table_1_prize4.md").write_text(g1_text, encoding="utf-8")
    (hh_dir / "game_20261121_121000_table_1_prize6.md").write_text(g2_text, encoding="utf-8")

    out_file = export_all_games_md(input_dir=hh_dir)
    assert out_file.exists()
    assert out_file.name == "ALL_GAMES_REPORT.md"

    report_text = out_file.read_text(encoding="utf-8")
    assert "- **Liczba rozegranych gier**: 2" in report_text
    assert "- **Łączna liczba rozdań**: 12" in report_text
    assert "- **Łączna liczba decyzji HUD (Hero)**: 20" in report_text
    assert "game_20261121_120000_table_1_prize4.md" in report_text
    assert "game_20261121_121000_table_1_prize6.md" in report_text






