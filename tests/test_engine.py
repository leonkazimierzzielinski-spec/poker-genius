"""Unit tests for Module 4: Mathematical Engine (engine/)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from engine.flop_db import FlopDatabase, canonicalize_flop, generate_all_1755_flops
from engine.monte_carlo import MonteCarloCalculator
from engine.preflop_nash import PreflopNashEngine, hand_to_canonical


def test_hand_to_canonical() -> None:
    """Check pocket pairs, suited, offsuit, and ValueError on invalid inputs."""
    # Pocket pairs
    assert hand_to_canonical(["7c", "7d"]) == "77"
    assert hand_to_canonical(["Ah", "As"]) == "AA"
    assert hand_to_canonical(["2s", "2c"]) == "22"

    # Suited hands (higher rank first + 's')
    assert hand_to_canonical(["Qh", "4h"]) == "Q4s"
    assert hand_to_canonical(["4h", "Qh"]) == "Q4s"
    assert hand_to_canonical(["As", "Ks"]) == "AKs"
    assert hand_to_canonical(["2d", "9d"]) == "92s"

    # Offsuit hands (higher rank first + 'o')
    assert hand_to_canonical(["As", "Kc"]) == "AKo"
    assert hand_to_canonical(["Kc", "As"]) == "AKo"
    assert hand_to_canonical(["3c", "As"]) == "A3o"
    assert hand_to_canonical(["7s", "2d"]) == "72o"
    assert hand_to_canonical(["2d", "7s"]) == "72o"

    # Invalid card count
    with pytest.raises(ValueError):
        hand_to_canonical(["Ah"])

    with pytest.raises(ValueError):
        hand_to_canonical(["Ah", "Kd", "2c"])

    with pytest.raises(ValueError):
        hand_to_canonical([])

    # Invalid card representations
    with pytest.raises(ValueError):
        hand_to_canonical(["10s", "2d"])

    with pytest.raises(ValueError):
        hand_to_canonical(["Ax", "Kd"])


def test_preflop_nash_lookup_and_speed() -> None:
    """Verify loading nash_3max.json, AA vs 72o decisions, and query latency < 5 ms."""
    tables_path = Path("data/preflop_tables/nash_3max.json")
    assert tables_path.exists(), "Preflop tables file data/preflop_tables/nash_3max.json must exist"

    engine = PreflopNashEngine(tables_path)

    # 1. Check AA decision across spots and stacks
    act_aa_btn, ev_aa_btn = engine.get_action(["As", "Ah"], 10.0, "BTN_OPEN")
    assert act_aa_btn in ("ALL_IN", "MIN_RAISE")
    assert ev_aa_btn > 0.0

    act_aa_call, ev_aa_call = engine.get_action(["As", "Ah"], 6.0, "BB_VS_BTN_SHOVE")
    assert act_aa_call == "CALL"
    assert ev_aa_call > 0.0

    # 2. Check 72o decision (should fold or check, ev == 0.0 for fold)
    act_72_btn, ev_72_btn = engine.get_action(["7c", "2d"], 10.0, "BTN_OPEN")
    assert act_72_btn == "FOLD"
    assert ev_72_btn == 0.0

    act_72_sb, ev_72_sb = engine.get_action(["7d", "2s"], 8.0, "SB_OPEN")
    assert act_72_sb == "FOLD"
    assert ev_72_sb == 0.0

    act_72_iso, _ = engine.get_action(["7c", "2h"], 12.0, "BB_ISO_VS_LIMP")
    assert act_72_iso == "CHECK"

    # 3. Latency check: single query and batch average must be well below 5 ms (0.005 s)
    t0 = time.perf_counter()
    queries = 500
    for _ in range(queries):
        engine.get_action(["As", "Kh"], 11.5, "BTN_OPEN")
    elapsed_total = time.perf_counter() - t0
    avg_query_ms = (elapsed_total / queries) * 1000.0

    print(f"Average preflop query time: {avg_query_ms:.4f} ms")
    assert avg_query_ms < 5.0, f"Query took too long: {avg_query_ms:.4f} ms (limit 5 ms)"


def test_monte_carlo_equity_and_budget() -> None:
    """Verify Monte Carlo equity estimation (> 0.70 for AA on Kd 7c 2s) and execution time < 150 ms."""
    mc = MonteCarloCalculator()

    # Time budget test
    t0 = time.perf_counter()
    equity = mc.estimate_equity(
        hero_cards=["As", "Ah"],
        board_cards=["Kd", "7c", "2s"],
        iterations=2000,
        time_budget_ms=80.0,
    )
    dt_ms = (time.perf_counter() - t0) * 1000.0

    print(f"Monte Carlo AA on Kd 7c 2s: equity={equity:.4f}, dt={dt_ms:.2f} ms")
    assert equity > 0.70, f"Pocket Aces equity on dry board should be > 0.70, got {equity}"
    assert dt_ms < 150.0, f"Simulation exceeded time budget: {dt_ms:.2f} ms (limit 150 ms)"

    # Test calculate_ev_bb
    # Simple call: equity * (pot + call) - (1 - equity) * call
    ev_call = mc.calculate_ev_bb(equity=0.5, pot_bb=3.0, call_cost_bb=1.0, fold_equity=0.0)
    assert ev_call == pytest.approx(1.5, abs=0.01)

    # Shove with fold equity
    ev_shove = mc.calculate_ev_bb(equity=0.5, pot_bb=3.0, call_cost_bb=1.0, fold_equity=0.5)
    assert ev_shove == pytest.approx(2.25, abs=0.01)


def test_generate_all_1755_flops() -> None:
    """Verify that canonical reduction produces exactly 1,755 unique flops."""
    flops = generate_all_1755_flops()
    assert len(flops) == 1755, f"Expected exactly 1755 flops, got {len(flops)}"
    assert len(set(flops)) == 1755, "All canonical flops must be unique"

    # Canonicalize specific flop from constitution/spec
    canonical_key, suit_map = canonicalize_flop(["Qd", "Qs", "8d"])
    assert canonical_key == "QaQb8a"
    assert suit_map == {"d": "a", "s": "b"}

    # Permutation invariance: any ordering of cards produces identical key and suit_map
    key_perm, map_perm = canonicalize_flop(["8d", "Qs", "Qd"])
    assert key_perm == canonical_key
    assert map_perm == suit_map


def test_flop_db_missing_file_safe(tmp_path: Path) -> None:
    """Verify FlopDatabase safely handles missing files and returns None on lookup."""
    missing_file = tmp_path / "does_not_exist.json"
    db = FlopDatabase(missing_file)
    assert db.db == {}

    result = db.lookup(
        board_cards=["Qd", "Qs", "8d"],
        hero_cards=["As", "Ah"],
        effective_bb=12.0,
    )
    assert result is None


def test_flop_db_lookup_with_data(tmp_path: Path) -> None:
    """Verify FlopDatabase returns strategy when data is present."""
    test_db_file = tmp_path / "test_flops.json"
    sample_data = {
        "QaQb8a": {
            "CHECK": 0.35,
            "BET_30": 0.55,
            "ALL_IN": 0.10,
        }
    }
    test_db_file.write_text(json.dumps(sample_data), encoding="utf-8")

    db = FlopDatabase(test_db_file)
    result = db.lookup(
        board_cards=["Qd", "Qs", "8d"],
        hero_cards=["Ah", "Kd"],
        effective_bb=10.0,
    )
    assert result is not None
    assert result["CHECK"] == pytest.approx(0.35)
    assert result["BET_30"] == pytest.approx(0.55)
    assert result["ALL_IN"] == pytest.approx(0.10)


def test_monte_carlo_multiway_3way() -> None:
    """Verify Monte Carlo equity estimation in 3-way pots (num_opponents=2)."""
    mc = MonteCarloCalculator()

    # AA vs 1 opponent on dry board (Kd 7c 2s)
    eq_1v1 = mc.estimate_equity(
        hero_cards=["As", "Ah"],
        board_cards=["Kd", "7c", "2s"],
        iterations=1500,
        time_budget_ms=100.0,
        num_opponents=1,
    )

    # AA vs 2 opponents on same board
    eq_3way = mc.estimate_equity(
        hero_cards=["As", "Ah"],
        board_cards=["Kd", "7c", "2s"],
        iterations=1500,
        time_budget_ms=100.0,
        num_opponents=2,
    )

    assert eq_1v1 > eq_3way, f"1v1 equity ({eq_1v1:.3f}) should exceed 3-way ({eq_3way:.3f})"
    assert 0.60 <= eq_3way <= 0.85, f"AA 3-way equity should be in [0.60, 0.85], got {eq_3way:.3f}"


def test_monte_carlo_deterministic_seed() -> None:
    """Verify Monte Carlo produces bit-exact deterministic equity for the same inputs."""
    mc = MonteCarloCalculator()

    eq1 = mc.estimate_equity(
        hero_cards=["Kh", "Qh"],
        board_cards=["Jh", "Th", "2c"],
        iterations=500,
        time_budget_ms=100.0,
        num_opponents=1,
    )
    eq2 = mc.estimate_equity(
        hero_cards=["Kh", "Qh"],
        board_cards=["Jh", "Th", "2c"],
        iterations=500,
        time_budget_ms=100.0,
        num_opponents=1,
    )
    assert eq1 == pytest.approx(eq2, abs=1e-9)

    # Different inputs produce different equity
    eq3 = mc.estimate_equity(
        hero_cards=["7c", "2d"],
        board_cards=["Jh", "Th", "2c"],
        iterations=500,
        time_budget_ms=100.0,
        num_opponents=1,
    )
    assert eq1 != eq3


def test_range_narrowing_big_river_bet_reduces_air_and_lowers_bluffcatcher_equity() -> None:
    """Verify that big bet on river reduces air and lowers bluffcatcher equity (exact enumeration)."""
    from engine.range_engine import (
        get_preflop_villain_range,
        narrow_range_by_postflop_action,
        compute_range_vs_hand_equity,
    )

    hero_bluffcatcher = ["7d", "6d"]  # 2nd pair on Kd 7c 2s Jc 3h
    board = ["Kd", "7c", "2s", "Jc", "3h"]

    # 1. Wide preflop range against limp/call
    wide_range = get_preflop_villain_range("BTN", "CALL_OPEN", 12.0, hero_bluffcatcher, board)
    eq_vs_wide = compute_range_vs_hand_equity(hero_bluffcatcher, board, wide_range)

    # 2. Narrowed range facing big river shove / overbet (> 0.70 pot)
    narrowed = narrow_range_by_postflop_action(wide_range, board, "ALL_IN", 1.5, "RIVER")
    eq_vs_big_bet = compute_range_vs_hand_equity(hero_bluffcatcher, board, narrowed)

    # Bluffcatcher has substantial equity vs wide checked range, but very low vs big bet
    assert eq_vs_wide > 0.45, f"Expected equity vs wide range > 0.45, got {eq_vs_wide}"
    assert eq_vs_big_bet < 0.25, f"Expected equity vs big bet < 0.25, got {eq_vs_big_bet}"
    assert eq_vs_wide - eq_vs_big_bet >= 0.25, "Big bet should drop bluffcatcher equity significantly"


def test_flop_db_nearest_cluster_lookup_and_fallback(tmp_path: Path) -> None:
    """Verify that FlopDatabase maps any flop to the nearest GTOpen cluster, and falls back safely if empty."""
    import json
    from engine.flop_db import FlopDatabase

    # 1. Fallback when database file does not exist
    missing_db = FlopDatabase(db_path=tmp_path / "nonexistent.json", gtopen_path=tmp_path / "gtopen_none.json")
    res_none = missing_db.lookup_nearest_flop(["Ah", "Kd", "2c"], "BTN_vs_BB_SRP", ["As", "Qs"])
    assert res_none is None, "Missing database must return None"

    # 2. Database with exact and cluster entries
    mock_gtopen = {
        "BTN_vs_BB_SRP": {
            "Ah 7d 2c": {
                "MONSTER": {"CHECK": 0.10, "BET_30": 0.60, "ALL_IN": 0.30},
                "STRONG": {"CHECK": 0.20, "BET_30": 0.70, "ALL_IN": 0.10},
                "MEDIUM": {"CHECK": 0.50, "BET_30": 0.50, "ALL_IN": 0.00},
                "DRAW": {"CHECK": 0.40, "BET_30": 0.55, "ALL_IN": 0.05},
                "AIR": {"CHECK": 0.65, "BET_30": 0.35, "ALL_IN": 0.00},
            },
            "Jh Ts 8s": {
                "MONSTER": {"CHECK": 0.15, "BET_30": 0.55, "ALL_IN": 0.30},
                "STRONG": {"CHECK": 0.25, "BET_30": 0.65, "ALL_IN": 0.10},
                "AIR": {"CHECK": 0.75, "BET_30": 0.25, "ALL_IN": 0.00},
            },
        }
    }
    mock_file = tmp_path / "gtopen_test.json"
    with open(mock_file, "w", encoding="utf-8") as f:
        json.dump(mock_gtopen, f)

    db = FlopDatabase(db_path=tmp_path / "nonexistent.json", gtopen_path=mock_file)

    # Exact match: "Ah 7d 2c" with top pair (STRONG: As Kh)
    res_exact = db.lookup_nearest_flop(["Ah", "7d", "2c"], "BTN_vs_BB_SRP", ["As", "Kh"])
    assert res_exact is not None
    assert res_exact["BET_30"] == 0.70

    # Nearest cluster: "Ad 7s 3c" (dry Ace-high, should cluster to "Ah 7d 2c")
    res_cluster = db.lookup_nearest_flop(["Ad", "7s", "3c"], "BTN_vs_BB_SRP", ["As", "Kh"])
    assert res_cluster is not None
    assert res_cluster["BET_30"] == 0.70

    # Wet board: "Jd Td 9d" (should cluster to "Jh Ts 8s" wet monotone connector)
    res_wet = db.lookup_nearest_flop(["Jd", "Td", "9d"], "BTN_vs_BB_SRP", ["2c", "3c"])  # AIR
    assert res_wet is not None
    assert res_wet["CHECK"] == 0.75




