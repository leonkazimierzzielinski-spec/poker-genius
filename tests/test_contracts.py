"""Unit tests for core contracts and constants."""

from core.constants import (
    BLIND_LEVELS,
    CARD_MATCH_THRESHOLD,
    EV_LOSS_THRESHOLD_BB,
    RANKS,
    STARTING_STACK,
    SUITS,
    TOTAL_CHIPS,
    VALID_ACTIONS,
    VALID_PROFILES,
    VALID_STREETS,
)
from core.contracts import Decision, PlayerState, TableState


def test_constants():
    """Verify core domain constants match CONSTITUTION.md."""
    assert TOTAL_CHIPS == 900
    assert STARTING_STACK == 300
    assert len(BLIND_LEVELS) == 5
    assert BLIND_LEVELS[0] == (10, 20)
    assert BLIND_LEVELS[-1] == (40, 80)
    assert CARD_MATCH_THRESHOLD == 0.92
    assert EV_LOSS_THRESHOLD_BB == 0.08
    assert RANKS == "23456789TJQKA"
    assert SUITS == "cdhs"
    assert "PREFLOP" in VALID_STREETS
    assert "FLOP" in VALID_STREETS
    assert "FOLD" in VALID_ACTIONS
    assert "ALL_IN" in VALID_ACTIONS
    assert "LOOSE_CALLERS" in VALID_PROFILES
    assert "STANDARD_EXPLOIT" in VALID_PROFILES
    assert "HIGH_STEAL" in VALID_PROFILES


def test_player_state_defaults_and_to_dict():
    """Verify PlayerState defaults and to_dict serialization."""
    player = PlayerState(seat_id=0, stack=300)
    assert player.seat_id == 0
    assert player.stack == 300
    assert player.current_bet == 0
    assert player.is_dealer is False
    assert player.is_active is True
    assert player.status_text == "ACTIVE"
    assert player.last_reaction_ms is None

    p_dict = player.to_dict()
    assert isinstance(p_dict, dict)
    assert p_dict["seat_id"] == 0
    assert p_dict["stack"] == 300
    assert p_dict["current_bet"] == 0
    assert p_dict["is_dealer"] is False
    assert p_dict["is_active"] is True
    assert p_dict["status_text"] == "ACTIVE"
    assert p_dict["last_reaction_ms"] is None


def test_table_state_creation_and_to_dict():
    """Verify TableState creation and nested to_dict serialization."""
    players = {
        0: PlayerState(seat_id=0, stack=280, current_bet=20, is_active=True),
        1: PlayerState(seat_id=1, stack=290, current_bet=10, is_dealer=True),
        2: PlayerState(seat_id=2, stack=300, current_bet=0, is_active=False),
    }
    table = TableState(
        table_id="table_1",
        timestamp_ms=1700000000123,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Qh", "4h"],
        board_cards=["Qd", "Qs", "8d"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "CHECK", "BET"],
        players=players,
        is_valid=True,
    )

    assert table.table_id == "table_1"
    assert table.street == "FLOP"
    assert table.is_hero_turn is True
    assert table.is_valid is True

    t_dict = table.to_dict()
    assert isinstance(t_dict, dict)
    assert t_dict["table_id"] == "table_1"
    assert t_dict["hero_cards"] == ["Qh", "4h"]
    assert t_dict["board_cards"] == ["Qd", "Qs", "8d"]
    assert isinstance(t_dict["players"], dict)
    assert isinstance(t_dict["players"][0], dict)
    assert t_dict["players"][0]["stack"] == 280
    assert t_dict["players"][0]["current_bet"] == 20


def test_decision_creation_and_to_dict():
    """Verify Decision creation and to_dict serialization."""
    decision = Decision(
        table_id="table_1",
        action="CHECK",
        ev_bb=0.12,
        confidence=0.96,
        profile_used="STANDARD_EXPLOIT",
        reason="Timing Tell: fast check",
    )

    assert decision.action == "CHECK"
    assert decision.ev_bb == 0.12
    assert decision.confidence == 0.96

    d_dict = decision.to_dict()
    assert isinstance(d_dict, dict)
    assert d_dict["table_id"] == "table_1"
    assert d_dict["action"] == "CHECK"
    assert d_dict["ev_bb"] == 0.12
    assert d_dict["confidence"] == 0.96
    assert d_dict["profile_used"] == "STANDARD_EXPLOIT"
    assert d_dict["reason"] == "Timing Tell: fast check"
