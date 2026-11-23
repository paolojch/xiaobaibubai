"""Floating screen keycap HUD popup displaying live keys and combos."""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


@dataclass
class KeyBadge:
    text: str
    created_ms: int
    held: bool = True
    released_ms: int = 0
    is_combo: bool = False


class KeycapHudWindow(QWidget):
    """Frameless transparent floating pill HUD showing real-time pressed keys."""

    def __init__(
        self,
        enabled: bool = True,
        click_through: bool = False,
        on_moved=None,
    ) -> None:
        super().__init__()
        self._enabled = enabled
        self._click_through = click_through
        self._on_moved = on_moved

        self._badges: list[KeyBadge] = []
        self._held_vks: dict[int, str] = {}
        self._held_vk_times: dict[int, int] = {}
        self._dragging = False
        self._drag_offset = QPoint()
        self._opacity_alpha = 0.0
        self._last_event_ms = 0

        self.setWindowTitle("xiaobaibubai Keycap HUD")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(460, 64)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_hud_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._badges.clear()
            self._held_vks.clear()
            self._held_vk_times.clear()
            self.hide()

    def set_click_through(self, enabled: bool) -> None:
        self._click_through = enabled
        self._apply_win32_click_through()

    def _apply_win32_click_through(self) -> None:
        if sys.platform != "win32":
            self.setAttribute(Qt.WA_TransparentForMouseEvents, bool(self._click_through))
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            WS_EX_NOACTIVATE = 0x08000000
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = get_style(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_NOACTIVATE
            if self._click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            set_style(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_win32_click_through()

    @staticmethod
    def _is_modifier(vk: int) -> bool:
        return vk in {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}

    def _active_modifiers(self) -> list[str]:
        mods: list[str] = []
        for label in ("Ctrl", "Alt", "Shift", "Win"):
            if label in self._held_vks.values():
                mods.append(label)
        return mods

    def on_key_event(self, vk: int, label: str, is_down: bool) -> None:
        if not self._enabled:
            return
        now = int(time.monotonic() * 1000)

        if is_down:
            # Ignore OS auto-repeat if already tracked held
            if vk in self._held_vks:
                self._last_event_ms = now
                return
            self._held_vks[vk] = label
            self._held_vk_times[vk] = now
            self._last_event_ms = now

            if self._is_modifier(vk):
                # Show modifier pill cleanly if no non-mod combo was just formed
                if not any(b.held and b.text == label for b in self._badges):
                    self._badges.append(KeyBadge(text=label, created_ms=now, held=True))
            else:
                mods = self._active_modifiers()
                if mods:
                    # Upgrade or replace trailing held modifier badges with a crisp combo badge
                    self._badges = [b for b in self._badges if not (b.held and b.text in mods)]
                    combo_text = " + ".join([*mods, label])
                    self._badges.append(
                        KeyBadge(text=combo_text, created_ms=now, held=True, is_combo=True)
                    )
                else:
                    self._badges.append(KeyBadge(text=label, created_ms=now, held=True))

            if len(self._badges) > 7:
                self._badges = self._badges[-7:]

            if not self.isVisible():
                self.show()
                self._apply_win32_click_through()
            self.update()
        else:
            self._held_vks.pop(vk, None)
            self._held_vk_times.pop(vk, None)
            for b in self._badges:
                if b.held and (b.text == label or b.text.endswith(f" + {label}") or (self._is_modifier(vk) and label in b.text)):
                    b.held = False
                    b.released_ms = now
            self._last_event_ms = now

    def held_keys_snapshot(self) -> list[tuple[int, str, int]]:
        """Return [(vk, label, pressed_ms), ...] for currently held HUD keys."""
        return [
            (vk, label, self._held_vk_times.get(vk, self._last_event_ms))
            for vk, label in self._held_vks.items()
        ]

    def reset_keys(self) -> None:
        self._held_vks.clear()
        self._held_vk_times.clear()
        now = int(time.monotonic() * 1000)
        for b in self._badges:
            if b.held:
                b.held = False
                b.released_ms = now

    def _tick(self) -> None:
        if not self._enabled or not self._badges:
            if self._opacity_alpha > 0.0:
                self._opacity_alpha = max(0.0, self._opacity_alpha - 0.12)
                self.update()
                if self._opacity_alpha <= 0.01:
                    self.hide()
            return

        now = int(time.monotonic() * 1000)
        # Keep held badges + badges released within last 1350ms
        self._badges = [
            b for b in self._badges if b.held or (now - b.released_ms) < 1350
        ]

        if self._badges:
            self._opacity_alpha = min(1.0, self._opacity_alpha + 0.25)
            self._resize_to_fit()
            self.update()
        else:
            self._opacity_alpha = max(0.0, self._opacity_alpha - 0.10)
            self.update()
            if self._opacity_alpha <= 0.01:
                self.hide()

    def _resize_to_fit(self) -> None:
        font = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
        fm = QFontMetrics(font)
        total_w = 24
        for b in self._badges:
            total_w += max(34, fm.horizontalAdvance(b.text) + 22) + 8
        target_w = max(140, min(720, total_w))
        if abs(target_w - self.width()) > 12:
            center_x = self.x() + self.width() // 2
            self.resize(target_w, 56)
            new_x = center_x - target_w // 2
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                new_x = max(avail.left() + 8, min(avail.right() - target_w - 8, new_x))
            self.move(new_x, self.y())

    def mousePressEvent(self, event) -> None:
        if not self._click_through and event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            if self._on_moved:
                self._on_moved(self.x(), self.y())
            event.accept()

    def paintEvent(self, event) -> None:
        if self._opacity_alpha <= 0.01 or not self._badges:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(self._opacity_alpha)

        font = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        now = int(time.monotonic() * 1000)
        widths = [max(34, fm.horizontalAdvance(b.text) + 22) for b in self._badges]
        content_w = sum(widths) + 8 * max(0, len(widths) - 1) + 22
        pill_h = 42
        start_x = (self.width() - content_w) / 2.0
        top_y = (self.height() - pill_h) / 2.0

        # Outer dark glass container pill
        container = QRectF(start_x, top_y, content_w, pill_h)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(container, 14, 14)
        painter.fillPath(bg_path, QColor(20, 22, 26, 220))
        painter.setPen(QPen(QColor(185, 232, 56, 130), 1.4))
        painter.drawPath(bg_path)

        cx = start_x + 11
        for badge, bw in zip(self._badges, widths):
            age_rel = 0 if badge.held else (now - badge.released_ms)
            alpha = 1.0 if badge.held else max(0.0, 1.0 - max(0, age_rel - 950) / 400.0)
            painter.setOpacity(self._opacity_alpha * alpha)

            key_rect = QRectF(cx, top_y + 6, bw, pill_h - 12)
            kpath = QPainterPath()
            kpath.addRoundedRect(key_rect, 8, 8)
            if badge.held:
                painter.fillPath(kpath, QColor(185, 232, 56, 240))
                painter.setPen(QPen(QColor(18, 20, 22), 1.5))
                painter.drawPath(kpath)
                painter.setPen(QColor(18, 20, 22))
            elif badge.is_combo:
                painter.fillPath(kpath, QColor(250, 250, 250, 240))
                painter.setPen(QPen(QColor(185, 232, 56), 1.5))
                painter.drawPath(kpath)
                painter.setPen(QColor(22, 22, 24))
            else:
                painter.fillPath(kpath, QColor(246, 246, 248, 235))
                painter.setPen(QPen(QColor(40, 42, 48), 1.2))
                painter.drawPath(kpath)
                painter.setPen(QColor(22, 22, 24))

            painter.drawText(key_rect, Qt.AlignCenter, badge.text)
            cx += bw + 8
