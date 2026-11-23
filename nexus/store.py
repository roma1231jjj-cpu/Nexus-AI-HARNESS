"""Хранение сессий: один JSON-файл на сессию, атомарная запись."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from . import protocol
from .config import SESSIONS

_lock = threading.RLock()
DEFAULT_TITLE = "Новая сессия"


class Store:
    def __init__(self, root: Path = SESSIONS) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- служебное
    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def _write(self, session: dict[str, Any]) -> None:
        path = self._path(session["id"])
        tmp = path.with_suffix(".json.tmp")
        with _lock:
            tmp.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)

    # ---------------------------------------------------------------- API
    def list(self) -> list[dict[str, Any]]:
        items = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append({
                "id": data.get("id"),
                "title": data.get("title") or "Без названия",
                "auto_title": bool(data.get("auto_title", False)),
                "updated": data.get("updated", 0),
                "created": data.get("created", 0),
                "messages": len(data.get("messages", [])),
            })
        items.sort(key=lambda s: s.get("updated", 0), reverse=True)
        return items

    def create(self, title: str = "") -> dict[str, Any]:
        clean = (title or "").strip()
        session = protocol.new_session(clean or DEFAULT_TITLE, auto_title=not clean)
        self._write(session)
        return session

    def get(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, session: dict[str, Any]) -> None:
        session["updated"] = protocol.now()
        self._write(session)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.exists():
            with _lock:
                path.unlink()
            return True
        return False

    def title_from(self, session: dict[str, Any], text: str) -> None:
        if session.get("title") in ("", DEFAULT_TITLE) and text.strip():
            clean = " ".join(text.strip().split())[:60]
            session["title"] = clean
            session["auto_title"] = False
