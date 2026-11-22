"""Точка входа Nexus-AI-HARNESS: и для портабельного exe, и для запуска из исходников.

    Nexus-AI-HARNESS.exe            поднять демон и открыть окно
    Nexus-AI-HARNESS.exe --port 8850
    Nexus-AI-HARNESS.exe --no-browser
    Nexus-AI-HARNESS.exe --update
    Nexus-AI-HARNESS.exe --check-update
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

from nexus import config, update
from nexus.version import VERSION


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def prepare() -> None:
    for folder in (config.DATA, config.SESSIONS, config.WORKSPACE, config.SHOTS,
                   config.DATA / "logs"):
        folder.mkdir(parents=True, exist_ok=True)
    config_path = config.DATA / "config.json"
    if not config_path.exists():
        config.save(config.load())


def open_window(url: str) -> None:
    """Открывает интерфейс в отдельном окне, если есть браузер с режимом --app."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Vivaldi\Application\vivaldi.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for exe in candidates:
        if os.path.exists(exe):
            os.system(f'start "" "{exe}" --app={url} --window-size=1180,900')
            return
    webbrowser.open(url)


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print(f"Nexus-AI-HARNESS {VERSION}")
        return 0
    if "--update" in args:
        result = update.apply()
        print(result.get("output") or result.get("reason") or "готово")
        return 0 if result.get("ok") else 1
    if "--check-update" in args:
        print(update.check(force=True))
        return 0

    if update.apply_pending():
        print("обновление скачано — перезапускаюсь с новой версии")
        return 0

    prepare()
    port = int(next((a for a in args if a.isdigit()), 8848))
    url = f"http://127.0.0.1:{port}/"

    if port_busy(port):
        print(f"демон уже работает: {url}")
        if "--no-browser" not in args:
            open_window(url)
        return 0

    if "--no-browser" not in args:
        threading.Timer(1.2, lambda: open_window(url)).start()

    from nexus.daemon import serve
    print(f"Nexus-AI-HARNESS {VERSION}: {url}")
    serve(port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
