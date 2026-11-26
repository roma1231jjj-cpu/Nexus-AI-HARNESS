"""Хранение сессий: один JSON-файл на сессию, атомарная запись."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from . import protocol
from .config import SESSIONS

_lock = threading.RLock()
DEFAULT_TITLE = "Новая сессия"
ID_RE = re.compile(r"^ses_[0-9a-f]{20}$")


class Store:
    def __init__(self, root: Path = SESSIONS) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- служебное
    def _path(self, session_id: str) -> Path | None:
        # id приходит из URL: без проверки формата "../config" читает и
        # перезаписывает файлы вне каталога сессий.
        if not isinstance(session_id, str) or not ID_RE.fullmatch(session_id):
            return None
        return self.root / f"{session_id}.json"

    def _write(self, session: dict[str, Any], create: bool = False) -> bool:
        path = self._path(str(session.get("id") or ""))
        if path is None:
            return False
        if not create and not path.exists():
            # сессию удалили, пока шёл ход, — не воскрешаем её
            return False
        tmp = path.with_suffix(".json.tmp")
        with _lock:
            tmp.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        return True

    # ---------------------------------------------------------------- API
    def list(self) -> list[dict[str, Any]]:
        items = []
        for path in self.root.glob("*.json"):
            if not ID_RE.fullmatch(path.stem):
                continue
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
        self._write(session, create=True)
        return session

    def get(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def save(self, session: dict[str, Any]) -> None:
        session["updated"] = protocol.now()
        self._write(session, create=False)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path is not None and path.exists():
            with _lock:
                path.unlink()
            return True
        return False

    def title_from(self, session: dict[str, Any], text: str) -> None:
        if session.get("title") in ("", DEFAULT_TITLE) and text.strip():
            clean = " ".join(text.strip().split())[:60]
            session["title"] = clean
            session["auto_title"] = False
