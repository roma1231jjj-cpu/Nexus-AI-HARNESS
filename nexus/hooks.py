"""Хуки Nexus: внешние команды на события агента.

Аналог pi.on() из pi-coding-agent. Хук — {name, command, timeout} в data/hooks.json
по имени события. Команда получает JSON на stdin, переменные NEXUS_EVENT и
NEXUS_WORKSPACE. Код возврата 2 на pre_tool блокирует вызов, stderr уходит модели
как причина отказа.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

EVENTS = (
    "session_start",
    "before_agent_start",
    "pre_tool",
    "post_tool",
    "on_error",
    "turn_end",
    "agent_end",
    "session_end",
)


class Hooks:
    def __init__(self, path: Path, workspace: Path) -> None:
        self.path = path
        self.workspace = workspace
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.root = path.parent.parent
        self.log_path = path.parent / "logs" / "hooks.log"
        self.load_error = ""
        self._lock = threading.Lock()
        self.load()

    # ---------------------------------------------------------------- загрузка
    def load(self) -> None:
        raw: dict[str, Any] = {}
        self.load_error = ""
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                self.load_error = f"hooks.json не прочитан: {exc}"
                self._log(self.load_error)
                raw = {}
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({event: [] for event in EVENTS}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        self.events = {
            event: [item for item in items if isinstance(item, dict) and item.get("command")]
            for event, items in raw.items()
            if event in EVENTS and isinstance(items, list)
        }

    def active(self, event: str) -> bool:
        return bool(self.events.get(event))

    def summary(self) -> dict[str, int]:
        return {event: len(items) for event, items in self.events.items() if items}

    # ---------------------------------------------------------------- вызов
    def _log(self, line: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%F %T')}] {line}\n")
        except OSError:
            pass

    def run(self, event: str, payload: dict[str, Any], blockable: bool = False) -> tuple[bool, str]:
        hooks = self.events.get(event) or []
        if not hooks:
            return True, ""
        body = json.dumps({"event": event, **payload}, ensure_ascii=False)
        env = dict(os.environ)
        env.update({"NEXUS_EVENT": event, "NEXUS_WORKSPACE": str(self.workspace),
                    "PYTHONIOENCODING": "utf-8"})
        for hook in hooks:
            name = hook.get("name") or hook["command"][:40]
            timeout = float(hook.get("timeout", 20))
            shell = bool(hook.get("shell", True))
            command = hook["command"].replace("{root}", str(self.root))
            try:
                done = subprocess.run(
                    command if shell else command.split(),
                    shell=shell, input=body, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout, env=env,
                    cwd=str(self.workspace) if self.workspace.exists() else None,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired:
                self._log(f"{event}/{name}: таймаут {timeout:g} с")
                if blockable:
                    return False, f"хук {name} не ответил за {timeout:g} с — действие заблокировано"
                continue
            except OSError as exc:
                self._log(f"{event}/{name}: не запустился ({exc})")
                if blockable:
                    return False, f"хук {name} не запустился ({exc}) — действие заблокировано"
                continue
            out, err = (done.stdout or "").strip(), (done.stderr or "").strip()
            if out:
                self._log(f"{event}/{name}: {out[:400]}")
            if done.returncode == 2:
                if blockable:
                    return False, err or out or f"хук {name} запретил действие"
                self._log(f"{event}/{name}: блокировка проигнорирована (событие не блокирующее)")
            elif done.returncode != 0:
                self._log(f"{event}/{name}: код {done.returncode} {err[:200]}")
        return True, ""

    def fire(self, event: str, **fields: Any) -> None:
        if self.active(event):
            with self._lock:
                self.run(event, fields)

    def pre_tool(self, tool_name: str, args: dict[str, Any], session_id: str) -> tuple[bool, str]:
        if not self.active("pre_tool"):
            return True, ""
        with self._lock:
            return self.run("pre_tool", {"tool": tool_name, "args": args, "session": session_id},
                            blockable=True)

    def post_tool(self, tool_name: str, args: dict[str, Any], output: str, ok: bool,
                  session_id: str, ms: int) -> None:
        if not self.active("post_tool"):
            return
        with self._lock:
            self.run("post_tool", {"tool": tool_name, "args": args, "output": output[:4000],
                                   "ok": ok, "session": session_id, "ms": ms})

    def on_error(self, session_id: str, text: str) -> None:
        if not self.active("on_error"):
            return
        with self._lock:
            self.run("on_error", {"session": session_id, "error": text[:4000]})
