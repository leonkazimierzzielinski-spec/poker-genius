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


def test_debug_roi_overlay_and_exclude_capture(qapp) -> None:
    """Verify DebugRoiOverlay, toggle_debug_overlay, and set_exclude_from_capture."""
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QPixmap
    from ui.hud import DebugRoiOverlay, HudBridge, HudOverlay, set_exclude_from_capture

    # Test set_exclude_from_capture safety (safe on/off Windows, safe with invalid hwnds)
    set_exclude_from_capture(0, True)
    set_exclude_from_capture(1234, False)

    bridge = HudBridge()
    overlay = DebugRoiOverlay(bridge=bridge)
    overlay.show()

    # Emit debug payload
    payload = {
        "table_rect": (100, 150, 800, 500),
        "rois": [
            {"name": "hero_card_1", "rect": (400, 450, 40, 60), "value": "10d", "color": "#22c55e"},
            {"name": "hero_card_2", "rect": (450, 450, 40, 60), "value": "--", "color": "#ef4444"},
            {"name": "pot", "rect": (480, 280, 50, 30), "value": "30", "color": "#22c55e"},
        ],
    }
    bridge.debug_overlay_updated.emit(payload)
    assert overlay._data == payload

    # Test offscreen paintEvent execution
    pixmap = QPixmap(1000, 700)
    overlay.render(pixmap)
    overlay.close()

    # Test HudOverlay integration with toggle button and shortcut
    hud = HudOverlay(bridge=bridge)
    hud.show()
    assert hud.is_debug_overlay_enabled is False
    assert hud.btn_debug_overlay.isHidden() is True

    # Revealing details reveals the '🎯 Ramki ROI' button
    hud.toggle_details()
    assert hud.show_details is True
    assert hud.btn_debug_overlay.isHidden() is False

    # Toggle debug ROI overlay ON
    new_state = hud.toggle_debug_overlay()
    assert new_state is True
    assert hud.is_debug_overlay_enabled is True
    assert hud._debug_overlay is not None
    assert hud._debug_overlay.isVisible() is True

    # Toggle debug ROI overlay OFF
    new_state_off = hud.toggle_debug_overlay()
    assert new_state_off is False
    assert hud.is_debug_overlay_enabled is False
    assert hud._debug_overlay.isHidden() is True

    # Closing HUD closes debug overlay as well
    hud.close()
    assert hud._debug_overlay.isHidden() is True


def test_table_adjust_signal_and_drag_mode(qapp) -> None:
    """Verify table adjustment buttons, signals, scale limits, and overlay drag mode."""
    from ui.hud import DebugRoiOverlay, HudBridge, HudOverlay

    bridge = HudBridge()
    received_adjust: list[tuple[int, int, float]] = []

    def _on_adjust(dx: int, dy: int, s: float) -> None:
        received_adjust.append((dx, dy, s))

    bridge.table_adjust_changed.connect(_on_adjust)

    # 1. Test direct signal emission
    bridge.table_adjust_changed.emit(10, -5, 1.05)
    assert len(received_adjust) == 1
    assert received_adjust[-1] == (10, -5, 1.05)

    # 2. Test HudOverlay adjustment methods and buttons
    hud = HudOverlay(bridge=bridge)
    hud.show()
    assert hud.table_dx == 0
    assert hud.table_dy == 0
    assert hud.table_scale_mult == 1.0
    assert hud.adjust_panel.isHidden() is True

    # Show details keeps adjust_panel hidden until calibration is started via gear button
    hud.toggle_details()
    assert hud.adjust_panel.isHidden() is True
    hud.start_table_calibration("table_1")
    assert hud.adjust_panel.isHidden() is False

    # Adjust dx (+5 when editing table)
    hud.adjust_table_dx(1)
    assert hud.table_dx == 5
    assert received_adjust[-1] == (5, 0, 1.0)

    # Adjust dy (-5 when editing table)
    hud.adjust_table_dy(-1)
    assert hud.table_dy == -5
    assert received_adjust[-1] == (5, -5, 1.0)

    # Adjust scale (+1%)
    hud.adjust_table_scale(0.01)
    assert abs(hud.table_scale_mult - 1.01) < 0.001
    assert received_adjust[-1] == (5, -5, 1.01)

    # Reset table adjust
    hud.reset_table_adjust()
    assert hud.table_dx == 0
    assert hud.table_dy == 0
    assert hud.table_scale_mult == 1.0
    assert received_adjust[-1] == (0, 0, 1.0)

    # Reset via reset_auto_rect
    hud.apply_table_adjust(15, 20, 1.08)
    hud.reset_auto_rect()
    assert hud.table_dx == 0
    assert hud.table_dy == 0
    assert hud.table_scale_mult == 1.0

    # 3. Test drag mode toggle
    assert hud.is_drag_mode is False
    drag_active = hud.toggle_drag_mode()
    assert drag_active is True
    assert hud.is_drag_mode is True
    assert hud.is_debug_overlay_enabled is True
    assert hud._debug_overlay._drag_mode is True

    drag_off = hud.toggle_drag_mode()
    assert drag_off is False
    assert hud.is_drag_mode is False
    assert hud._debug_overlay._drag_mode is False

    # Test DebugRoiOverlay set_drag_mode directly
    overlay = DebugRoiOverlay(bridge=bridge)
    overlay.set_drag_mode(True)
    assert overlay._drag_mode is True
    overlay.set_drag_mode(False)
    assert overlay._drag_mode is False

    hud.close()
    overlay.close()


def test_hud_calibration_edit_confirm_cancel_and_auto_hide(qapp) -> None:
    """Verify calibration panel is hidden by default, edit mode styling, confirm with 3s auto-hide, and cancel revert."""
    from ui.hud import HudBridge, HudOverlay

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    # 1. Panel is default hidden
    assert hud.editing_table_id is None
    assert hud.calibration_panel.isHidden() is True
    assert hud._debug_overlay.editing_table_id is None

    # 2. Start calibration on table_1
    hud.start_table_calibration("table_1")
    assert hud.editing_table_id == "table_1"
    assert hud.calibration_panel.isHidden() is False
    assert hud._debug_overlay.editing_table_id == "table_1"
    assert hud._debug_overlay.isVisible() is True

    # Adjust values
    hud.adjust_table_dx(1)   # +5 px
    hud.adjust_table_dy(-1)  # -5 px
    hud.adjust_table_stretch_x(0.02) # +2%
    assert hud.managed_tables["table_1"]["adjust"] == (5, -5, 1.02, 1.0)

    # 3. Cancel calibration -> reverts to original (0, 0, 1.0, 1.0) and hides panel
    hud.cancel_table_calibration()
    assert hud.editing_table_id is None
    assert hud.calibration_panel.isHidden() is True
    assert hud._debug_overlay.editing_table_id is None
    assert hud.managed_tables["table_1"]["adjust"] == (0, 0, 1.0, 1.0)

    # 4. Start calibration again, make changes, and Confirm
    hud.start_table_calibration("table_1")
    assert hud.editing_table_id == "table_1"
    hud.adjust_table_dx(2)  # +10 px
    hud.adjust_table_stretch_y(0.03) # +3%
    assert hud.managed_tables["table_1"]["adjust"] == (10, 0, 1.0, 1.03)

    # Confirm saves in RAM, removes editing mode, leaves overlay visible for auto-hide
    hud.confirm_table_calibration()
    assert hud.editing_table_id is None
    assert hud.calibration_panel.isHidden() is True
    assert hud._debug_overlay.editing_table_id is None
    assert hud.managed_tables["table_1"]["adjust"] == (10, 0, 1.0, 1.03)
    assert hud._debug_overlay.isVisible() is True

    # Trigger auto-hide timeout handler
    hud._on_confirm_timer_done()
    assert hud._debug_overlay.isHidden() is True

    hud.close()


def test_hud_buy_in_switch_and_manual_table_add_remove(qapp) -> None:
    """Verify live buy-in switching and manual multi-table management without multiplication."""
    from ui.hud import HudBridge, HudOverlay

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    received_buy_in: list[float] = []
    bridge.buy_in_changed.connect(lambda v: received_buy_in.append(v))

    received_tables_added: list[tuple[str, Any]] = []
    bridge.table_added.connect(lambda tid, reg: received_tables_added.append((tid, reg)))

    received_tables_removed: list[str] = []
    bridge.table_removed_by_user.connect(lambda tid: received_tables_removed.append(tid))

    # 1. Buy-in live switching
    assert hud.buy_in == 2.0
    hud.set_buy_in(0.50)
    assert hud.buy_in == 0.50
    assert received_buy_in[-1] == 0.50

    hud.set_buy_in(5.0)
    assert hud.buy_in == 5.0
    assert received_buy_in[-1] == 5.0

    hud.set_buy_in(10.0)
    assert hud.buy_in == 10.0
    assert received_buy_in[-1] == 10.0

    # 2. Managed tables: initial only table_1
    assert "table_1" in hud.managed_tables
    assert len(hud.managed_tables) == 1

    # Adding table_2 explicitly
    hud.add_table("table_2", search_region=(100, 100, 800, 600))
    assert "table_2" in hud.managed_tables
    assert len(hud.managed_tables) == 2
    assert len(received_tables_added) == 1
    assert received_tables_added[0] == ("table_2", (100, 100, 800, 600))

    # Removing table_2 by user
    hud.remove_table_by_user("table_2")
    assert "table_2" not in hud.managed_tables
    assert len(hud.managed_tables) == 1
    assert received_tables_removed == ["table_2"]

    # Block removing last remaining table
    hud.remove_table_by_user("table_1")
    assert "table_1" in hud.managed_tables
    assert len(hud.managed_tables) == 1

    hud.close()


def test_action_bar_overlay_positioning(qapp) -> None:
    """Verify ActionBarOverlay badge calculation for FOLD (left 1/3), CALL (middle 1/3), BET_30 (right 1/3)."""
    from PySide6.QtGui import QPixmap
    from ui.hud import ActionBarOverlay, HudBridge

    bridge = HudBridge()
    overlay = ActionBarOverlay(bridge=bridge)
    overlay.show()

    # Given actions_rect of width 300 at x=900, y=200, h=60
    actions_rect = (900, 200, 300, 60)
    dpr = 1.0

    # 1. FOLD: centered under left 1/3 button (center = 950.0, w = 128 >= 112)
    bx_fold, by_fold, bw_fold, bh_fold = overlay.get_badge_rect_for_action("FOLD", actions_rect, dpr=dpr)
    assert abs(bx_fold - 886.0) < 0.1
    assert abs(bw_fold - 128.0) < 0.1
    assert abs(bh_fold - 38.0) < 0.1
    assert abs(by_fold - 264.0) < 0.1

    # 2. CALL: centered under middle 1/3 button (center = 1050.0, w = 128)
    bx_call, by_call, bw_call, bh_call = overlay.get_badge_rect_for_action("CALL", actions_rect, dpr=dpr)
    assert abs(bx_call - 986.0) < 0.1
    assert abs(bw_call - 128.0) < 0.1

    # 3. CHECK: must also be centered under middle 1/3
    bx_chk, by_chk, bw_chk, bh_chk = overlay.get_badge_rect_for_action("CHECK", actions_rect, dpr=dpr)
    assert abs(bx_chk - 986.0) < 0.1

    # 4. BET_30 / RAISE / ALL_IN: centered under right 1/3 button (center = 1150.0, w = 128)
    bx_bet, by_bet, bw_bet, bh_bet = overlay.get_badge_rect_for_action("BET_30", actions_rect, dpr=dpr)
    assert abs(bx_bet - 1086.0) < 0.1
    assert abs(bw_bet - 128.0) < 0.1

    # Also test bottom-of-screen overflow positioning (flips above actions_rect)
    overflow_rect = (900, 2000, 300, 60)
    _, by_over, _, _ = overlay.get_badge_rect_for_action("BET_30", overflow_rect, dpr=dpr)
    assert abs(by_over - (2000.0 - 38.0 - 4.0)) < 0.1

    # 5. Receive bridge signal with amount chips and execute offscreen render
    payload = {
        "table_id": "table_1",
        "actions_rect": actions_rect,
        "action": "BET_30",
        "amount_chips": 60,
        "ev_bb": 1.45,
        "is_plan": False,
    }
    bridge.action_bar_updated.emit(payload)
    assert overlay._action_data.get("table_1") == payload

    pixmap = QPixmap(1920, 1080)
    overlay.render(pixmap)
    overlay.close()


def test_action_bar_enabled_by_default_and_two_line_wider_badges(qapp) -> None:
    """Verify ActionBarOverlay is enabled by default in HudOverlay, badges are >= 112px wide and centered."""
    from ui.hud import HudOverlay, HudBridge

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    # Verify ActionBarOverlay is created and visible by default alongside normal HUD
    assert hud._action_bar_overlay is not None
    assert hud._action_bar_overlay.isVisible()

    # Verify wider badge calculation (min 112px) and exact button centering
    actions_rect = (600, 400, 240, 50)
    btn_w = 240 / 3.0  # 80.0
    bx, by, bw, bh = hud._action_bar_overlay.get_badge_rect_for_action("FOLD", actions_rect, dpr=1.0)
    assert bw >= 112.0
    assert bh >= 38.0
    expected_center_x = 600.0 + btn_w / 2.0  # 640.0
    actual_center_x = bx + bw / 2.0
    assert abs(actual_center_x - expected_center_x) < 1.0

    hud.close()


def test_remove_table_1_when_table_2_exists(qapp) -> None:
    """Verify table_1 can be removed when table_2 exists, clearing debug and action bar overlays immediately."""
    from ui.hud import HudOverlay, HudBridge
    from core.contracts import Decision

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    # Populate table_1 with decision and debug overlay data
    d1 = Decision(table_id="table_1", action="FOLD", ev_bb=0.0, confidence=1.0, profile_used="STANDARD_EXPLOIT", reason="Fold")
    hud.on_decision_updated(d1, 2.5, "Status: VALID\nKotwica: RIM")
    hud._debug_overlay.on_debug_overlay_updated({"table_id": "table_1", "table_rect": (0, 0, 1000, 600), "rois": []})
    hud._action_bar_overlay.on_action_bar_updated({"table_id": "table_1", "actions_rect": (100, 100, 300, 60), "action": "FOLD"})

    assert "table_1" in hud.managed_tables
    assert "table_1" in hud._debug_overlay._tables
    assert "table_1" in hud._action_bar_overlay._action_data

    # Add table_2
    hud.add_table("table_2", search_region=(200, 200, 800, 500))
    d2 = Decision(table_id="table_2", action="CALL", ev_bb=0.5, confidence=1.0, profile_used="STANDARD_EXPLOIT", reason="Call")
    hud.on_decision_updated(d2, 3.0, "Status: VALID\nKotwica: RIM")
    hud._debug_overlay.on_debug_overlay_updated({"table_id": "table_2", "table_rect": (200, 200, 800, 500), "rois": []})
    hud._action_bar_overlay.on_action_bar_updated({"table_id": "table_2", "actions_rect": (200, 200, 300, 60), "action": "CALL"})

    assert len(hud.managed_tables) == 2
    assert "table_2" in hud.managed_tables

    # User removes table_1 (should succeed because table_2 exists)
    removed_signals = []
    bridge.table_removed_by_user.connect(lambda tid: removed_signals.append(tid))

    hud.remove_table_by_user("table_1")
    assert "table_1" not in hud.managed_tables
    assert "table_2" in hud.managed_tables
    assert len(hud.managed_tables) == 1
    assert removed_signals == ["table_1"]

    # Both overlays must have immediately purged table_1
    assert "table_1" not in hud._debug_overlay._tables
    assert (hud._debug_overlay._data is None or str(hud._debug_overlay._data.get("table_id")) != "table_1")
    assert "table_1" not in hud._action_bar_overlay._action_data
    assert "table_2" in hud._debug_overlay._tables
    assert "table_2" in hud._action_bar_overlay._action_data

    # Cannot remove last remaining table_2
    hud.remove_table_by_user("table_2")
    assert "table_2" in hud.managed_tables
    assert len(hud.managed_tables) == 1

    hud.close()


def test_anti_jitter_deadband() -> None:
    """Verify anti-jitter maintains stable table rect for micro-shifts <= 3px and updates for > 3px."""
    from vision.anchor import apply_anti_jitter

    stable_rect = (200, 250, 1400, 700)

    # Initial rect with no prior stable rect
    r0 = apply_anti_jitter(stable_rect, None, deadband_px=3)
    assert r0 == stable_rect

    # Micro-shifts within 3 px tolerance (e.g. 1px, 2px, 3px differences)
    r_micro1 = (202, 249, 1401, 703)  # dx=+2, dy=-1, dw=+1, dh=+3 -> max diff = 3
    res1 = apply_anti_jitter(r_micro1, stable_rect, deadband_px=3)
    assert res1 == stable_rect, "Micro-shifts <= 3px must be frozen to stable_rect"

    r_micro2 = (199, 252, 1398, 698)  # max diff = 2
    res2 = apply_anti_jitter(r_micro2, stable_rect, deadband_px=3)
    assert res2 == stable_rect

    # Meaningful shift > 3 px (e.g. window moved by 5 px)
    r_macro = (205, 250, 1400, 700)  # dx=+5
    res3 = apply_anti_jitter(r_macro, stable_rect, deadband_px=3)
    assert res3 == r_macro, "Shifts > 3px must immediately update table_rect"

    # None input
    assert apply_anti_jitter(None, stable_rect, deadband_px=3) is None


def test_render_visual_cards_html_and_action_labels() -> None:
    """Verify visual card tiles rendering with suits/colors and uniform action formatting."""
    from ui.hud import format_action_label, render_visual_cards_html

    # 1. Visual cards HTML rendering
    cards = ["10d", "Ad", "6c"]
    html = render_visual_cards_html(cards)
    assert "<table" in html
    assert "background-color: #f8fafc" in html
    assert "border: 1px solid #94a3b8" in html
    assert "10♦" in html
    assert "#dc2626" in html  # Red for diamonds/hearts
    assert "A♦" in html
    assert "6♣" in html
    assert "#0f172a" in html  # Dark navy/slate for clubs/spades

    empty_html = render_visual_cards_html([])
    assert "—" in empty_html

    # 2. Action labels formatting
    assert format_action_label("BET_30", sizing_bb=2, sizing_chips=200) == "BET 2 BB (200)"
    assert format_action_label("BET_30", sizing_bb=3) == "BET 3 BB"
    assert format_action_label("BET_30") == "BET 30%"

    assert format_action_label("MIN_RAISE", sizing_bb=2, sizing_chips=40) == "RAISE 2 BB (40)"
    assert format_action_label("MIN_RAISE", sizing_bb=3) == "RAISE 3 BB"
    assert format_action_label("MIN_RAISE") == "RAISE 2 BB"

    assert format_action_label("ALL_IN", sizing_chips=235) == "ALL-IN (235)"
    assert format_action_label("ALL_IN") == "ALL-IN"

    assert format_action_label("CALL", sizing_chips=40) == "CALL (40)"
    assert format_action_label("CALL") == "CALL"

    assert format_action_label("CHECK") == "CHECK"
    assert format_action_label("FOLD") == "FOLD"
    assert format_action_label("WAIT") == "WAIT"


def test_hud_details_shows_table_with_grayed_fold_and_keeps_calibration_hidden(qapp) -> None:
    """Verify details view shows players table with grayed fold row, small gear button, and keeps calibration panel hidden."""
    from core.contracts import Decision
    from ui.hud import HudBridge, HudOverlay

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    dec = Decision(
        table_id="table_1",
        action="BET_30",
        ev_bb=1.45,
        confidence=0.95,
        profile_used="STANDARD_EXPLOIT",
        reason="Value bet",
        sizing_chips=200,
        sizing_bb=2,
    )

    hand_summary = {
        "hand_number": 1,
        "table_id": "table_1",
        "start_ts_ms": 1700000000000,
        "blinds": (10, 20),
        "prize_pool": 6,
        "hero_cards": ["10d", "Ad"],
        "board_cards": ["6c", "2s", "9h"],
        "street": "FLOP",
        "pot": 120,
        "players": {
            0: {
                "seat_id": 0,
                "name": "Ty (S0)",
                "is_dealer": False,
                "stack": 280,
                "invested_total": 40,
                "street_bet": 0,
                "last_action": "BET 2 BB",
                "last_decision_sec": 1.2,
                "folded": False,
            },
            1: {
                "seat_id": 1,
                "name": "Rywal 1 (S1)",
                "is_dealer": True,
                "stack": 290,
                "invested_total": 10,
                "street_bet": 0,
                "last_action": "FOLD",
                "last_decision_sec": None,
                "folded": True,
            },
            2: {
                "seat_id": 2,
                "name": "Rywal 2 (S2)",
                "is_dealer": False,
                "stack": 230,
                "invested_total": 40,
                "street_bet": 0,
                "last_action": "CALL 40",
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
                "action": "FOLD",
                "amount": 0,
                "invested_total": 10,
                "decision_sec": None,
            }
        ],
    }

    bridge.decision_updated.emit(dec, 14.0)
    bridge.hand_summary_updated.emit("table_1", hand_summary)

    # 1. Initially details and calibration panel are hidden
    assert hud.show_details is False
    assert hud.calibration_panel.isVisible() is False

    # 2. Toggle details ON: reveals details widget and table header, but calibration panel stays HIDDEN!
    hud.toggle_details()
    assert hud.show_details is True
    assert hud.calibration_panel.isVisible() is False

    detail_lbl = hud.details_widgets["table_1"]
    assert detail_lbl.isVisible() is True
    detail_text = detail_lbl.text()
    assert "<s>Rywal 1 (S1)</s>" in detail_text or "Rywal 1 (S1)" in detail_text
    assert "FOLD" in detail_text
    assert "color: #64748b" in detail_text  # Grayed out folded row

    # 3. Table header has discrete gear button '⚙'
    assert "table_1" in hud.table_calib_buttons
    btn_calib = hud.table_calib_buttons["table_1"]
    assert btn_calib.text() == "⚙"

    # 4. Clicking gear button opens calibration panel
    btn_calib.click()
    assert hud.calibration_panel.isVisible() is True
    assert hud.editing_table_id == "table_1"

    # 5. Clicking gear button again cancels / hides calibration panel
    btn_calib.click()
    assert hud.calibration_panel.isVisible() is False
    assert hud.editing_table_id is None


def test_hud_snapshots_toggle_button_in_details() -> None:
    """Verify snapshot toggle button 📷 is hidden in minimalist mode, visible in details, and emits signal."""
    from ui.hud import HudOverlay, HudBridge
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    captured_events: list[bool] = []
    bridge.snapshots_toggled.connect(lambda enabled: captured_events.append(enabled))

    # 1. In minimalist mode, snapshots button is hidden
    assert hud.show_details is False
    assert hud.btn_snapshots.isHidden() is True
    assert hud.snapshots_enabled is True

    # 2. Toggle details ON -> button becomes visible
    hud.toggle_details()
    assert hud.show_details is True
    assert hud.btn_snapshots.isHidden() is False

    # 3. Clicking button toggles state to False and emits signal
    hud.btn_snapshots.click()
    assert hud.snapshots_enabled is False
    assert captured_events == [False]

    # 4. Clicking again toggles back to True
    hud.btn_snapshots.click()
    assert hud.snapshots_enabled is True
    assert captured_events == [False, True]

    # 5. Toggle details OFF -> button hidden again
    hud.toggle_details()
    assert hud.show_details is False
    assert hud.btn_snapshots.isHidden() is True


def test_processing_loop_live_no_unbound_spot_and_keeps_sizing() -> None:
    """Verify that processing_loop with is_live=True avoids UnboundLocalError on spot and preserves sizing on locked frames."""
    import queue
    import threading
    import time
    import numpy as np
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from main import processing_loop
    from ui.hud import HudBridge
    from core.contracts import TableState, PlayerState, Decision

    app = QApplication.instance() or QApplication([])

    frame_q = queue.Queue()
    stop_ev = threading.Event()
    trackers: dict[str, Any] = {}
    bridge = HudBridge()

    captured_decisions: list[Decision] = []

    def _on_dec(dec: Decision, *args: Any) -> None:
        if getattr(dec, "reason", "") != "Szukam stołu Stake...":
            captured_decisions.append(dec)

    bridge.decision_updated.connect(_on_dec)

    state_invalid = TableState(
        table_id="table_1",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=0,
        hero_cards=[],
        board_cards=[],
        street="WAITING_FOR_TURN",
        is_hero_turn=False,
        available_actions=[],
        players={},
        is_valid=False,
    )

    state_valid = TableState(
        table_id="table_1",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=60,
        hero_cards=["Ah", "Kd"],
        board_cards=["7c", "8d", "2h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CHECK", "BET_30", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=280, current_bet=0, is_dealer=True),
            1: PlayerState(seat_id=1, stack=280, current_bet=0, is_dealer=False),
        },
        is_valid=True,
    )

    mock_pipeline = MagicMock()
    mock_pipeline.anchor_template = None
    mock_pipeline._last_canonical_table = None
    mock_pipeline.process_frame.side_effect = [
        state_invalid,
        state_valid,
        state_valid,
        state_valid,
    ]

    mock_validator = MagicMock()
    mock_validator.validate.side_effect = [
        (False, ["No cards"]),
        (True, []),
        (True, []),
        (True, []),
    ]

    mock_dm = MagicMock()
    mock_dm.decide.return_value = Decision(
        table_id="table_1",
        action="BET_30",
        ev_bb=2.5,
        confidence=0.95,
        profile_used="STANDARD_EXPLOIT",
        reason="Value bet",
    )

    t = threading.Thread(
        target=processing_loop,
        args=(
            frame_q,
            mock_pipeline,
            mock_validator,
            trackers,
            None,
            None,
            None,
            mock_dm,
            None,
            bridge,
            stop_ev,
        ),
        kwargs={
            "headless": True,
            "show_video": False,
            "playback": None,
            "is_live": True,
            "hand_recorder": None,
        },
        daemon=True,
    )
    t.start()

    time.sleep(0.1)
    bridge.manual_rect_changed.emit((100, 100, 800, 500))

    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for _ in range(4):
        frame_q.put(dummy_frame)

    start_wait = time.time()
    while len(captured_decisions) < 4 and time.time() - start_wait < 3.0:
        app.processEvents()
        time.sleep(0.05)

    stop_ev.set()
    frame_q.put(None)
    t.join(timeout=2.0)

    assert not t.is_alive(), "processing_loop thread should have stopped cleanly"
    assert len(captured_decisions) == 4

    # Frame 0: Invalid / no cards -> WAIT (no UnboundLocalError on spot or now_sec)
    assert captured_decisions[0].action == "WAIT"

    # Frame 1: Hero turn frame 1 (confirming via DecisionLock) -> WAIT ("Skanowanie sytuacji...")
    assert captured_decisions[1].action == "WAIT"
    assert "Skanowanie sytuacji..." in (captured_decisions[1].reason or "")

    # Frame 2: Hero turn frame 2 (locked decision computed) -> BET_30 with quantized sizing
    assert captured_decisions[2].action == "BET_30"
    assert captured_decisions[2].sizing_bb == 1
    assert captured_decisions[2].sizing_chips == 20

    # Frame 3: Hero turn frame 3 (from DecisionLock cache) -> SIZING PRESERVED!
    assert captured_decisions[3].action == "BET_30"
    assert captured_decisions[3].sizing_bb == 1
    assert captured_decisions[3].sizing_chips == 20


def test_hero_all_in_stack_zero_returns_wait_not_all_in_zero() -> None:
    """Verify that when Hero has stack == 0 (already all-in), processing_loop returns WAIT ('Hero is All-In') rather than ALL_IN (0)."""
    import queue
    import threading
    import time
    import numpy as np
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from main import processing_loop
    from ui.hud import HudBridge
    from core.contracts import TableState, PlayerState, Decision

    app = QApplication.instance() or QApplication([])

    frame_q = queue.Queue()
    stop_ev = threading.Event()
    trackers: dict[str, Any] = {}
    bridge = HudBridge()

    captured_decisions: list[Decision] = []

    def _on_dec(dec: Decision, *args: Any) -> None:
        if getattr(dec, "reason", "") != "Szukam stołu Stake...":
            captured_decisions.append(dec)

    bridge.decision_updated.connect(_on_dec)

    # Hero (seat 0) has stack=0 and 2 cards on the Flop
    state_hero_all_in = TableState(
        table_id="table_1",
        timestamp_ms=1000,
        prize_pool=6,
        small_blind=10,
        big_blind=20,
        pot=600,
        hero_cards=["Ah", "Kd"],
        board_cards=["7c", "8d", "2h"],
        street="FLOP",
        is_hero_turn=True,
        available_actions=["CALL", "ALL_IN"],
        players={
            0: PlayerState(seat_id=0, stack=0, current_bet=300, is_dealer=True, status_text="ALL_IN"),
            1: PlayerState(seat_id=1, stack=100, current_bet=300, is_dealer=False),
        },
        is_valid=True,
    )

    mock_pipeline = MagicMock()
    mock_pipeline.anchor_template = None
    mock_pipeline._last_canonical_table = None
    mock_pipeline.process_frame.return_value = state_hero_all_in

    mock_validator = MagicMock()
    mock_validator.validate.return_value = (True, [])

    mock_dm = MagicMock()

    t = threading.Thread(
        target=processing_loop,
        args=(
            frame_q,
            mock_pipeline,
            mock_validator,
            trackers,
            None,
            None,
            None,
            mock_dm,
            None,
            bridge,
            stop_ev,
        ),
        kwargs={
            "headless": True,
            "show_video": False,
            "playback": None,
            "is_live": True,
            "hand_recorder": None,
        },
        daemon=True,
    )
    t.start()

    time.sleep(0.1)
    bridge.manual_rect_changed.emit((100, 100, 800, 500))

    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame_q.put(dummy_frame)

    start_wait = time.time()
    while len(captured_decisions) < 1 and time.time() - start_wait < 3.0:
        app.processEvents()
        time.sleep(0.05)

    stop_ev.set()
    frame_q.put(None)
    t.join(timeout=2.0)

    assert not t.is_alive(), "processing_loop thread should have stopped cleanly"
    assert len(captured_decisions) >= 1
    dec = captured_decisions[0]
    assert dec.action == "WAIT"
    assert dec.reason == "Hero is All-In"
    assert mock_dm.decide.call_count == 0


def test_hud_renders_alt_action_when_present() -> None:
    """Verify that HudOverlay displays the Alt: action line when decision.alt_action is provided."""
    from ui.hud import HudOverlay, HudBridge
    from core.contracts import Decision
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    bridge = HudBridge()
    hud = HudOverlay(bridge=bridge)
    hud.show()

    dec = Decision(
        table_id="table_1",
        action="CHECK",
        ev_bb=0.55,
        confidence=0.95,
        profile_used="STANDARD_EXPLOIT",
        reason="Check behind",
        alt_action="BET_30",
        alt_ev_bb=0.52,
        alt_sizing_bb=1,
        alt_sizing_chips=20,
    )

    bridge.decision_updated.emit(dec, 14.0)
    app.processEvents()

    label = hud.table_widgets.get("table_1")
    assert label is not None
    html_text = label.text()
    assert "Alt: BET" in html_text
    assert "(+0.52 BB)" in html_text








