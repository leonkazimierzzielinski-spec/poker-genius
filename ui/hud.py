"""HUD overlay for poker_assistant using PySide6.

Features:
- Windows click-through (WS_EX_TRANSPARENT)
- Movable when unlocked (shortcut Ctrl+Shift+L)
- Multi-table support (table_widgets: dict[str, QLabel])
- Real-time action recommendation badge, EV, latency, and exploit reason
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QMouseEvent, QPainter, QPen, QShortcut
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


class HudBridge(QObject):
    """Thread-safe Qt signal bridge delivering decisions to HUD."""

    _raw_decision_updated = Signal((object, float, str), (object, float))
    decision_updated = _DecisionSignalDescriptor()
    manual_rect_changed = Signal(object)
    table_removed = Signal(str)


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
        self.details_widgets: dict[str, QLabel] = {}
        self.is_locked: bool = False
        self.show_details: bool = False
        self._drag_pos: QPoint | None = None
        self._selector: RegionSelectorOverlay | None = None
        self._manual_rect: tuple[int, int, int, int] | None = None

        self._init_window()
        self._init_ui()
        self._init_shortcuts()

        if self.bridge is not None:
            self.bridge.decision_updated.connect(self.on_decision_updated)
            if hasattr(self.bridge, "table_removed"):
                self.bridge.table_removed.connect(self.remove_table)

    def _init_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)

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

        # Header bar
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        self.title_label = QLabel("🎯 <b>POKER ASSISTANT</b>", self.container)
        self.title_label.setStyleSheet("color: #ecf0f1; font-size: 12px; font-weight: bold;")
        header_row.addWidget(self.title_label)
        header_row.addStretch()

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

        self.btn_details = QPushButton("🔍 Szczegóły", self.container)
        self.btn_details.setStyleSheet(btn_style)
        self.btn_details.clicked.connect(self.toggle_details)
        header_row.addWidget(self.btn_details)

        self.btn_select_rect = QPushButton("📐 Obszar", self.container)
        self.btn_select_rect.setStyleSheet(btn_style)
        self.btn_select_rect.clicked.connect(self.start_region_selection)
        header_row.addWidget(self.btn_select_rect)

        self.btn_auto_rect = QPushButton("↺ Auto", self.container)
        self.btn_auto_rect.setStyleSheet(btn_style)
        self.btn_auto_rect.clicked.connect(self.reset_auto_rect)
        header_row.addWidget(self.btn_auto_rect)

        self.container_layout.addLayout(header_row)

        self.status_label = QLabel(self.container)
        self.container_layout.addWidget(self.status_label)

        # Multi-table cards layout
        self.tables_layout = QVBoxLayout()
        self.tables_layout.setSpacing(6)
        self.container_layout.addLayout(self.tables_layout)

        self._apply_lock_state()

    def _init_shortcuts(self) -> None:
        # Fallback local shortcuts for when window has focus
        self.lock_shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self.lock_shortcut.activated.connect(self.toggle_lock)
        self.close_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Q"), self)
        self.close_shortcut.activated.connect(self._emergency_close)
        self.details_shortcut = QShortcut(QKeySequence("Ctrl+Shift+D"), self)
        self.details_shortcut.activated.connect(self.toggle_details)
        self.rect_shortcut = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        self.rect_shortcut.activated.connect(self.start_region_selection)

        # Windows global hotkey timer via GetAsyncKeyState (works even when click-through/no focus)
        self._key_l_pressed: bool = False
        self._key_q_pressed: bool = False
        self._key_d_pressed: bool = False
        self._key_r_pressed: bool = False
        if sys.platform == "win32":
            self._hotkey_timer = QTimer(self)
            self._hotkey_timer.setInterval(50)  # Check every 50 ms
            self._hotkey_timer.timeout.connect(self._check_global_hotkeys)
            self._hotkey_timer.start()

    def _check_global_hotkeys(self) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            # VK_CONTROL = 0x11, VK_SHIFT = 0x10, VK_L = 0x4C, VK_Q = 0x51, VK_D = 0x44, VK_R = 0x52
            ctrl_down = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            shift_down = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            l_down = bool(user32.GetAsyncKeyState(0x4C) & 0x8000)
            q_down = bool(user32.GetAsyncKeyState(0x51) & 0x8000)
            d_down = bool(user32.GetAsyncKeyState(0x44) & 0x8000)
            r_down = bool(user32.GetAsyncKeyState(0x52) & 0x8000)

            # Debounced toggle position lock (Ctrl + Shift + L)
            if ctrl_down and shift_down and l_down:
                if not self._key_l_pressed:
                    self._key_l_pressed = True
                    self.toggle_lock()
            else:
                self._key_l_pressed = False

            # Debounced emergency close (Ctrl + Shift + Q)
            if ctrl_down and shift_down and q_down:
                if not self._key_q_pressed:
                    self._key_q_pressed = True
                    self._emergency_close()
            else:
                self._key_q_pressed = False

            # Debounced toggle details (Ctrl + Shift + D)
            if ctrl_down and shift_down and d_down:
                if not self._key_d_pressed:
                    self._key_d_pressed = True
                    self.toggle_details()
            else:
                self._key_d_pressed = False

            # Debounced select table region (Ctrl + Shift + R)
            if ctrl_down and shift_down and r_down:
                if not self._key_r_pressed:
                    self._key_r_pressed = True
                    self.start_region_selection()
            else:
                self._key_r_pressed = False
        except Exception:
            pass

    def _emergency_close(self) -> None:
        """Emergency application close handler."""
        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def _apply_lock_state(self) -> None:
        hwnd = int(self.winId()) if self.effectiveWinId() else 0
        set_click_through(hwnd, self.is_locked)

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
        """Toggle position lock mode.

        When unlocked, WS_EX_TRANSPARENT is disabled and window can be dragged.
        When locked, clicks pass through to game window.

        Returns:
            bool: New is_locked state.
        """
        self.is_locked = not self.is_locked
        self._apply_lock_state()
        return self.is_locked

    def toggle_details(self) -> bool:
        """Toggle scan diagnostics panel visibility.

        Returns:
            bool: New show_details state.
        """
        self.show_details = not self.show_details
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

    def start_region_selection(self) -> None:
        """Open fullscreen region selector overlay to manually choose table ROI."""
        self._selector = RegionSelectorOverlay(on_selected=self._on_region_selected)
        self._selector.showFullScreen()

    def _on_region_selected(self, rect: tuple[int, int, int, int] | None) -> None:
        """Handle region selected by RegionSelectorOverlay."""
        self._manual_rect = rect
        if rect is not None:
            if self.bridge is not None and hasattr(self.bridge, "manual_rect_changed"):
                self.bridge.manual_rect_changed.emit(rect)
            self.status_label.setText(f"📐 <b>Obszar manualny:</b> {rect[2]}x{rect[3]} @ ({rect[0]},{rect[1]})")
            self.btn_select_rect.setStyleSheet(
                "background-color: #27ae60; color: #ffffff; border: 1px solid #2ecc71; "
                "border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
            )

    def reset_auto_rect(self) -> None:
        """Reset table detection to automatic template matching."""
        self._manual_rect = None
        if self.bridge is not None and hasattr(self.bridge, "manual_rect_changed"):
            self.bridge.manual_rect_changed.emit(None)
        self.btn_select_rect.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.08); color: #cbd5e1; "
            "border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 2px 6px; "
            "font-size: 10px; font-weight: bold;"
        )
        self._apply_lock_state()

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
        """Update or insert decision card for the corresponding table.

        Args:
            decision: Decision contract object.
            latency_ms: Processing latency in milliseconds.
            scan_summary: Multi-line diagnostic scan summary.
        """
        table_id = getattr(decision, "table_id", "default_table")
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
                action_color = "#27ae60"  # Green
            elif action in ("CALL", "CHECK"):
                action_color = "#e67e22"  # Amber/Orange
            elif action == "FOLD":
                action_color = "#c0392b"  # Red
            elif action == "WAIT":
                action_color = "#4a5568"  # Gray
            else:
                action_color = "#2980b9"  # Blue
            action_badge_style = f"background-color: {action_color};"

        # EV text & color
        if ev_bb is not None:
            ev_str = f"EV: {ev_bb:+.2f} BB"
            ev_color = "#2ecc71" if ev_bb >= 0.0 else "#e74c3c"
        else:
            ev_str = "EV: --"
            ev_color = "#95a5a6"

        lat_str = f"{latency_ms:.1f} ms"
        plan_subtitle = '<div style="font-size: 10px; color: #38bdf8; margin-top: 3px;">⏳ Podgląd w przód (czekam na turę)</div>' if is_plan else ""

        card_html = f"""
        <div style="background-color: rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 8px; margin-top: 4px;">
            <div style="font-size: 10px; color: #94a3b8; margin-bottom: 4px;">
                <b>{table_id}</b> &bull; <span style="color: #60a5fa;">{profile_used}</span>
            </div>
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
        if table_id in self.table_widgets:
            widget = self.table_widgets.pop(table_id)
            self.tables_layout.removeWidget(widget)
            widget.deleteLater()
        if table_id in self.details_widgets:
            dw = self.details_widgets.pop(table_id)
            self.tables_layout.removeWidget(dw)
            dw.deleteLater()
        self.adjustSize()
