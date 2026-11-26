"""HTTP-демон Nexus: UI + JSON API + SSE-поток событий сессии."""

from __future__ import annotations

import hmac
import json
import mimetypes
import queue
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import config, training, tools, update
from .agent import Runner, SessionBus
from .browser import BrowserHub
from .hooks import Hooks
from .mcp import McpHub
from .store import Store
from .version import VERSION

UI_DIR = config.UI_DIR
MAX_BODY = 24 * 1024 * 1024
COOKIE = "nx_token"


def _token() -> str:
    """Токен демона: файл в data/, создаётся один раз."""
    path = config.DATA / "token"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


TOKEN = _token()


class App:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.store = Store()
        self.bus = SessionBus()
        self.hub = BrowserHub(self.cfg.get("browser", {}))
        self.hooks = Hooks(Path(self.cfg.get("hooks_file") or (config.DATA / "hooks.json")),
                           Path(self.cfg.get("workspace") or config.WORKSPACE))
        self.mcp = McpHub(self.cfg.get("mcp", {}), config.DATA / "logs")
        self.mcp_status = self.mcp.connect()
        self.mcp.register(tools)
        self.runner = Runner(self.store, self.bus, self.hub, self.hooks)
        self._lock = threading.Lock()
        self.update_state: dict[str, Any] = {"ok": False, "code": "ev.updatePending", "vars": {},
                                             "reason": "проверка ещё не шла"}
        threading.Thread(target=self._update_worker, daemon=True, name="nexus-update").start()

    def _update_worker(self) -> None:
        try:
            self.update_state = update.check()
        except Exception as exc:  # noqa: BLE001
            self.update_state = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    def refresh(self, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if patch:
                self.cfg = config.save({**self.cfg, **patch})
            else:
                self.cfg = config.load()
            self.hub.cfg = self.cfg.get("browser", {})
            return self.cfg

    def state(self) -> dict[str, Any]:
        models: list[str] = []
        try:
            models = provider_models(self.cfg)
        except Exception:
            models = []
        return {
            "config": self.cfg,
            "modes": [{"id": k, **v} for k, v in config.MODES.items()],
            "sessions": self.store.list(),
            "models": models,
            "version": VERSION,
            "workspace": self.cfg.get("workspace"),
            "training": training.stats(),
            "mcp": {**self.mcp.summary(), "status": self.mcp_status},
            "hooks": self.hooks.summary(),
            "hooks_error": getattr(self.hooks, "load_error", ""),
            "tools": [{"name": name, "class": tool.get("class")} for name, tool in tools.TOOLS.items()],
            "update": self.update_state,
        }


def provider_models(cfg: dict[str, Any]) -> list[str]:
    from .providers import list_models

    return list_models(cfg)


APP = App()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"Nexus/{VERSION}"

    def log_message(self, *args: Any) -> None:  # тихий лог
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8",
              extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- доступ
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):
            name, _, rest = host.partition("]")
            name += "]"
            port = rest.lstrip(":")
        else:
            name, _, port = host.partition(":")
        if name not in ("127.0.0.1", "localhost", "[::1]"):
            return False
        return port in ("", str(self.server.server_address[1]))

    def _origin_ok(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            return True
        port = self.server.server_address[1]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}",
                          f"http://[::1]:{port}")

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Nexus-Token") or ""
        if not supplied:
            for part in (self.headers.get("Cookie") or "").split(";"):
                key, _, value = part.strip().partition("=")
                if key == COOKIE:
                    supplied = value
                    break
        return bool(supplied) and hmac.compare_digest(supplied, TOKEN)

    def _deny(self) -> None:
        if self.path.startswith("/api/"):
            self._json({"error": "unauthorized", "code": "ev.unauthorized"}, 401)
        else:
            self._send(403, b"forbidden", "text/plain; charset=utf-8")

    def _json(self, data: Any, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode())

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _static(self, rel: str, cookie: bool = False) -> None:
        base = Path(UI_DIR).resolve()
        path = (base / rel.lstrip("/")).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in (".js", ".css", ".html"):
            ctype += "; charset=utf-8"
        extra = { "Set-Cookie": f"{COOKIE}={TOKEN}; Path=/; HttpOnly; SameSite=Strict" } if cookie else None
        self._send(200, path.read_bytes(), ctype, extra)

    # ---------------------------------------------------------------- GET
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]

        if not self._host_ok():
            return self._deny()
        if path == "/api/health":
            return self._json({"ok": True, "version": VERSION})
        if path.startswith("/api/") and not self._authorized():
            return self._deny()

        if path in ("/", "/index.html"):
            if not self._origin_ok():
                return self._deny()
            return self._static("index.html", cookie=True)
        if path in ("/app.js", "/i18n.js", "/style.css", "/favicon.svg"):
            return self._static(path)
        if path == "/api/state":
            return self._json(APP.state())
        if path == "/api/training":
            return self._json(training.stats())
        if path == "/api/training/status":
            return self._json(training.status())
        if path == "/api/models":
            try:
                return self._json({"models": provider_models(APP.cfg)})
            except Exception as exc:  # noqa: BLE001
                return self._json({"models": [], "error": str(exc)})
        if path == "/api/sessions":
            return self._json({"sessions": APP.store.list()})

        if len(parts) == 3 and parts[:2] == ["api", "sessions"]:
            session = APP.store.get(parts[2])
            if session is None:
                return self._json({"error": "нет сессии", "code": "ev.noSession", "vars": {}}, 404)
            session["running"] = APP.runner.is_running(parts[2])
            return self._json(session)

        if len(parts) == 4 and parts[:2] == ["api", "sessions"] and parts[3] == "events":
            return self._sse(parts[2])

        if len(parts) == 3 and parts[0] == "api" and parts[1] == "shots":
            base = Path(config.SHOTS).resolve()
            shot = (base / parts[2]).resolve()
            if not shot.is_relative_to(base):
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
            if shot.is_file():
                return self._send(200, shot.read_bytes(), "image/png")
            return self._send(404, b"no shot", "text/plain")

        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ---------------------------------------------------------------- POST
    def _post_allowed(self) -> int:
        if not self._host_ok() or not self._authorized() or not self._origin_ok():
            return 401
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return 0 if ctype == "application/json" else 415

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]

        rejected = self._post_allowed()
        if rejected:
            if rejected == 415:
                return self._send(415, b"json required", "text/plain; charset=utf-8")
            return self._deny()

        if path == "/api/sessions":
            body = self._body()
            session = APP.store.create(str(body.get("title") or ""))
            return self._json(session)

        if path == "/api/training/add":
            body = self._body()
            category = str(body.get("category", ""))
            name = str(body.get("name", "материал"))
            text = str(body.get("content", ""))
            fmt = str(body.get("format", "text"))
            try:
                if fmt == "jsonl":
                    result = training.add_jsonl(category, name, text)
                else:
                    result = {"written": training.add_text(category, name, text)}
            except ValueError as exc:
                return self._json({"error": str(exc), "code": "ev.addFailed",
                                   "vars": {"e": str(exc)}}, 400)
            return self._json({**result, "stats": training.stats()})

        if path == "/api/training/seed":
            script = config.ROOT / "packaging" / "seed_training.py"
            if not script.exists():
                return self._json({"error": "нет packaging/seed_training.py",
                                   "code": "ev.noSeedScript", "vars": {}}, 404)
            done = subprocess.run([sys.executable, str(script)], cwd=str(config.ROOT),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=600)
            return self._json({"ok": done.returncode == 0,
                               "output": (done.stdout or done.stderr or "")[-1500:],
                               "stats": training.stats()})

        if path == "/api/training/compose":
            body = self._body()
            counts = training.compose(body.get("categories") or [])
            return self._json(counts)

        if path == "/api/training/start":
            result = training.start(self._body())
            return self._json(result, 409 if result.get("error") else 200)

        if path == "/api/training/stop":
            return self._json(training.stop())

        if path == "/api/update":
            result = update.apply()
            APP.update_state = update.check(force=True)
            return self._json({**result, "state": APP.update_state})

        if path == "/api/config":
            body = self._body()
            if "mode" in body and not config.valid_mode(body.get("mode")):
                return self._json({"error": "неизвестный режим", "code": "ev.badMode",
                                   "vars": {}}, 400)
            return self._json(APP.refresh(body))

        if path == "/api/approve":
            body = self._body()
            ok = APP.bus.decide(str(body.get("call_id", "")), str(body.get("decision", "deny")))
            return self._json({"ok": ok})

        if len(parts) == 4 and parts[:2] == ["api", "sessions"]:
            session_id, action = parts[2], parts[3]
            if action == "message":
                body = self._body()
                if body.get("mode"):
                    if not config.valid_mode(body["mode"]):
                        return self._json({"error": "неизвестный режим", "code": "ev.badMode",
                                           "vars": {}}, 400)
                    APP.refresh({"mode": body["mode"]})
                started = APP.runner.start_turn(session_id, str(body.get("text", "")), APP.cfg)
                return self._json({"started": started},
                                  200 if started else 409)
            if action == "stop":
                APP.bus.stop(session_id)
                return self._json({"ok": True})

        # удаление сессии — только DELETE, POST остаётся для сообщений/остановки
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_DELETE(self) -> None:
        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]
        if not self._host_ok() or not self._authorized() or not self._origin_ok():
            return self._deny()
        if len(parts) == 3 and parts[:2] == ["api", "sessions"]:
            return self._json({"deleted": APP.store.delete(parts[2])})
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ---------------------------------------------------------------- SSE
    def _sse(self, session_id: str) -> None:
        q = APP.bus.subscribe(session_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b": nexus stream\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            APP.bus.unsubscribe(session_id, q)


def serve(port: int = 8848, host: str = "127.0.0.1") -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"Nexus-AI-HARNESS: http://{host}:{port}/  (модель: {APP.cfg.get('model') or '—'}, "
          f"режим: {APP.cfg.get('mode')})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено")
    finally:
        server.server_close()
