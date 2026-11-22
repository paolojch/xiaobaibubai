"""Cross-platform PyInstaller build script for xiaobaibubai (Windows .exe & macOS .app/.dmg/.zip)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
SPEC_WORK_DIR = BUILD_DIR / "pyinstaller_work"

EXCLUDED_MODULES = [
    "cv2",
    "numpy",
    "PIL",
    "scipy",
    "matplotlib",
    "tkinter",
    "unittest",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtMultimedia",
    "PySide6.QtNetwork",
    "PySide6.QtOpenGL",
    "PySide6.QtPdf",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]


def _prepare_icons() -> tuple[Path | None, Path | None]:
    """Generate .ico (Windows) and .icns (macOS) from the idle cat artwork if Pillow is available."""
    src_png = ROOT / "assets" / "parts" / "cat_idle_1.png"
    if not src_png.exists():
        return None, None
    try:
        from PIL import Image
    except Exception:
        return None, None

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    img = Image.open(src_png).convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    side = max(img.width, img.height)
    pad = int(side * 0.08)
    canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
    canvas.paste(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2))
    square = canvas.resize((512, 512), Image.Resampling.LANCZOS)

    ico_path = BUILD_DIR / "xiaobaibubai.ico"
    square.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    icns_path: Path | None = None
    if sys.platform == "darwin":
        iconset_dir = BUILD_DIR / "xiaobaibubai.iconset"
        iconset_dir.mkdir(parents=True, exist_ok=True)
        for sz in (16, 32, 128, 256, 512):
            square.resize((sz, sz), Image.Resampling.LANCZOS).save(
                iconset_dir / f"icon_{sz}x{sz}.png"
            )
            if sz <= 256:
                square.resize((sz * 2, sz * 2), Image.Resampling.LANCZOS).save(
                    iconset_dir / f"icon_{sz}x{sz}@2x.png"
                )
        candidate = BUILD_DIR / "xiaobaibubai.icns"
        res = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(candidate)],
            check=False,
        )
        if res.returncode == 0 and candidate.exists():
            icns_path = candidate

    return ico_path, icns_path


def _add_data_arg(rel_path: str) -> str:
    sep = ";" if os.name == "nt" else ":"
    return f"{ROOT / rel_path}{sep}{rel_path}"


def build(clean: bool = True) -> Path:
    if clean and SPEC_WORK_DIR.exists():
        shutil.rmtree(SPEC_WORK_DIR, ignore_errors=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    ico_path, icns_path = _prepare_icons()
    is_win = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--paths",
        str(ROOT),
        "--workpath",
        str(SPEC_WORK_DIR),
        "--distpath",
        str(DIST_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--add-data",
        _add_data_arg("assets/parts"),
        "--add-data",
        _add_data_arg("assets/frames"),
        "--add-data",
        _add_data_arg("assets/sounds"),
    ]

    for mod in EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", mod])

    if is_win:
        cmd.extend(["--onefile", "--name", "xiaobaibubai-Windows"])
        if ico_path and ico_path.exists():
            cmd.extend(["--icon", str(ico_path)])
    elif is_mac:
        cmd.extend(
            [
                "--onedir",
                "--name",
                "xiaobaibubai",
                "--osx-bundle-identifier",
                "com.xiaobaibubai.pet",
                "--hidden-import",
                "pynput.keyboard._darwin",
                "--hidden-import",
                "pynput.mouse._darwin",
            ]
        )
        if icns_path and icns_path.exists():
            cmd.extend(["--icon", str(icns_path)])
    else:
        cmd.extend(["--onefile", "--name", "xiaobaibubai-Linux"])

    cmd.append(str(ROOT / "src" / "main.py"))

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    if is_win:
        exe = DIST_DIR / "xiaobaibubai-Windows.exe"
        print(f"Built Windows portable executable: {exe} ({exe.stat().st_size / (1024 * 1024):.1f} MB)")
        return exe

    if is_mac:
        app_bundle = DIST_DIR / "xiaobaibubai.app"
        zip_path = DIST_DIR / "xiaobaibubai-macOS.zip"
        if zip_path.exists():
            zip_path.unlink()
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(app_bundle), str(zip_path)],
            check=True,
        )
        dmg_path = DIST_DIR / "xiaobaibubai-macOS.dmg"
        if dmg_path.exists():
            dmg_path.unlink()
        dmg_staging = BUILD_DIR / "dmg_staging"
        if dmg_staging.exists():
            shutil.rmtree(dmg_staging, ignore_errors=True)
        dmg_staging.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ditto", str(app_bundle), str(dmg_staging / "xiaobaibubai.app")],
            check=True,
        )
        applications_link = dmg_staging / "Applications"
        if not applications_link.exists():
            applications_link.symlink_to("/Applications")
        for attempt in range(3):
            res = subprocess.run(
                [
                    "hdiutil",
                    "create",
                    "-volname",
                    "xiaobaibubai",
                    "-srcfolder",
                    str(dmg_staging),
                    "-ov",
                    "-format",
                    "UDZO",
                    str(dmg_path),
                ],
                check=False,
            )
            if res.returncode == 0 and dmg_path.exists():
                break
            time.sleep(2)
        print(f"Built macOS bundle: {app_bundle}, {zip_path}, {dmg_path}")
        return dmg_path if dmg_path.exists() else zip_path

    return DIST_DIR / "xiaobaibubai-Linux"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build standalone xiaobaibubai packages")
    parser.add_argument("--no-clean", action="store_true", help="Keep previous PyInstaller work dir")
    args = parser.parse_args()
    build(clean=not args.no_clean)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
