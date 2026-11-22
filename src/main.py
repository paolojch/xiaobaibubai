"""Application entry point wiring input hook, state machine, sounds, HUD, and tray."""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QPoint, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if not getattr(sys, "frozen", False) and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_resource_root, load_config, save_config
from src.input_hook import GlobalInputHook
from src.keycap_hud import KeycapHudWindow
from src.pet_window import CatPetWindow
from src.rig import get_key_spec
from src.sound_engine import SoundEngine
from src.state_machine import CatStateMachine

RESOURCE_ROOT = get_resource_root()


class BongoCatController:
    """Coordinates global hooks, rig state machine, sound engine, HUD, and tray."""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.config = load_config()
        self.frames_dir = RESOURCE_ROOT / "assets" / "frames"
        self.parts_dir = RESOURCE_ROOT / "assets" / "parts"
        self.sounds_dir = RESOURCE_ROOT / "assets" / "sounds"

        self.sound_engine = SoundEngine(self.sounds_dir)
        self.sound_engine.enabled = self.config.sound_enabled
        self.sound_engine.mouse_enabled = self.config.mouse_sound_enabled
        self.sound_engine.set_volume(self.config.sound_volume)
        self.sound_engine.set_keyboard_pack(self.config.sound_pack)

        self.state_machine = CatStateMachine(
            idle_frame=self.config.idle_frame,
            blink_enabled=self.config.blink_enabled,
            mouse_react_enabled=self.config.mouse_react_enabled,
            mirror_keyboard=self.config.mirror_keyboard,
            eye_tracking_enabled=self.config.eye_tracking_enabled,
            petting_enabled=self.config.petting_enabled,
        )

        self.pet_window = CatPetWindow(
            parts_dir=self.parts_dir,
            config=self.config,
            state_machine=self.state_machine,
            sound_packs=self.sound_engine.available_keyboard_packs(),
        )
        self._place_initial_windows()

        self.hud_window = KeycapHudWindow(
            enabled=self.config.show_keycap_hud,
            click_through=self.config.click_through,
            on_moved=self._on_hud_moved,
        )
        self._position_hud_window()

        self.hook = GlobalInputHook()
        self.hook.key_event.connect(self._on_key_event, Qt.QueuedConnection)
        self.hook.mouse_button_event.connect(self._on_mouse_button, Qt.QueuedConnection)
        self.hook.mouse_moved.connect(self._on_mouse_moved, Qt.QueuedConnection)

        self.pet_window.config_changed.connect(self._on_config_changed)
        self.pet_window.reset_inputs_requested.connect(self._reset_inputs)
        self.pet_window.reset_position_requested.connect(self._reset_positions)
        self.pet_window.quit_requested.connect(self.quit)

        self._last_cursor_gx: int | None = None
        self._last_cursor_gy: int | None = None
        self._setup_tray()

    def _place_initial_windows(self) -> None:
        screen = self.app.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        if self.config.window_x is None or self.config.window_y is None:
            self.config.window_x = avail.right() - self.config.pet_size - 28
            self.config.window_y = avail.bottom() - self.config.pet_size - 16
        else:
            self.config.window_x = max(
                avail.left() - self.config.pet_size // 2,
                min(avail.right() - self.config.pet_size // 2, self.config.window_x),
            )
            self.config.window_y = max(
                avail.top(),
                min(avail.bottom() - self.config.pet_size // 2, self.config.window_y),
            )
        self.pet_window.move(self.config.window_x, self.config.window_y)

    def _position_hud_window(self) -> None:
        screen = self.app.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        if self.config.hud_x is not None and self.config.hud_y is not None:
            self.hud_window.move(self.config.hud_x, self.config.hud_y)
        else:
            hx = avail.center().x() - self.hud_window.width() // 2
            hy = avail.bottom() - self.hud_window.height() - 28
            self.hud_window.move(hx, hy)

    def _on_hud_moved(self, x: int, y: int) -> None:
        self.config.hud_x = x
        self.config.hud_y = y
        save_config(self.config)

    def _setup_tray(self) -> None:
        icon_path = self.frames_dir / "4.png"
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        self.app.setWindowIcon(icon)

        self.tray = QSystemTrayIcon(icon, self.app)
        self.tray.setToolTip("小白不白 (xiaobaibubai) 桌宠（右键设置）")
        self._tray_menu = QMenu()
        self._tray_menu.aboutToShow.connect(self._refresh_tray_menu)
        self.tray.setContextMenu(self._tray_menu)
        self._refresh_tray_menu()
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _refresh_tray_menu(self) -> None:
        self._tray_menu.clear()
        self.pet_window.build_menu(self._tray_menu)

    def _reset_positions(self) -> None:
        self.config.window_x = None
        self.config.window_y = None
        self.config.hud_x = None
        self.config.hud_y = None
        self._place_initial_windows()
        self._position_hud_window()
        save_config(self.config)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            if self.config.click_through:
                self.pet_window.set_click_through(False)
            self.pet_window.raise_()

    def _on_config_changed(self) -> None:
        self.sound_engine.enabled = self.config.sound_enabled
        self.sound_engine.mouse_enabled = self.config.mouse_sound_enabled
        self.sound_engine.set_volume(self.config.sound_volume)
        if self.sound_engine.current_pack_id != self.config.sound_pack:
            self.sound_engine.set_keyboard_pack(self.config.sound_pack)

        self.hud_window.set_hud_enabled(self.config.show_keycap_hud)
        self.hud_window.set_click_through(self.config.click_through)
        save_config(self.config)

    def _cursor_direction(
        self, gx: int, gy: int
    ) -> tuple[float, float, tuple[float, float] | None, tuple[float, float] | None]:
        """Compute normalized 360-degree head-gaze vector and full-screen normalized cursor coords."""
        w = max(1, self.pet_window.width())
        h = max(1, self.pet_window.height())
        face_x = self.pet_window.x() + w * 0.48
        face_y = self.pet_window.y() + h * 0.22

        # Tie near-head sensitivity to window size so circling right around the head (~60-110px)
        # drives full 3D head yaw/pitch smoothly regardless of desktop resolution or pet_size.
        scale_x = max(88.0, w * 0.46)
        scale_y = max(80.0, h * 0.42)

        dx = math.tanh((gx - face_x) / scale_x)
        dy = math.tanh((gy - face_y) / scale_y)

        lx = (gx - self.pet_window.x()) / w
        ly = (gy - self.pet_window.y()) / h
        local_norm = (lx, ly) if (0.0 <= lx <= 1.0 and 0.0 <= ly <= 1.0) else None

        screen = QGuiApplication.screenAt(QPoint(gx, gy)) or self.app.primaryScreen()
        screen_norm: tuple[float, float] | None = None
        if screen:
            avail = screen.availableGeometry()
            sw = max(1, avail.width())
            sh = max(1, avail.height())
            snx = max(-1.0, min(1.0, ((gx - avail.left()) / sw) * 2.0 - 1.0))
            sny = max(-1.0, min(1.0, ((gy - avail.top()) / sh) * 2.0 - 1.0))
            screen_norm = (snx, sny)

        return dx, dy, local_norm, screen_norm

    def _on_key_event(self, vk: int, label: str, bubble_label: str, is_down: bool) -> None:
        now = int(time.monotonic() * 1000)
        if is_down:
            is_fresh = self.state_machine.on_key_down(vk, now, bubble_label=bubble_label)
            if is_fresh:
                self.sound_engine.play_key(vk, down=True)
                spec = get_key_spec(vk, mirror=self.config.mirror_keyboard)
                self.pet_window.trigger_key_feedback(spec)
        else:
            was_down = self.state_machine.on_key_up(vk, now)
            if was_down:
                self.sound_engine.play_key(vk, down=False)

        self.hud_window.on_key_event(vk, label, is_down)

    def _on_mouse_button(self, button: str, is_down: bool, gx: int, gy: int) -> None:
        now = int(time.monotonic() * 1000)
        dir_x, dir_y, local_norm, screen_norm = self._cursor_direction(gx, gy)
        if button == "left" and (self.state_machine.is_on_head(local_norm) or not is_down):
            if self.state_machine.is_on_head(local_norm):
                self.state_machine.on_head_click(is_down, now)
                if is_down:
                    self.sound_engine.play_mouse(button, down=True)
                    self.pet_window.trigger_mouse_feedback()
                    return
            elif not is_down:
                self.state_machine.on_head_click(False, now)
        self.state_machine.on_mouse_move(
            now, dir_x=dir_x, dir_y=dir_y, local_norm=local_norm, screen_norm=screen_norm
        )
        self.state_machine.on_mouse_button(button, is_down, now)
        if is_down:
            self.sound_engine.play_mouse(button, down=True)
            self.pet_window.trigger_mouse_feedback()
        else:
            self.sound_engine.play_mouse(button, down=False)

    def _on_mouse_moved(self, gx: int, gy: int) -> None:
        if self._last_cursor_gx is not None and self._last_cursor_gy is not None:
            if abs(gx - self._last_cursor_gx) + abs(gy - self._last_cursor_gy) < 4:
                return
        self._last_cursor_gx = gx
        self._last_cursor_gy = gy
        now = int(time.monotonic() * 1000)
        dir_x, dir_y, local_norm, screen_norm = self._cursor_direction(gx, gy)
        self.state_machine.on_mouse_move(
            now, dir_x=dir_x, dir_y=dir_y, local_norm=local_norm, screen_norm=screen_norm
        )

    def _reset_inputs(self) -> None:
        self.state_machine.reset_inputs()
        self.hud_window.reset_keys()

    def start(self) -> None:
        self.pet_window.show()
        self.hook.start()

    def quit(self) -> None:
        self.hook.stop()
        self.sound_engine.close()
        save_config(self.config)
        self.tray.hide()
        self.app.quit()


def main() -> int:
    # Ensure only one desktop pet instance runs at a time across Windows and macOS
    _mutex = None
    _lock_file: QLockFile | None = None
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            _mutex = kernel32.CreateMutexW(None, False, "Local\\XiaoBaiBuBaiDesktopPetSingleton")
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                return 0
        except Exception:
            _mutex = None
    else:
        try:
            lock_path = str(Path(QDir.tempPath()) / "xiaobaibubai_pet.lock")
            _lock_file = QLockFile(lock_path)
            _lock_file.setStaleLockTime(0)
            if not _lock_file.tryLock(100):
                return 0
        except Exception:
            _lock_file = None

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("xiaobaibubai")
    app.setQuitOnLastWindowClosed(False)
    controller = BongoCatController(app)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
