"""Verify cleaned & aligned cat frame assets."""

import unittest
from pathlib import Path
import numpy as np
from PIL import Image

FRAMES_DIR = Path(__file__).resolve().parent.parent / "assets" / "frames"
PARTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "parts"


class TestAssets(unittest.TestCase):
    def test_all_seven_frames_exist_with_uniform_dimensions(self) -> None:
        sizes = set()
        for i in range(1, 8):
            p = FRAMES_DIR / f"{i}.png"
            self.assertTrue(p.exists(), f"Missing frame: {p}")
            im = Image.open(p)
            self.assertEqual(im.mode, "RGBA")
            sizes.add(im.size)
            arr = np.array(im)
            self.assertEqual(arr[0, 0, 3], 0)
            self.assertEqual(arr[0, -1, 3], 0)
        self.assertEqual(len(sizes), 1, f"All frames must share identical canvas size, got {sizes}")

    def test_tail_s_badge_removed_in_frames_1_6_7(self) -> None:
        for i in (1, 6, 7):
            arr = np.array(Image.open(FRAMES_DIR / f"{i}.png"))
            roi = arr[645:725, 705:820]
            bright = (roi[:, :, 3] > 80) & (roi[:, :, 0] > 180) & (roi[:, :, 1] > 180) & (roi[:, :, 2] > 180)
            self.assertLess(int(bright.sum()), 20, f"Frame {i} still has bright [S] pixels: {int(bright.sum())}")

    def test_belly_and_chest_badges_removed(self) -> None:
        import cv2

        for i in (2, 3, 4, 5):
            arr = np.array(Image.open(FRAMES_DIR / f"{i}.png"))
            roi = arr[530:655, 455:640]
            bright = ((roi[:, :, 3] > 80) & (roi[:, :, 0] > 150) & (roi[:, :, 1] > 150) & (roi[:, :, 2] > 150)).astype(np.uint8)
            # Solid badge boxes (~70x60px) survive 9x9 erosion with >1000px; thin ~5px white paw strokes vanish completely
            eroded = cv2.erode(bright, np.ones((9, 9), np.uint8))
            self.assertEqual(int(eroded.sum()), 0, f"Frame {i} still has solid bright badge pixels: {int(eroded.sum())}")
        arr5 = np.array(Image.open(FRAMES_DIR / "5.png"))
        kb_roi = arr5[725:860, 440:730]
        green = (kb_roi[:, :, 3] > 40) & (kb_roi[:, :, 1] > 150) & (kb_roi[:, :, 2] < 140)
        self.assertLess(int(green.sum()), 10, f"Frame 5 still has green sparkle pixels: {int(green.sum())}")

    def test_keyboard_alignment_across_frames(self) -> None:
        ref = np.array(Image.open(FRAMES_DIR / "4.png"))
        ref_bot = (ref[820:930, 170:890, 3] > 128).astype(np.float32)
        for i in (1, 2, 3, 5, 6, 7):
            cur = np.array(Image.open(FRAMES_DIR / f"{i}.png"))
            cur_bot = (cur[820:930, 170:890, 3] > 128).astype(np.float32)
            iou = float((ref_bot * cur_bot).sum()) / float(np.maximum(ref_bot, cur_bot).sum())
            self.assertGreater(iou, 0.94, f"Frame {i} keyboard bottom alignment IoU too low: {iou:.4f}")

    def test_layered_rig_parts_exist(self) -> None:
        import json

        expected_parts = (
            "keyboard_base.png",
            "mouse_base.png",
            "body_idle.png",
            "head_idle_open.png",
            "head_idle_squint.png",
            "body_typing.png",
            "head_typing_open.png",
            "head_typing_squint.png",
            "body_mouse.png",
            "head_mouse_open.png",
            "head_mouse_squint.png",
            "head_mouse_sil.png",
            "whiskers_mouse_left.png",
            "whiskers_mouse_right.png",
            "arm_mouse_right_rest.png",
            "body_torso.png",
            "head_open.png",
            "head_squint.png",
        )
        for fname in expected_parts:
            p = PARTS_DIR / fname
            self.assertTrue(p.exists(), f"Missing part: {p}")
            with Image.open(p) as im:
                self.assertEqual(im.mode, "RGBA")
        meta = json.loads((PARTS_DIR / "parts_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["canvas_size"], 940)
        self.assertEqual(len(meta["kb_quad"]), 4)
        for mode in ("idle", "typing", "mouse"):
            self.assertIn(mode, meta["modes"])
            for eye_key in ("left_eye", "right_eye"):
                self.assertIn("angle_deg", meta["modes"][mode][eye_key])


if __name__ == "__main__":
    unittest.main()
