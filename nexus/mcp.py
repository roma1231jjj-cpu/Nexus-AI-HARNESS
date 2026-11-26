"""MCP-клиент Nexus: внешние серверы инструментов по stdio (JSON-RPC 2.0).

Конфиг: config["mcp"]["servers"] = {"browse": {"command": [...], "env": {...},
"class": "browser", "prefix": "mcp"}}.

Инструменты сервера регистрируются как mcp__<server>__<tool> и живут в общем
реестре tools.TOOLS, поэтому модель видит их наравне со встроенными.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .version import VERSION

LOG_LIMIT = 4000


class McpError(RuntimeError):
    pass


class McpServer:
    def __init__(self, name: str, spec: dict[str, Any], log_dir: Path) -> None:
        self.name = name
        self.spec = spec
        self.log_path = log_dir / f"mcp-{name}.log"
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.pending: dict[int, queue.Queue] = {}
        self._next_id = 0
        self._lock = threading.Lock()
        self.info: dict[str, Any] = {}
        self.tools: list[dict[str, Any]] = []
        self.error = ""

    # ------------------------------------------------------------------ процесс
    def _log(self, text: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%F %T')}] {text[:LOG_LIMIT]}\n")
        except OSError:
            pass

    def start(self) -> None:
        command = self.spec.get("command")
        if isinstance(command, str):
            command = [command]
        if not command:
            raise McpError("нет command")
        env = dict(os.environ)
        env.update({k: str(v) for k, v in (self.spec.get("env") or {}).items()})
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            cwd=self.spec.get("cwd") or None,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read_stdout, daemon=True, name=f"mcp-{self.name}-out").start()
        threading.Thread(target=self._read_stderr, daemon=True, name=f"mcp-{self.name}-err").start()
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nexus-harness", "version": VERSION},
        }, timeout=30)
        self.info = result or {}
        self._notify("notifications/initialized", {})
        listing = self.request("tools/list", {}, timeout=30) or {}
        self.tools = listing.get("tools") or []
        self._log(f"подключён: {self.info.get('serverInfo', {}).get('name', '?')}, "
                  f"инструментов {len(self.tools)}")

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            self.lines.put(line)
        self.lines.put(None)

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            if line.strip():
                self._log(line.strip())

    # ------------------------------------------------------------------ обмен
    def _send(self, payload: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise McpError("сервер не запущен")
        with self._lock:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any], timeout: float = 60) -> Any:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        box: queue.Queue = queue.Queue()
        self.pending[request_id] = box
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline = time.time() + timeout
            while time.time() < deadline:
                wait = max(0.05, min(0.5, deadline - time.time()))
                try:
                    line = self.lines.get(timeout=wait)
                except queue.Empty:
                    continue
                if line is None:
                    raise McpError(f"{self.name}: процесс закрыл поток")
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    self._log(f"мусор в потоке: {line[:200]}")
                    continue
                if data.get("id") != request_id:
                    self._log(f"постороннее сообщение: {line[:300]}")
                    continue
                if "error" in data:
                    err = data["error"]
                    raise McpError(f"{self.name}: {err.get('message') or err}")
                return data.get("result")
            raise McpError(f"{self.name}: таймаут {method}")
        finally:
            self.pending.pop(request_id, None)

    def call(self, tool: str, arguments: dict[str, Any], timeout: float = 120) -> str:
        result = self.request("tools/call", {"name": tool, "arguments": arguments}, timeout=timeout)
        if isinstance(result, dict) and result.get("isError"):
            self._log(f"{tool} вернул isError")
        return _flatten(result)

    def close(self) -> None:
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.proc.kill()
            except OSError:
                pass


def _flatten(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        chunks.append(str(item.get("text", "")))
                    else:
                        chunks.append(json.dumps(item, ensure_ascii=False))
                else:
                    chunks.append(str(item))
            text = "\n".join(chunks)
            if result.get("structuredContent") and not text:
                text = json.dumps(result["structuredContent"], ensure_ascii=False)
            return text
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, list):
        return "\n".join(_flatten(item) for item in result)
    return str(result)


class McpHub:
    """Держит все серверы из конфига и регистрирует их инструменты в tools.TOOLS."""

    def __init__(self, cfg: dict[str, Any], log_dir: Path) -> None:
        self.specs = (cfg or {}).get("servers") or {}
        self.log_dir = log_dir
        self.servers: dict[str, McpServer] = {}
        self.registered: list[str] = []

    def connect(self) -> list[dict[str, str]]:
        status = []
        for name, spec in self.specs.items():
            if not isinstance(spec, dict) or spec.get("enabled") is False:
                continue
            server = McpServer(name, spec, self.log_dir)
            try:
                server.start()
            except Exception as exc:  # noqa: BLE001
                server.error = str(exc)
                status.append({"name": name, "ok": False, "error": str(exc)})
                continue
            self.servers[name] = server
            status.append({"name": name, "ok": True, "tools": len(server.tools)})
        return status

    def register(self, tools_module: Any) -> list[str]:
        for name, server in self.servers.items():
            prefix = server.spec.get("prefix") or "mcp"
            risk = server.spec.get("class") or "exec"
            for tool in server.tools:
                tool_name = str(tool.get("name") or "").strip()
                if not tool_name:
                    continue
                exposed = f"{prefix}__{name}__{tool_name}".replace("-", "_")
                schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
                description = str(tool.get("description") or f"{name}: {tool_name}")[:600]

                def runner(ctx: Any, _server: McpServer = server, _tool: str = tool_name,
                           **kwargs: Any) -> str:
                    return _server.call(_tool, kwargs)

                tools_module.register(exposed, risk, description, schema, runner)
                self.registered.append(exposed)
        return self.registered

    def close(self) -> None:
        for server in self.servers.values():
            server.close()
        self.servers.clear()

    def summary(self) -> dict[str, Any]:
        return {
            "servers": [
                {"name": name, "ok": not s.error, "error": s.error, "tools": len(s.tools),
                 "info": s.info.get("serverInfo", {})}
                for name, s in self.servers.items()
            ],
            "registered": self.registered,
        }
