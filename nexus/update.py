"""Автообновление Nexus-AI-HARNESS из git-репозитория.

Проверка тихая: `git fetch` раз в несколько часов, сравнение с upstream.
Применение — `git pull --ff-only`, поэтому локальные правки не затираются:
если ветки разошлись, обновление вежливо отказывается.

    python run.py --update     # обновить и выйти
    python -m nexus.update     # то же самое
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
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
    return (ROOT / ".git").exists() and _git("rev-parse", "--is-inside-work-tree")[0] == 0


def status() -> dict[str, Any]:
    if not available():
        return {"ok": False, "reason": "это не git-копия"}
    code, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return {"ok": False, "reason": branch[:200]}
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
    if not available():
        return {"ok": False, "reason": "это не git-копия"}
    fresh = STAMP.exists() and time.time() - STAMP.stat().st_mtime < CHECK_EVERY
    if not force and fresh:
        return status()
    _git("fetch", "--quiet", "--prune", timeout=90)
    result = status()
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def apply() -> dict[str, Any]:
    if not available():
        return {"ok": False, "reason": "это не git-копия"}
    before = status()
    if not before.get("remote"):
        return {"ok": False, "reason": "не задан origin"}
    if before.get("dirty"):
        return {"ok": False, "reason": "есть локальные правки, обновление отложено",
                "dirty": True}
    code, output = _git("pull", "--ff-only", timeout=180)
    after = status()
    return {"ok": code == 0, "output": output[-1500:], "before": before, "after": after}


def main() -> int:
    result = apply()
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
