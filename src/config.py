"""Configuration persistence for the BongoCat desktop pet."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def get_resource_root() -> Path:
    """Return read-only asset root (supports source tree and PyInstaller frozen bundle)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _is_writable_dir(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def get_default_config_path() -> Path:
    """Return a writable config.json path across source runs, Windows .exe, and macOS .app."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent / "config.json"

    if sys.platform == "win32":
        exe_dir = Path(sys.executable).resolve().parent
        if _is_writable_dir(exe_dir):
            return exe_dir / "config.json"
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
        return base / "xiaobaibubai" / "config.json"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "xiaobaibubai" / "config.json"

    return Path.home() / ".config" / "xiaobaibubai" / "config.json"


PROJECT_ROOT = get_resource_root()
DEFAULT_CONFIG_PATH = get_default_config_path()


@dataclass
class PetConfig:
    """User preferences persisted across launches."""

    window_x: int | None = None
    window_y: int | None = None
    hud_x: int | None = None
    hud_y: int | None = None
    pet_size: int = 340
    opacity: float = 1.0
    always_on_top: bool = True
    click_through: bool = False
    show_keycap_bubble: bool = True
    show_keycap_hud: bool = False
    show_sparkles: bool = True
    mirror_keyboard: bool = True
    eye_tracking_enabled: bool = True
    petting_enabled: bool = True
    key_glow_enabled: bool = True
    sound_enabled: bool = True
    mouse_sound_enabled: bool = True
    sound_pack: str = "holy-panda"
    sound_volume: float = 0.75
    idle_frame: int = 1  # 1 = upright sitting pose (default), 4 = crouched curled paws
    blink_enabled: bool = True
    mouse_react_enabled: bool = True

    def clamped(self) -> PetConfig:
        """Return a copy with numeric bounds safely clamped."""
        self.pet_size = max(180, min(640, int(self.pet_size)))
        self.opacity = max(0.25, min(1.0, float(self.opacity)))
        self.sound_volume = max(0.0, min(1.0, float(self.sound_volume)))
        if self.idle_frame not in (1, 4):
            self.idle_frame = 1
        return self


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> PetConfig:
    """Load configuration from JSON, falling back to defaults on error."""
    if not path.exists():
        return PetConfig().clamped()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        valid_fields = set(PetConfig.__dataclass_fields__.keys())
        filtered = {k: v for k, v in raw.items() if k in valid_fields}
        return PetConfig(**filtered).clamped()
    except Exception:
        return PetConfig().clamped()


def save_config(cfg: PetConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Persist configuration atomically."""
    cfg.clamped()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
