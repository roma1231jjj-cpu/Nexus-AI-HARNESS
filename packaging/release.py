"""Публикация релиза на GitHub: тег по версии + три файла сборки.

    python packaging/release.py                  # версия из nexus/version.py
    python packaging/release.py --tag v1.2.0

Нужен доступ к репозиторию: токен берётся из git credential helper либо из
переменных GITHUB_TOKEN / GH_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
sys.path.insert(0, str(ROOT))

from nexus.version import REPO, VERSION  # noqa: E402


def token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    payload = chr(10).join(["protocol=https", "host=github.com", ""])
    try:
        env = dict(os.environ)
        env.pop("GIT_TERMINAL_PROMPT", None)
        print("беру токен из git credential helper…")
        cred = subprocess.run(["git", "credential", "fill"], cwd=str(ROOT), env=env,
                              input=payload, capture_output=True, text=True, timeout=30)
        for line in cred.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def api(method: str, url: str, payload=None, raw: bytes | None = None,
        ctype: str = "application/json", auth: str = "") -> dict:
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {auth}", "Accept": "application/vnd.github+json",
        "Content-Type": ctype, "User-Agent": "Nexus-AI-HARNESS-release"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode() or "{}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=f"v{VERSION}")
    args = parser.parse_args()
    auth = token()
    if not auth:
        print("нет доступа: задай GITHUB_TOKEN или войди в git credential helper")
        return 2

    dist = ROOT / "dist"
    assets = [
        dist / "portable" / "Nexus-AI-HARNESS.exe",
        dist / "archive" / f"Nexus-AI-HARNESS-{VERSION}-portable.zip",
        dist / "setup" / f"Nexus-AI-HARNESS-Setup-{VERSION}.exe",
    ]
    missing = [str(a) for a in assets if not a.exists()]
    if missing:
        print("сначала собери: python packaging/build.py --clean")
        print("нет файлов:", missing)
        return 2

    print("публикую ветку и тег…")
    subprocess.run(["git", "tag", "-f", args.tag, "-m", f"Nexus-AI-HARNESS {VERSION}"],
                   cwd=str(ROOT))
    # ветка обновлений — main: master в репозитории нет, пуш туда создавал
    # сиротскую ветку, и автообновление не видело новых версий
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=str(ROOT))
    subprocess.run(["git", "push", "-f", "origin", args.tag], cwd=str(ROOT))

    note = ["Портабельный exe, архив и установщик.",
            "Автообновление: приложение само находит этот релиз",
            "и подменяет бинарник при перезапуске."]
    body = "## Nexus-AI-HARNESS " + VERSION + "" + chr(10) * 2 + " ".join(note) + chr(10)

    release = api("POST", f"https://api.github.com/repos/{REPO}/releases", {
        "tag_name": args.tag, "name": f"Nexus-AI-HARNESS {VERSION}",
        "body": body, "draft": False, "prerelease": False}, auth=auth)
    print("релиз:", release["html_url"])
    for path in assets:
        result = api("POST",
                     f"https://uploads.github.com/repos/{REPO}/releases/{release['id']}/assets"
                     f"?name={path.name}", raw=path.read_bytes(),
                     ctype="application/octet-stream", auth=auth)
        print("загружено:", result.get("name"), f"{result.get('size', 0) / 1048576:.1f} МБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
