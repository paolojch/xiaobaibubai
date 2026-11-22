"""Unit tests for mechanical keyboard & mouse SoundEngine."""

import unittest
from pathlib import Path

from src.sound_engine import SoundEngine, resolve_sound_group

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "assets" / "sounds"


class TestSoundEngine(unittest.TestCase):
    def test_sound_packs_and_group_resolution(self) -> None:
        engine = SoundEngine(SOUNDS_DIR)
        try:
            packs = dict(engine.available_keyboard_packs())
            self.assertTrue({"holy-panda", "ink-black", "alpaca", "blue-abs"}.issubset(packs.keys()))

            for pid in ("holy-panda", "ink-black", "alpaca", "blue-abs"):
                self.assertTrue(engine.set_keyboard_pack(pid))
                self.assertEqual(resolve_sound_group(0x20, engine._kb_sounds), "space")
                self.assertEqual(resolve_sound_group(0x41, engine._kb_sounds), "default")
                engine.play_key(0x20, down=True)
                engine.play_key(0x20, down=False)
                engine.play_key(0x41, down=True)

            self.assertEqual(resolve_sound_group(0xA0, {"default": {}, "shiftLeft": {}}), "shiftLeft")
            self.assertEqual(resolve_sound_group(0xA0, {"default": {}}), "default")

            engine.set_volume(0.4)
            self.assertEqual(engine.volume, 0.4)
            engine.play_mouse("left", down=True)
            engine.play_mouse("left", down=False)
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
