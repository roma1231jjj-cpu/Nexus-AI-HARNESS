"""Скриншоты для README и релиза: по одному на каждую тему.

    python packaging/shots.py                # docs/theme-*.png
    python packaging/shots.py --port 8848

Поднимает демон, если он не запущен, подкладывает демонстрационную сессию,
снимает по кадру в каждой теме и убирает за собой.
"""

from __future__ import annotations

import argparse
import atexit
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexus import protocol  # noqa: E402
from nexus.config import SESSIONS, WORKSPACE  # noqa: E402

THEMES = [("dark", "theme-dark.png"), ("light", "theme-light.png"),
          ("graphite", "theme-graphite.png")]

DEMO_ID = "ses_demo000000000000000000000"

DEMO_MESSAGES = [
    ("user", "Проверь папку проекта и скажи, что тут можно улучшить."),
    ("assistant", "Посмотрел: 12 файлов, тестов нет, README устарел. "
                  "Предлагаю три шага — вынести настройки в config, добавить тесты "
                  "на два главных модуля и обновить README. Начинаю с конфига."),
    ("user", "Открой страницу с документацией и забери оттуда пример."),
    ("assistant", "Открыл вкладку в твоём браузере, забрал пример: "
                  "`client.connect(url, timeout=5)`. Перенёс в проект, подставил наш адрес."),
]


def port_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


def seed_demo() -> Path:
    # бэкап с меткой времени: не затираем предыдущий, если прошлый прогон упал
    backup = ROOT / "build" / f"sessions-backup-{int(time.time())}"
    if SESSIONS.exists():
        shutil.copytree(SESSIONS, backup)
    SESSIONS.mkdir(parents=True, exist_ok=True)
    messages = []
    for role, text in DEMO_MESSAGES:
        if role == "user":
            messages.append(protocol.message("user", [protocol.text_part(text)]))
        else:
            messages.append(protocol.message("assistant", [protocol.text_part(text)]))
    demo = {
        "id": DEMO_ID,
        "title": "Проверь папку проекта и скажи, что тут можно улучшить.",
        "created": time.time() - 900,
        "updated": time.time(),
        "mode": "act",
        "messages": messages,
        "todos": [
            {"id": "1", "text": "Разобрать структуру проекта", "state": "done"},
            {"id": "2", "text": "Вынести настройки в config", "state": "doing"},
            {"id": "3", "text": "Добавить тесты", "state": "todo"},
        ],
    }
    (SESSIONS / f"{DEMO_ID}.json").write_text(json.dumps(demo, ensure_ascii=False), encoding="utf-8")
    return backup


def restore(backup: Path) -> None:
    (SESSIONS / f"{DEMO_ID}.json").unlink(missing_ok=True)
    if backup.exists():
        shutil.rmtree(SESSIONS, ignore_errors=True)
        shutil.copytree(backup, SESSIONS)
        shutil.rmtree(backup, ignore_errors=True)


def start_daemon(port: int) -> subprocess.Popen | None:
    if port_alive(port):
        return None
    exe = ROOT / ".venv" / "Scripts" / "python.exe"
    python = str(exe if exe.exists() else sys.executable)
    log = open(ROOT / "build" / "shots-daemon.log", "w", encoding="utf-8") \
        if (ROOT / "build").exists() else subprocess.DEVNULL
    proc = subprocess.Popen([python, "run.py", str(port)], cwd=str(ROOT),
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        if port_alive(port):
            break
        time.sleep(0.5)
    return proc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8848)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    (ROOT / "build").mkdir(parents=True, exist_ok=True)
    if port_alive(args.port):
        print(f"демон уже запущен на порту {args.port}: останови его, иначе демо-сессия "
              "попадёт в живые данные")
        return 4

    backup = seed_demo()
    atexit.register(restore, backup)
    daemon = start_daemon(args.port)
    if daemon:
        atexit.register(daemon.terminate)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("нужен playwright: pip install playwright")
        restore(backup)
        return 2

    url = f"http://127.0.0.1:{args.port}/"
    shots = 0
    with sync_playwright() as play:
        browser = None
        for channel in ("chrome", "msedge", None):
            try:
                browser = play.chromium.launch(channel=channel, headless=True) if channel \
                    else play.chromium.launch(headless=True)
                break
            except Exception:  # noqa: BLE001
                continue
        if browser is None:
            print("не нашёл браузер для playwright")
            restore(backup)
            return 3

        page = browser.new_page(viewport={"width": args.width, "height": args.height},
                                device_scale_factor=1)
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(1200)
        # открываем демонстрационную сессию
        try:
            page.click(f"text={DEMO_MESSAGES[0][1][:32]}", timeout=4000)
            page.wait_for_timeout(900)
        except Exception:  # noqa: BLE001
            pass

        for theme, filename in THEMES:
            page.evaluate("(theme) => localStorage.setItem('nexus-theme', theme)", theme)
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1100)
            try:
                page.click(f"text={DEMO_MESSAGES[0][1][:32]}", timeout=3000)
                page.wait_for_timeout(700)
            except Exception:  # noqa: BLE001
                pass
            target = ROOT / "docs" / filename
            page.screenshot(path=str(target))
            print("скриншот:", target.relative_to(ROOT), f"{target.stat().st_size // 1024} КБ")
            shots += 1
        browser.close()

    restore(backup)
    if daemon:
        daemon.terminate()
    print("готово, кадров:", shots)
    return 0 if shots == len(THEMES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
