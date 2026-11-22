"""Сборка портабельной версии, архива и установщика.

    python packaging/build.py            # всё: exe, zip, setup
    python packaging/build.py --exe      # только один exe
    python packaging/build.py --zip
    python packaging/build.py --setup

Результат раскладывается по папкам, чтобы рабочие файлы не смешивались с релизами:

    dist/portable/Nexus-AI-HARNESS.exe
    dist/archive/Nexus-AI-HARNESS-<версия>-portable.zip
    dist/setup/Nexus-AI-HARNESS-Setup-<версия>.exe
    build/            промежуточные файлы PyInstaller
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexus.version import VERSION  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
EXE = "Nexus-AI-HARNESS.exe"


def make_icon() -> Path:
    """Простая иконка: тёмный квадрат с фиолетовой буквой N."""
    icon = ROOT / "packaging" / "nexus.ico"
    if icon.exists():
        return icon
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return icon
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=52, fill=(14, 10, 24, 255))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 168)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2 - 6), "N", font=font, fill=(160, 120, 255, 255), anchor="mm")
    image.save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return icon


def pyinstaller(entry: str, name: str, dist_dir: Path, extra: list[str]) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    command = [
        PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--name", name,
        "--distpath", str(dist_dir),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        *extra,
        str(ROOT / entry),
    ]
    print("сборка:", name)
    subprocess.run(command, check=True, cwd=str(ROOT))
    out = dist_dir / f"{name}.exe"
    print("готово:", out, f"{out.stat().st_size / 1048576:.1f} МБ")
    return out


def build_exe() -> Path:
    icon = make_icon()
    extra = [
        "--add-data", f"{ROOT / 'nexus' / 'ui'}{';' if sys.platform == 'win32' else ':'}ui",
        "--collect-submodules", "nexus",
        "--hidden-import", "nexus.daemon",
        "--hidden-import", "nexus.update",
        "--hidden-import", "nexus.version",
    ]
    if icon.exists():
        extra += ["--icon", str(icon)]
    return pyinstaller("app_main.py", "Nexus-AI-HARNESS", DIST / "portable", extra)


def build_zip(exe: Path) -> Path:
    folder = DIST / "archive"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"Nexus-AI-HARNESS-{VERSION}-portable.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe, EXE)
        for extra in ("README.md", "LICENSE"):
            path = ROOT / extra
            if path.exists():
                archive.write(path, extra)
        archive.writestr("data/workspace/.gitkeep", "")
    print("архив:", target, f"{target.stat().st_size / 1048576:.1f} МБ")
    return target


def build_setup(archive: Path) -> Path:
    icon = make_icon()
    extra = [
        "--add-data", f"{archive}{';' if sys.platform == 'win32' else ':'}.",
        "--hidden-import", "zipfile",
    ]
    if icon.exists():
        extra += ["--icon", str(icon)]
    return pyinstaller("packaging/installer.py", f"Nexus-AI-HARNESS-Setup-{VERSION}",
                       DIST / "setup", extra)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", action="store_true")
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--clean", action="store_true", help="удалить dist и build перед сборкой")
    args = parser.parse_args()
    everything = not (args.exe or args.zip or args.setup)

    if args.clean and everything:
        for folder in (DIST, BUILD):
            shutil.rmtree(folder, ignore_errors=True)

    exe = DIST / "portable" / EXE
    if everything or args.exe:
        exe = build_exe()
    archive = next((DIST / "archive").glob("Nexus-AI-HARNESS-*-portable.zip"), None)
    if everything or args.zip:
        if not exe.exists():
            print("нет exe — сначала --exe")
            return 2
        archive = build_zip(exe)
    if everything or args.setup:
        if archive is None or not archive.exists():
            print("нет архива — сначала --zip")
            return 2
        build_setup(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
