"""Transparent always-on-top BongoCat window rendering the layered procedural rig."""

from __future__ import annotations

import ctypes
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QMenu, QWidget

from src.config import PetConfig
from src.rig import CatRig, KeySpec
from src.state_machine import CatStateMachine


@dataclass
class SparkleParticle:
    x: float
    y: float
    size: float
    created_ms: int
    duration_ms: int = 480


class CatPetWindow(QWidget):
    """Frameless transparent desktop pet compositing layered cat parts at 60 FPS."""

    config_changed = Signal()
    quit_requested = Signal()
    reset_inputs_requested = Signal()
    reset_position_requested = Signal()

    def __init__(
        self,
        parts_dir: Path | str,
        config: PetConfig,
        state_machine: CatStateMachine,
        sound_packs: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        parts_dir = Path(parts_dir)
        self.parts_dir = parts_dir
        self.config = config
        self.state_machine = state_machine
        self.sound_packs = sound_packs

        self.rig = CatRig(parts_dir)
        self._pix_keyboard = QPixmap(str(parts_dir / "keyboard_base.png"))
        self._pix_mouse = QPixmap(str(parts_dir / "mouse_base.png"))
        self._pix_bodies = {
            "idle": QPixmap(str(parts_dir / "body_idle.png")),
            "typing": QPixmap(str(parts_dir / "body_typing.png")),
            "mouse": QPixmap(str(parts_dir / "body_mouse.png")),
        }
        self._pix_heads_open = {
            "idle": QPixmap(str(parts_dir / "head_idle_open.png")),
            "typing": QPixmap(str(parts_dir / "head_typing_open.png")),
            "mouse": QPixmap(str(parts_dir / "head_mouse_open.png")),
        }
        self._pix_heads_squint = {
            "idle": QPixmap(str(parts_dir / "head_idle_squint.png")),
            "typing": QPixmap(str(parts_dir / "head_typing_squint.png")),
            "mouse": QPixmap(str(parts_dir / "head_mouse_squint.png")),
        }
        self._pix_head_sil = {
            "idle": QPixmap(str(parts_dir / "head_idle_sil.png")),
            "typing": QPixmap(str(parts_dir / "head_typing_sil.png")),
            "mouse": QPixmap(str(parts_dir / "head_mouse_sil.png")),
        }
        self._pix_mouse_right_rest = QPixmap(str(parts_dir / "arm_mouse_right_rest.png"))

        required_pix = [
            ("keyboard_base.png", self._pix_keyboard),
            ("mouse_base.png", self._pix_mouse),
            ("arm_mouse_right_rest.png", self._pix_mouse_right_rest),
        ]
        for mode in ("idle", "typing", "mouse"):
            required_pix.append((f"body_{mode}.png", self._pix_bodies[mode]))
            required_pix.append((f"head_{mode}_open.png", self._pix_heads_open[mode]))
            required_pix.append((f"head_{mode}_squint.png", self._pix_heads_squint[mode]))
            required_pix.append((f"head_{mode}_sil.png", self._pix_head_sil[mode]))

        for name, pix in required_pix:
            if pix.isNull():
                raise FileNotFoundError(f"Missing cat rig part: {parts_dir / name}")

        self._sparkles: list[SparkleParticle] = []
        self._last_punch_ms: int = -10000
        self._ss_buf: QImage | None = None
        self._dragging = False
        self._drag_moved = False
        self._drag_offset = QPoint()
        self._start_ms = int(time.monotonic() * 1000)

        self.setWindowTitle("小白不白 (xiaobaibubai)")
        self.setMouseTracking(True)
        self._apply_window_flags(initial=True)
        self.resize(config.pet_size, config.pet_size)
        self.setWindowOpacity(config.opacity)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60 FPS
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start()

    def _apply_window_flags(self, initial: bool = False) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if self.config.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if not initial and was_visible:
            self.show()
        self._apply_win32_click_through()

    def _apply_win32_click_through(self) -> None:
        if sys.platform != "win32":
            self.setAttribute(Qt.WA_TransparentForMouseEvents, bool(self.config.click_through))
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
            if self.config.click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            set_style(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_win32_click_through()

    def trigger_key_feedback(self, spec: KeySpec) -> None:
        """Spawn bounce & lime-green keyboard sparkle at the pressed key."""
        now = int(time.monotonic() * 1000)
        self._last_punch_ms = now

        if self.config.show_sparkles and random.random() < 0.72:
            pt = self.rig.kb_uv_to_px(spec.u, spec.v)
            self._sparkles.append(
                SparkleParticle(
                    x=pt.x() + random.uniform(-26.0, 26.0),
                    y=pt.y() + random.uniform(-16.0, 14.0),
                    size=random.uniform(16.0, 26.0),
                    created_ms=now,
                )
            )
            if len(self._sparkles) > 10:
                self._sparkles = self._sparkles[-10:]

    def trigger_mouse_feedback(self) -> None:
        self._last_punch_ms = int(time.monotonic() * 1000)

    def set_pet_size(self, size: int) -> None:
        size = max(180, min(640, int(size)))
        if size == self.config.pet_size:
            return
        center = self.geometry().center()
        self.config.pet_size = size
        self.resize(size, size)
        self.move(center.x() - size // 2, center.y() - size // 2)
        self.config.window_x = self.x()
        self.config.window_y = self.y()
        self.config_changed.emit()

    def set_opacity_value(self, opacity: float) -> None:
        self.config.opacity = max(0.25, min(1.0, float(opacity)))
        self.setWindowOpacity(self.config.opacity)
        self.config_changed.emit()

    def set_always_on_top(self, on_top: bool) -> None:
        self.config.always_on_top = on_top
        self._apply_window_flags()
        self.config_changed.emit()

    def set_click_through(self, enabled: bool) -> None:
        self.config.click_through = enabled
        self._apply_win32_click_through()
        self.config_changed.emit()

    def _tick(self) -> None:
        now = int(time.monotonic() * 1000)
        self._sparkles = [s for s in self._sparkles if (now - s.created_ms) < s.duration_ms]
        self.update()

    def mousePressEvent(self, event) -> None:
        if self.config.click_through:
            return
        if event.button() == Qt.LeftButton:
            now = int(time.monotonic() * 1000)
            lx = event.position().x() / max(1, self.width())
            ly = event.position().y() / max(1, self.height())
            if self.state_machine.is_on_head((lx, ly)):
                self.state_machine.on_head_click(True, now)
            self._dragging = True
            self._drag_moved = False
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        lx = pos.x() / max(1, self.width())
        ly = pos.y() / max(1, self.height())
        if not self.config.click_through:
            if 0.12 <= lx <= 0.88 and 0.06 <= ly <= 0.90:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_offset - self.pos()
            if abs(delta.x()) > 2 or abs(delta.y()) > 2:
                self._drag_moved = True
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return

        # Use same smooth radial tanh around cat face center as GlobalInputHook so local hover never conflicts
        now = int(time.monotonic() * 1000)
        dir_x = math.tanh((lx - 0.48) / 0.46)
        dir_y = math.tanh((ly - 0.22) / 0.42)
        scr = self.screen()
        screen_norm = None
        if scr is not None:
            avail = scr.availableGeometry()
            gp = event.globalPosition()
            snx = max(-1.0, min(1.0, ((gp.x() - avail.left()) / max(1, avail.width())) * 2.0 - 1.0))
            sny = max(-1.0, min(1.0, ((gp.y() - avail.top()) / max(1, avail.height())) * 2.0 - 1.0))
            screen_norm = (snx, sny)
        self.state_machine.on_mouse_move(
            now, dir_x=dir_x, dir_y=dir_y, local_norm=(lx, ly), screen_norm=screen_norm
        )

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            now = int(time.monotonic() * 1000)
            self.state_machine.on_head_click(False, now)
            if self._drag_moved:
                self.config.window_x = self.x()
                self.config.window_y = self.y()
                self.config_changed.emit()
            event.accept()

    def wheelEvent(self, event) -> None:
        if self.config.click_through:
            return
        delta = event.angleDelta().y()
        if delta != 0:
            step = 16 if delta > 0 else -16
            self.set_pet_size(self.config.pet_size + step)
            event.accept()

    def build_menu(self, parent_menu: QMenu | None = None) -> QMenu:
        """Build context/tray menu with all 1:1 customization toggles."""
        menu = parent_menu if parent_menu is not None else QMenu(self)

        act_bubble = QAction("猫实时按键气泡", menu, checkable=True)
        act_bubble.setChecked(self.config.show_keycap_bubble)
        act_bubble.triggered.connect(lambda c: self._toggle_attr("show_keycap_bubble", c))
        menu.addAction(act_bubble)

        act_hud = QAction("屏幕底部独立按键胶囊条", menu, checkable=True)
        act_hud.setChecked(self.config.show_keycap_hud)
        act_hud.triggered.connect(lambda c: self._toggle_attr("show_keycap_hud", c))
        menu.addAction(act_hud)

        act_glow = QAction("键盘与鼠标荧光绿高光", menu, checkable=True)
        act_glow.setChecked(self.config.key_glow_enabled)
        act_glow.triggered.connect(lambda c: self._toggle_attr("key_glow_enabled", c))
        menu.addAction(act_glow)

        act_spark = QAction("键盘绿星闪烁特效", menu, checkable=True)
        act_spark.setChecked(self.config.show_sparkles)
        act_spark.triggered.connect(lambda c: self._toggle_attr("show_sparkles", c))
        menu.addAction(act_spark)

        menu.addSeparator()

        # Sound Submenu
        sound_menu = menu.addMenu("机械键盘音效")
        act_snd = QAction("开启按键音效", sound_menu, checkable=True)
        act_snd.setChecked(self.config.sound_enabled)
        act_snd.triggered.connect(lambda c: self._toggle_attr("sound_enabled", c))
        sound_menu.addAction(act_snd)

        act_msnd = QAction("开启鼠标点击音", sound_menu, checkable=True)
        act_msnd.setChecked(self.config.mouse_sound_enabled)
        act_msnd.triggered.connect(lambda c: self._toggle_attr("mouse_sound_enabled", c))
        sound_menu.addAction(act_msnd)

        sound_menu.addSeparator()
        pack_group = QActionGroup(sound_menu)
        pack_group.setExclusive(True)
        for pid, label in self.sound_packs:
            act_p = QAction(f"轴体：{label}", sound_menu, checkable=True)
            act_p.setChecked(self.config.sound_pack == pid)
            act_p.triggered.connect(lambda _c, p=pid: self._select_sound_pack(p))
            pack_group.addAction(act_p)
            sound_menu.addAction(act_p)

        vol_menu = sound_menu.addMenu("音量")
        vol_group = QActionGroup(vol_menu)
        vol_group.setExclusive(True)
        for label, val in [("100%", 1.0), ("75%", 0.75), ("50%", 0.5), ("25%", 0.25)]:
            act_v = QAction(label, vol_menu, checkable=True)
            act_v.setChecked(abs(self.config.sound_volume - val) < 0.08)
            act_v.triggered.connect(lambda _c, v=val: self._set_volume(v))
            vol_group.addAction(act_v)
            vol_menu.addAction(act_v)

        # Cat Behavior Submenu
        pose_menu = menu.addMenu("猫咪交互与视角")

        act_mirror = QAction("原版猫视角键位（A在右、J在左）", pose_menu, checkable=True)
        act_player = QAction("玩家正向键位（A在左、J在右）", pose_menu, checkable=True)
        view_grp = QActionGroup(pose_menu)
        view_grp.setExclusive(True)
        act_mirror.setChecked(self.config.mirror_keyboard)
        act_player.setChecked(not self.config.mirror_keyboard)
        act_mirror.triggered.connect(lambda: self._set_mirror(True))
        act_player.triggered.connect(lambda: self._set_mirror(False))
        view_grp.addAction(act_mirror)
        view_grp.addAction(act_player)
        pose_menu.addAction(act_mirror)
        pose_menu.addAction(act_player)
        pose_menu.addSeparator()

        act_idle_rest = QAction("待机坐姿（双腿搭键盘，默认）", pose_menu, checkable=True)
        act_idle_up = QAction("待机蜷爪（收爪贴胸前）", pose_menu, checkable=True)
        idle_grp = QActionGroup(pose_menu)
        idle_grp.setExclusive(True)
        act_idle_rest.setChecked(self.config.idle_frame == 1)
        act_idle_up.setChecked(self.config.idle_frame == 4)
        act_idle_rest.triggered.connect(lambda: self._set_idle_frame(1))
        act_idle_up.triggered.connect(lambda: self._set_idle_frame(4))
        idle_grp.addAction(act_idle_rest)
        idle_grp.addAction(act_idle_up)
        pose_menu.addAction(act_idle_rest)
        pose_menu.addAction(act_idle_up)
        pose_menu.addSeparator()

        act_eye = QAction("眼球黑瞳追踪鼠标", pose_menu, checkable=True)
        act_eye.setChecked(self.config.eye_tracking_enabled)
        act_eye.triggered.connect(lambda c: self._toggle_sm("eye_tracking_enabled", c))
        pose_menu.addAction(act_eye)

        act_pet = QAction("悬停摸头眯眼反应", pose_menu, checkable=True)
        act_pet.setChecked(self.config.petting_enabled)
        act_pet.triggered.connect(lambda c: self._toggle_sm("petting_enabled", c))
        pose_menu.addAction(act_pet)

        act_blink = QAction("自动眨眼与犯困", pose_menu, checkable=True)
        act_blink.setChecked(self.config.blink_enabled)
        act_blink.triggered.connect(lambda c: self._toggle_sm("blink_enabled", c))
        pose_menu.addAction(act_blink)

        act_mouse = QAction("左爪握鼠标联动", pose_menu, checkable=True)
        act_mouse.setChecked(self.config.mouse_react_enabled)
        act_mouse.triggered.connect(lambda c: self._toggle_sm("mouse_react_enabled", c))
        pose_menu.addAction(act_mouse)

        # Size Submenu
        size_menu = menu.addMenu("窗口大小（也可滚轮缩放）")
        size_grp = QActionGroup(size_menu)
        size_grp.setExclusive(True)
        for label, px in [("小巧 (240px)", 240), ("标准 (340px)", 340), ("较大 (440px)", 440), ("超大 (540px)", 540)]:
            act_s = QAction(label, size_menu, checkable=True)
            act_s.setChecked(abs(self.config.pet_size - px) < 25)
            act_s.triggered.connect(lambda _c, s=px: self.set_pet_size(s))
            size_grp.addAction(act_s)
            size_menu.addAction(act_s)

        # Opacity Submenu
        op_menu = menu.addMenu("窗口透明度")
        op_grp = QActionGroup(op_menu)
        op_grp.setExclusive(True)
        for label, op in [("100% 不透明", 1.0), ("85%", 0.85), ("70%", 0.70), ("50%", 0.50)]:
            act_o = QAction(label, op_menu, checkable=True)
            act_o.setChecked(abs(self.config.opacity - op) < 0.06)
            act_o.triggered.connect(lambda _c, o=op: self.set_opacity_value(o))
            op_grp.addAction(act_o)
            op_menu.addAction(act_o)

        menu.addSeparator()

        act_top = QAction("窗口置顶", menu, checkable=True)
        act_top.setChecked(self.config.always_on_top)
        act_top.triggered.connect(self.set_always_on_top)
        menu.addAction(act_top)

        act_ct = QAction("点击穿透（从托盘可关闭）", menu, checkable=True)
        act_ct.setChecked(self.config.click_through)
        act_ct.triggered.connect(self.set_click_through)
        menu.addAction(act_ct)

        act_reset = QAction("复位按键状态", menu)
        act_reset.triggered.connect(self.reset_inputs_requested.emit)
        menu.addAction(act_reset)

        act_recenter = QAction("重置窗口位置", menu)
        act_recenter.triggered.connect(self.reset_position_requested.emit)
        menu.addAction(act_recenter)

        menu.addSeparator()
        act_quit = QAction("退出 小白不白", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)
        return menu

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = self.build_menu()
        menu.exec(global_pos)

    def _toggle_attr(self, name: str, value: bool) -> None:
        setattr(self.config, name, value)
        self.config_changed.emit()

    def _toggle_sm(self, name: str, value: bool) -> None:
        setattr(self.config, name, value)
        setattr(self.state_machine, name, value)
        self.config_changed.emit()

    def _set_mirror(self, mirror: bool) -> None:
        self.config.mirror_keyboard = mirror
        self.state_machine.mirror_keyboard = mirror
        self.config_changed.emit()

    def _select_sound_pack(self, pack_id: str) -> None:
        self.config.sound_pack = pack_id
        self.config_changed.emit()

    def _set_volume(self, value: float) -> None:
        self.config.sound_volume = value
        self.config_changed.emit()

    def _set_idle_frame(self, frame: int) -> None:
        self.config.idle_frame = frame
        self.state_machine.idle_frame = frame
        self.config_changed.emit()

    @staticmethod
    def _draw_four_point_star(
        painter: QPainter, cx: float, cy: float, radius: float, alpha: float
    ) -> None:
        inner = radius * 0.28
        pts = [
            QPointF(cx, cy - radius),
            QPointF(cx + inner, cy - inner),
            QPointF(cx + radius, cy),
            QPointF(cx + inner, cy + inner),
            QPointF(cx, cy + radius),
            QPointF(cx - inner, cy + inner),
            QPointF(cx - radius, cy),
            QPointF(cx - inner, cy - inner),
        ]
        path = QPainterPath()
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        path.closeSubpath()

        painter.save()
        painter.setOpacity(alpha)
        painter.fillPath(path, QColor(199, 235, 78))
        painter.restore()

    def _draw_chest_bubbles(
        self, painter: QPainter, bubbles: list[tuple[str, float, float, bool, float]]
    ) -> None:
        """Render video-style white black-bordered keycap badges aligned above pressed keys."""
        if not bubbles:
            return
        font = QFont("Segoe UI")
        font.setPixelSize(31)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        # Place bubbles cleanly across belly & left of tail directly above each key's u
        placed_rects: list[QRectF] = []
        for idx, (label, u, w_scale, held, alpha) in enumerate(bubbles):
            bx = 215.0 + u * 585.0
            by = 595.0 - (idx % 2) * 14.0 - (1.0 - alpha) * 26.0
            bw = max(62.0 * w_scale, fm.horizontalAdvance(label) + 32.0)
            bh = 58.0

            # Gentle horizontal/vertical nudge if overlapping previous bubble
            rect = QRectF(bx - bw * 0.5, by - bh * 0.5, bw, bh)
            for prev in placed_rects[-3:]:
                if rect.intersects(prev):
                    rect.translate(0.0, -34.0)
            placed_rects.append(rect)

            painter.save()
            painter.setOpacity(alpha)
            rpath = QPainterPath()
            rpath.addRoundedRect(rect, 15.0, 15.0)
            fill_col = QColor(252, 252, 254, 250) if held else QColor(246, 246, 248, 242)
            painter.fillPath(rpath, fill_col)
            painter.setPen(QPen(QColor(22, 22, 24), 4.2))
            painter.drawPath(rpath)

            if label == " ":
                # Subtle spacebar mark inside wide keycap
                bar_y = rect.center().y() + 10.0
                painter.setPen(QPen(QColor(150, 154, 162), 3.0, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(
                    QPointF(rect.center().x() - 14.0, bar_y),
                    QPointF(rect.center().x() + 14.0, bar_y),
                )
            else:
                painter.setPen(QColor(20, 20, 22))
                if label in ("⇧", "↵", "⌫", "⇥"):
                    sym_font = QFont("Segoe UI")
                    sym_font.setPixelSize(37)
                    sym_font.setWeight(QFont.Weight.Bold)
                    painter.setFont(sym_font)
                    painter.drawText(rect, Qt.AlignCenter, label)
                    painter.setFont(font)
                else:
                    painter.drawText(rect, Qt.AlignCenter, label)
            painter.restore()

    def paintEvent(self, event) -> None:
        win_painter = QPainter(self)
        # Clear entire translucent layered surface each frame so pose switches never ghost
        win_painter.setCompositionMode(QPainter.CompositionMode_Clear)
        win_painter.fillRect(self.rect(), Qt.transparent)
        win_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        win_painter.setRenderHint(QPainter.Antialiasing, True)
        win_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 2x supersampled offscreen rendering eliminates downscale aliasing jaggies at 240px pet size
        w, h = self.width(), self.height()
        if w < 720 or h < 720:
            ss_w = max(w, min(940, w * 2))
            ss_h = max(h, min(940, h * 2))
            if self._ss_buf is None or self._ss_buf.width() != ss_w or self._ss_buf.height() != ss_h:
                self._ss_buf = QImage(ss_w, ss_h, QImage.Format_ARGB32_Premultiplied)
            self._ss_buf.fill(Qt.transparent)
            ss_painter = QPainter(self._ss_buf)
            ss_painter.setRenderHint(QPainter.Antialiasing, True)
            ss_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            self._paint_scene(ss_painter, ss_w, ss_h)
            ss_painter.end()
            win_painter.drawImage(self.rect(), self._ss_buf)
        else:
            self._paint_scene(win_painter, w, h)

    def _paint_scene(self, painter: QPainter, target_w: int, target_h: int) -> None:
        now = int(time.monotonic() * 1000)
        snap = self.state_machine.snapshot(now)

        # Mid-Motion Pivot Morph across any pose transitions (continuous motion without ghosting)
        _POSE_ANCHORS = {
            "idle": (488.0, 185.0, 0.0, 1.00),
            "typing": (498.0, 250.0, 0.0, 0.90),
            "mouse_typing": (484.0, 250.0, -3.5, 0.90),
            "mouse": (250.0, 195.0, -11.0, 0.96),
        }
        t_raw = max(0.0, min(1.0, snap.pose_transition))
        s = t_raw * t_raw * (3.0 - 2.0 * t_raw)
        if snap.prev_pose_mode != snap.pose_mode and s < 1.0:
            ax, ay, a_lean, a_sy = _POSE_ANCHORS.get(snap.prev_pose_mode, (488.0, 220.0, 0.0, 1.0))
            bx, by, b_lean, b_sy = _POSE_ANCHORS.get(snap.pose_mode, (488.0, 220.0, 0.0, 1.0))
            if s < 0.5:
                mode = snap.prev_pose_mode
                morph_dx = (bx - ax) * s * 0.56
                morph_dy = (by - ay) * s * 0.36
                morph_deg = (b_lean - a_lean) * s * 0.60
                morph_sy = 1.0 + (b_sy / a_sy - 1.0) * s * 0.48
            else:
                mode = snap.pose_mode
                rem = 1.0 - s
                morph_dx = (ax - bx) * rem * 0.56
                morph_dy = (ay - by) * rem * 0.36
                morph_deg = (a_lean - b_lean) * rem * 0.60
                morph_sy = 1.0 + (a_sy / b_sy - 1.0) * rem * 0.48
        else:
            mode = snap.pose_mode
            morph_dx = morph_dy = morph_deg = 0.0
            morph_sy = 1.0

        # Scale 940x940 canonical rig space inside a slight safe margin so extreme 3D ear tilts NEVER clip at top/sides
        margin_x = target_w * 0.018
        margin_y = target_h * 0.032
        painter.translate(margin_x, margin_y)
        scale_x = (target_w * 0.955) / self.rig.canvas_size
        scale_y = (target_h * 0.955) / self.rig.canvas_size
        painter.scale(scale_x, scale_y)

        # Breathing & keypress punch
        punch_age = now - self._last_punch_ms
        punch_dy = 0.0
        if 0 <= punch_age < 90:
            t = punch_age / 90.0
            punch_dy = 6.5 * math.sin(t * math.pi)
        phase = ((now - self._start_ms) % 3600) / 3600.0 * 2.0 * math.pi
        breath_dy = -2.8 * math.sin(phase)

        m_ext = max(0.0, min(1.0, snap.mouse_arm_ext))
        m_ease = 1.0 - (1.0 - m_ext) ** 2
        if mode in ("mouse", "mouse_typing"):
            base_grip_dx = (self.rig.mouse_grip_center.x() - self.rig.mouse_center.x()) * m_ease
            base_grip_dy = (self.rig.mouse_grip_center.y() - self.rig.mouse_center.y()) * m_ease
            slide_dx = max(-36.0, min(34.0, snap.mouse_dx * 36.0)) * m_ease
            slide_dy = max(-28.0, min(28.0, snap.mouse_dy * 28.0)) * m_ease
            mouse_offset = QPointF(base_grip_dx + slide_dx, base_grip_dy + slide_dy)
        else:
            mouse_offset = QPointF(0.0, 0.0)

        # Mode-specific torso & 3D head calibration
        head_pitch_sx = 1.0
        head_pitch_sy = 1.0
        yaw_deg = 0.0
        pitch_deg = 0.0
        if mode == "idle":
            pivot = QPointF(485.0, 712.0)
            neck_pivot = self.rig.idle_neck_pivot
            head_3d_pivot = QPointF(488.0, 232.0)
            lean_deg = 0.0
            torso_dx = 0.0
            # Elevate idle sitting cat by 15px so front & hind paws sit clearly ABOVE the keyboard top bezel
            torso_dy = -15.0 + breath_dy * 0.55
            yaw_deg = -snap.head_turn_x * 20.0
            pitch_deg = -snap.head_turn_y * 18.0
            head_turn_deg = snap.head_turn_x * 10.0 - snap.head_turn_x * snap.head_turn_y * 4.0
            head_dx = snap.head_turn_x * 13.0
            head_dy = snap.head_turn_y * 10.0
            if snap.groom_progress > 0.01:
                g_ease = 1.0 - (1.0 - snap.groom_progress) ** 2
                lick_nod = 0.5 - 0.5 * math.cos(snap.groom_lick_phase)
                # Blend out cursor-tracking yaw/pitch during grooming so 3D card-tilt doesn't stack on top of nod;
                # use gentle volumetric pitch + curved facial-feature nod instead.
                damp = 1.0 - 0.85 * g_ease
                yaw_deg *= damp
                pitch_deg = pitch_deg * damp - 5.5 * lick_nod * g_ease
                head_pitch_sy = 1.0 - 0.026 * lick_nod * g_ease
                head_pitch_sx = 1.0 + 0.008 * lick_nod * g_ease
                torso_dy += 1.5 * lick_nod * g_ease
                head_turn_deg = head_turn_deg * damp + (-1.5 + 2.4 * lick_nod) * g_ease
                head_dx *= damp
                head_dy = head_dy * damp + 3.0 * lick_nod * g_ease
        elif mode == "mouse":
            pivot = QPointF(472.0, 710.0)
            neck_pivot = QPointF(295.0, 344.0)
            head_3d_pivot = QPointF(282.0, 206.0)
            lean_deg = snap.lean_x * 2.2
            torso_dx = snap.mouse_dx * 5.0
            torso_dy = breath_dy * 0.45
            # Balanced front-view 3D yaw + pitch + head tilt clearly visible without cardboard-flat distortion
            yaw_deg = -snap.head_turn_x * 20.0
            pitch_deg = -snap.head_turn_y * 18.0
            head_turn_deg = snap.head_turn_x * 10.5 - snap.head_turn_x * snap.head_turn_y * 4.5
            head_dx = snap.head_turn_x * 13.0
            head_dy = snap.head_turn_y * 10.0
        elif mode == "mouse_typing":
            # Video 38s-end centered-crouch posture leaning smoothly left when mouse arm reaches out
            pivot = QPointF(485.0, 715.0)
            neck_pivot = QPointF(475.0, 408.0)
            head_3d_pivot = QPointF(475.0, 255.0)
            lean_deg = snap.lean_x * 5.0 - m_ease * 1.8
            torso_dx = snap.lean_x * 12.0
            torso_dy = abs(snap.lean_x) * 3.0 + punch_dy * 0.45 + breath_dy * 0.65
            yaw_deg = -snap.head_turn_x * 14.0
            pitch_deg = -snap.head_turn_y * 12.0
            head_turn_deg = snap.head_turn_x * 8.0
            head_dx = snap.head_turn_x * 5.0
            head_dy = snap.head_turn_y * 4.5 + punch_dy * 0.45
        else:
            pivot = QPointF(485.0, 715.0)
            neck_pivot = QPointF(475.0, 408.0)
            head_3d_pivot = QPointF(475.0, 255.0)
            lean_deg = snap.lean_x * 5.0
            torso_dx = snap.lean_x * 14.0
            torso_dy = abs(snap.lean_x) * 4.0 + punch_dy * 0.45 + breath_dy * 0.65
            # Turn typing head clearly toward pressed key side (including left keys J/K/L/Backspace)
            yaw_deg = -snap.head_turn_x * 13.0
            pitch_deg = -snap.head_drop * 10.0
            head_turn_deg = snap.head_turn_x * 7.8
            head_dx = snap.head_turn_x * 4.0
            head_dy = snap.head_drop * 4.0 + punch_dy * 0.45

        persp_boost = 1.55
        head_local_xf = QTransform()
        head_local_xf.translate(neck_pivot.x() + head_dx, neck_pivot.y() + head_dy)
        head_local_xf.rotate(head_turn_deg)
        head_local_xf.scale(head_pitch_sx, head_pitch_sy)
        head_local_xf.translate(-neck_pivot.x(), -neck_pivot.y())
        head_local_xf.translate(head_3d_pivot.x(), head_3d_pivot.y())
        head_local_xf.scale(1.0 / persp_boost, 1.0 / persp_boost)
        head_local_xf.rotate(yaw_deg, Qt.YAxis)
        head_local_xf.rotate(pitch_deg, Qt.XAxis)
        head_local_xf.scale(persp_boost, persp_boost)
        head_local_xf.translate(-head_3d_pivot.x(), -head_3d_pivot.y())

        def torso_point(pt: QPointF) -> QPointF:
            total_deg = lean_deg + morph_deg
            rad = math.radians(total_deg)
            ox = pt.x() - pivot.x()
            oy = (pt.y() - pivot.y()) * morph_sy
            rx = ox * math.cos(rad) - oy * math.sin(rad)
            ry = ox * math.sin(rad) + oy * math.cos(rad)
            return QPointF(
                pivot.x() + rx + torso_dx + morph_dx,
                pivot.y() + ry + torso_dy + morph_dy,
            )

        def head_point(pt: QPointF) -> QPointF:
            return torso_point(head_local_xf.map(pt))

        # 1. White mouse on desk (drawn BEFORE cat arm/torso so left paw rests cleanly on top of mouse)
        mx, my, _, _ = self.rig.mouse_rect
        painter.drawPixmap(QPointF(mx + mouse_offset.x(), my + mouse_offset.y()), self._pix_mouse)
        if self.config.key_glow_enabled:
            self.rig.draw_mouse_click_glow(
                painter, mouse_offset, snap.mouse_left_down, snap.mouse_right_down
            )

        # 2. Cat torso layer matching current transition phase
        asset_key = "typing" if mode == "mouse_typing" else mode
        painter.save()
        painter.translate(pivot.x() + torso_dx + morph_dx, pivot.y() + torso_dy + morph_dy)
        painter.rotate(lean_deg + morph_deg)
        painter.scale(1.0, morph_sy)
        painter.translate(-pivot.x(), -pivot.y())
        painter.drawPixmap(0, 0, self._pix_bodies[asset_key])

        if mode == "typing":
            if snap.left_arm_ext < 0.14:
                self.rig.draw_curled_paw(painter, "left")
            if snap.right_arm_ext < 0.14:
                self.rig.draw_curled_paw(painter, "right")
        elif mode == "mouse_typing":
            if m_ease < 0.34:
                paw_alpha = min(1.0, (0.34 - m_ease) / 0.24)
                self.rig.draw_curled_paw(painter, "left", alpha=paw_alpha)
            if snap.right_arm_ext < 0.14:
                self.rig.draw_curled_paw(painter, "right")
        painter.restore()

        # In mouse or mouse_typing mode, animate left arm smoothly reaching onto the live-moving mouse top
        if mode == "mouse" or (mode == "mouse_typing" and m_ease >= 0.08):
            cur_mouse_cx = self.rig.mouse_center.x() + mouse_offset.x()
            cur_mouse_cy = self.rig.mouse_center.y() + mouse_offset.y()
            grip_pt = QPointF(cur_mouse_cx - 3.0, cur_mouse_cy - 18.0)

            if mode == "mouse":
                l_shoulder = torso_point(QPointF(216.0, 442.0))
                arm_fur = QColor(12, 12, 12)
                w_start, w_end = 44.0, 24.0
                retract_pt = QPointF(l_shoulder.x() + 22.0, l_shoulder.y() + 68.0)
            else:
                # In mouse_typing (video 38s-end), left arm flows seamlessly off left upper shoulder
                # (smooth outer curve from head cheek down arm) while keeping armpit/chest cleanly separated.
                l_shoulder = torso_point(QPointF(324.0, 424.0))
                arm_fur = QColor(25, 25, 25)
                w_start = 37.0 * (0.64 + 0.36 * m_ease)
                w_end = 22.0 * (0.82 + 0.18 * m_ease)
                if m_ease > 0.25:
                    painter.save()
                    painter.setBrush(arm_fur)
                    painter.setPen(Qt.NoPen)
                    mt_bridge = QPainterPath()
                    mt_bridge.moveTo(head_point(QPointF(324.5, 298.0)))
                    mt_bridge.cubicTo(
                        head_point(QPointF(320.0, 344.0)),
                        torso_point(QPointF(300.0, 392.0)),
                        torso_point(QPointF(283.0, 442.0)),
                    )
                    mt_bridge.lineTo(torso_point(QPointF(346.0, 455.0)))
                    mt_bridge.lineTo(head_point(QPointF(365.0, 305.0)))
                    mt_bridge.closeSubpath()
                    painter.drawPath(mt_bridge)
                    painter.restore()
                retract_pt = torso_point(QPointF(348.0, 548.0))

            reach_k = max(0.08, m_ease)
            arm_tip = QPointF(
                retract_pt.x() + (grip_pt.x() - retract_pt.x()) * reach_k,
                retract_pt.y() + (grip_pt.y() - retract_pt.y()) * reach_k - 22.0 * math.sin(reach_k * math.pi),
            )
            self.rig.draw_extended_arm(
                painter,
                "left",
                l_shoulder,
                arm_tip,
                outer_line=True,
                paw_contact_offset_y=-2.0,
                fur_color=arm_fur,
                width_start=w_start,
                width_end=w_end,
                paw_rx=28.0 * (0.72 + 0.28 * m_ease),
                paw_ry=23.0 * (0.72 + 0.28 * m_ease),
            )

        # 3. Crisp 5-row 3D mechanical keyboard with live per-key press depression & green glow + sparkles
        self.rig.draw_keyboard(painter, snap.key_glows, show_glow=self.config.key_glow_enabled)

        for sp in self._sparkles:
            progress = (now - sp.created_ms) / sp.duration_ms
            if progress >= 1.0:
                continue
            sc = math.sin(min(1.0, progress * 1.35) * math.pi)
            al = max(0.0, 1.0 - max(0.0, progress - 0.35) / 0.65)
            self._draw_four_point_star(painter, sp.x, sp.y, sp.size * max(0.25, sc), al)

        # 4. Tangent-continuous cubic Bezier neck envelope (eliminates notches on ANY head turn or lean)
        painter.save()
        if asset_key == "mouse":
            neck_fur = QColor(12, 12, 12)
            hl = head_point(QPointF(152.0, 310.0))
            c1_l = head_point(QPointF(172.0, 350.0))
            c2_l = torso_point(QPointF(180.0, 396.0))
            bl = torso_point(QPointF(173.0, 445.0))
            hr = head_point(QPointF(418.0, 270.0))
            c1_r = head_point(QPointF(445.0, 332.0))
            c2_r = torso_point(QPointF(522.0, 392.0))
            br = torso_point(QPointF(564.5, 460.0))
        elif asset_key == "idle":
            neck_fur = QColor(24, 24, 23)
            hl = head_point(QPointF(347.5, 278.0))
            c1_l = head_point(QPointF(348.0, 325.0))
            c2_l = torso_point(QPointF(318.0, 380.0))
            bl = torso_point(QPointF(302.5, 428.0))
            hr = head_point(QPointF(628.5, 278.0))
            c1_r = head_point(QPointF(620.0, 325.0))
            c2_r = torso_point(QPointF(634.0, 380.0))
            br = torso_point(QPointF(646.5, 428.0))
        else:
            neck_fur = QColor(25, 25, 25)
            hl = head_point(QPointF(324.5, 298.0))
            c1_l = head_point(QPointF(329.0, 345.0))
            c2_l = torso_point(QPointF(306.0, 395.0))
            bl = torso_point(QPointF(291.5, 446.0))
            hr = head_point(QPointF(622.5, 298.0))
            c1_r = head_point(QPointF(616.0, 345.0))
            c2_r = torso_point(QPointF(631.0, 395.0))
            br = torso_point(QPointF(643.5, 446.0))

        neck_bridge = QPainterPath()
        neck_bridge.moveTo(hl)
        neck_bridge.cubicTo(c1_l, c2_l, bl)
        neck_bridge.lineTo(br)
        neck_bridge.cubicTo(c2_r, c1_r, hr)
        neck_bridge.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(neck_fur)
        painter.drawPath(neck_bridge)
        painter.restore()

        # Cat head silhouette + live turning 3D eyes, smooth blink/squint lids, gaze pupils & whiskers
        painter.save()
        painter.translate(pivot.x() + torso_dx + morph_dx, pivot.y() + torso_dy + morph_dy)
        painter.rotate(lean_deg + morph_deg)
        painter.scale(1.0, morph_sy)
        painter.translate(-pivot.x(), -pivot.y())
        painter.setTransform(head_local_xf, combine=True)

        painter.drawPixmap(0, 0, self._pix_head_sil[asset_key])
        self.rig.draw_head_features(
            painter,
            asset_key,
            snap.head_turn_x,
            snap.head_turn_y,
            snap.eye_dx,
            snap.eye_dy,
            snap.eye_openness,
        )
        painter.restore()

        # 5. Extended/retracting articulated typing arms (reach out onto pressed keys & retract smoothly)
        def _interp_typing_tip(rest_pt: QPointF, key_uv: tuple[float, float], ext: float) -> QPointF:
            key_pt = self.rig.kb_uv_to_px(*key_uv)
            ease = 1.0 - (1.0 - max(0.0, min(1.0, ext))) ** 2
            arc_lift = -18.0 * math.sin(ease * math.pi)
            return QPointF(
                rest_pt.x() + (key_pt.x() - rest_pt.x()) * ease,
                rest_pt.y() + (key_pt.y() - rest_pt.y()) * ease + arc_lift,
            )

        if mode == "idle":
            if snap.groom_progress < 0.42:
                idle_paw_alpha = max(0.0, 1.0 - snap.groom_progress / 0.42)
                self.rig.draw_idle_front_paws(painter, torso_point, alpha=idle_paw_alpha)
            if snap.groom_progress > 0.15:
                # Draw tongue BEFORE foreground paw so the intact white paw rim cleanly stays in front
                # and the tongue wraps tightly around the curved back contour of the paw!
                self.rig.draw_licking_tongue(
                    painter,
                    head_point,
                    snap.groom_progress,
                    snap.groom_lick_phase,
                    snap.head_turn_y,
                )
            if snap.groom_progress > 0.12:
                self.rig.draw_groom_paws(
                    painter, torso_point, snap.groom_progress, snap.groom_lick_phase
                )

        if mode == "typing" and snap.left_arm_ext >= 0.14 and snap.left_arm_uv is not None:
            l_shoulder = torso_point(self.rig.left_shoulder)
            l_rest = torso_point(QPointF(346.0, 560.0))
            tip = _interp_typing_tip(l_rest, snap.left_arm_uv, snap.left_arm_ext)
            self.rig.draw_extended_arm(painter, "left", l_shoulder, tip, outer_line=True)

        if snap.right_arm_ext >= 0.14 and snap.right_arm_uv is not None:
            if mode == "mouse":
                r_anchor = self.rig.mouse_right_shoulder
            elif mode == "mouse_typing":
                r_anchor = QPointF(566.0, 472.0)
            else:
                r_anchor = self.rig.right_shoulder
            r_shoulder = torso_point(r_anchor)
            r_rest = torso_point(QPointF(502.0, 622.0) if mode == "mouse" else QPointF(602.0, 560.0))
            tip = _interp_typing_tip(r_rest, snap.right_arm_uv, snap.right_arm_ext)
            arm_fur = QColor(12, 12, 12) if mode == "mouse" else None
            self.rig.draw_extended_arm(
                painter, "right", r_shoulder, tip, outer_line=True, fur_color=arm_fur
            )
        elif mode == "mouse":
            # Draw resting right arm & paw cleanly with continuous arm-to-paw white outline matching 7.png
            r_shoulder = torso_point(self.rig.mouse_right_shoulder)
            r_rest_kb = torso_point(QPointF(526.0, 706.0))
            self.rig.draw_extended_arm(
                painter,
                "right",
                r_shoulder,
                r_rest_kb,
                outer_line=True,
                paw_contact_offset_y=-2.0,
                fur_color=QColor(12, 12, 12),
                width_start=34.0,
                width_end=21.0,
                paw_rx=26.0,
                paw_ry=21.0,
            )

        # 6. Video-style chest floating keycap tiles
        if self.config.show_keycap_bubble:
            self._draw_chest_bubbles(painter, snap.chest_bubbles)
