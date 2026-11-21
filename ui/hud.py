"""HUD overlay for poker_assistant using PySide6.

Features:
- Windows click-through (WS_EX_TRANSPARENT)
- Movable when unlocked (shortcut Ctrl+Shift+L)
- Multi-table support (table_widgets: dict[str, QLabel])
- Real-time action recommendation badge, EV, latency, and exploit reason
- Exclusion from screen capture (WDA_EXCLUDEFROMCAPTURE)
- Debug ROI overlay with live calibration edit mode and 3-second auto-hide
- Action-Only bar overlay (ActionBarOverlay) directly below game buttons
- Dynamic Buy-in selector ($0.50 / $2 / $5 / $10)
- Manual multi-table add/remove without table multiplication
"""

from __future__ import annotations

import ctypes
import inspect
import sys
from typing import Any

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal, Slot, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from core.contracts import Decision
except ImportError:
    Decision = Any  # type: ignore[misc, assignment]


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Enable or disable mouse click-through for a window on Windows.

    Args:
        hwnd: Native OS window handle.
        enabled: True to make clicks pass through, False to make clickable.
    """
    if sys.platform != "win32" or not hwnd:
        return

    try:
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        user32 = ctypes.windll.user32

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            new_style = (style | WS_EX_LAYERED) | WS_EX_TRANSPARENT
        else:
            new_style = (style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
    except Exception:
        pass


def set_exclude_from_capture(hwnd: int, enabled: bool = True) -> None:
    """Exclude a window from screen capture (dxcam / BitBlt / Desktop Duplication) on Windows.

    Uses SetWindowDisplayAffinity with WDA_EXCLUDEFROMCAPTURE (0x00000011).
    Args:
        hwnd: Native OS window handle.
        enabled: True to exclude from capture, False to restore normal capture.
    """
    if sys.platform != "win32" or not hwnd:
        return

    try:
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        WDA_NONE = 0x00000000
        affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity)
    except Exception:
        pass


class _DecisionSignalDescriptor:
    """Descriptor supporting both 2-arg (legacy) and 3-arg decision_updated emissions."""

    def __set_name__(self, owner: Any, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return owner._raw_decision_updated
        if not hasattr(instance, "_wrapped_decision_updated"):
            class _Wrapper:
                def __init__(self, obj: Any) -> None:
                    self._obj = obj

                def connect(self, slot: Any) -> None:
                    self._obj._raw_decision_updated.connect(slot)
                    self._obj._raw_decision_updated[object, float].connect(slot)

                def disconnect(self, *args: Any) -> None:
                    try:
                        self._obj._raw_decision_updated.disconnect(*args)
                    except Exception:
                        pass
                    try:
                        self._obj._raw_decision_updated[object, float].disconnect(*args)
                    except Exception:
                        pass

                def emit(self, *args: Any) -> None:
                    if len(args) == 2:
                        self._obj._raw_decision_updated[object, float].emit(*args)
                    else:
                        self._obj._raw_decision_updated.emit(*args)

                def __getitem__(self, item: Any) -> Any:
                    return self._obj._raw_decision_updated[item]

            instance._wrapped_decision_updated = _Wrapper(instance)
        return instance._wrapped_decision_updated


class _TableAdjustSignalDescriptor:
    """Descriptor supporting both legacy 3-arg (dx, dy, s) and 5-arg (tid, dx, dy, sx, sy) emissions."""

    def __set_name__(self, owner: Any, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return owner._raw_table_adjust_changed
        if not hasattr(instance, "_wrapped_table_adjust_changed"):
            class _Wrapper:
                def __init__(self, obj: Any) -> None:
                    self._obj = obj

                def connect(self, slot: Any) -> None:
                    try:
                        sig = inspect.signature(slot)
                        num_params = len([
                            p for p in sig.parameters.values()
                            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                        ])
                        if num_params == 3:
                            self._obj._raw_table_adjust_changed[int, int, float].connect(slot)
                            return
                        elif num_params == 5:
                            self._obj._raw_table_adjust_changed[str, int, int, float, float].connect(slot)
                            return
                    except Exception:
                        pass
                    try:
                        self._obj._raw_table_adjust_changed[int, int, float].connect(slot)
                    except Exception:
                        pass
                    try:
                        self._obj._raw_table_adjust_changed.connect(slot)
                    except Exception:
                        pass

                def disconnect(self, *args: Any) -> None:
                    try:
                        self._obj._raw_table_adjust_changed.disconnect(*args)
                    except Exception:
                        pass
                    try:
                        self._obj._raw_table_adjust_changed[int, int, float].disconnect(*args)
                    except Exception:
                        pass
                    try:
                        self._obj._raw_table_adjust_changed[str, int, int, float, float].disconnect(*args)
                    except Exception:
                        pass

                def emit(self, *args: Any) -> None:
                    if len(args) == 3:
                        self._obj._raw_table_adjust_changed[int, int, float].emit(*args)
                    elif len(args) == 5:
                        self._obj._raw_table_adjust_changed.emit(*args)
                    else:
                        self._obj._raw_table_adjust_changed.emit(*args)

                def __getitem__(self, item: Any) -> Any:
                    return self._obj._raw_table_adjust_changed[item]

            instance._wrapped_table_adjust_changed = _Wrapper(instance)
        return instance._wrapped_table_adjust_changed


def format_cards_html(scan_summary: str) -> str:
    """Extract and format Hero and Board cards into a rich HTML snippet with colored suits."""
    if not scan_summary:
        return ""

    hero_str = ""
    board_str = ""
    for line in scan_summary.splitlines():
        line = line.strip()
        if line.startswith("Hero:"):
            parts = line.split("|")
            hero_str = parts[0].replace("Hero:", "").strip()
            if len(parts) > 1 and "Board:" in parts[1]:
                board_str = parts[1].replace("Board:", "").strip()
            break

    def _fmt(tokens_str: str) -> str:
        out = []
        for token in tokens_str.split():
            token = token.strip("[],'\"")
            if not token or token == "--":
                continue
            rank = token[:-1]
            suit = token[-1]
            if rank in ("T", "10"):
                rank = "10"
            if suit in ("h", "H"):
                s_sym = '<span style="color:#ff5c5c; font-weight:bold;">♥</span>'
            elif suit in ("d", "D"):
                s_sym = '<span style="color:#ff5c5c; font-weight:bold;">♦</span>'
            elif suit in ("s", "S"):
                s_sym = '<span style="color:#e2e8f0; font-weight:bold;">♠</span>'
            elif suit in ("c", "C"):
                s_sym = '<span style="color:#e2e8f0; font-weight:bold;">♣</span>'
            else:
                s_sym = suit
            out.append(f"<span style='color:#ffffff; font-weight:bold;'>{rank}</span>{s_sym}")
        return " ".join(out)

    hero_fmt = _fmt(hero_str)
    board_fmt = _fmt(board_str)

    if hero_fmt and board_fmt:
        return f"🃏 {hero_fmt} &nbsp;&bull;&nbsp; <span style='color:#94a3b8;'>Board:</span> {board_fmt}"
    elif hero_fmt:
        return f"🃏 {hero_fmt}"
    elif board_fmt:
        return f"<span style='color:#94a3b8;'>Board:</span> {board_fmt}"
    return ""


class HudBridge(QObject):
    """Thread-safe Qt signal bridge delivering decisions to HUD."""

    _raw_decision_updated = Signal((object, float, str), (object, float))
    decision_updated = _DecisionSignalDescriptor()
    manual_rect_changed = Signal(object)
    table_removed = Signal(str)
    table_removed_by_user = Signal(str)
    table_added = Signal(str, object)
    _raw_table_adjust_changed = Signal((str, int, int, float, float), (int, int, float))
    table_adjust_changed = _TableAdjustSignalDescriptor()
    debug_overlay_updated = Signal(object)
    buy_in_changed = Signal(float)
    action_bar_updated = Signal(object)


class RegionSelectorOverlay(QWidget):
    """Fullscreen semi-transparent overlay for selecting table ROI with mouse."""

    selected = Signal(object)

    def __init__(
        self,
        on_selected: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if on_selected is not None:
            self.selected.connect(on_selected)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._start_pos: QPoint | None = None
        self._current_pos: QPoint | None = None
        self._is_selecting: bool = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_pos = event.position().toPoint()
            self._current_pos = self._start_pos
            self._is_selecting = True
            self.update()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_selecting:
            self._current_pos = event.position().toPoint()
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._is_selecting and event.button() == Qt.MouseButton.LeftButton:
            self._is_selecting = False
            if self._start_pos is not None:
                end_pos = event.position().toPoint()
                x1 = min(self._start_pos.x(), end_pos.x())
                y1 = min(self._start_pos.y(), end_pos.y())
                x2 = max(self._start_pos.x(), end_pos.x())
                y2 = max(self._start_pos.y(), end_pos.y())
                w = x2 - x1
                h = y2 - y1

                if w >= 50 and h >= 50:
                    dpr = self.devicePixelRatio()
                    phys_x = int(round(x1 * dpr))
                    phys_y = int(round(y1 * dpr))
                    phys_w = int(round(w * dpr))
                    phys_h = int(round(h * dpr))
                    self.selected.emit((phys_x, phys_y, phys_w, phys_h))
            self.close()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self._is_selecting and self._start_pos and self._current_pos:
            x1 = min(self._start_pos.x(), self._current_pos.x())
            y1 = min(self._start_pos.y(), self._current_pos.y())
            w = abs(self._current_pos.x() - self._start_pos.x())
            h = abs(self._current_pos.y() - self._start_pos.y())

            pen = QPen(QColor("#f1c40f"))
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(241, 196, 15, 35))
            painter.drawRect(x1, y1, w, h)

            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            painter.drawText(x1 + 6, max(20, y1 - 6), f"{w} x {h} px")

        painter.setPen(QColor("#f1c40f"))
        painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        info_text = "📐 Zaznacz stół pokera (przeciągnij myszą) | Naciśnij ESC, aby anulować"
        painter.drawText(self.rect().adjusted(0, 30, 0, 0), Qt.AlignmentFlag.AlignHCenter, info_text)


class ActionBarOverlay(QWidget):
    """Frameless, transparent, click-through overlay showing action badges directly below hero_actions buttons."""

    def __init__(
        self,
        bridge: HudBridge | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self._action_data: dict[str, dict[str, Any]] = {}

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.virtualGeometry())

        if self.bridge is not None and hasattr(self.bridge, "action_bar_updated"):
            self.bridge.action_bar_updated.connect(self.on_action_bar_updated)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        hwnd = int(self.winId()) if self.effectiveWinId() else 0
        set_click_through(hwnd, True)
        set_exclude_from_capture(hwnd, True)

    @Slot(object)
    def on_action_bar_updated(self, data: Any) -> None:
        """Receive updated action bar data for a table."""
        if isinstance(data, dict):
            tid = str(data.get("table_id") or "table_1")
            self._action_data[tid] = data
            if self.isVisible():
                self.update()

    def remove_table(self, table_id: str) -> None:
        """Remove a stale table action bar."""
        self._action_data.pop(table_id, None)
        if self.isVisible():
            self.update()

    def get_badge_rect_for_action(
        self, action: str, actions_rect: tuple[int, int, int, int], dpr: float = 1.0
    ) -> tuple[float, float, float, float]:
        """Compute logical bounding box for the action badge (useful for tests and paint)."""
        ax, ay, aw, ah = actions_rect
        lax = ax / dpr
        lay = ay / dpr
        law = aw / dpr
        lah = ah / dpr

        col_w = law / 3.0
        bar_h = 28.0
        bar_y = lay + lah + 4.0

        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            screen_h = screen.geometry().height()
            if bar_y + bar_h > screen_h:
                bar_y = max(4.0, lay - bar_h - 4.0)

        # Columns: 0 = Fold, 1 = Check/Call, 2 = Bet/Raise/All-In
        act_upper = action.upper()
        if act_upper == "FOLD":
            col_x = lax
        elif act_upper in ("CHECK", "CALL"):
            col_x = lax + col_w
        else:
            col_x = lax + 2.0 * col_w

        return (col_x, bar_y, col_w, bar_h)

    def paintEvent(self, event: Any) -> None:
        if not self._action_data:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        screen = self.screen() or QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        dpr = max(0.1, dpr)

        font_action = QFont("Arial", 11, QFont.Weight.Bold)

        for tid, data in self._action_data.items():
            if not data:
                continue
            action = str(data.get("action") or "WAIT").upper()
            if action in ("WAIT", "", "NONE"):
                continue

            actions_rect = data.get("actions_rect")
            if not actions_rect or len(actions_rect) < 4:
                continue

            bx, by, bw, bh = self.get_badge_rect_for_action(action, actions_rect, dpr)
            amt = data.get("amount_chips")
            is_plan = bool(data.get("is_plan", False))

            if action == "FOLD":
                text = "▲ PLAN: FOLD" if is_plan else "▲ FOLD"
                bg_color = QColor(192, 57, 43, 200 if is_plan else 245)
                border_color = QColor("#e74c3c")
            elif action == "CHECK":
                text = "▲ PLAN: CHECK" if is_plan else "▲ CHECK"
                bg_color = QColor(230, 126, 34, 200 if is_plan else 245)
                border_color = QColor("#f39c12")
            elif action == "CALL":
                amt_str = f" {amt}" if amt is not None else ""
                text = f"▲ PLAN: CALL{amt_str}" if is_plan else f"▲ CALL{amt_str}"
                bg_color = QColor(230, 126, 34, 200 if is_plan else 245)
                border_color = QColor("#f39c12")
            elif action == "BET_30":
                amt_str = f" {amt}" if amt is not None else ""
                text = f"▲ PLAN: BET{amt_str}" if is_plan else f"▲ BET{amt_str}"
                bg_color = QColor(39, 174, 96, 200 if is_plan else 245)
                border_color = QColor("#2ecc71")
            elif action == "MIN_RAISE":
                amt_str = f" {amt}" if amt is not None else ""
                text = f"▲ PLAN: RAISE{amt_str}" if is_plan else f"▲ RAISE{amt_str}"
                bg_color = QColor(39, 174, 96, 200 if is_plan else 245)
                border_color = QColor("#2ecc71")
            elif action == "ALL_IN":
                amt_str = f" {amt}" if (amt is not None and amt > 0) else ""
                text = f"▲ PLAN: ALL-IN{amt_str}" if is_plan else f"▲ ALL-IN{amt_str}"
                bg_color = QColor(39, 174, 96, 200 if is_plan else 245)
                border_color = QColor("#2ecc71")
            else:
                amt_str = f" {amt}" if amt is not None else ""
                text = f"▲ {action}{amt_str}"
                bg_color = QColor(41, 128, 185, 200 if is_plan else 245)
                border_color = QColor("#3498db")

            badge_rect = QRectF(bx + 2, by, bw - 4, bh)

            pen = QPen(border_color, 1.5)
            pen.setStyle(Qt.PenStyle.DashLine if is_plan else Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(bg_color)
            painter.drawRoundedRect(badge_rect, 5, 5)

            painter.setPen(QColor("#ffffff"))
            painter.setFont(font_action)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)


class DebugRoiOverlay(QWidget):
    """Fullscreen semi-transparent click-through overlay drawing table bounds and ROIs."""

    def __init__(
        self,
        bridge: HudBridge | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self._data: dict[str, Any] | None = None
        self._tables: dict[str, dict[str, Any]] = {}
        self.editing_table_id: str | None = None
        self._drag_mode: bool = False
        self._drag_start_pos: QPoint | None = None
        self._drag_start_adjust: tuple[int, int] = (0, 0)
        self._current_dx: int = 0
        self._current_dy: int = 0
        self._current_scale: float = 1.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.virtualGeometry())

        if self.bridge is not None and hasattr(self.bridge, "debug_overlay_updated"):
            self.bridge.debug_overlay_updated.connect(self.on_debug_overlay_updated)
        if self.bridge is not None and hasattr(self.bridge, "table_removed"):
            self.bridge.table_removed.connect(self.remove_table)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        hwnd = int(self.winId()) if self.effectiveWinId() else 0
        set_click_through(hwnd, True)
        set_exclude_from_capture(hwnd, True)

    @Slot(object)
    def on_debug_overlay_updated(self, data: Any) -> None:
        """Receive updated table & ROI rectangles and redraw."""
        if isinstance(data, dict):
            self._data = data
            tid = str(data.get("table_id") or "default")
            self._tables[tid] = data
            if self.isVisible():
                self.update()

    @Slot(str)
    def remove_table(self, table_id: str) -> None:
        """Remove a stale table from debug overlay."""
        self._tables.pop(table_id, None)
        if self.isVisible():
            self.update()

    def set_drag_mode(self, enabled: bool) -> None:
        """Enable or disable interactive table dragging mode."""
        self._drag_mode = enabled
        hwnd = int(self.winId()) if self.effectiveWinId() else 0
        if enabled:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            set_click_through(hwnd, False)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            set_click_through(hwnd, True)
            self.unsetCursor()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_start_adjust = (self._current_dx, self._current_dy)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode and self._drag_start_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            screen = self.screen() or QApplication.primaryScreen()
            dpr = screen.devicePixelRatio() if screen else 1.0
            new_dx = self._drag_start_adjust[0] + int(round(delta.x() * dpr))
            new_dy = self._drag_start_adjust[1] + int(round(delta.y() * dpr))
            self._current_dx = new_dx
            self._current_dy = new_dy
            if self.bridge is not None and hasattr(self.bridge, "table_adjust_changed"):
                tid = self.editing_table_id or "table_1"
                try:
                    self.bridge.table_adjust_changed.emit(tid, new_dx, new_dy, self._current_scale, self._current_scale)
                except Exception:
                    pass
                try:
                    self.bridge.table_adjust_changed.emit(new_dx, new_dy, self._current_scale)
                except Exception:
                    pass
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
            self.set_drag_mode(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event: Any) -> None:
        if not self._data and not self._tables:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        screen = self.screen() or QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        dpr = max(0.1, dpr)

        font_tbl = QFont("Arial", 9, QFont.Weight.Bold)
        fm_tbl = QFontMetrics(font_tbl)
        font_roi = QFont("Arial", 8, QFont.Weight.Bold)
        fm_roi = QFontMetrics(font_roi)

        short_map = {
            "hero_card_1": "H1",
            "hero_card_2": "H2",
            "board_card_1": "B1",
            "board_card_2": "B2",
            "board_card_3": "B3",
            "board_card_4": "B4",
            "board_card_5": "B5",
            "pot": "Pot",
            "prize_pool": "Prize",
            "blinds": "Blinds",
            "hero_actions": "Acts",
            "seat_0_timer": "Turn",
            "seat_0_stack": "S0 stk",
            "seat_0_bet": "S0 bet",
            "seat_0_dealer": "S0 [D]",
            "seat_1_stack": "S1 stk",
            "seat_1_bet": "S1 bet",
            "seat_1_dealer": "S1 [D]",
            "seat_2_stack": "S2 stk",
            "seat_2_bet": "S2 bet",
            "seat_2_dealer": "S2 [D]",
        }

        tables_to_draw = list(self._tables.values()) if self._tables else ([self._data] if self._data else [])

        for tbl_data in tables_to_draw:
            if not tbl_data:
                continue

            tid = str(tbl_data.get("table_id") or "default")
            is_editing = (self.editing_table_id is not None and self.editing_table_id == tid)

            table_rect = tbl_data.get("table_rect")
            if table_rect and len(table_rect) >= 4:
                tx, ty, tw, th = table_rect
                lx = tx / dpr
                ly = ty / dpr
                lw = tw / dpr
                lh = th / dpr

                if is_editing:
                    # Highlight table in edit mode (bright orange / gold)
                    pen = QPen(QColor("#f39c12"))
                    pen.setWidth(3)
                    pen.setStyle(Qt.PenStyle.SolidLine)
                    painter.setPen(pen)
                    painter.setBrush(QColor(243, 156, 18, 30))
                    painter.drawRect(QRectF(lx, ly, lw, lh))

                    tbl_label = f"✎ [TRYB EDYCJI - {tid}] ({int(tx)}, {int(ty)}, {int(tw)}x{int(th)})"
                    lbl_w = fm_tbl.horizontalAdvance(tbl_label) + 12
                    lbl_h = fm_tbl.height() + 6
                    lbl_rect = QRectF(lx + 4, max(4.0, ly - lbl_h - 2), lbl_w, lbl_h)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(15, 23, 42, 245))
                    painter.drawRoundedRect(lbl_rect, 4, 4)
                    painter.setPen(QColor("#f39c12"))
                    painter.setFont(font_tbl)
                    painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, tbl_label)
                else:
                    # Distinct dashed table outline (cyan)
                    pen = QPen(QColor("#00f0ff"))
                    pen.setWidth(2)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(QColor(0, 240, 255, 12))
                    painter.drawRect(QRectF(lx, ly, lw, lh))

                    tbl_label = f"TABLE ({int(tx)}, {int(ty)}, {int(tw)}x{int(th)})"
                    lbl_w = fm_tbl.horizontalAdvance(tbl_label) + 8
                    lbl_h = fm_tbl.height() + 4
                    lbl_rect = QRectF(lx + 4, max(4.0, ly - lbl_h - 2), lbl_w, lbl_h)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(15, 23, 42, 220))
                    painter.drawRoundedRect(lbl_rect, 3, 3)
                    painter.setPen(QColor("#00f0ff"))
                    painter.setFont(font_tbl)
                    painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, tbl_label)

            # Draw ROIs
            rois = tbl_data.get("rois", [])
            for roi in rois:
                rect = roi.get("rect")
                if not rect or len(rect) < 4:
                    continue
                rx, ry, rw, rh = rect
                if rw <= 0 or rh <= 0:
                    continue

                rlx = rx / dpr
                rly = ry / dpr
                rlw = rw / dpr
                rlh = rh / dpr

                name = roi.get("name", "")
                val = str(roi.get("value", "--"))
                color_str = roi.get("color")
                if not color_str:
                    is_detected = val not in ("--", "", "None", "0")
                    color_str = "#22c55e" if is_detected else "#ef4444"

                roi_color = QColor("#f39c12") if is_editing else QColor(color_str)
                pen = QPen(roi_color)
                pen.setWidth(2 if is_editing else 1)
                painter.setPen(pen)
                fill = QColor(roi_color)
                fill.setAlpha(30 if is_editing else 20)
                painter.setBrush(fill)
                painter.drawRect(QRectF(rlx, rly, rlw, rlh))

                short_name = short_map.get(name, name)
                lbl_text = f"{short_name}: {val}" if val and val != "--" else f"{short_name}: --"

                tw_txt = fm_roi.horizontalAdvance(lbl_text) + 6
                th_txt = fm_roi.height() + 2
                lbl_y = rly - th_txt if rly >= th_txt else rly + 2
                lbl_bg = QRectF(rlx, lbl_y, tw_txt, th_txt)

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(15, 23, 42, 230))
                painter.drawRoundedRect(lbl_bg, 2, 2)

                painter.setPen(QColor("#ffffff") if val != "--" else QColor("#94a3b8"))
                painter.setFont(font_roi)
                painter.drawText(lbl_bg, Qt.AlignmentFlag.AlignCenter, lbl_text)


class HudOverlay(QWidget):
    """Frameless, always-on-top, click-through HUD overlay."""

    def __init__(
        self,
        bridge: HudBridge | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bridge = bridge

        self.table_widgets: dict[str, QLabel] = {}
        self.table_header_widgets: dict[str, QWidget] = {}
        self.table_delete_buttons: dict[str, QPushButton] = {}
        self.details_widgets: dict[str, QLabel] = {}
        self.cards_line_by_table: dict[str, str] = {}
        self.is_locked: bool = False
        self.show_details: bool = False
        self.is_debug_overlay_enabled: bool = False
        self.is_action_only_mode: bool = False

        self.buy_in: float = 2.0
        self.managed_tables: dict[str, dict[str, Any]] = {
            "table_1": {"search_region": None, "adjust": (0, 0, 1.0, 1.0)}
        }
        self.editing_table_id: str | None = None
        self._pre_edit_adjust: tuple[int, int, float, float] = (0, 0, 1.0, 1.0)

        # Legacy backward-compat attributes for table_1
        self.table_dx: int = 0
        self.table_dy: int = 0
        self.table_scale_mult: float = 1.0
        self.table_scale_x: float = 1.0
        self.table_scale_y: float = 1.0

        self.is_drag_mode: bool = False
        self._drag_pos: QPoint | None = None
        self._selector: RegionSelectorOverlay | None = None
        self._debug_overlay: DebugRoiOverlay | None = None
        self._action_bar_overlay: ActionBarOverlay | None = None
        self._manual_rect: tuple[int, int, int, int] | None = None
        self._is_internal_adjust: bool = False

        if QApplication.instance() is not None:
            self._debug_overlay = DebugRoiOverlay(bridge=self.bridge)
            self._action_bar_overlay = ActionBarOverlay(bridge=self.bridge)

        self._init_window()
        self._init_ui()
        self._init_shortcuts()

        if self.bridge is not None:
            self.bridge.decision_updated.connect(self.on_decision_updated)
            if hasattr(self.bridge, "table_removed"):
                self.bridge.table_removed.connect(self.remove_table)
            if hasattr(self.bridge, "table_adjust_changed"):
                try:
                    self.bridge.table_adjust_changed[str, int, int, float, float].connect(self.on_table_adjust_5arg_from_bridge)
                    self.bridge.table_adjust_changed[int, int, float].connect(self.on_table_adjust_from_bridge)
                except Exception:
                    self.bridge.table_adjust_changed.connect(self.on_table_adjust_from_bridge)

    def _init_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(430)

    def _init_ui(self) -> None:
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(4, 4, 4, 4)
        self.root_layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setObjectName("hudContainer")
        self.root_layout.addWidget(self.container)

        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(10, 8, 10, 10)
        self.container_layout.setSpacing(6)

        btn_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.18);
                color: #ffffff;
            }
        """

        # Action-Only Compact Pill (hidden by default)
        self.action_only_pill = QWidget(self.container)
        pill_layout = QHBoxLayout(self.action_only_pill)
        pill_layout.setContentsMargins(4, 2, 4, 2)
        pill_layout.setSpacing(8)

        self.pill_label = QLabel("🎯 <b>HUD [⚡ Tylko akcja | Ctrl+Shift+A]</b>", self.action_only_pill)
        self.pill_label.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: bold;")
        pill_layout.addWidget(self.pill_label)
        pill_layout.addStretch()

        self.btn_pill_restore = QPushButton("Rozwiń HUD", self.action_only_pill)
        self.btn_pill_restore.setStyleSheet(btn_style)
        self.btn_pill_restore.clicked.connect(self.toggle_action_only_mode)
        pill_layout.addWidget(self.btn_pill_restore)

        self.action_only_pill.setVisible(False)
        self.container_layout.addWidget(self.action_only_pill)

        # Normal HUD Widget
        self.normal_hud_widget = QWidget(self.container)
        self.normal_hud_layout = QVBoxLayout(self.normal_hud_widget)
        self.normal_hud_layout.setContentsMargins(0, 0, 0, 0)
        self.normal_hud_layout.setSpacing(6)

        # Header bar
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        self.title_label = QLabel("🎯 <b>POKER ASSISTANT</b>", self.normal_hud_widget)
        self.title_label.setStyleSheet("color: #ecf0f1; font-size: 12px; font-weight: bold;")
        header_row.addWidget(self.title_label)
        header_row.addStretch()

        self.btn_details = QPushButton("🔍 Szczegóły", self.normal_hud_widget)
        self.btn_details.setStyleSheet(btn_style)
        self.btn_details.clicked.connect(self.toggle_details)
        header_row.addWidget(self.btn_details)

        self.btn_action_only = QPushButton("⚡ Tylko akcja", self.normal_hud_widget)
        self.btn_action_only.setStyleSheet(btn_style)
        self.btn_action_only.setToolTip("Tryb Tylko Akcja pod przyciskami gry (Ctrl+Shift+A)")
        self.btn_action_only.clicked.connect(self.toggle_action_only_mode)
        header_row.addWidget(self.btn_action_only)

        self.btn_add_table = QPushButton("+ Stół", self.normal_hud_widget)
        self.btn_add_table.setStyleSheet(btn_style)
        self.btn_add_table.setToolTip("Dodaj kolejny stół do monitorowania")
        self.btn_add_table.clicked.connect(self.start_add_table_flow)
        header_row.addWidget(self.btn_add_table)

        self.normal_hud_layout.addLayout(header_row)

        self.status_label = QLabel(self.normal_hud_widget)
        self.normal_hud_layout.addWidget(self.status_label)

        # Buy-in selector row (visible in details)
        self.buy_in_panel = QWidget(self.normal_hud_widget)
        buy_in_layout = QHBoxLayout(self.buy_in_panel)
        buy_in_layout.setContentsMargins(0, 2, 0, 2)
        buy_in_layout.setSpacing(4)

        lbl_bi = QLabel("<b>Buy-in:</b>", self.buy_in_panel)
        lbl_bi.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold;")
        buy_in_layout.addWidget(lbl_bi)

        self.buy_in_buttons: dict[float, QPushButton] = {}
        for val, text in [(0.50, "$0.50"), (2.0, "$2"), (5.0, "$5"), (10.0, "$10")]:
            btn = QPushButton(text, self.buy_in_panel)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(lambda checked=False, v=val: self.set_buy_in(v))
            buy_in_layout.addWidget(btn)
            self.buy_in_buttons[val] = btn

        buy_in_layout.addStretch()

        self.btn_debug_overlay = QPushButton("🎯 Ramki ROI", self.buy_in_panel)
        self.btn_debug_overlay.setStyleSheet(btn_style)
        self.btn_debug_overlay.setToolTip("Pokaż / ukryj ramki stołu i pól ROI (Ctrl+Shift+O)")
        self.btn_debug_overlay.clicked.connect(self.toggle_debug_overlay)
        self.btn_debug_overlay.setVisible(self.show_details)
        buy_in_layout.addWidget(self.btn_debug_overlay)

        # Legacy backward-compat buttons
        self.btn_select_rect = QPushButton("📐 Obszar", self.buy_in_panel)
        self.btn_select_rect.setStyleSheet(btn_style)
        self.btn_select_rect.clicked.connect(self.start_region_selection)
        self.btn_select_rect.setVisible(False)
        buy_in_layout.addWidget(self.btn_select_rect)

        self.btn_auto_rect = QPushButton("↺ Auto", self.buy_in_panel)
        self.btn_auto_rect.setStyleSheet(btn_style)
        self.btn_auto_rect.clicked.connect(self.reset_auto_rect)
        self.btn_auto_rect.setVisible(False)
        buy_in_layout.addWidget(self.btn_auto_rect)

        self.buy_in_panel.setVisible(self.show_details)
        self.normal_hud_layout.addWidget(self.buy_in_panel)
        self._update_buy_in_buttons_ui()

        # Calibration Panel (DEFAULT HIDDEN! Opens via '✎ Kalibruj')
        self.calibration_panel = QFrame(self.normal_hud_widget)
        self.calibration_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 41, 59, 0.85);
                border: 1px solid rgba(243, 156, 18, 0.6);
                border-radius: 6px;
                padding: 4px;
            }
        """)
        calib_layout = QVBoxLayout(self.calibration_panel)
        calib_layout.setContentsMargins(6, 4, 6, 4)
        calib_layout.setSpacing(4)

        calib_header_row = QHBoxLayout()
        self.calib_title_label = QLabel("✎ <b>Tryb edycji ramki stołu</b>", self.calibration_panel)
        self.calib_title_label.setStyleSheet("color: #f39c12; font-size: 11px; font-weight: bold;")
        calib_header_row.addWidget(self.calib_title_label)
        calib_header_row.addStretch()

        self.adjust_label = QLabel("Offset: (0, 0) | 100%", self.calibration_panel)
        self.adjust_label.setStyleSheet("color: #cbd5e1; font-size: 10px; font-weight: bold;")
        calib_header_row.addWidget(self.adjust_label)
        calib_layout.addLayout(calib_header_row)

        adj_btn_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 3px;
                padding: 1px 5px;
                font-size: 11px;
                font-weight: bold;
                min-width: 20px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                color: #ffffff;
            }
        """

        controls_row1 = QHBoxLayout()
        controls_row1.setSpacing(4)

        self.btn_adj_left = QPushButton("◀", self.calibration_panel)
        self.btn_adj_left.setStyleSheet(adj_btn_style)
        self.btn_adj_left.setToolTip("Przesuń stół w lewo (Shift: 15px, domyślnie 5px)")
        self.btn_adj_left.clicked.connect(lambda: self.adjust_table_dx(-1))
        controls_row1.addWidget(self.btn_adj_left)

        self.btn_adj_up = QPushButton("▲", self.calibration_panel)
        self.btn_adj_up.setStyleSheet(adj_btn_style)
        self.btn_adj_up.setToolTip("Przesuń stół w górę (Shift: 15px, domyślnie 5px)")
        self.btn_adj_up.clicked.connect(lambda: self.adjust_table_dy(-1))
        controls_row1.addWidget(self.btn_adj_up)

        self.btn_adj_down = QPushButton("▼", self.calibration_panel)
        self.btn_adj_down.setStyleSheet(adj_btn_style)
        self.btn_adj_down.setToolTip("Przesuń stół w dół (Shift: 15px, domyślnie 5px)")
        self.btn_adj_down.clicked.connect(lambda: self.adjust_table_dy(1))
        controls_row1.addWidget(self.btn_adj_down)

        self.btn_adj_right = QPushButton("▶", self.calibration_panel)
        self.btn_adj_right.setStyleSheet(adj_btn_style)
        self.btn_adj_right.setToolTip("Przesuń stół w prawo (Shift: 15px, domyślnie 5px)")
        self.btn_adj_right.clicked.connect(lambda: self.adjust_table_dx(1))
        controls_row1.addWidget(self.btn_adj_right)

        self.btn_adj_sminus = QPushButton("Skala -", self.calibration_panel)
        self.btn_adj_sminus.setStyleSheet(adj_btn_style)
        self.btn_adj_sminus.setToolTip("Zmniejsz skalę stołu o 1%")
        self.btn_adj_sminus.clicked.connect(lambda: self.adjust_table_scale(-0.01))
        controls_row1.addWidget(self.btn_adj_sminus)

        self.btn_adj_splus = QPushButton("Skala +", self.calibration_panel)
        self.btn_adj_splus.setStyleSheet(adj_btn_style)
        self.btn_adj_splus.setToolTip("Zwiększ skalę stołu o 1%")
        self.btn_adj_splus.clicked.connect(lambda: self.adjust_table_scale(0.01))
        controls_row1.addWidget(self.btn_adj_splus)

        self.btn_adj_wminus = QPushButton("Szer ↔ -", self.calibration_panel)
        self.btn_adj_wminus.setStyleSheet(adj_btn_style)
        self.btn_adj_wminus.setToolTip("Zmniejsz szerokość stołu o 1%")
        self.btn_adj_wminus.clicked.connect(lambda: self.adjust_table_stretch_x(-0.01))
        controls_row1.addWidget(self.btn_adj_wminus)

        self.btn_adj_wplus = QPushButton("Szer ↔ +", self.calibration_panel)
        self.btn_adj_wplus.setStyleSheet(adj_btn_style)
        self.btn_adj_wplus.setToolTip("Zwiększ szerokość stołu o 1%")
        self.btn_adj_wplus.clicked.connect(lambda: self.adjust_table_stretch_x(0.01))
        controls_row1.addWidget(self.btn_adj_wplus)

        self.btn_adj_hminus = QPushButton("Wys ↕ -", self.calibration_panel)
        self.btn_adj_hminus.setStyleSheet(adj_btn_style)
        self.btn_adj_hminus.setToolTip("Zmniejsz wysokość stołu o 1%")
        self.btn_adj_hminus.clicked.connect(lambda: self.adjust_table_stretch_y(-0.01))
        controls_row1.addWidget(self.btn_adj_hminus)

        self.btn_adj_hplus = QPushButton("Wys ↕ +", self.calibration_panel)
        self.btn_adj_hplus.setStyleSheet(adj_btn_style)
        self.btn_adj_hplus.setToolTip("Zwiększ wysokość stołu o 1%")
        self.btn_adj_hplus.clicked.connect(lambda: self.adjust_table_stretch_y(0.01))
        controls_row1.addWidget(self.btn_adj_hplus)

        self.btn_adj_drag = QPushButton("✋ Przesuń", self.calibration_panel)
        self.btn_adj_drag.setStyleSheet(adj_btn_style)
        self.btn_adj_drag.setToolTip("Tryb przeciągania ramki stołu myszą")
        self.btn_adj_drag.clicked.connect(self.toggle_drag_mode)
        controls_row1.addWidget(self.btn_adj_drag)

        self.btn_adj_reset = QPushButton("↺", self.calibration_panel)
        self.btn_adj_reset.setStyleSheet(adj_btn_style)
        self.btn_adj_reset.setToolTip("Resetuj przesunięcie i skalę")
        self.btn_adj_reset.clicked.connect(self.reset_table_adjust)
        controls_row1.addWidget(self.btn_adj_reset)

        calib_layout.addLayout(controls_row1)

        # Confirm & Cancel row
        confirm_row = QHBoxLayout()
        confirm_row.addStretch()

        self.btn_calib_confirm = QPushButton("✔ Zatwierdź", self.calibration_panel)
        self.btn_calib_confirm.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: #ffffff;
                border: 1px solid #2ecc71;
                border-radius: 4px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        self.btn_calib_confirm.setToolTip("Zapisz w pamięci (ramki gasną po 3 s)")
        self.btn_calib_confirm.clicked.connect(self.confirm_table_calibration)
        confirm_row.addWidget(self.btn_calib_confirm)

        self.btn_calib_cancel = QPushButton("✕ Anuluj", self.calibration_panel)
        self.btn_calib_cancel.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: #ffffff;
                border: 1px solid #e74c3c;
                border-radius: 4px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e74c3c;
            }
        """)
        self.btn_calib_cancel.setToolTip("Cofnij do wartości sprzed edycji")
        self.btn_calib_cancel.clicked.connect(self.cancel_table_calibration)
        confirm_row.addWidget(self.btn_calib_cancel)

        calib_layout.addLayout(confirm_row)

        self.calibration_panel.setVisible(False)
        self.adjust_panel = self.calibration_panel  # Backward compatibility alias
        self.normal_hud_layout.addWidget(self.calibration_panel)

        # Multi-table cards layout
        self.tables_layout = QVBoxLayout()
        self.tables_layout.setSpacing(6)
        self.normal_hud_layout.addLayout(self.tables_layout)

        self.container_layout.addWidget(self.normal_hud_widget)
        self._apply_lock_state()

    def _init_shortcuts(self) -> None:
        self.lock_shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self.lock_shortcut.activated.connect(self.toggle_lock)
        self.close_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Q"), self)
        self.close_shortcut.activated.connect(self._emergency_close)
        self.details_shortcut = QShortcut(QKeySequence("Ctrl+Shift+D"), self)
        self.details_shortcut.activated.connect(self.toggle_details)
        self.debug_overlay_shortcut = QShortcut(QKeySequence("Ctrl+Shift+O"), self)
        self.debug_overlay_shortcut.activated.connect(self.toggle_debug_overlay)
        self.rect_shortcut = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        self.rect_shortcut.activated.connect(self.start_region_selection)
        self.action_only_shortcut = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        self.action_only_shortcut.activated.connect(self.toggle_action_only_mode)

        # Windows global hotkey timer via GetAsyncKeyState
        self._key_l_pressed: bool = False
        self._key_q_pressed: bool = False
        self._key_d_pressed: bool = False
        self._key_r_pressed: bool = False
        self._key_o_pressed: bool = False
        self._key_a_pressed: bool = False
        if sys.platform == "win32":
            self._hotkey_timer = QTimer(self)
            self._hotkey_timer.setInterval(50)
            self._hotkey_timer.timeout.connect(self._check_global_hotkeys)
            self._hotkey_timer.start()

    def _check_global_hotkeys(self) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            ctrl_down = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            shift_down = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            l_down = bool(user32.GetAsyncKeyState(0x4C) & 0x8000)
            q_down = bool(user32.GetAsyncKeyState(0x51) & 0x8000)
            d_down = bool(user32.GetAsyncKeyState(0x44) & 0x8000)
            r_down = bool(user32.GetAsyncKeyState(0x52) & 0x8000)
            o_down = bool(user32.GetAsyncKeyState(0x4F) & 0x8000)
            a_down = bool(user32.GetAsyncKeyState(0x41) & 0x8000)

            if ctrl_down and shift_down and l_down:
                if not self._key_l_pressed:
                    self._key_l_pressed = True
                    self.toggle_lock()
            else:
                self._key_l_pressed = False

            if ctrl_down and shift_down and q_down:
                if not self._key_q_pressed:
                    self._key_q_pressed = True
                    self._emergency_close()
            else:
                self._key_q_pressed = False

            if ctrl_down and shift_down and d_down:
                if not self._key_d_pressed:
                    self._key_d_pressed = True
                    self.toggle_details()
            else:
                self._key_d_pressed = False

            if ctrl_down and shift_down and r_down:
                if not self._key_r_pressed:
                    self._key_r_pressed = True
                    self.start_region_selection()
            else:
                self._key_r_pressed = False

            if ctrl_down and shift_down and o_down:
                if not self._key_o_pressed:
                    self._key_o_pressed = True
                    self.toggle_debug_overlay()
            else:
                self._key_o_pressed = False

            if ctrl_down and shift_down and a_down:
                if not self._key_a_pressed:
                    self._key_a_pressed = True
                    self.toggle_action_only_mode()
            else:
                self._key_a_pressed = False
        except Exception:
            pass

    def _emergency_close(self) -> None:
        """Emergency application close handler."""
        if self._debug_overlay is not None:
            self._debug_overlay.close()
        if self._action_bar_overlay is not None:
            self._action_bar_overlay.close()
        if self._selector is not None:
            self._selector.close()
        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def closeEvent(self, event: Any) -> None:
        """Window close handler."""
        if self._debug_overlay is not None:
            self._debug_overlay.close()
        if self._action_bar_overlay is not None:
            self._action_bar_overlay.close()
        if self._selector is not None:
            self._selector.close()
        super().closeEvent(event)

    def _apply_lock_state(self) -> None:
        hwnd = int(self.winId()) if self.effectiveWinId() else 0
        set_click_through(hwnd, self.is_locked)
        set_exclude_from_capture(hwnd, True)

        if self.is_locked:
            self.status_label.setText("🔒 <b>HUD ZABLOKOWANY</b> (Ctrl+Shift+L odblokuj | Ctrl+Shift+Q zamknij)")
            self.status_label.setStyleSheet("color: #7f8c8d; font-size: 10px;")
            self.container.setStyleSheet("""
                QFrame#hudContainer {
                    background-color: rgba(18, 22, 32, 235);
                    border-radius: 8px;
                    border: 1px solid rgba(255, 255, 255, 35);
                }
            """)
        else:
            self.status_label.setText("🔓 <b>[ODBLOKOWANY - przeciągnij myszą]</b> (Ctrl+Shift+L zablokuj)")
            self.status_label.setStyleSheet("color: #f1c40f; font-weight: bold; font-size: 11px;")
            self.container.setStyleSheet("""
                QFrame#hudContainer {
                    background-color: rgba(22, 27, 38, 245);
                    border-radius: 8px;
                    border: 2px dashed #f1c40f;
                }
            """)

    def toggle_lock(self) -> bool:
        """Toggle position lock mode."""
        self.is_locked = not self.is_locked
        self._apply_lock_state()
        return self.is_locked

    def toggle_details(self) -> bool:
        """Toggle scan diagnostics panel visibility."""
        self.show_details = not self.show_details
        if hasattr(self, "buy_in_panel"):
            self.buy_in_panel.setVisible(self.show_details)
        if hasattr(self, "btn_debug_overlay"):
            self.btn_debug_overlay.setVisible(self.show_details)
        if hasattr(self, "adjust_panel"):
            self.adjust_panel.setVisible(self.show_details)
        for tid, header in self.table_header_widgets.items():
            header.setVisible(self.show_details)
        for tid, detail_lbl in self.details_widgets.items():
            detail_lbl.setVisible(self.show_details and bool(detail_lbl.text()))
        if self.show_details:
            self.btn_details.setStyleSheet(
                "background-color: #2980b9; color: #ffffff; border: 1px solid #3498db; "
                "border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
            )
        else:
            self.btn_details.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); color: #cbd5e1; "
                "border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 2px 6px; "
                "font-size: 10px; font-weight: bold;"
            )
        self.adjustSize()
        return self.show_details

    def toggle_debug_overlay(self) -> bool:
        """Toggle visibility of DebugRoiOverlay."""
        self.is_debug_overlay_enabled = not self.is_debug_overlay_enabled
        if self._debug_overlay is not None:
            if self.is_debug_overlay_enabled:
                screen = QApplication.primaryScreen()
                if screen:
                    self._debug_overlay.setGeometry(screen.virtualGeometry())
                self._debug_overlay.show()
            else:
                if self.editing_table_id is None:
                    self._debug_overlay.hide()

        if self.is_debug_overlay_enabled:
            self.btn_debug_overlay.setStyleSheet(
                "background-color: #10b981; color: #ffffff; border: 1px solid #34d399; "
                "border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
            )
        else:
            self.btn_debug_overlay.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); color: #cbd5e1; "
                "border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 2px 6px; "
                "font-size: 10px; font-weight: bold;"
            )
        self.adjustSize()
        return self.is_debug_overlay_enabled

    def toggle_action_only_mode(self) -> bool:
        """Toggle Action-Only mode (ActionBarOverlay below game buttons)."""
        self.is_action_only_mode = not self.is_action_only_mode
        if self.is_action_only_mode:
            if self._action_bar_overlay is not None:
                screen = QApplication.primaryScreen()
                if screen:
                    self._action_bar_overlay.setGeometry(screen.virtualGeometry())
                self._action_bar_overlay.show()
            if hasattr(self, "normal_hud_widget"):
                self.normal_hud_widget.setVisible(False)
            if hasattr(self, "action_only_pill"):
                self.action_only_pill.setVisible(True)
            if hasattr(self, "btn_action_only"):
                self.btn_action_only.setStyleSheet(
                    "background-color: #e67e22; color: #ffffff; border: 1px solid #d35400; "
                    "border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
                )
        else:
            if self._action_bar_overlay is not None:
                self._action_bar_overlay.hide()
            if hasattr(self, "action_only_pill"):
                self.action_only_pill.setVisible(False)
            if hasattr(self, "normal_hud_widget"):
                self.normal_hud_widget.setVisible(True)
            if hasattr(self, "btn_action_only"):
                self.btn_action_only.setStyleSheet(
                    "background-color: rgba(255, 255, 255, 0.08); color: #cbd5e1; "
                    "border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 2px 6px; "
                    "font-size: 10px; font-weight: bold;"
                )
        self.adjustSize()
        return self.is_action_only_mode

    def set_buy_in(self, val: float) -> None:
        """Set tournament buy-in amount and notify bridge."""
        self.buy_in = val
        self._update_buy_in_buttons_ui()
        if self.bridge is not None and hasattr(self.bridge, "buy_in_changed"):
            self.bridge.buy_in_changed.emit(val)

    def _update_buy_in_buttons_ui(self) -> None:
        active_style = (
            "background-color: #2980b9; color: #ffffff; border: 1px solid #3498db; "
            "border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
        )
        inactive_style = (
            "background-color: rgba(255, 255, 255, 0.08); color: #cbd5e1; "
            "border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 2px 8px; "
            "font-size: 11px; font-weight: bold;"
        )
        for v, btn in self.buy_in_buttons.items():
            if abs(v - self.buy_in) < 0.01:
                btn.setStyleSheet(active_style)
            else:
                btn.setStyleSheet(inactive_style)

    def start_add_table_flow(self) -> None:
        """Start interactive region selection to add a new table."""
        idx = 1
        while f"table_{idx}" in self.managed_tables:
            idx += 1
        next_tid = f"table_{idx}"

        def _on_region_selected(rect: Any) -> None:
            if rect is not None:
                self.add_table(next_tid, rect)

        self._selector = RegionSelectorOverlay(on_selected=_on_region_selected)
        self._selector.showFullScreen()

    def add_table(self, table_id: str, search_region: Any = None) -> None:
        """Add a managed table explicitly."""
        self.managed_tables[table_id] = {
            "search_region": search_region,
            "adjust": (0, 0, 1.0, 1.0),
        }
        self._update_table_delete_buttons_visibility()
        if self.bridge is not None and hasattr(self.bridge, "table_added"):
            self.bridge.table_added.emit(table_id, search_region)
        self.adjustSize()

    def remove_table_by_user(self, table_id: str) -> None:
        """Remove a managed table by user action."""
        if len(self.managed_tables) <= 1:
            return
        self.managed_tables.pop(table_id, None)
        self.remove_table(table_id)
        self._update_table_delete_buttons_visibility()
        if self.bridge is not None and hasattr(self.bridge, "table_removed_by_user"):
            self.bridge.table_removed_by_user.emit(table_id)
        self.adjustSize()

    def _update_table_delete_buttons_visibility(self) -> None:
        can_delete = len(self.managed_tables) > 1
        for btn in self.table_delete_buttons.values():
            btn.setVisible(can_delete)

    def start_table_calibration(self, table_id: str) -> None:
        """Open calibration panel for a specific table."""
        self.editing_table_id = table_id
        if table_id not in self.managed_tables:
            self.managed_tables[table_id] = {
                "search_region": None,
                "adjust": (0, 0, 1.0, 1.0),
            }
        self._pre_edit_adjust = tuple(self.managed_tables[table_id]["adjust"])
        if hasattr(self, "calib_title_label"):
            self.calib_title_label.setText(f"✎ <b>Kalibracja: {table_id}</b>")
        if hasattr(self, "calibration_panel"):
            self.calibration_panel.setVisible(True)
        if self._debug_overlay is not None:
            self._debug_overlay.editing_table_id = table_id
            if not self._debug_overlay.isVisible():
                self._debug_overlay.show()
            self._debug_overlay.update()
        self._update_adjust_label()
        self.adjustSize()

    def confirm_table_calibration(self) -> None:
        """Confirm in-memory table calibration, hide panel, and auto-hide overlay after 3 seconds."""
        if self.editing_table_id:
            if hasattr(self, "calibration_panel"):
                self.calibration_panel.setVisible(False)
            if self._debug_overlay is not None:
                self._debug_overlay.editing_table_id = None
                self._debug_overlay.update()
                if not self.is_debug_overlay_enabled:
                    QTimer.singleShot(3000, self._on_confirm_timer_done)
            self.editing_table_id = None
            self.adjustSize()

    def _on_confirm_timer_done(self) -> None:
        if not self.is_debug_overlay_enabled and self.editing_table_id is None:
            if self._debug_overlay is not None:
                self._debug_overlay.hide()

    def cancel_table_calibration(self) -> None:
        """Cancel calibration and revert adjustments for the current table."""
        if self.editing_table_id:
            tid = self.editing_table_id
            dx, dy, sx, sy = self._pre_edit_adjust
            self.managed_tables[tid]["adjust"] = (dx, dy, sx, sy)
            if tid == "table_1":
                self.table_dx = dx
                self.table_dy = dy
                self.table_scale_mult = sx
                self.table_scale_x = sx
                self.table_scale_y = sy
            if self.bridge is not None and hasattr(self.bridge, "table_adjust_changed"):
                try:
                    self.bridge.table_adjust_changed.emit(tid, dx, dy, sx, sy)
                except Exception:
                    pass
                try:
                    self.bridge.table_adjust_changed.emit(dx, dy, sx)
                except Exception:
                    pass
            if hasattr(self, "calibration_panel"):
                self.calibration_panel.setVisible(False)
            if self._debug_overlay is not None:
                self._debug_overlay.editing_table_id = None
                if not self.is_debug_overlay_enabled:
                    self._debug_overlay.hide()
                self._debug_overlay.update()
            self.editing_table_id = None
            self._update_adjust_label()
            self.adjustSize()

    def start_region_selection(self) -> None:
        """Open fullscreen region selector overlay to manually choose table ROI."""
        self._selector = RegionSelectorOverlay(on_selected=self._on_region_selected)
        self._selector.showFullScreen()

    def _on_region_selected(self, rect: tuple[int, int, int, int] | None) -> None:
        """Handle region selected by RegionSelectorOverlay."""
        self._manual_rect = rect
        tid = self.editing_table_id or "table_1"
        if rect is not None:
            if tid in self.managed_tables:
                self.managed_tables[tid]["search_region"] = rect
            if self.bridge is not None and hasattr(self.bridge, "manual_rect_changed"):
                self.bridge.manual_rect_changed.emit(rect)
            self.status_label.setText(f"📐 <b>Obszar:</b> {rect[2]}x{rect[3]} @ ({rect[0]},{rect[1]})")

    def reset_auto_rect(self) -> None:
        """Reset table detection to automatic template matching."""
        self._manual_rect = None
        tid = self.editing_table_id or "table_1"
        if tid in self.managed_tables:
            self.managed_tables[tid]["search_region"] = None
        if self.bridge is not None and hasattr(self.bridge, "manual_rect_changed"):
            self.bridge.manual_rect_changed.emit(None)
        self.reset_table_adjust()
        self._apply_lock_state()

    def adjust_table_dx(self, direction: int) -> None:
        """Adjust horizontal table offset."""
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.editing_table_id is not None:
            step = 15 if shift else 5
        else:
            step = 2 if shift else 10
        tid = self.editing_table_id or "table_1"
        dx, dy, sx, sy = self.managed_tables.get(tid, {}).get("adjust", (0, 0, 1.0, 1.0))
        self.apply_table_adjust(dx + direction * step, dy, sx, sy, table_id=tid)

    def adjust_table_dy(self, direction: int) -> None:
        """Adjust vertical table offset."""
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.editing_table_id is not None:
            step = 15 if shift else 5
        else:
            step = 2 if shift else 10
        tid = self.editing_table_id or "table_1"
        dx, dy, sx, sy = self.managed_tables.get(tid, {}).get("adjust", (0, 0, 1.0, 1.0))
        self.apply_table_adjust(dx, dy + direction * step, sx, sy, table_id=tid)

    def adjust_table_scale(self, delta: float) -> None:
        """Adjust uniform table scale."""
        tid = self.editing_table_id or "table_1"
        dx, dy, sx, sy = self.managed_tables.get(tid, {}).get("adjust", (0, 0, 1.0, 1.0))
        new_sx = max(0.50, min(2.00, round(sx + delta, 2)))
        new_sy = max(0.50, min(2.00, round(sy + delta, 2)))
        self.apply_table_adjust(dx, dy, new_sx, new_sy, table_id=tid)

    def adjust_table_stretch_x(self, delta: float) -> None:
        """Adjust horizontal scale stretch."""
        tid = self.editing_table_id or "table_1"
        dx, dy, sx, sy = self.managed_tables.get(tid, {}).get("adjust", (0, 0, 1.0, 1.0))
        new_sx = max(0.50, min(2.00, round(sx + delta, 2)))
        self.apply_table_adjust(dx, dy, new_sx, sy, table_id=tid)

    def adjust_table_stretch_y(self, delta: float) -> None:
        """Adjust vertical scale stretch."""
        tid = self.editing_table_id or "table_1"
        dx, dy, sx, sy = self.managed_tables.get(tid, {}).get("adjust", (0, 0, 1.0, 1.0))
        new_sy = max(0.50, min(2.00, round(sy + delta, 2)))
        self.apply_table_adjust(dx, dy, sx, new_sy, table_id=tid)

    def apply_table_adjust(
        self,
        dx: int,
        dy: int,
        scale_x: float,
        scale_y: float | None = None,
        table_id: str | None = None,
    ) -> None:
        """Apply table adjustment and emit to bridge."""
        if scale_y is None:
            scale_y = scale_x
        tid = table_id or self.editing_table_id or "table_1"
        if tid not in self.managed_tables:
            self.managed_tables[tid] = {"search_region": None, "adjust": (0, 0, 1.0, 1.0)}
        self.managed_tables[tid]["adjust"] = (dx, dy, scale_x, scale_y)

        if tid == "table_1":
            self.table_dx = dx
            self.table_dy = dy
            self.table_scale_mult = scale_x
            self.table_scale_x = scale_x
            self.table_scale_y = scale_y

        self._update_adjust_label()
        if self._debug_overlay is not None:
            self._debug_overlay._current_dx = dx
            self._debug_overlay._current_dy = dy
            self._debug_overlay._current_scale = scale_x
        if self.bridge is not None and hasattr(self.bridge, "table_adjust_changed"):
            self._is_internal_adjust = True
            try:
                self.bridge.table_adjust_changed.emit(tid, dx, dy, scale_x, scale_y)
            except Exception:
                pass
            try:
                self.bridge.table_adjust_changed.emit(dx, dy, scale_x)
            except Exception:
                pass
            finally:
                self._is_internal_adjust = False

    def reset_table_adjust(self) -> None:
        """Reset manual table offset and scale to (0, 0) | 100%."""
        tid = self.editing_table_id or "table_1"
        self.apply_table_adjust(0, 0, 1.0, 1.0, table_id=tid)

    def _update_adjust_label(self) -> None:
        tid = self.editing_table_id or "table_1"
        adj = self.managed_tables.get(tid, {}).get("adjust", (0, 0, 1.0, 1.0))
        dx, dy, sx, sy = adj
        pct_x = int(round(sx * 100))
        pct_y = int(round(sy * 100))
        if hasattr(self, "adjust_label"):
            if abs(sx - sy) < 0.005:
                self.adjust_label.setText(f"Offset: ({dx:+d}, {dy:+d}) | {pct_x}%")
            else:
                self.adjust_label.setText(f"Offset: ({dx:+d}, {dy:+d}) | ↔{pct_x}% ↕{pct_y}%")

    def toggle_drag_mode(self) -> bool:
        """Toggle interactive drag mode on debug overlay."""
        self.is_drag_mode = not self.is_drag_mode
        if self._debug_overlay is not None:
            if self.is_drag_mode and not self.is_debug_overlay_enabled:
                self.toggle_debug_overlay()
            self._debug_overlay.set_drag_mode(self.is_drag_mode)
        if hasattr(self, "btn_adj_drag"):
            if self.is_drag_mode:
                self.btn_adj_drag.setStyleSheet(
                    "background-color: #e67e22; color: #ffffff; border: 1px solid #d35400; "
                    "border-radius: 3px; padding: 1px 5px; font-size: 11px; font-weight: bold;"
                )
            else:
                self.btn_adj_drag.setStyleSheet(
                    "background-color: rgba(255, 255, 255, 0.08); color: #cbd5e1; "
                    "border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 3px; padding: 1px 5px; "
                    "font-size: 11px; font-weight: bold;"
                )
        return self.is_drag_mode

    @Slot(int, int, float)
    def on_table_adjust_from_bridge(self, dx: int, dy: int, scale_mult: float) -> None:
        """Receive legacy adjustment update without re-emitting."""
        if getattr(self, "_is_internal_adjust", False):
            return
        tid = self.editing_table_id or "table_1"
        self.on_table_adjust_5arg_from_bridge(tid, dx, dy, scale_mult, scale_mult)

    @Slot(str, int, int, float, float)
    def on_table_adjust_5arg_from_bridge(self, table_id: str, dx: int, dy: int, sx: float, sy: float) -> None:
        """Receive 5-arg adjustment update without re-emitting."""
        if getattr(self, "_is_internal_adjust", False):
            return
        if table_id not in self.managed_tables:
            self.managed_tables[table_id] = {"search_region": None, "adjust": (0, 0, 1.0, 1.0)}
        cur = self.managed_tables[table_id].get("adjust")
        if cur == (dx, dy, sx, sy):
            return
        self.managed_tables[table_id]["adjust"] = (dx, dy, sx, sy)
        if table_id == "table_1":
            self.table_dx = dx
            self.table_dy = dy
            self.table_scale_mult = sx
            self.table_scale_x = sx
            self.table_scale_y = sy
        self._update_adjust_label()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._apply_lock_state()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.is_locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            not self.is_locked
            and event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_pos is not None
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    @Slot(object, float, str)
    @Slot(object, float)
    def on_decision_updated(
        self,
        decision: Any,
        latency_ms: float = 0.0,
        scan_summary: str = "",
    ) -> None:
        """Update or insert decision card for the corresponding table."""
        table_id = getattr(decision, "table_id", "table_1")
        action = getattr(decision, "action", "WAIT")
        ev_bb = getattr(decision, "ev_bb", None)
        profile_used = getattr(decision, "profile_used", "STANDARD_EXPLOIT")
        reason = getattr(decision, "reason", "")

        is_plan = str(reason).startswith("[PLAN]")
        badge_text = f"PLAN: {action}" if is_plan else action

        # Action badge colors & styling
        if is_plan:
            if action in ("ALL_IN", "BET_30", "MIN_RAISE"):
                action_badge_style = "background-color: rgba(39, 174, 96, 0.45); border: 1px dashed #2ecc71;"
            elif action in ("CALL", "CHECK"):
                action_badge_style = "background-color: rgba(230, 126, 34, 0.45); border: 1px dashed #f39c12;"
            elif action == "FOLD":
                action_badge_style = "background-color: rgba(192, 57, 43, 0.45); border: 1px dashed #e74c3c;"
            else:
                action_badge_style = "background-color: rgba(74, 85, 104, 0.45); border: 1px dashed #94a3b8;"
        else:
            if action in ("ALL_IN", "BET_30", "MIN_RAISE"):
                action_color = "#27ae60"
            elif action in ("CALL", "CHECK"):
                action_color = "#e67e22"
            elif action == "FOLD":
                action_color = "#c0392b"
            elif action == "WAIT":
                action_color = "#4a5568"
            else:
                action_color = "#2980b9"
            action_badge_style = f"background-color: {action_color};"

        if ev_bb is not None:
            ev_str = f"EV: {ev_bb:+.2f} BB"
            ev_color = "#2ecc71" if ev_bb >= 0.0 else "#e74c3c"
        else:
            ev_str = "EV: --"
            ev_color = "#95a5a6"

        lat_str = f"{latency_ms:.1f} ms"
        plan_subtitle = '<div style="font-size: 10px; color: #38bdf8; margin-top: 3px;">⏳ Podgląd w przód (czekam na turę)</div>' if is_plan else ""

        cards_bar = format_cards_html(scan_summary)
        self.cards_line_by_table[table_id] = cards_bar
        cards_row = (
            f'<div style="font-size: 11px; margin-bottom: 5px; padding: 3px 6px; background: rgba(0, 0, 0, 0.3); border-radius: 4px;">{cards_bar}</div>'
            if cards_bar
            else ""
        )

        card_html = f"""
        <div style="background-color: rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 8px; margin-top: 2px;">
            <div style="font-size: 10px; color: #94a3b8; margin-bottom: 4px;">
                <b>{table_id}</b> &bull; <span style="color: #60a5fa;">{profile_used}</span>
            </div>
            {cards_row}
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 4px;">
                <tr>
                    <td align="left" style="white-space: nowrap;">
                        <span style="{action_badge_style} color: #ffffff; font-size: 15px; font-weight: bold; padding: 3px 10px; border-radius: 4px;">
                            {badge_text}
                        </span>
                    </td>
                    <td align="right" style="font-size: 14px; font-weight: bold; color: {ev_color}; padding-right: 6px; white-space: nowrap;">
                        {ev_str}
                    </td>
                </tr>
            </table>
            {plan_subtitle}
            <div style="font-size: 11px; color: #cbd5e1; margin-top: 4px;">
                {reason}
            </div>
            <div style="font-size: 9px; color: #64748b; text-align: right; margin-top: 2px;">
                ⏱ {lat_str}
            </div>
        </div>
        """

        if table_id not in self.table_widgets:
            # Per-table header toolbar (visible in details)
            header_w = QWidget(self.container)
            hl = QHBoxLayout(header_w)
            hl.setContentsMargins(0, 2, 0, 0)
            hl.setSpacing(4)

            btn_calib = QPushButton("✎ Kalibruj", header_w)
            btn_calib.setStyleSheet("""
                QPushButton {
                    background-color: rgba(243, 156, 18, 0.2);
                    color: #f39c12;
                    border: 1px solid rgba(243, 156, 18, 0.5);
                    border-radius: 3px;
                    padding: 1px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(243, 156, 18, 0.4);
                }
            """)
            btn_calib.clicked.connect(lambda checked=False, tid=table_id: self.start_table_calibration(tid))
            hl.addWidget(btn_calib)

            btn_area = QPushButton("📐 Obszar", header_w)
            btn_area.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #cbd5e1;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 3px;
                    padding: 1px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.2);
                }
            """)
            btn_area.clicked.connect(lambda checked=False, tid=table_id: self.start_region_selection())
            hl.addWidget(btn_area)

            btn_auto = QPushButton("↺ Auto", header_w)
            btn_auto.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #cbd5e1;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 3px;
                    padding: 1px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.2);
                }
            """)
            btn_auto.clicked.connect(lambda checked=False, tid=table_id: self.reset_auto_rect())
            hl.addWidget(btn_auto)

            hl.addStretch()

            btn_del = QPushButton("✕", header_w)
            btn_del.setStyleSheet("""
                QPushButton {
                    background-color: rgba(231, 76, 60, 0.2);
                    color: #e74c3c;
                    border: 1px solid rgba(231, 76, 60, 0.5);
                    border-radius: 3px;
                    padding: 1px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(231, 76, 60, 0.4);
                }
            """)
            btn_del.clicked.connect(lambda checked=False, tid=table_id: self.remove_table_by_user(tid))
            btn_del.setVisible(len(self.managed_tables) > 1)
            hl.addWidget(btn_del)

            header_w.setVisible(self.show_details)
            self.tables_layout.addWidget(header_w)
            self.table_header_widgets[table_id] = header_w
            self.table_delete_buttons[table_id] = btn_del

            label = QLabel(self.container)
            label.setTextFormat(Qt.TextFormat.RichText)
            self.tables_layout.addWidget(label)
            self.table_widgets[table_id] = label

            detail_label = QLabel(self.container)
            detail_label.setStyleSheet(
                "font-family: Consolas, 'Courier New', monospace; font-size: 10px; "
                "background-color: rgba(0, 0, 0, 0.45); color: #cbd5e1; "
                "padding: 6px; border-radius: 4px; border: 1px solid rgba(255, 255, 255, 0.1);"
            )
            detail_label.setTextFormat(Qt.TextFormat.PlainText)
            detail_label.setVisible(self.show_details and bool(scan_summary))
            self.tables_layout.addWidget(detail_label)
            self.details_widgets[table_id] = detail_label

        self.table_widgets[table_id].setText(card_html)

        if table_id in self.details_widgets:
            self.details_widgets[table_id].setText(scan_summary)
            self.details_widgets[table_id].setVisible(self.show_details and bool(scan_summary))

        self.adjustSize()

    @Slot(str)
    def remove_table(self, table_id: str) -> None:
        """Remove a stale table widget and details from layout."""
        self.cards_line_by_table.pop(table_id, None)
        if self._debug_overlay is not None:
            self._debug_overlay.remove_table(table_id)
        if self._action_bar_overlay is not None:
            self._action_bar_overlay.remove_table(table_id)
        if table_id in self.table_header_widgets:
            hw = self.table_header_widgets.pop(table_id)
            self.tables_layout.removeWidget(hw)
            hw.deleteLater()
        self.table_delete_buttons.pop(table_id, None)
        if table_id in self.table_widgets:
            widget = self.table_widgets.pop(table_id)
            self.tables_layout.removeWidget(widget)
            widget.deleteLater()
        if table_id in self.details_widgets:
            dw = self.details_widgets.pop(table_id)
            self.tables_layout.removeWidget(dw)
            dw.deleteLater()
        self.adjustSize()
