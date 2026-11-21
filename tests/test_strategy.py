"""Unit tests for Module 5 (strategy: exploitation and simplification layer)."""

from types import SimpleNamespace
import pytest

from strategy.multiplier_adapter import MultiplierAdapter, ProfileModifiers
from strategy.exploit import ExploitEngine
from strategy.simplifier import StrategySimplifier
from strategy.decision_maker import DecisionMaker


def test_multiplier_adapter_profiles():
    """Verify profiles for prize pools 4, 6, 8, 10, and 20."""
    adapter = MultiplierAdapter()

    # Prize pool 4 (2x) -> LOOSE_CALLERS
    p4 = adapter.get_modifiers(prize_pool=4, buy_in=2)
    assert p4.profile_name == "LOOSE_CALLERS"
    assert p4.bluff_factor == pytest.approx(0.70)
    assert p4.value_shove_boost_bb == pytest.approx(0.10)
    assert p4.prefer_high_variance_borderline is True
    assert p4.use_icm is False

    # Prize pool 6 (3x) -> STANDARD_EXPLOIT
    p6 = adapter.get_modifiers(prize_pool=6, buy_in=2)
    assert p6.profile_name == "STANDARD_EXPLOIT"
    assert p6.bluff_factor == pytest.approx(1.0)
    assert p6.steal_boost_bb == pytest.approx(0.0)
    assert p6.value_shove_boost_bb == pytest.approx(0.0)
    assert p6.prefer_high_variance_borderline is False
    assert p6.use_icm is False

    # Prize pool 8 (4x) -> STANDARD_EXPLOIT
    p8 = adapter.get_modifiers(prize_pool=8, buy_in=2)
    assert p8.profile_name == "STANDARD_EXPLOIT"
    assert p8.prefer_high_variance_borderline is False

    # Prize pool 10 (5x) -> HIGH_STEAL
    p10 = adapter.get_modifiers(prize_pool=10, buy_in=2)
    assert p10.profile_name == "HIGH_STEAL"
    assert p10.bluff_factor == pytest.approx(1.10)
    assert p10.steal_boost_bb == pytest.approx(0.15)
    assert p10.use_icm is True

    # Prize pool 20 (10x) -> HIGH_STEAL
    p20 = adapter.get_modifiers(prize_pool=20, buy_in=2)
    assert p20.profile_name == "HIGH_STEAL"
    assert p20.bluff_factor == pytest.approx(1.10)
    assert p20.steal_boost_bb == pytest.approx(0.15)
    assert p20.use_icm is True


def test_exploit_timing_tell_fast_check():
    """Simulate fast check (<500ms) and verify BET_30 boost and Timing Tell reason."""
    engine = ExploitEngine()
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT", bluff_factor=1.0)

    # Opponent seat 1 checked in 250 ms
    state = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, is_active=True, last_reaction_ms=None),
            1: SimpleNamespace(seat_id=1, is_active=True, last_reaction_ms=250),
            2: SimpleNamespace(seat_id=2, is_active=True, last_reaction_ms=1200),
        },
        street="FLOP",
        big_blind=20,
    )

    candidate_evs = {"CHECK": 0.05, "BET_30": 0.10}
    adjusted_evs, reasons = engine.apply_exploits(candidate_evs, state, modifiers, spot="POSTFLOP")

    # Fast check bonus: 0.12 * 1.0 = 0.12 -> 0.10 + 0.12 = 0.22
    assert adjusted_evs["BET_30"] == pytest.approx(0.22)
    assert any("Timing Tell" in r for r in reasons)


def test_exploit_timing_tell_ignores_zero_ms_transition_artifact() -> None:
    """Verify that reaction times < 150 ms (0 ms or 50 ms transition artifacts) do NOT trigger timing tell."""
    engine = ExploitEngine()
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT", bluff_factor=1.0)

    # 1. Artifact reaction time = 0 ms (new street transition frame)
    state_0ms = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, is_active=True, last_reaction_ms=None),
            1: SimpleNamespace(seat_id=1, is_active=True, last_reaction_ms=0, current_bet=0),
            2: SimpleNamespace(seat_id=2, is_active=True, last_reaction_ms=1200, current_bet=0),
        },
        street="FLOP",
        big_blind=20,
    )
    candidate_evs = {"CHECK": 0.05, "BET_30": 0.10}
    evs_0, reasons_0 = engine.apply_exploits(candidate_evs.copy(), state_0ms, modifiers, spot="POSTFLOP")
    assert evs_0["BET_30"] == pytest.approx(0.10)
    assert not any("Timing Tell" in r for r in reasons_0)

    # 2. Artifact reaction time = 50 ms
    state_50ms = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, is_active=True, last_reaction_ms=None),
            1: SimpleNamespace(seat_id=1, is_active=True, last_reaction_ms=50, current_bet=0),
            2: SimpleNamespace(seat_id=2, is_active=True, last_reaction_ms=1200, current_bet=0),
        },
        street="FLOP",
        big_blind=20,
    )
    evs_50, reasons_50 = engine.apply_exploits(candidate_evs.copy(), state_50ms, modifiers, spot="POSTFLOP")
    assert evs_50["BET_30"] == pytest.approx(0.10)
    assert not any("Timing Tell" in r for r in reasons_50)

    # 3. Real fast check = 250 ms (triggers timing tell)
    state_250ms = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, is_active=True, last_reaction_ms=None),
            1: SimpleNamespace(seat_id=1, is_active=True, last_reaction_ms=250, current_bet=0),
            2: SimpleNamespace(seat_id=2, is_active=True, last_reaction_ms=1200, current_bet=0),
        },
        street="FLOP",
        big_blind=20,
    )
    evs_250, reasons_250 = engine.apply_exploits(candidate_evs.copy(), state_250ms, modifiers, spot="POSTFLOP")
    assert evs_250["BET_30"] == pytest.approx(0.22)
    assert any("Timing Tell: fast check <500ms" in r for r in reasons_250)


def test_exploit_sizing_tell_one_bb():
    """Simulate 1 BB weak bet on flop and verify ALL_IN boost and Sizing Tell reason."""
    engine = ExploitEngine()
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT", bluff_factor=1.0)

    # Opponent bet 1 BB (current_bet == big_blind) on FLOP
    state = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, is_active=True, current_bet=0),
            1: SimpleNamespace(seat_id=1, is_active=True, current_bet=20),
            2: SimpleNamespace(seat_id=2, is_active=False, current_bet=0),
        },
        street="FLOP",
        big_blind=20,
    )

    candidate_evs = {"FOLD": 0.0, "CALL": 0.10, "ALL_IN": 0.15}
    adjusted_evs, reasons = engine.apply_exploits(candidate_evs, state, modifiers, spot="POSTFLOP")

    # ALL_IN should get +0.15 -> 0.15 + 0.15 = 0.30
    assert adjusted_evs["ALL_IN"] == pytest.approx(0.30)
    assert any("Sizing Tell" in r for r in reasons)


def test_simplifier_ev_loss_threshold():
    """Verify that marginal actions below +0.08 BB are rejected in STANDARD_EXPLOIT."""
    simplifier = StrategySimplifier(ev_loss_threshold_bb=0.08)
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT", prefer_high_variance_borderline=False)

    candidate_evs = {"FOLD": 0.0, "CALL": 0.04}
    action, ev, note = simplifier.select_pure_action(candidate_evs, modifiers)

    assert action == "FOLD"
    assert ev == pytest.approx(0.0)
    assert note is not None
    assert "< +0.08 BB" in note


def test_simplifier_loose_callers_borderline():
    """Verify that borderline ~0 EV high-variance shoves are accepted in LOOSE_CALLERS."""
    simplifier = StrategySimplifier(ev_loss_threshold_bb=0.08)
    modifiers = ProfileModifiers(profile_name="LOOSE_CALLERS", prefer_high_variance_borderline=True)

    candidate_evs = {"FOLD": 0.0, "ALL_IN": 0.01}
    action, ev, note = simplifier.select_pure_action(candidate_evs, modifiers)

    assert action == "ALL_IN"
    assert ev == pytest.approx(0.01)
    assert note == "Borderline 0EV high-variance call/shove"


def test_exploit_bb_iso_vs_limp():
    """Verify MDA Iso-Shove bonus when spot is BB_ISO_VS_LIMP."""
    engine = ExploitEngine()
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT")
    state = SimpleNamespace(players={}, street="PREFLOP", big_blind=20)

    candidate_evs = {"CHECK": 0.0, "MIN_RAISE": 0.10, "ALL_IN": 0.20}
    adjusted_evs, reasons = engine.apply_exploits(candidate_evs, state, modifiers, spot="BB_ISO_VS_LIMP")

    assert adjusted_evs["ALL_IN"] == pytest.approx(0.30)
    assert any("MDA Iso-Shove" in r for r in reasons)


def test_exploit_high_steal_boost():
    """Verify preflop steal boost in HIGH_STEAL profile."""
    engine = ExploitEngine()
    modifiers = ProfileModifiers(profile_name="HIGH_STEAL", steal_boost_bb=0.15)
    state = SimpleNamespace(players={}, street="PREFLOP", big_blind=20)

    candidate_evs = {"FOLD": 0.0, "MIN_RAISE": 0.10, "ALL_IN": 0.05}
    adjusted_evs, reasons = engine.apply_exploits(candidate_evs, state, modifiers, spot="BTN_OPEN")

    assert adjusted_evs["MIN_RAISE"] == pytest.approx(0.25)
    assert adjusted_evs["ALL_IN"] == pytest.approx(0.20)
    assert any("High Steal" in r for r in reasons)


def test_simplifier_available_actions_filtering():
    """Verify simplifier respects available table actions."""
    simplifier = StrategySimplifier(ev_loss_threshold_bb=0.08)
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT")

    # Table allows only FOLD and CALL (facing a bet)
    candidate_evs = {"CHECK": 0.50, "CALL": 0.20, "FOLD": 0.0}
    action, ev, _ = simplifier.select_pure_action(
        candidate_evs,
        modifiers,
        available_actions=["FOLD", "CALL"],
    )
    assert action == "CALL"
    assert ev == pytest.approx(0.20)


def test_decision_maker_waiting_state():
    """Verify DecisionMaker returns WAIT when Hero is not to act or state invalid."""
    dm = DecisionMaker()

    # Hero not to act
    state_not_hero = SimpleNamespace(
        table_id="table_1",
        is_valid=True,
        is_hero_turn=False,
        street="FLOP",
    )
    decision = dm.decide(state_not_hero, {"CHECK": 0.1})
    assert decision.action == "WAIT"
    assert decision.ev_bb is None

    # Invalid state
    state_invalid = SimpleNamespace(
        table_id="table_1",
        is_valid=False,
        is_hero_turn=True,
        street="FLOP",
    )
    decision_invalid = dm.decide(state_invalid, {"CHECK": 0.1})
    assert decision_invalid.action == "WAIT"

    # Waiting for turn street
    state_waiting = SimpleNamespace(
        table_id="table_1",
        is_valid=True,
        is_hero_turn=True,
        street="WAITING_FOR_TURN",
    )
    decision_waiting = dm.decide(state_waiting, {"CHECK": 0.1})
    assert decision_waiting.action == "WAIT"


def test_decision_maker_with_contracts():
    """Verify integration of DecisionMaker with real TableState and PlayerState contracts."""
    pytest.importorskip("core.contracts")
    from core.contracts import PlayerState, TableState, Decision

    state = TableState(
        table_id="tbl_spin_1",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah", "Ks"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=290, current_bet=10, is_dealer=False, is_active=True),
            1: PlayerState(seat_id=1, stack=280, current_bet=20, is_dealer=False, is_active=True),
            2: PlayerState(seat_id=2, stack=300, current_bet=0, is_dealer=True, is_active=True),
        },
        is_valid=True,
    )

    dm = DecisionMaker(buy_in=2)
    decision = dm.decide(
        state=state,
        candidate_evs={"FOLD": 0.0, "ALL_IN": 0.50},
        spot="SB_OPEN",
    )

    assert isinstance(decision, Decision)
    assert decision.table_id == "tbl_spin_1"
    assert decision.action == "ALL_IN"
    assert decision.profile_used == "LOOSE_CALLERS"
    assert decision.ev_bb is not None
    assert decision.ev_bb > 0.50  # Value shove boost (+0.10) applied
    assert decision.confidence == 0.95


def test_hero_cards_incomplete_returns_wait() -> None:
    """Verify that if hero has fewer or more than 2 cards, DecisionMaker strictly returns WAIT."""
    dm = DecisionMaker(buy_in=2)

    # 1 card
    st1 = SimpleNamespace(
        table_id="tbl_1",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah"],
        board_cards=[],
        is_hero_turn=True,
        street="PREFLOP",
        is_valid=True,
    )
    dec1 = dm.decide(st1, {"ALL_IN": 2.5, "FOLD": 0.0}, spot="BTN_OPEN")
    assert dec1.action == "WAIT"
    assert "Incomplete hero cards" in dec1.reason
    assert dec1.ev_bb is None

    # 0 cards
    st0 = SimpleNamespace(
        table_id="tbl_1",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=[],
        board_cards=[],
        is_hero_turn=True,
        street="PREFLOP",
        is_valid=True,
    )
    dec0 = dm.decide(st0, {"ALL_IN": 2.5, "FOLD": 0.0}, spot="BTN_OPEN")
    assert dec0.action == "WAIT"
    assert "Incomplete hero cards" in dec0.reason


def test_decision_maker_preview_mode() -> None:
    """Verify that allow_preview=True generates [PLAN] recommendations outside Hero turn, while default returns WAIT."""
    dm = DecisionMaker(buy_in=2)

    st_outside_turn = SimpleNamespace(
        table_id="tbl_preview",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        is_hero_turn=False,
        street="WAITING_FOR_TURN",
        is_valid=True,
    )

    # Default allow_preview=False strictly returns WAIT
    dec_default = dm.decide(st_outside_turn, {"ALL_IN": 1.5, "FOLD": 0.0}, spot="BTN_OPEN", allow_preview=False)
    assert dec_default.action == "WAIT"
    assert dec_default.ev_bb is None
    assert dec_default.reason == "Waiting for Hero turn"

    # allow_preview=True produces active recommendation prefixed with [PLAN]
    dec_plan = dm.decide(st_outside_turn, {"ALL_IN": 1.5, "FOLD": 0.0}, spot="BTN_OPEN", allow_preview=True)
    assert dec_plan.action == "ALL_IN"
    assert dec_plan.ev_bb is not None and dec_plan.ev_bb > 0.0
    assert dec_plan.reason.startswith("[PLAN]")

    # Incomplete cards with allow_preview=True still returns WAIT
    st_incomplete = SimpleNamespace(
        table_id="tbl_preview",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah"],
        board_cards=[],
        is_hero_turn=False,
        street="WAITING_FOR_TURN",
        is_valid=True,
    )
    dec_inc = dm.decide(st_incomplete, {"ALL_IN": 1.5, "FOLD": 0.0}, spot="BTN_OPEN", allow_preview=True)
    assert dec_inc.action == "WAIT"
    assert "Incomplete hero cards" in dec_inc.reason


def test_exploit_timing_tell_fast_bet_not_check() -> None:
    """Verify that last_reaction_ms < 500 when opponent has bet > 0 does NOT trigger fast check tell."""
    engine = ExploitEngine()
    modifiers = ProfileModifiers(profile_name="STANDARD_EXPLOIT", bluff_factor=1.0)

    # Opponent seat 1 acted quickly (250 ms) but bet 40 chips (not a check!)
    state = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, is_active=True, last_reaction_ms=None, current_bet=0),
            1: SimpleNamespace(seat_id=1, is_active=True, last_reaction_ms=250, current_bet=40),
            2: SimpleNamespace(seat_id=2, is_active=True, last_reaction_ms=1200, current_bet=0),
        },
        street="FLOP",
        big_blind=20,
    )

    candidate_evs = {"CHECK": 0.05, "BET_30": 0.10}
    adjusted_evs, reasons = engine.apply_exploits(candidate_evs, state, modifiers, spot="POSTFLOP")

    # Fast check bonus must NOT apply
    assert "Timing Tell: fast check <500ms" not in reasons
    assert adjusted_evs["BET_30"] == pytest.approx(0.10)


def test_quantize_sizing_to_bb_and_all_in() -> None:
    """Verify sizing quantization to BB multiples and deterministic ALL-IN thresholding."""
    from strategy.simplifier import quantize_sizing_to_bb

    # 1. BB multiples for BB=20
    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=38, big_blind=20, hero_stack=300, effective_stack=300, min_bb_mult=1
    )
    assert mode == "BB_MULT"
    assert bb_mult == 2
    assert chips == 40

    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=21, big_blind=20, hero_stack=300, effective_stack=300, min_bb_mult=1
    )
    assert mode == "BB_MULT"
    assert bb_mult == 1
    assert chips == 20

    # 2. BB multiples for BB=100
    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=260, big_blind=100, hero_stack=1000, effective_stack=1000, min_bb_mult=1
    )
    assert mode == "BB_MULT"
    assert bb_mult == 3
    assert chips == 300

    # 3. Transition to ALL_IN at >= 65% of effective stack
    # 0.65 * 300 = 195 chips. Sizing 200 chips (10 BB) is >= 195 -> ALL_IN
    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=200, big_blind=20, hero_stack=300, effective_stack=300, min_bb_mult=1
    )
    assert mode == "ALL_IN"
    assert bb_mult is None
    assert chips == 300

    # 4. Transition to ALL_IN when effective_stack <= 3 * BB facing aggression
    # eff_stk = 50 <= 60 (3 BB), bb_mult >= 2 -> ALL_IN
    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=40, big_blind=20, hero_stack=250, effective_stack=50, min_bb_mult=1
    )
    assert mode == "ALL_IN"
    assert bb_mult is None
    assert chips == 250

    # 5. Chips exceed Hero stack
    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=150, big_blind=20, hero_stack=80, effective_stack=300, min_bb_mult=1
    )
    assert mode == "ALL_IN"
    assert bb_mult is None
    assert chips == 80

    # 6. Hero stack is 0
    mode, bb_mult, chips = quantize_sizing_to_bb(
        target_chips=40, big_blind=20, hero_stack=0, effective_stack=300, min_bb_mult=1
    )
    assert mode == "ALL_IN"
    assert bb_mult is None
    assert chips == 0


def test_decision_lock_confirms_and_freezes_until_state_change() -> None:
    """Verify DecisionLock 2-frame confirmation, caching until change, and reset."""
    from strategy.decision_lock import DecisionLock, compute_decision_fingerprint
    from core.contracts import TableState, PlayerState, Decision

    lock = DecisionLock(confirm_frames=2)

    s1 = TableState(
        table_id="t1",
        timestamp_ms=1000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=30,
        hero_cards=["Ah", "Kd"],
        board_cards=[],
        street="PREFLOP",
        is_hero_turn=True,
        available_actions=["FOLD", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=290, current_bet=10),
            1: PlayerState(seat_id=1, stack=280, current_bet=20),
        },
        is_valid=True,
    )
    fp1 = compute_decision_fingerprint(s1)

    assert lock.get_locked(fp1) is None
    # 1st observation: not confirmed yet
    assert lock.observe_and_should_compute(fp1) is False
    assert lock.get_locked(fp1) is None

    # 2nd observation: confirmed!
    assert lock.observe_and_should_compute(fp1) is True

    dec1 = Decision(
        table_id="t1",
        action="ALL_IN",
        ev_bb=2.5,
        confidence=0.95,
        profile_used="STANDARD",
        reason="Test",
    )
    lock.lock(fp1, dec1)

    # Now fp1 is locked
    assert lock.get_locked(fp1) is dec1
    # Subsequent observations of the same fp return False
    assert lock.observe_and_should_compute(fp1) is False
    assert lock.get_locked(fp1) is dec1

    # State changes to flop (fp2)
    s2 = TableState(
        table_id="t1",
        timestamp_ms=2000,
        prize_pool=4,
        small_blind=10,
        big_blind=20,
        pot=70,
        hero_cards=["Ah", "Kd"],
        board_cards=["7c", "8d", "2h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CHECK", "BET_30"],
        players={
            0: PlayerState(seat_id=0, stack=270, current_bet=0),
            1: PlayerState(seat_id=1, stack=260, current_bet=0),
        },
        is_valid=True,
    )
    fp2 = compute_decision_fingerprint(s2)
    assert fp2 != fp1

    # Locked decision for fp2 does not exist
    assert lock.get_locked(fp2) is None
    # 1st observation of fp2: pending
    assert lock.observe_and_should_compute(fp2) is False
    # 2nd observation of fp2: confirmed!
    assert lock.observe_and_should_compute(fp2) is True

    dec2 = Decision(
        table_id="t1",
        action="BET_30",
        ev_bb=1.2,
        confidence=0.90,
        profile_used="STANDARD",
        reason="Flop bet",
    )
    lock.lock(fp2, dec2)
    assert lock.get_locked(fp2) is dec2

    # Reset clears all locks
    lock.reset()
    assert lock.get_locked(fp2) is None




