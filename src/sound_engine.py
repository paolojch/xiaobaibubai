"""Multi-channel mechanical keyboard and mouse sound playback engine."""

from __future__ import annotations

import json
import random
from pathlib import Path

# Virtual key -> pack.json group name
VK_TO_SOUND_GROUP: dict[int, str] = {
    0x20: "space",
    0x0D: "enter",
    0x08: "del",
    0x2E: "del",
    0x09: "tab",
    0xA0: "shiftLeft",
    0x10: "shiftLeft",
    0xA1: "shiftRight",
    0xA2: "ctrlLeft",
    0xA3: "ctrlLeft",
    0x11: "ctrlLeft",
}


def resolve_sound_group(vk: int, groups: dict[str, dict[str, list[str]]]) -> str:
    """Resolve the best matching sound group for a virtual key, falling back to 'default'."""
    preferred = VK_TO_SOUND_GROUP.get(vk, "default")
    if preferred in groups:
        return preferred
    return "default"


class SoundEngine:
    """Plays overlapping low-latency mechanical switch & mouse click WAV samples."""

    def __init__(self, sounds_root: Path) -> None:
        self.sounds_root = sounds_root
        self.enabled: bool = True
        self.mouse_enabled: bool = True
        self.volume: float = 0.75
        self.current_pack_id: str = "holy-panda"

        self._mixer = None
        self._available_packs: dict[str, dict] = {}
        self._kb_sounds: dict[str, dict[str, list]] = {}
        self._mouse_sounds: dict[str, dict[str, list]] = {}
        self._last_sample: dict[str, int] = {}

        self._init_mixer()
        self._scan_packs()
        self.set_keyboard_pack(self.current_pack_id)
        self._load_mouse_pack("orochi-v2")

    def _init_mixer(self) -> None:
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=256)
                pygame.mixer.init()
            pygame.mixer.set_num_channels(32)
            self._mixer = pygame.mixer
        except Exception:
            self._mixer = None

    def _scan_packs(self) -> None:
        kb_dir = self.sounds_root / "keyboard"
        if not kb_dir.exists():
            return
        for pdir in sorted(kb_dir.iterdir()):
            meta_file = pdir / "pack.json"
            if pdir.is_dir() and meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    meta["_dir"] = pdir
                    self._available_packs[meta["id"]] = meta
                except Exception:
                    continue

    def available_keyboard_packs(self) -> list[tuple[str, str]]:
        """Return [(pack_id, display_label), ...] sorted nicely."""
        return [
            (pid, f"{meta.get('brand', '')} {meta.get('name', pid)}".strip())
            for pid, meta in self._available_packs.items()
        ]

    def _load_group_sounds(self, pack_dir: Path, groups_meta: dict) -> dict[str, dict[str, list]]:
        loaded: dict[str, dict[str, list]] = {}
        for gname, gspec in groups_meta.items():
            loaded[gname] = {"down": [], "up": []}
            for direction in ("down", "up"):
                for fname in gspec.get(direction, []):
                    wav_path = pack_dir / fname
                    if not wav_path.exists() or self._mixer is None:
                        continue
                    try:
                        snd = self._mixer.Sound(str(wav_path))
                        snd.set_volume(self.volume)
                        loaded[gname][direction].append(snd)
                    except Exception:
                        continue
        return loaded

    def set_keyboard_pack(self, pack_id: str) -> bool:
        """Switch active keyboard sound pack."""
        if pack_id not in self._available_packs:
            if not self._available_packs:
                return False
            pack_id = next(iter(self._available_packs.keys()))

        meta = self._available_packs[pack_id]
        self.current_pack_id = pack_id
        self._kb_sounds = self._load_group_sounds(meta["_dir"], meta.get("groups", {}))
        self.set_volume(self.volume)
        return True

    def _load_mouse_pack(self, pack_id: str) -> None:
        pdir = self.sounds_root / "mouse" / pack_id
        meta_file = pdir / "pack.json"
        if not meta_file.exists():
            return
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            self._mouse_sounds = self._load_group_sounds(pdir, meta.get("groups", {}))
            self.set_volume(self.volume)
        except Exception:
            self._mouse_sounds = {}

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, float(volume)))
        for table in (self._kb_sounds, self._mouse_sounds):
            for g in table.values():
                for direction in ("down", "up"):
                    for snd in g.get(direction, []):
                        snd.set_volume(self.volume)

    def _pick_non_repeating(self, key: str, items: list):
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        last = self._last_sample.get(key, -1)
        choices = [i for i in range(len(items)) if i != last]
        idx = random.choice(choices)
        self._last_sample[key] = idx
        return items[idx]

    def play_key(self, vk: int, down: bool) -> None:
        if not self.enabled or self._mixer is None or not self._kb_sounds:
            return
        group = resolve_sound_group(vk, self._kb_sounds)
        direction = "down" if down else "up"
        candidates = self._kb_sounds.get(group, {}).get(direction, [])
        if not candidates and group != "default":
            candidates = self._kb_sounds.get("default", {}).get(direction, [])
        snd = self._pick_non_repeating(f"kb:{group}:{direction}", candidates)
        if snd is not None:
            snd.play()

    def play_mouse(self, button: str, down: bool) -> None:
        if not self.enabled or not self.mouse_enabled or self._mixer is None:
            return
        group = "right" if button == "right" else "left"
        direction = "down" if down else "up"
        candidates = self._mouse_sounds.get(group, {}).get(direction, [])
        snd = self._pick_non_repeating(f"mouse:{group}:{direction}", candidates)
        if snd is not None:
            snd.play()

    def close(self) -> None:
        if self._mixer is not None:
            try:
                self._mixer.quit()
            except Exception:
                pass
            self._mixer = None
