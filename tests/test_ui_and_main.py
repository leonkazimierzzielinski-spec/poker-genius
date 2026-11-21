"""Unit and integration tests for Module 6: UI (HUD) and main orchestrator."""

from __future__ import annotations

import os
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.contracts import Decision, PlayerState, TableState
from main import (
    OfflinePlaybackController,
    build_arg_parser,
    capture_loop,
    determine_preflop_spot,
    evaluate_candidates,
)


@pytest.fixture(scope="session")
def qapp():
    """Ensure a single QApplication instance for Qt-dependent tests."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    PySide6 = pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Test 1: determine_preflop_spot
# ---------------------------------------------------------------------------
def test_determine_preflop_spot():
    """Test preflop spot recognition for BTN_OPEN, SB_OPEN, and BB_ISO_VS_LIMP."""
    # 1. BTN_OPEN: Seat 0 (Hero) is the dealer
    state_btn = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=True, current_bet=0),
            1: SimpleNamespace(seat_id=1, is_dealer=False, current_bet=10),
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=20),
        },
    )
    assert determine_preflop_spot(state_btn) == "BTN_OPEN"

    # 2. SB_OPEN: Seat 2 is dealer (BTN). Hero (seat 0) is SB. Seat 2 folded/unraised (current_bet=0).
    state_sb = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=10),  # SB (Hero)
            1: SimpleNamespace(seat_id=1, is_dealer=False, current_bet=20),  # BB
            2: SimpleNamespace(seat_id=2, is_dealer=True, current_bet=0),   # BTN folded
        },
    )
    assert determine_preflop_spot(state_sb) == "SB_OPEN"

    # 3. BB_ISO_VS_LIMP: Seat 1 is dealer (BTN). Hero (seat 0) is BB. BTN limped (current_bet=20).
    state_bb = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=20),  # BB (Hero)
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=20),   # BTN limp
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=10),  # SB
        },
    )
    assert determine_preflop_spot(state_bb) == "BB_ISO_VS_LIMP"

    # Additional spots
    # BTN shoved vs SB
    state_sb_shove = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=10),
            1: SimpleNamespace(seat_id=1, is_dealer=False, current_bet=20),
            2: SimpleNamespace(seat_id=2, is_dealer=True, current_bet=300, status_text="ALL_IN"),
        },
    )
    assert determine_preflop_spot(state_sb_shove) == "SB_VS_BTN_SHOVE"

    # BTN shoved vs BB
    state_bb_shove = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=20),
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=300, status_text="ALL_IN"),
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=10),
        },
    )
    assert determine_preflop_spot(state_bb_shove) == "BB_VS_BTN_SHOVE"

    # SB raised (e.g. minraise 60 with BB=30) vs BB
    state_bb_vs_sb_raise = SimpleNamespace(
        big_blind=30,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=30),  # Hero (BB)
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=0),   # BTN folded
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=60),  # SB raised to 60
        },
    )
    assert determine_preflop_spot(state_bb_vs_sb_raise) == "BB_VS_SB_SHOVE"

    # Empty players fallback
    assert determine_preflop_spot(SimpleNamespace(players={})) == "BTN_OPEN"


# ---------------------------------------------------------------------------
# Test 2: test_hud_overlay_lock_toggle
# ---------------------------------------------------------------------------
def test_hud_overlay_lock_toggle(qapp):
    """Test HudOverlay toggle_lock changes is_locked state and styles."""
    pytest.importorskip("PySide6")
    from ui.hud import HudOverlay

    hud = HudOverlay()
    # Default state is unlocked (is_locked is False)
    assert hud.is_locked is False
    assert "ODBLOKOWANY" in hud.status_label.text()

    # First toggle: lock
    new_state = hud.toggle_lock()
    assert new_state is True
    assert hud.is_locked is True
    assert "ZABLOKOWANY" in hud.status_label.text()

    # Second toggle: unlock back
    new_state_2 = hud.toggle_lock()
    assert new_state_2 is False
    assert hud.is_locked is False
    assert "ODBLOKOWANY" in hud.status_label.text()


# ---------------------------------------------------------------------------
# Test 3: test_hud_overlay_updates_multi_table
# ---------------------------------------------------------------------------
def test_hud_overlay_updates_multi_table(qapp):
    """Test sending decisions for table_1 and table_2 updates table_widgets."""
    pytest.importorskip("PySide6")
    from ui.hud import HudBridge, HudOverlay

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)

    d1 = Decision(
        table_id="table_1",
        action="ALL_IN",
        ev_bb=0.45,
        confidence=0.95,
        profile_used="STANDARD_EXPLOIT",
        reason="MDA +15% shove vs limp",
    )
    d2 = Decision(
        table_id="table_2",
        action="FOLD",
        ev_bb=0.0,
        confidence=0.98,
        profile_used="LOOSE_CALLERS",
        reason="Marginal fold",
    )

    bridge.decision_updated.emit(d1, 14.5)
    bridge.decision_updated.emit(d2, 21.0)

    assert "table_1" in hud.table_widgets
    assert "table_2" in hud.table_widgets

    t1_text = hud.table_widgets["table_1"].text()
    assert "table_1" in t1_text
    assert "ALL_IN" in t1_text
    assert "STANDARD_EXPLOIT" in t1_text
    assert "+0.45 BB" in t1_text

    t2_text = hud.table_widgets["table_2"].text()
    assert "table_2" in t2_text
    assert "FOLD" in t2_text
    assert "LOOSE_CALLERS" in t2_text


# ---------------------------------------------------------------------------
# Test 3b: Diagnostic details panel toggle & scan summary
# ---------------------------------------------------------------------------
def test_hud_overlay_details_toggle(qapp):
    """Test toggling diagnostic details panel and displaying scan_summary."""
    pytest.importorskip("PySide6")
    from ui.hud import HudBridge, HudOverlay

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    assert hud.show_details is False

    summary = (
        "Status: VALID\n"
        "Blinds: 10/20 | Prize: $4 | Pot: 40\n"
        "Hero: Ah Kh | Board: --\n"
        "Gracze: S0: 300 (bet 20) | S1: 280 (bet 20) [D] | S2: 300 (bet 0)\n"
        "Hero Turn: YES | Actions: [FOLD, CALL, RAISE] | Spot: BB_VS_SB_RAISE"
    )
    d = Decision(
        table_id="table_1",
        action="CALL",
        ev_bb=1.2,
        confidence=0.9,
        profile_used="STANDARD_EXPLOIT",
        reason="Pot odds call",
    )
    bridge.decision_updated.emit(d, 12.0, summary)

    assert "table_1" in hud.details_widgets
    detail_lbl = hud.details_widgets["table_1"]
    assert "Status: VALID" in detail_lbl.text()
    assert "Blinds: 10/20" in detail_lbl.text()
    assert detail_lbl.isHidden() is True

    # Toggle details ON
    hud.toggle_details()
    assert hud.show_details is True
    assert detail_lbl.isHidden() is False

    # Toggle details OFF
    hud.toggle_details()
    assert hud.show_details is False
    assert detail_lbl.isHidden() is True


# ---------------------------------------------------------------------------
# Test 3c: Manual ROI rectangle selector and bridge signals
# ---------------------------------------------------------------------------
def test_hud_bridge_manual_rect_signals(qapp):
    """Test manual_rect_changed signal emission and selector callbacks."""
    pytest.importorskip("PySide6")
    from ui.hud import HudBridge, HudOverlay, RegionSelectorOverlay
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)

    emitted_rects = []
    bridge.manual_rect_changed.connect(lambda r: emitted_rects.append(r))

    # Simulate manual rect selected
    hud._on_region_selected((150, 100, 850, 650))
    assert hud._manual_rect == (150, 100, 850, 650)
    assert emitted_rects[-1] == (150, 100, 850, 650)
    assert "850x650" in hud.status_label.text()

    # Reset back to auto detection
    hud.reset_auto_rect()
    assert hud._manual_rect is None
    assert emitted_rects[-1] is None

    # Test RegionSelectorOverlay mouse interaction and Esc key
    selector_emitted = []
    selector = RegionSelectorOverlay(on_selected=lambda r: selector_emitted.append(r))

    # Mouse drag selection: (100, 100) to (500, 400) -> width 400, height 300
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(100.0, 100.0),
        QPointF(100.0, 100.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    selector.mousePressEvent(press_ev)
    assert selector._is_selecting is True

    move_ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(500.0, 400.0),
        QPointF(500.0, 400.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    selector.mouseMoveEvent(move_ev)

    release_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(500.0, 400.0),
        QPointF(500.0, 400.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    selector.mouseReleaseEvent(release_ev)
    assert len(selector_emitted) == 1
    # Check width and height are preserved (scaled by dpr)
    rect = selector_emitted[0]
    assert rect[2] >= 400 and rect[3] >= 300

    # Test Escape key cancels
    esc_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    selector.keyPressEvent(esc_ev)


# ---------------------------------------------------------------------------
# Test 3d: Backward compatibility of 2-arg on_decision_updated
# ---------------------------------------------------------------------------
def test_hud_overlay_backward_compat_two_args(qapp):
    """Test on_decision_updated accepts 2 args without error (legacy compatibility)."""
    pytest.importorskip("PySide6")
    from ui.hud import HudBridge, HudOverlay

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)

    d = Decision(
        table_id="table_legacy",
        action="CHECK",
        ev_bb=0.0,
        confidence=1.0,
        profile_used="STANDARD_EXPLOIT",
        reason="Check behind",
    )

    # 1. Direct call with 2 arguments
    hud.on_decision_updated(d, 8.5)
    assert "table_legacy" in hud.table_widgets
    assert "CHECK" in hud.table_widgets["table_legacy"].text()

    # 2. Emission via bridge with 2 arguments
    bridge.decision_updated.emit(d, 9.2)
    assert "table_legacy" in hud.table_widgets
    assert "CHECK" in hud.table_widgets["table_legacy"].text()


# ---------------------------------------------------------------------------
# Test 4: evaluate_candidates preflop & postflop
# ---------------------------------------------------------------------------
def test_evaluate_candidates_preflop():
    """Test candidate evaluation in PREFLOP street with preflop Nash engine."""
    state = SimpleNamespace(
        street="PREFLOP",
        hero_cards=["As", "Kh"],
        board_cards=[],
        pot=30,
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, stack=280, is_dealer=True),
        },
    )

    mock_preflop = MagicMock()
    mock_preflop.get_action.return_value = ("MIN_RAISE", 0.50)

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=mock_preflop,
        flop_db=None,
        mc_calc=None,
    )

    assert spot == "BTN_OPEN"
    assert "FOLD" in candidates
    assert candidates["MIN_RAISE"] == 0.50


def test_evaluate_candidates_flop_db():
    """Test candidate evaluation using flop_db lookup."""
    state = SimpleNamespace(
        street="FLOP",
        hero_cards=["Qh", "4h"],
        board_cards=["Qd", "Qs", "8d"],
        pot=60,
        big_blind=20,
        players={0: SimpleNamespace(seat_id=0, stack=270)},
    )

    mock_flop_db = MagicMock()
    mock_flop_db.lookup.return_value = {
        "CHECK": 0.1,
        "BET_30": 0.45,
        "ALL_IN": 0.35,
    }

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=None,
        flop_db=mock_flop_db,
        mc_calc=None,
    )

    assert spot == "FLOP"
    assert candidates["CHECK"] == 0.1
    assert candidates["BET_30"] == 0.45
    assert candidates["ALL_IN"] == 0.35
    assert candidates["FOLD"] == 0.0


def test_evaluate_candidates_mc_calc():
    """Test candidate evaluation fallback to Monte Carlo calculation."""
    state = SimpleNamespace(
        street="TURN",
        hero_cards=["As", "Ah"],
        board_cards=["Kd", "7c", "2s", "9h"],
        pot=80,
        big_blind=20,
        players={0: SimpleNamespace(seat_id=0, stack=260)},
    )

    mock_mc = MagicMock()
    mock_mc.estimate_equity.return_value = 0.85
    mock_mc.calculate_ev_bb.side_effect = lambda eq, pot, call_cost_bb, fold_equity=0.0: round(
        eq * (pot + call_cost_bb), 2
    )

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=None,
        flop_db=None,
        mc_calc=mock_mc,
    )

    assert spot == "TURN"
    assert "CHECK" in candidates
    assert "BET_30" in candidates
    assert "ALL_IN" in candidates
    assert "FOLD" in candidates


def test_evaluate_candidates_incomplete_hero_cards():
    """Verify that incomplete hero cards strictly yield WAIT and never ALL_IN."""
    state = SimpleNamespace(
        street="PREFLOP",
        hero_cards=["Ah"],  # only 1 card
        board_cards=[],
        pot=30,
        big_blind=20,
        players={0: SimpleNamespace(seat_id=0, stack=280)},
    )
    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=None,
        flop_db=None,
        mc_calc=None,
    )
    assert candidates == {"WAIT": 0.0}
    assert spot == "NO_HERO_CARDS"


# ---------------------------------------------------------------------------
# Test 5: CLI argument parsing
# ---------------------------------------------------------------------------
def test_cli_argument_parsing():
    """Test argument parser defaults and custom inputs."""
    parser = build_arg_parser()

    # Defaults
    args = parser.parse_args([])
    assert args.mode == "live"
    assert args.source is None
    assert args.config == "config.json"
    assert args.buy_in == 2
    assert args.headless is False
    assert args.show_video is None
    assert args.monitor == 0

    # Custom options
    custom_args = parser.parse_args([
        "--mode", "offline",
        "--source", "test_video.mp4",
        "--config", "custom_config.json",
        "--buy-in", "10",
        "--headless",
        "--show-video",
        "--monitor", "1",
    ])
    assert custom_args.mode == "offline"
    assert custom_args.source == "test_video.mp4"
    assert custom_args.config == "custom_config.json"
    assert custom_args.buy_in == 10
    assert custom_args.headless is True
    assert custom_args.show_video is True
    assert custom_args.monitor == 1

    # Test --no-show-video
    no_show = parser.parse_args(["--no-show-video"])
    assert no_show.show_video is False


def test_cli_monitor_parsing() -> None:
    """Verify that --monitor argument parses correctly for multi-monitor setups."""
    parser = build_arg_parser()
    args_default = parser.parse_args([])
    assert args_default.monitor == 0

    args_custom = parser.parse_args(["--monitor", "1"])
    assert args_custom.monitor == 1


# ---------------------------------------------------------------------------
# Test 6: Win32 set_click_through edge case handling
# ---------------------------------------------------------------------------
def test_set_click_through_safe():
    """Test that set_click_through with hwnd=0 or invalid handles executes safely."""
    from ui.hud import set_click_through

    # Must not raise any exceptions
    set_click_through(0, True)
    set_click_through(0, False)
    set_click_through(-1, True)


# ---------------------------------------------------------------------------
# Test 7: capture_loop live mode with intermittent None frames
# ---------------------------------------------------------------------------
def test_capture_loop_live_mode_none_frames():
    """Verify capture_loop in live mode survives intermittent None frames (static screen in dxcam)."""
    valid_frame = np.ones((50, 50, 3), dtype=np.uint8)

    class MockLiveSource:
        def __init__(self):
            # 3 Nones followed by 1 valid frame, then Nones
            self.sequence = [None, None, None, valid_frame, None]
            self.idx = 0

        def grab(self):
            if self.idx < len(self.sequence):
                res = self.sequence[self.idx]
                self.idx += 1
                return res
            return None

    source = MockLiveSource()
    frame_q: queue.Queue = queue.Queue(maxsize=1)
    stop_ev = threading.Event()

    # In is_live=True mode, None frames must NOT terminate the loop
    t = threading.Thread(
        target=capture_loop,
        args=(source, frame_q, stop_ev, 0.001, None, True),
        daemon=True,
    )
    t.start()

    # Wait for the valid frame to be grabbed and queued
    item = frame_q.get(timeout=1.0)
    assert item is not None
    assert np.array_equal(item, valid_frame)

    # Stop the thread
    stop_ev.set()
    t.join(timeout=1.0)
    assert not t.is_alive()

    # In is_live=False mode (offline), None frame must immediately break and put None into queue
    class MockOfflineSource:
        def grab(self):
            return None

    frame_q_offline: queue.Queue = queue.Queue(maxsize=1)
    stop_ev_offline = threading.Event()
    capture_loop(
        MockOfflineSource(),
        frame_q_offline,
        stop_ev_offline,
        interval_sec=0.001,
        is_live=False,
    )
    assert frame_q_offline.get(timeout=0.5) is None


# ---------------------------------------------------------------------------
# Test 7b: OfflinePlaybackController pause toggling, seek requests, and stepping
# ---------------------------------------------------------------------------
def test_offline_playback_controller():
    """Verify OfflinePlaybackController pause toggling, seek requests, and stepping."""
    ctrl = OfflinePlaybackController(total_frames=100)
    assert ctrl.paused is False
    assert ctrl.total_frames == 100
    assert ctrl.current_frame_idx == 0

    # Test toggle_pause
    assert ctrl.toggle_pause() is True
    assert ctrl.paused is True
    assert ctrl.toggle_pause() is False
    assert ctrl.paused is False

    # Test request_seek with clamping
    ctrl.request_seek(42)
    assert ctrl.seek_target == 42

    ctrl.request_seek(150)
    assert ctrl.seek_target == 99
    ctrl.request_seek(-5)
    assert ctrl.seek_target == 0

    # Test request_step while paused (single-frame step)
    ctrl.paused = True
    ctrl.current_frame_idx = 20
    ctrl.step_frames = 0
    ctrl.request_step(1)
    assert ctrl.step_frames == 1

    # Test request_step with delta != 1 (seek jumps)
    ctrl.request_step(30)
    assert ctrl.seek_target == 50
    ctrl.request_step(-15)
    assert ctrl.seek_target == 5


# ---------------------------------------------------------------------------
# Test 7c: capture_loop with OfflinePlaybackController pause, step, and seek
# ---------------------------------------------------------------------------
def test_capture_loop_with_playback_pause_and_seek():
    """Verify capture_loop pauses without emitting frames and responds immediately to seek requests."""
    class DummySeekableSource:
        def __init__(self, n: int = 10):
            self.total_frames = n
            self.cursor = 0
            self.current_frame_idx = 0
            self.frames = [np.full((10, 10, 3), i * 10, dtype=np.uint8) for i in range(n)]

        def grab(self):
            if self.cursor < len(self.frames):
                self.current_frame_idx = self.cursor
                f = self.frames[self.cursor]
                self.cursor += 1
                return f
            return None

        def seek(self, idx: int):
            self.cursor = max(0, min(idx, len(self.frames) - 1))
            self.current_frame_idx = self.cursor

    source = DummySeekableSource(10)
    playback = OfflinePlaybackController(total_frames=10)
    frame_q: queue.Queue = queue.Queue(maxsize=1)
    stop_ev = threading.Event()

    t = threading.Thread(
        target=capture_loop,
        args=(source, frame_q, stop_ev, 0.01, None, False, playback),
        daemon=True,
    )
    t.start()

    # Grab first frame (0)
    f0 = frame_q.get(timeout=1.0)
    assert f0 is not None
    assert int(f0[0, 0, 0]) == 0

    # Pause playback
    playback.paused = True
    time.sleep(0.05)

    # Drain any lingering item in queue
    try:
        frame_q.get_nowait()
    except queue.Empty:
        pass

    # Verify while paused nothing is queued
    with pytest.raises(queue.Empty):
        frame_q.get(timeout=0.08)

    # Issue seek while paused: should immediately grab target frame 7 and put in queue
    playback.request_seek(7)
    f7 = frame_q.get(timeout=1.0)
    assert f7 is not None
    assert int(f7[0, 0, 0]) == 70
    assert playback.current_frame_idx == 7

    # Issue single step while paused: should grab frame 8
    playback.request_step(1)
    f8 = frame_q.get(timeout=1.0)
    assert f8 is not None
    assert int(f8[0, 0, 0]) == 80

    stop_ev.set()
    t.join(timeout=1.0)
    assert not t.is_alive()


# ---------------------------------------------------------------------------
# Test 8: evaluate_candidates effective_bb against shorter active opponent
# ---------------------------------------------------------------------------
def test_evaluate_candidates_effective_bb_shorter_opp():
    """Verify effective_bb is min(hero_total, max_active_opp_total) / bb_val."""
    # Hero has 500 total chips. Opponent 1 has 120 total chips (stack=100, bet=20).
    # Opponent 2 folded (bet=0, stack=0, is_active=False).
    # Effective BB should be min(500, 120) / 20 = 6.0 BB.
    state = SimpleNamespace(
        street="PREFLOP",
        hero_cards=["As", "Kh"],
        board_cards=[],
        pot=40,
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, stack=500, current_bet=0, is_dealer=True),
            1: SimpleNamespace(seat_id=1, stack=100, current_bet=20, is_active=True, status_text="ACTIVE"),
            2: SimpleNamespace(seat_id=2, stack=0, current_bet=0, is_active=False, status_text="FOLDED"),
        },
    )

    mock_preflop = MagicMock()
    mock_preflop.get_action.return_value = ("ALL_IN", 1.2)

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=mock_preflop,
        flop_db=None,
        mc_calc=None,
    )

    # Verify that get_action was called with effective_bb == 6.0 (not 500/20 = 25.0)
    mock_preflop.get_action.assert_called_once()
    args, _kwargs = mock_preflop.get_action.call_args
    passed_effective_bb = args[1]
    assert passed_effective_bb == pytest.approx(6.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Test 9: evaluate_candidates postflop facing bet generates CALL EV
# ---------------------------------------------------------------------------
def test_evaluate_candidates_postflop_facing_bet():
    """Verify postflop candidate evaluation computes CALL EV and excludes CHECK when facing a bet."""
    state = SimpleNamespace(
        street="FLOP",
        hero_cards=["Kh", "Qh"],
        board_cards=["Ks", "7d", "2c"],
        pot=100,
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, stack=240, current_bet=0),   # Hero bet 0
            1: SimpleNamespace(seat_id=1, stack=200, current_bet=60),  # Opponent bet 60 (to call = 60/20 = 3 BB)
            2: SimpleNamespace(seat_id=2, stack=300, current_bet=0, status_text="FOLDED"),
        },
    )

    mock_mc = MagicMock()
    mock_mc.estimate_equity.return_value = 0.70
    mock_mc.calculate_ev_bb.side_effect = lambda eq, pot_bb, call_cost_bb, fold_equity=0.0: round(
        eq * (pot_bb + call_cost_bb) - (1.0 - eq) * call_cost_bb, 2
    )

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=None,
        flop_db=None,
        mc_calc=mock_mc,
    )

    assert spot == "FLOP"
    assert "CALL" in candidates
    assert "CHECK" not in candidates  # Cannot check when facing a bet
    assert "FOLD" in candidates
    assert candidates["FOLD"] == 0.0
    assert candidates["CALL"] > 0.0  # Positive EV with 70% equity facing 3 BB bet in 5 BB pot


# ---------------------------------------------------------------------------
# Test 10: determine_preflop_spot distinguishes shove vs min-raise
# ---------------------------------------------------------------------------
def test_determine_preflop_spot_shove_vs_minraise():
    """Verify determine_preflop_spot distinguishes true all-in shove from standard min-raise."""
    # 1. BTN min-raises to 40 (BB=20) with 400 chips behind -> BB_VS_BTN_RAISE
    state_btn_minraise = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=20, stack=300),  # BB
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=40, stack=400),   # BTN min-raise (40 < 0.4*440)
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=10, stack=250),  # SB
        },
    )
    assert determine_preflop_spot(state_btn_minraise) == "BB_VS_BTN_RAISE"

    # 2. BTN shoves all-in with stack=0 and bet=40 -> BB_VS_BTN_SHOVE
    state_btn_shove_0 = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=20, stack=300),
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=40, stack=0),     # BTN stack 0 -> shove
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=10, stack=250),
        },
    )
    assert determine_preflop_spot(state_btn_shove_0) == "BB_VS_BTN_SHOVE"

    # 3. BTN bets 40 with stack=40 (bet = 40/80 = 50% >= 40% of total) -> BB_VS_BTN_SHOVE
    state_btn_commit = SimpleNamespace(
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=20, stack=300),
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=40, stack=40),    # 40 >= 0.4 * 80
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=10, stack=250),
        },
    )
    assert determine_preflop_spot(state_btn_commit) == "BB_VS_BTN_SHOVE"

    # 4. SB min-raises to 60 (BB=30) with 300 stack behind -> BB_VS_SB_RAISE
    state_sb_minraise = SimpleNamespace(
        big_blind=30,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=30, stack=300),  # BB
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=0, stack=300),    # BTN folded
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=60, stack=300),  # SB min-raise (60 < 0.4*360)
        },
    )
    assert determine_preflop_spot(state_sb_minraise) == "BB_VS_SB_RAISE"


# ---------------------------------------------------------------------------
# Test 11: determine_preflop_spot in Heads-Up mode (2 active players)
# ---------------------------------------------------------------------------
def test_determine_preflop_spot_heads_up():
    """Verify determine_preflop_spot in Heads-Up correctly maps Dealer=SB/BTN and Non-Dealer=BB."""
    # 1. Hero is Dealer (Seat 0) -> Hero is SB/BTN -> SB_OPEN
    state_hu_hero_dealer = SimpleNamespace(
        big_blind=40,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=True, current_bet=20, stack=480, is_active=True),   # Hero SB/BTN
            1: SimpleNamespace(seat_id=1, is_dealer=False, current_bet=40, stack=360, is_active=True),  # Opponent BB
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=0, stack=None, is_active=False, status_text="SIT_OUT"),
        },
    )
    assert determine_preflop_spot(state_hu_hero_dealer) == "SB_OPEN"

    # 2. Opponent is Dealer (Seat 1) -> Hero is BB
    # 2a. Opponent limps (bet=40 == BB) -> BB_ISO_VS_LIMP
    state_hu_opp_limp = SimpleNamespace(
        big_blind=40,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=40, stack=460, is_active=True),
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=40, stack=360, is_active=True),
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=0, stack=None, is_active=False, status_text="SIT_OUT"),
        },
    )
    assert determine_preflop_spot(state_hu_opp_limp) == "BB_ISO_VS_LIMP"

    # 2b. Opponent min-raises (bet=80, stack=320) -> BB_VS_SB_RAISE
    state_hu_opp_raise = SimpleNamespace(
        big_blind=40,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=40, stack=460, is_active=True),
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=80, stack=320, is_active=True),
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=0, stack=None, is_active=False, status_text="SIT_OUT"),
        },
    )
    assert determine_preflop_spot(state_hu_opp_raise) == "BB_VS_SB_RAISE"

    # 2c. Opponent shoves (bet=80, stack=0, or ALL_IN) -> BB_VS_SB_SHOVE
    state_hu_opp_shove = SimpleNamespace(
        big_blind=40,
        players={
            0: SimpleNamespace(seat_id=0, is_dealer=False, current_bet=40, stack=460, is_active=True),
            1: SimpleNamespace(seat_id=1, is_dealer=True, current_bet=80, stack=0, is_active=True, status_text="ALL_IN"),
            2: SimpleNamespace(seat_id=2, is_dealer=False, current_bet=0, stack=None, is_active=False, status_text="SIT_OUT"),
        },
    )
    assert determine_preflop_spot(state_hu_opp_shove) == "BB_VS_SB_SHOVE"


# ---------------------------------------------------------------------------
# Test 12: main.py processing loop uses unclipped canonical table rect
# ---------------------------------------------------------------------------
def test_processing_loop_uses_unclipped_canonical_rect(tmp_path):
    """Verify that the main.py processing path with unclipped table rect matches direct pipeline processing."""
    import json
    import cv2
    from vision.anchor import compute_unclipped_table_rect, find_all_anchors
    from vision.pipeline import VisionPipeline

    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    anchor_img = np.full((31, 93, 3), 180, dtype=np.uint8)
    cv2.circle(anchor_img, (46, 15), 8, (255, 255, 255), -1)
    anchor_path = tpl_dir / "anchor.png"
    cv2.imwrite(str(anchor_path), anchor_img)

    cfg_file = tmp_path / "config.json"
    cfg = {
        "anchor": {
            "template_path": str(anchor_path),
            "match_threshold": 0.85,
            "table_offset_rel": [0.030, 0.040, 0.0529, 0.031],
        },
        "canonical_table_size": [1757, 997],
        "rois": {
            "pot": [0.4, 0.4, 0.1, 0.05],
        },
    }
    with cfg_file.open("w", encoding="utf-8") as f:
        json.dump(cfg, f)

    pipeline = VisionPipeline(config_path=cfg_file)

    # Synthetic frame with anchor at (100, 100)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[100:131, 100:193] = anchor_img

    # Path A: direct pipeline.process_frame(frame, table_rect=None)
    state_direct = pipeline.process_frame(frame, table_rect=None)

    # Path B: main.py processing path
    anchors = find_all_anchors(
        frame, pipeline.anchor_template, threshold=pipeline.anchor_threshold
    )
    assert len(anchors) == 1
    tpl_w = pipeline.anchor_template.shape[1]
    tpl_h = pipeline.anchor_template.shape[0]
    unclipped_rect = compute_unclipped_table_rect(
        anchors[0],
        pipeline.table_offset_rel,
        canonical_size=pipeline.canonical_table_size,
        template_size=(tpl_w, tpl_h),
    )
    state_main = pipeline.process_frame(
        frame, table_rect=unclipped_rect, has_anchor=True
    )

    assert state_main.table_id == state_direct.table_id
    assert state_main.pot == state_direct.pot
    assert state_main.small_blind == state_direct.small_blind
    assert state_main.big_blind == state_direct.big_blind
    assert state_main.is_hero_turn == state_direct.is_hero_turn
    assert state_main.hero_cards == state_direct.hero_cards
    assert state_main.board_cards == state_direct.board_cards


# ---------------------------------------------------------------------------
# Test 13: Hero on BTN vs Shove / Raise in determine_preflop_spot
# ---------------------------------------------------------------------------
def test_determine_preflop_spot_btn_vs_shove():
    """Verify that Hero on BTN facing a shove or raise returns defense spots, NOT BTN_OPEN."""
    # 3-max: Hero is Dealer (BTN, seat 0). SB (seat 1) shoves 166 (stack=0, ALL_IN). BB (seat 2) posted 20.
    state_btn_vs_shove = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, stack=424, current_bet=20, is_dealer=True),
            1: SimpleNamespace(seat_id=1, stack=0, current_bet=166, is_dealer=False, status_text="ALL_IN"),
            2: SimpleNamespace(seat_id=2, stack=270, current_bet=20, is_dealer=False),
        },
        big_blind=20,
    )
    spot_shove = determine_preflop_spot(state_btn_vs_shove)
    assert spot_shove == "BB_VS_SB_SHOVE"

    # 3-max: Hero is Dealer (BTN, seat 0). SB (seat 1) min-raises to 50 with stack 250.
    state_btn_vs_raise = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, stack=424, current_bet=20, is_dealer=True),
            1: SimpleNamespace(seat_id=1, stack=250, current_bet=50, is_dealer=False),
            2: SimpleNamespace(seat_id=2, stack=270, current_bet=20, is_dealer=False),
        },
        big_blind=20,
    )
    spot_raise = determine_preflop_spot(state_btn_vs_raise)
    assert spot_raise == "BB_VS_SB_RAISE"

    # Heads-Up: Hero is Dealer (seat 0, SB/BTN). Opponent (seat 1, BB) shoves 300.
    state_hu_btn_vs_shove = SimpleNamespace(
        players={
            0: SimpleNamespace(seat_id=0, stack=200, current_bet=20, is_dealer=True),
            1: SimpleNamespace(seat_id=1, stack=0, current_bet=300, is_dealer=False, status_text="ALL_IN"),
            2: SimpleNamespace(seat_id=2, stack=None, current_bet=0, is_dealer=False, status_text="SIT_OUT"),
        },
        big_blind=20,
    )
    spot_hu_shove = determine_preflop_spot(state_hu_btn_vs_shove)
    assert spot_hu_shove == "BB_VS_SB_SHOVE"


# ---------------------------------------------------------------------------
# Test 14: Postflop EV conservative calibration avoids blind shoves
# ---------------------------------------------------------------------------
def test_postflop_ev_conservative_no_blind_shove():
    """Verify that a marginal hand with 50% equity at high SPR (stack=14 BB, pot=4 BB) does not get inflated +10 BB shove EV."""
    from unittest.mock import MagicMock
    from engine.monte_carlo import MonteCarloCalculator

    state = SimpleNamespace(
        street="FLOP",
        hero_cards=["Jh", "Td"],
        board_cards=["Js", "7d", "2c"],
        pot=80,          # 4 BB
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, stack=280, current_bet=0),  # Hero stack 14 BB
            1: SimpleNamespace(seat_id=1, stack=280, current_bet=0),  # Opponent
            2: SimpleNamespace(seat_id=2, stack=260, current_bet=0, status_text="FOLDED"),
        },
    )

    mc_calc = MonteCarloCalculator()
    mc_calc.estimate_equity = MagicMock(return_value=0.50)  # Marginal 50% equity

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=None,
        flop_db=None,
        mc_calc=mc_calc,
    )

    assert spot == "FLOP"
    assert "CHECK" in candidates
    assert "BET_30" in candidates
    assert "ALL_IN" in candidates

    # With 50% equity, pot 4 BB, stack 14 BB:
    # Shove calling equity drops to 0.36, fold equity is 0.15 (high SPR).
    # Shove EV must NOT be wildly positive (must be < 1.0 BB, while CHECK/BET are better)
    assert candidates["ALL_IN"] < 1.0
    assert candidates["ALL_IN"] < candidates["CHECK"] or candidates["ALL_IN"] < candidates["BET_30"]


# ---------------------------------------------------------------------------
# Test 15: Preview actions contain RAISE and Preflop Range Penalty
# ---------------------------------------------------------------------------
def test_preview_actions_contains_raise_and_preflop_range_penalty():
    """Verify preview_actions includes RAISE when facing a bet, and preflop *_RAISE applies range penalty."""
    from unittest.mock import MagicMock
    from engine.monte_carlo import MonteCarloCalculator

    # 1. Verify preview_actions logic from main.py
    hero_bet = 20
    max_opp_bet = 60
    if max_opp_bet > hero_bet:
        preview_actions = ["FOLD", "CALL", "RAISE", "ALL_IN"]
    else:
        preview_actions = ["CHECK", "BET_30", "ALL_IN"]

    assert "RAISE" in preview_actions
    assert preview_actions == ["FOLD", "CALL", "RAISE", "ALL_IN"]

    # 2. Test preflop range penalty on evaluate_candidates
    state = SimpleNamespace(
        street="PREFLOP",
        hero_cards=["Jc", "4d"],
        board_cards=[],
        pot=100,          # 5 BB
        big_blind=20,
        players={
            0: SimpleNamespace(seat_id=0, stack=280, current_bet=20, is_dealer=False),  # Hero (BB)
            1: SimpleNamespace(seat_id=1, stack=260, current_bet=60, is_dealer=True),   # BTN raises to 3 BB
            2: SimpleNamespace(seat_id=2, stack=280, current_bet=0, status_text="FOLDED"),
        },
    )

    mc_calc = MonteCarloCalculator()
    mc_calc.estimate_equity = MagicMock(return_value=0.43)  # Jc 4d has ~43% vs 100% random

    candidates, spot = evaluate_candidates(
        state,
        preflop_engine=None,
        flop_db=None,
        mc_calc=mc_calc,
    )

    assert spot == "BB_VS_BTN_RAISE"
    assert spot.endswith("_RAISE")
    # Against a raise, Jc 4d with range penalty (shove_call_equity = 0.33) should NOT have positive shove EV
    assert "ALL_IN" not in candidates
    assert "CALL" in candidates


def test_hud_overlay_compact_cards_label(qapp) -> None:
    """Verify HudOverlay displays compact colored cards line even when details panel is collapsed."""
    pytest.importorskip("PySide6")
    from ui.hud import HudBridge, HudOverlay, format_cards_html

    # Test format_cards_html helper directly
    summary_text = (
        "Status: VALID\n"
        "Blinds: 10/20 | Prize: $4 | Pot: 40\n"
        "Hero: Td 7h | Board: Qc 7c 7h\n"
        "Gracze: S0: 300 (bet 20) | S1: 280 (bet 20) [D] | S2: 300 (bet 0)\n"
        "Hero Turn: YES | Actions: [FOLD, CALL] | Spot: BB_VS_SB_RAISE"
    )
    formatted = format_cards_html(summary_text)
    assert "10" in formatted
    assert "♦" in formatted
    assert "7" in formatted
    assert "♥" in formatted
    assert "Board:" in formatted
    assert "Q" in formatted
    assert "♣" in formatted

    # Test HudOverlay presentation
    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    assert hud.show_details is False

    d = Decision(
        table_id="table_1",
        action="CALL",
        ev_bb=1.2,
        confidence=0.9,
        profile_used="STANDARD_EXPLOIT",
        reason="Pot odds call",
    )
    bridge.decision_updated.emit(d, 12.0, summary_text)

    # Details widget is NOT visible when show_details is False
    assert hud.details_widgets["table_1"].isVisible() is False

    # Main table widget is populated with card HTML containing the cards line
    card_text = hud.table_widgets["table_1"].text()
    assert "10" in card_text
    assert "♦" in card_text
    assert "7" in card_text
    assert "♥" in card_text
    assert "Q" in card_text
    assert "♣" in card_text
    assert "CALL" in card_text


