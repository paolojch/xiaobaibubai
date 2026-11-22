"""Offscreen Qt smoke tests for config, CatPetWindow, and KeycapHudWindow."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config import PetConfig, load_config, save_config
from src.keycap_hud import KeycapHudWindow
from src.pet_window import CatPetWindow
from src.rig import get_key_spec
from src.state_machine import CatStateMachine

ROOT = Path(__file__).resolve().parent.parent


class TestUiSmoke(unittest.TestCase):
    def test_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.json"
            cfg = PetConfig(pet_size=9999, opacity=0.1, sound_pack="ink-black", idle_frame=1)
            self.assertFalse(cfg.show_keycap_hud)
            self.assertTrue(cfg.mirror_keyboard)
            save_config(cfg, cfg_path)
            loaded = load_config(cfg_path)
            self.assertEqual(loaded.pet_size, 640)
            self.assertEqual(loaded.opacity, 0.25)
            self.assertEqual(loaded.sound_pack, "ink-black")
            self.assertEqual(loaded.idle_frame, 1)

    def test_pet_window_and_hud_render_smoke(self) -> None:
        app = QApplication.instance() or QApplication([])
        cfg = PetConfig()
        self.assertEqual(cfg.idle_frame, 1)
        sm = CatStateMachine()
        pet = CatPetWindow(
            parts_dir=ROOT / "assets" / "parts",
            config=cfg,
            state_machine=sm,
            sound_packs=[("holy-panda", "Holy Panda")],
        )
        hud = KeycapHudWindow(enabled=True)

        # Verify idle sitting render
        self.assertEqual(pet.grab().width(), cfg.pet_size)

        # Verify mouse lean render
        sm.on_mouse_move(1000, dir_x=-0.7, dir_y=-0.1)
        self.assertEqual(pet.grab().width(), cfg.pet_size)

        # Verify typing crouch + bubbles render
        sm.on_key_down(ord("A"), 1020, bubble_label="A")
        sm.on_key_down(0x20, 1040, bubble_label=" ")
        pet.trigger_key_feedback(get_key_spec(ord("A"), mirror=True))
        hud.on_key_event(0xA2, "Ctrl", True)
        hud.on_key_event(0x43, "C", True)
        hud.on_key_event(0x43, "C", False)
        hud.on_key_event(0xA2, "Ctrl", False)

        menu = pet.build_menu()
        self.assertGreaterEqual(len(menu.actions()), 10)

        pet_pix = pet.grab()
        self.assertEqual(pet_pix.width(), cfg.pet_size)
        self.assertEqual(pet_pix.height(), cfg.pet_size)

        hud._tick()
        hud_pix = hud.grab()
        self.assertGreater(hud_pix.width(), 0)

        pet._anim_timer.stop()
        hud._timer.stop()
        pet.close()
        hud.close()
        app.processEvents()

    def test_live_pose_transitions_have_eyes_and_no_ghosting(self) -> None:
        import time
        import numpy as np
        from PySide6.QtGui import QImage

        app = QApplication.instance() or QApplication([])
        cfg = PetConfig(pet_size=420, idle_frame=1)
        sm = CatStateMachine(idle_frame=1, blink_enabled=False, mouse_react_enabled=True)
        pet = CatPetWindow(
            parts_dir=ROOT / "assets" / "parts",
            config=cfg,
            state_machine=sm,
            sound_packs=[("holy-panda", "Holy Panda")],
        )
        pet.show()
        app.processEvents()

        def grab_rgba() -> np.ndarray:
            qimg = pet.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
            w, h = qimg.width(), qimg.height()
            buf = bytes(qimg.constBits())
            return np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4)).copy()

        def count_eye_green(arr: np.ndarray) -> int:
            # Eyes are strictly in top half (y < 190 on 420x420)
            top = arr[:190]
            return int(((top[:, :, 3] > 200) & (top[:, :, 1] > 180) & (top[:, :, 0] > 140) & (top[:, :, 2] < 130)).sum())

        # 1. Idle sitting pose must render bright green eyes
        idle_arr = grab_rgba()
        self.assertGreater(count_eye_green(idle_arr), 180)

        # 2. Mouse mode must render green eyes and clear old upright sitting right ear region
        now = int(time.monotonic() * 1000)
        sm.on_mouse_move(now, dir_x=0.85, dir_y=-0.1)
        for _ in range(15):
            sm.snapshot(now)
        pet.repaint()
        app.processEvents()
        mouse_arr = grab_rgba()
        self.assertGreater(count_eye_green(mouse_arr), 180)
        # Right ear area of idle cat (~x=220..265, y=15..65 on 420x420) must now be empty (transparent)
        old_idle_ear_dark = int((mouse_arr[15:65, 225:265, 3] > 100).sum())
        self.assertLess(old_idle_ear_dark, 20, f"Ghosting detected in idle right ear region: {old_idle_ear_dark}")

        # 3. Typing mode must render angled green eyes and clear old left-shifted mouse ear region
        now2 = now + 20
        sm.on_key_down(ord("A"), now2, bubble_label="A")
        for _ in range(15):
            sm.snapshot(now2)
        pet.repaint()
        app.processEvents()
        type_arr = grab_rgba()
        self.assertGreater(count_eye_green(type_arr), 180)
        # Left leaning ear area of mouse cat (~x=55..110, y=15..65 on 420x420) must be cleared
        old_mouse_ear_dark = int((type_arr[15:65, 55:110, 3] > 100).sum())
        self.assertLess(old_mouse_ear_dark, 20, f"Ghosting detected in mouse left ear region: {old_mouse_ear_dark}")

        pet._anim_timer.stop()
        pet.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
