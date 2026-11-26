"""Автообновление Nexus-AI-HARNESS из git-репозитория.

Проверка тихая: `git fetch` раз в несколько часов, сравнение с upstream.
Применение — `git pull --ff-only`, поэтому локальные правки не затираются:
если ветки разошлись, обновление вежливо отказывается.

    python run.py --update     # обновить и выйти
    python -m nexus.update     # то же самое
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import config
from .version import ASSETS, RELEASES_API, VERSION

ROOT = config.ROOT
FROZEN = config.FROZEN
STAMP = ROOT / "data" / ".update-check"
CHECK_EVERY = 6 * 3600


def _git(*args: str, timeout: float = 60) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return done.returncode, (done.stdout or "").strip() + (done.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def available() -> bool:
    if FROZEN:
        return True
    return (ROOT / ".git").exists() and _git("rev-parse", "--is-inside-work-tree")[0] == 0


def _release() -> dict[str, Any]:
    request = urllib.request.Request(RELEASES_API, headers={
        "User-Agent": f"Nexus-AI-HARNESS/{VERSION}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def _frozen_status(force: bool = False) -> dict[str, Any]:
    fresh = STAMP.exists() and time.time() - STAMP.stat().st_mtime < CHECK_EVERY
    cached: dict[str, Any] = {}
    if STAMP.exists():
        try:
            cached = json.loads(STAMP.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
    if not force and fresh and cached.get("mode") == "release":
        return cached
    try:
        data = _release()
        latest = str(data.get("tag_name") or "")
        assets = [{"name": item.get("name"), "url": item.get("browser_download_url"),
                   "size": item.get("size"), "digest": item.get("digest")}
                  for item in data.get("assets") or []]
        result = {
            "ok": True, "mode": "release", "current": VERSION, "latest": latest.lstrip("v"),
            "behind": 0 if latest.lstrip("v") == VERSION else 1,
            "html": data.get("html_url"), "assets": assets,
            "dirty": False, "checked": int(time.time()),
        }
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        result = {"ok": False, "mode": "release", "reason": f"нет связи с GitHub: {exc}",
                  "code": "ev.updateOffline", "vars": {"e": str(exc)},
                  "current": VERSION, "checked": int(time.time())}
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def status() -> dict[str, Any]:
    if FROZEN:
        return _frozen_status()
    if not available():
        return {"ok": False, "reason": "это не git-копия", "code": "ev.updateNotGit", "vars": {}}
    code, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return {"ok": False, "reason": branch[:200], "code": "ev.updateGitError",
                "vars": {"e": branch[:200]}}
    _, remote = _git("remote", "get-url", "origin")
    _, local = _git("rev-parse", "--short", "HEAD")
    _, when = _git("log", "-1", "--format=%cI")
    _, subject = _git("log", "-1", "--format=%s")
    _, drifts = _git("status", "--porcelain")
    behind = ahead = 0
    if remote:
        code, counts = _git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
        if code == 0 and counts:
            parts = counts.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
    return {
        "ok": True, "branch": branch, "remote": remote, "commit": local,
        "committed": when, "subject": subject, "behind": behind, "ahead": ahead,
        "dirty": bool(drifts.strip()),
        "checked": int(time.time()),
    }


def check(force: bool = False) -> dict[str, Any]:
    if FROZEN:
        return _frozen_status(force=force)
    if not available():
        return {"ok": False, "reason": "это не git-копия", "code": "ev.updateNotGit", "vars": {}}
    fresh = STAMP.exists() and time.time() - STAMP.stat().st_mtime < CHECK_EVERY
    if not force and fresh:
        return status()
    _git("fetch", "--quiet", "--prune", timeout=90)
    result = status()
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def apply() -> dict[str, Any]:
    if FROZEN:
        return _apply_release()
    if not available():
        return {"ok": False, "reason": "это не git-копия", "code": "ev.updateNotGit", "vars": {}}
    before = status()
    if not before.get("remote"):
        return {"ok": False, "reason": "не задан origin", "code": "ev.updateNoRemote", "vars": {}}
    if before.get("dirty"):
        return {"ok": False, "reason": "есть локальные правки, обновление отложено",
                "code": "ev.updateDirty", "vars": {}, "dirty": True}
    code, output = _git("pull", "--ff-only", timeout=180)
    after = status()
    return {"ok": code == 0, "output": output[-1500:], "before": before, "after": after}


def main() -> int:
    result = apply()
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())


def _apply_release() -> dict[str, Any]:
    """Портабельная сборка: качает новый exe рядом и подменяет его при перезапуске."""
    state = _frozen_status(force=True)
    if not state.get("ok"):
        return {"ok": False, "reason": state.get("reason", "нет данных о релизе"),
                "code": state.get("code") or "ev.updateNoRelease",
                "vars": state.get("vars") or {}}
    if not state.get("behind"):
        return {"ok": True, "output": f"уже последняя версия ({VERSION})",
                "code": "ev.updateLatest", "vars": {"v": VERSION}}
    exe = Path(sys_executable())
    asset = next((a for a in state.get("assets", [])
                  if a["name"] == ASSETS["portable"]), None)
    if not asset:
        return {"ok": False, "reason": "в релизе нет файла Nexus-AI-HARNESS.exe",
                "code": "ev.updateNoAsset", "vars": {}}
    target = exe.with_suffix(".exe.new")
    expect_size = int(asset.get("size") or 0)
    digest = str(asset.get("digest") or "").lower()
    hasher = hashlib.sha256()
    total = 0
    try:
        request = urllib.request.Request(asset["url"], headers={
            "User-Agent": f"Nexus-AI-HARNESS/{VERSION}"})
        with urllib.request.urlopen(request, timeout=180) as response, open(target, "wb") as fh:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                hasher.update(chunk)
                total += len(chunk)
                fh.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        return {"ok": False, "reason": f"не скачалось: {exc}",
                "code": "ev.updateDownloadFailed", "vars": {"e": str(exc)}}
    if expect_size and total != expect_size:
        target.unlink(missing_ok=True)
        return {"ok": False, "reason": f"скачано {total} байт вместо {expect_size} — файл оборван",
                "code": "ev.updateDownloadFailed", "vars": {}}
    if digest.startswith("sha256:") and hasher.hexdigest() != digest[7:]:
        target.unlink(missing_ok=True)
        return {"ok": False, "reason": "SHA-256 скачанного файла не совпал с релизом",
                "code": "ev.updateHashMismatch", "vars": {}}
    return {"ok": True, "output": f"скачана версия {state.get('latest')} — применится при следующем запуске",
            "code": "ev.updateDownloaded", "vars": {"v": state.get("latest")},
            "pending": str(target)}


def sys_executable() -> str:
    import sys

    return sys.executable if FROZEN else str(ROOT / "Nexus-AI-HARNESS.exe")


def apply_pending() -> bool:
    """Подменяет exe, скачанный прошлым обновлением. Возвращает True, если нужен рестарт."""
    if not FROZEN:
        return False
    exe = Path(sys_executable())
    fresh = exe.with_suffix(".exe.new")
    if not fresh.exists() or fresh.stat().st_size < 1_000_000:
        return False
    script = exe.with_suffix(".update.bat")
    lines = [
        "@echo off",
        "timeout /t 2 >nul",
        f'move /y "{fresh}" "{exe}" >nul',
        f'start "" "{exe}"',
        'del "%~f0"',
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x00000008, close_fds=True)
    return True
