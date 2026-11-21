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
    debug_overlay_updated = Signal(object)
    table_adjust_changed = Signal(int, int, float)


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
                self.bridge.table_adjust_changed.emit(new_dx, new_dy, self._current_scale)
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

            table_rect = tbl_data.get("table_rect")
            if table_rect and len(table_rect) >= 4:
                tx, ty, tw, th = table_rect
                lx = tx / dpr
                ly = ty / dpr
                lw = tw / dpr
                lh = th / dpr

                # Distinct dashed table outline (cyan)
                pen = QPen(QColor("#00f0ff"))
                pen.setWidth(2)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(QColor(0, 240, 255, 12))
                painter.drawRect(QRectF(lx, ly, lw, lh))

                # Table label
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

                roi_color = QColor(color_str)
                pen = QPen(roi_color)
                pen.setWidth(1)
                painter.setPen(pen)
                fill = QColor(roi_color)
                fill.setAlpha(20)
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
        self.details_widgets: dict[str, QLabel] = {}
        self.cards_line_by_table: dict[str, str] = {}
        self.is_locked: bool = False
        self.show_details: bool = False
        self.is_debug_overlay_enabled: bool = False
        self.table_dx: int = 0
        self.table_dy: int = 0
        self.table_scale_mult: float = 1.0
        self.is_drag_mode: bool = False
        self._drag_pos: QPoint | None = None
        self._selector: RegionSelectorOverlay | None = None
        self._debug_overlay: DebugRoiOverlay | None = None
        self._manual_rect: tuple[int, int, int, int] | None = None

        if QApplication.instance() is not None:
            self._debug_overlay = DebugRoiOverlay(bridge=self.bridge)

        self._init_window()
        self._init_ui()
        self._init_shortcuts()

        if self.bridge is not None:
            self.bridge.decision_updated.connect(self.on_decision_updated)
            if hasattr(self.bridge, "table_removed"):
                self.bridge.table_removed.connect(self.remove_table)
            if hasattr(self.bridge, "table_adjust_changed"):
                self.bridge.table_adjust_changed.connect(self.on_table_adjust_from_bridge)

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

        self.btn_debug_overlay = QPushButton("🎯 Ramki ROI", self.container)
        self.btn_debug_overlay.setStyleSheet(btn_style)
        self.btn_debug_overlay.clicked.connect(self.toggle_debug_overlay)
        self.btn_debug_overlay.setVisible(self.show_details)
        header_row.addWidget(self.btn_debug_overlay)

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

        # Manual table adjustment panel (visible when show_details is True)
        self.adjust_panel = QWidget(self.container)
        adjust_layout = QHBoxLayout(self.adjust_panel)
        adjust_layout.setContentsMargins(0, 2, 0, 2)
        adjust_layout.setSpacing(4)

        adj_btn_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 3px;
                padding: 1px 5px;
                font-size: 11px;
                font-weight: bold;
                min-width: 18px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                color: #ffffff;
            }
        """

        self.btn_adj_left = QPushButton("◀", self.adjust_panel)
        self.btn_adj_left.setStyleSheet(adj_btn_style)
        self.btn_adj_left.setToolTip("Przesuń stół w lewo (Shift: 2px, domyślnie 10px)")
        self.btn_adj_left.clicked.connect(lambda: self.adjust_table_dx(-1))
        adjust_layout.addWidget(self.btn_adj_left)

        self.btn_adj_up = QPushButton("▲", self.adjust_panel)
        self.btn_adj_up.setStyleSheet(adj_btn_style)
        self.btn_adj_up.setToolTip("Przesuń stół w górę (Shift: 2px, domyślnie 10px)")
        self.btn_adj_up.clicked.connect(lambda: self.adjust_table_dy(-1))
        adjust_layout.addWidget(self.btn_adj_up)

        self.btn_adj_down = QPushButton("▼", self.adjust_panel)
        self.btn_adj_down.setStyleSheet(adj_btn_style)
        self.btn_adj_down.setToolTip("Przesuń stół w dół (Shift: 2px, domyślnie 10px)")
        self.btn_adj_down.clicked.connect(lambda: self.adjust_table_dy(1))
        adjust_layout.addWidget(self.btn_adj_down)

        self.btn_adj_right = QPushButton("▶", self.adjust_panel)
        self.btn_adj_right.setStyleSheet(adj_btn_style)
        self.btn_adj_right.setToolTip("Przesuń stół w prawo (Shift: 2px, domyślnie 10px)")
        self.btn_adj_right.clicked.connect(lambda: self.adjust_table_dx(1))
        adjust_layout.addWidget(self.btn_adj_right)

        self.btn_adj_sminus = QPushButton("-", self.adjust_panel)
        self.btn_adj_sminus.setStyleSheet(adj_btn_style)
        self.btn_adj_sminus.setToolTip("Zmniejsz skalę stołu o 1%")
        self.btn_adj_sminus.clicked.connect(lambda: self.adjust_table_scale(-0.01))
        adjust_layout.addWidget(self.btn_adj_sminus)

        self.btn_adj_splus = QPushButton("+", self.adjust_panel)
        self.btn_adj_splus.setStyleSheet(adj_btn_style)
        self.btn_adj_splus.setToolTip("Zwiększ skalę stołu o 1%")
        self.btn_adj_splus.clicked.connect(lambda: self.adjust_table_scale(0.01))
        adjust_layout.addWidget(self.btn_adj_splus)

        self.btn_adj_drag = QPushButton("✋ Przesuń", self.adjust_panel)
        self.btn_adj_drag.setStyleSheet(adj_btn_style)
        self.btn_adj_drag.setToolTip("Tryb przeciągania ramki stołu myszą")
        self.btn_adj_drag.clicked.connect(self.toggle_drag_mode)
        adjust_layout.addWidget(self.btn_adj_drag)

        self.btn_adj_reset = QPushButton("↺", self.adjust_panel)
        self.btn_adj_reset.setStyleSheet(adj_btn_style)
        self.btn_adj_reset.setToolTip("Resetuj przesunięcie i skalę do (0, 0) | 100%")
        self.btn_adj_reset.clicked.connect(self.reset_table_adjust)
        adjust_layout.addWidget(self.btn_adj_reset)

        self.adjust_label = QLabel("Offset: (0, 0) | 100%", self.adjust_panel)
        self.adjust_label.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold;")
        adjust_layout.addWidget(self.adjust_label)

        self.adjust_panel.setVisible(self.show_details)
        self.container_layout.addWidget(self.adjust_panel)

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
        self.debug_overlay_shortcut = QShortcut(QKeySequence("Ctrl+Shift+O"), self)
        self.debug_overlay_shortcut.activated.connect(self.toggle_debug_overlay)
        self.rect_shortcut = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        self.rect_shortcut.activated.connect(self.start_region_selection)

        # Windows global hotkey timer via GetAsyncKeyState (works even when click-through/no focus)
        self._key_l_pressed: bool = False
        self._key_q_pressed: bool = False
        self._key_d_pressed: bool = False
        self._key_r_pressed: bool = False
        self._key_o_pressed: bool = False
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
            # VK_CONTROL = 0x11, VK_SHIFT = 0x10, VK_L = 0x4C, VK_Q = 0x51, VK_D = 0x44, VK_R = 0x52, VK_O = 0x4F
            ctrl_down = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            shift_down = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            l_down = bool(user32.GetAsyncKeyState(0x4C) & 0x8000)
            q_down = bool(user32.GetAsyncKeyState(0x51) & 0x8000)
            d_down = bool(user32.GetAsyncKeyState(0x44) & 0x8000)
            r_down = bool(user32.GetAsyncKeyState(0x52) & 0x8000)
            o_down = bool(user32.GetAsyncKeyState(0x4F) & 0x8000)

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

            # Debounced toggle debug ROI overlay (Ctrl + Shift + O)
            if ctrl_down and shift_down and o_down:
                if not self._key_o_pressed:
                    self._key_o_pressed = True
                    self.toggle_debug_overlay()
            else:
                self._key_o_pressed = False
        except Exception:
            pass

    def _emergency_close(self) -> None:
        """Emergency application close handler."""
        if self._debug_overlay is not None:
            self._debug_overlay.close()
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
        self.btn_debug_overlay.setVisible(self.show_details)
        if hasattr(self, "adjust_panel"):
            self.adjust_panel.setVisible(self.show_details)
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
        """Toggle visibility of DebugRoiOverlay.

        Returns:
            bool: New is_debug_overlay_enabled state.
        """
        self.is_debug_overlay_enabled = not self.is_debug_overlay_enabled
        if self._debug_overlay is not None:
            if self.is_debug_overlay_enabled:
                screen = QApplication.primaryScreen()
                if screen:
                    self._debug_overlay.setGeometry(screen.virtualGeometry())
                self._debug_overlay.show()
            else:
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
        self.reset_table_adjust()
        self._apply_lock_state()

    def adjust_table_dx(self, direction: int) -> None:
        """Adjust horizontal table offset."""
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = 2 if shift else 10
        self.apply_table_adjust(self.table_dx + direction * step, self.table_dy, self.table_scale_mult)

    def adjust_table_dy(self, direction: int) -> None:
        """Adjust vertical table offset."""
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = 2 if shift else 10
        self.apply_table_adjust(self.table_dx, self.table_dy + direction * step, self.table_scale_mult)

    def adjust_table_scale(self, delta: float) -> None:
        """Adjust table scale multiplier."""
        new_s = max(0.50, min(2.00, round(self.table_scale_mult + delta, 2)))
        self.apply_table_adjust(self.table_dx, self.table_dy, new_s)

    def apply_table_adjust(self, dx: int, dy: int, scale_mult: float) -> None:
        """Apply table adjustment and emit to bridge."""
        self.table_dx = dx
        self.table_dy = dy
        self.table_scale_mult = scale_mult
        self._update_adjust_label()
        if self._debug_overlay is not None:
            self._debug_overlay._current_dx = dx
            self._debug_overlay._current_dy = dy
            self._debug_overlay._current_scale = scale_mult
        if self.bridge is not None and hasattr(self.bridge, "table_adjust_changed"):
            self.bridge.table_adjust_changed.emit(dx, dy, scale_mult)

    def reset_table_adjust(self) -> None:
        """Reset manual table offset and scale to (0, 0) | 100%."""
        self.apply_table_adjust(0, 0, 1.0)

    def _update_adjust_label(self) -> None:
        pct = int(round(self.table_scale_mult * 100))
        if hasattr(self, "adjust_label"):
            self.adjust_label.setText(f"({self.table_dx:+d}, {self.table_dy:+d}) | {pct}%")

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
        """Receive adjustment update (e.g. from mouse drag on overlay)."""
        self.table_dx = dx
        self.table_dy = dy
        self.table_scale_mult = scale_mult
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

        cards_bar = format_cards_html(scan_summary)
        self.cards_line_by_table[table_id] = cards_bar
        cards_row = (
            f'<div style="font-size: 11px; margin-bottom: 5px; padding: 3px 6px; background: rgba(0, 0, 0, 0.3); border-radius: 4px;">{cards_bar}</div>'
            if cards_bar
            else ""
        )

        card_html = f"""
        <div style="background-color: rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 8px; margin-top: 4px;">
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
        if table_id in self.table_widgets:
            widget = self.table_widgets.pop(table_id)
            self.tables_layout.removeWidget(widget)
            widget.deleteLater()
        if table_id in self.details_widgets:
            dw = self.details_widgets.pop(table_id)
            self.tables_layout.removeWidget(dw)
            dw.deleteLater()
        self.adjustSize()
