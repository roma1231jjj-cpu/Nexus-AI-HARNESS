"""Установщик Nexus-AI-HARNESS: распаковывает портабельную сборку и делает ярлыки.

Собирается PyInstaller'ом с архивом внутри. Ставит без прав администратора:
%LOCALAPPDATA%\\Nexus-AI-HARNESS, ярлык на рабочем столе и в меню «Пуск»,
пишет деинсталлятор и запись в «Установка и удаление программ».
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from nexus.version import VERSION

APP_NAME = "Nexus-AI-HARNESS"
TARGET = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME

UNINSTALL_BAT = """@echo off
chcp 65001 >nul
echo Удаляю {name}...
taskkill /f /im Nexus-AI-HARNESS.exe >nul 2>&1
timeout /t 1 >nul
del "%USERPROFILE%\\Desktop\\{name}.lnk" >nul 2>&1
del "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{name}.lnk" >nul 2>&1
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{name}" /f >nul 2>&1
rem данные (сессии, обучение, снимки) не удаляем: переносим рядом и оставляем
if exist "{target}\\data" move "{target}\\data" "%LOCALAPPDATA%\\{name}-data" >nul 2>&1
rmdir /s /q "{target}" >nul 2>&1
echo Готово.
timeout /t 2 >nul
"""


def payload() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    found = sorted(base.glob("Nexus-AI-HARNESS-*-portable.zip"))
    if not found:
        raise SystemExit("в установщике нет архива сборки")
    return found[0]


def shortcut(target: Path, link: Path, workdir: Path) -> None:
    script = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{link}');"
        f"$s.TargetPath = '{target}';"
        f"$s.WorkingDirectory = '{workdir}';"
        f"$s.Description = '{APP_NAME}';"
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False)


def main() -> int:
    archive = payload()
    print(f"{APP_NAME}: установка в {TARGET}")
    if TARGET.exists():
        for process in ("Nexus-AI-HARNESS.exe",):
            subprocess.run(["taskkill", "/f", "/im", process], capture_output=True)
    TARGET.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(TARGET)

    exe = TARGET / "Nexus-AI-HARNESS.exe"
    if not exe.exists():
        raise SystemExit("в архиве нет exe")

    keep = Path(os.environ.get("LOCALAPPDATA", Path.home())) / f"{APP_NAME}-data"
    if keep.exists():
        shutil.copytree(keep, TARGET / "data", dirs_exist_ok=True)
        shutil.rmtree(keep, ignore_errors=True)

    desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop" / f"{APP_NAME}.lnk"
    start = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" /
             "Start Menu" / "Programs" / f"{APP_NAME}.lnk")
    for link in (desktop, start):
        try:
            shortcut(exe, link, TARGET)
        except Exception as exc:  # noqa: BLE001
            print("ярлык не создан:", exc)

    (TARGET / "uninstall.bat").write_text(
        UNINSTALL_BAT.format(name=APP_NAME, target=TARGET), encoding="utf-8")

    uninstall_cmd = f'"{TARGET / "uninstall.bat"}"'
    subprocess.run(["reg", "add", rf"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}",
                    "/v", "DisplayName", "/d", APP_NAME, "/f"], capture_output=True)
    subprocess.run(["reg", "add", rf"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}",
                    "/v", "DisplayVersion", "/d", VERSION, "/f"], capture_output=True)
    subprocess.run(["reg", "add", rf"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}",
                    "/v", "UninstallString", "/d", uninstall_cmd, "/f"], capture_output=True)
    subprocess.run(["reg", "add", rf"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}",
                    "/v", "InstallLocation", "/d", str(TARGET), "/f"], capture_output=True)

    print("запускаю приложение")
    subprocess.Popen([str(exe)], cwd=str(TARGET), close_fds=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        ctypes.windll.user32.MessageBoxW(0, str(exc), "Ошибка установки", 0x10)
        raise
