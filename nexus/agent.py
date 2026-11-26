"""Цикл агента: сообщение → модель → инструменты → результат, с политикой доступа."""

from __future__ import annotations

import queue
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import config, protocol, providers, tools
from .browser import BrowserHub
from .store import Store


class SessionBus:
    """События сессии для SSE + ожидание подтверждений."""

    def __init__(self) -> None:
        self._queues: dict[str, list[queue.Queue]] = {}
        self._pending: dict[str, dict[str, threading.Event]] = {}
        self._decisions: dict[str, str] = {}
        self._stops: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def subscribe(self, session_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._queues.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str, q: queue.Queue) -> None:
        with self._lock:
            items = self._queues.get(session_id, [])
            if q in items:
                items.remove(q)

    def emit(self, session_id: str, event: dict[str, Any]) -> None:
        event.setdefault("time", protocol.now())
        with self._lock:
            for q in self._queues.get(session_id, []):
                q.put(event)

    def stop_signal(self, session_id: str) -> threading.Event:
        with self._lock:
            return self._stops.setdefault(session_id, threading.Event())

    def stop(self, session_id: str) -> None:
        self.stop_signal(session_id).set()
        # Не оставляем подтверждение висеть до таймаута: стоп = отказ.
        with self._lock:
            for call_id, flag in (self._pending.get(session_id) or {}).items():
                self._decisions[call_id] = "stopped"
                flag.set()

    def clear_stop(self, session_id: str) -> None:
        self.stop_signal(session_id).clear()

    def ask(self, session_id: str, call_id: str) -> str:
        flag = threading.Event()
        with self._lock:
            self._pending.setdefault(session_id, {})[call_id] = flag
        deadline = time.time() + 900
        while time.time() < deadline:
            if flag.wait(timeout=0.25):
                with self._lock:
                    self._pending.get(session_id, {}).pop(call_id, None)
                    return self._decisions.pop(call_id, "deny")
            if self.stop_signal(session_id).is_set():
                with self._lock:
                    self._pending.get(session_id, {}).pop(call_id, None)
                    self._decisions.pop(call_id, None)
                return "stopped"
        with self._lock:
            self._pending.get(session_id, {}).pop(call_id, None)
        return "timeout"

    def decide(self, call_id: str, decision: str) -> bool:
        with self._lock:
            self._decisions[call_id] = decision
            for flags in self._pending.values():
                if call_id in flags:
                    flags[call_id].set()
                    return True
        return False


_STREAM_END = object()


def _iter_stoppable(events: Any, stop: threading.Event) -> Any:
    """Читает поток модели в фоне, чтобы «стоп» срабатывал во время генерации."""
    channel: queue.Queue = queue.Queue(maxsize=256)

    def pump() -> None:
        try:
            for event in events:
                channel.put(event)
            channel.put(_STREAM_END)
        except BaseException as exc:  # noqa: BLE001
            channel.put(exc)

    threading.Thread(target=pump, daemon=True, name="nexus-stream").start()
    while not stop.is_set():
        try:
            item = channel.get(timeout=0.2)
        except queue.Empty:
            continue
        if item is _STREAM_END:
            return
        if isinstance(item, BaseException):
            raise item
        yield item


class Runner:
    def __init__(self, store: Store, bus: SessionBus, hub: BrowserHub, hooks: Any = None) -> None:
        self.store = store
        self.bus = bus
        self.hub = hub
        self.hooks = hooks
        self._running: dict[str, bool] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- политика
    @staticmethod
    def needs_approval(cfg: dict[str, Any], tool_name: str, args: dict[str, Any]) -> bool:
        mode = cfg.get("mode", "plan")
        if not config.valid_mode(mode):
            # опечатка/подделка в конфиге не должна тихо включать полный доступ
            mode = "plan"
        tool = tools.TOOLS.get(tool_name) or {}
        if mode == "full":
            return False
        if mode == "plan":
            return True
        # act: спрашиваем про мышь/клавиатуру, JS в браузере и опасные команды
        if tool.get("class") == "gui":
            return True
        if tool_name == "browser_eval":
            return True
        if tool_name == "shell" and tools.is_dangerous(str(args.get("command", ""))):
            return True
        return False

    # ---------------------------------------------------------------- запуск
    def start_turn(self, session_id: str, text: str, cfg: dict[str, Any]) -> bool:
        with self._lock:
            if self._running.get(session_id):
                return False
            self._running[session_id] = True
        thread = threading.Thread(target=self._turn_worker, args=(session_id, text, cfg),
                                  name=f"nexus-turn-{session_id[-6:]}", daemon=True)
        thread.start()
        return True

    def is_running(self, session_id: str) -> bool:
        return bool(self._running.get(session_id))

    # ---------------------------------------------------------------- воркер
    def _turn_worker(self, session_id: str, text: str, cfg: dict[str, Any]) -> None:
        try:
            self.bus.clear_stop(session_id)
            session = self.store.get(session_id)
            if session is None:
                return
            self.store.title_from(session, text)

            user_msg = protocol.message("user", [protocol.text_part(text)])
            session["messages"].append(user_msg)
            session["mode"] = cfg.get("mode", session.get("mode"))
            self.store.save(session)
            self.bus.emit(session_id, {"type": "message", "message": user_msg})

            ctx = tools.Ctx(Path(cfg.get("workspace") or config.WORKSPACE), self.hub, session)
            max_steps = int(cfg.get("max_steps", 24))
            if self.hooks:
                self.hooks.fire("session_start", session=session_id)

            for step in range(max_steps):
                if self.bus.stop_signal(session_id).is_set():
                    self.bus.emit(session_id, {"type": "error", "code": "ev.stopped", "vars": {},
                                               "text": "остановлено пользователем"})
                    break

                self.bus.emit(session_id, {"type": "status", "state": "thinking"})
                reply = protocol.message("assistant")
                session["messages"].append(reply)
                buffer: list[str] = []
                calls: list[dict[str, Any]] = []
                stream_error = ""

                try:
                    chat = [{"role": "system", "content": config.system_prompt(cfg)}]
                    chat += protocol.to_chat(session["messages"][:-1])
                    for event in _iter_stoppable(
                        providers.stream(cfg, chat, tools.schemas()),
                        self.bus.stop_signal(session_id),
                    ):
                        if event["type"] == "text":
                            buffer.append(event["text"])
                            reply["parts"] = [protocol.text_part("".join(buffer))]
                            self.bus.emit(session_id, {"type": "delta", "message_id": reply["id"],
                                                       "text": event["text"]})
                        elif event["type"] == "tool_call":
                            call = event["call"]
                            calls.append(call)
                            part = protocol.tool_call_part(call["id"], call["name"], call["args"])
                            reply["parts"] = [protocol.text_part("".join(buffer))] + [
                                protocol.tool_call_part(c["id"], c["name"], c["args"]) for c in calls
                            ]
                            self.bus.emit(session_id, {"type": "tool_call", "message_id": reply["id"],
                                                       "part": part})
                        elif event["type"] == "done":
                            break
                except Exception as exc:  # noqa: BLE001
                    stream_error = f"{type(exc).__name__}: {exc}"

                if buffer:
                    reply["parts"] = [protocol.text_part("".join(buffer))]
                elif not calls:
                    reply["parts"] = []
                self.store.save(session)

                if stream_error and self.hooks:
                    self.hooks.on_error(session_id, stream_error)
                if stream_error:
                    # ошибку сохраняем в сессию, иначе после перезагрузки страницы от неё не остаётся следа
                    self.bus.emit(session_id, {"type": "error", "text": stream_error})
                    if not reply["parts"]:
                        session["messages"].remove(reply)
                    session["messages"].append(
                        protocol.message("assistant", [protocol.error_part(stream_error)]))
                    self.store.save(session)
                    break

                if not calls:
                    break

                for call in calls:
                    if self.bus.stop_signal(session_id).is_set():
                        break
                    name = call["name"]
                    args = call.get("args") or {}

                    if self.needs_approval(cfg, name, args):
                        part = protocol.approval_part(call["id"], name, args)
                        session["messages"].append(protocol.message("tool", [part], {"pending": True}))
                        self.store.save(session)
                        self.bus.emit(session_id, {"type": "approval", "call_id": call["id"],
                                                    "tool": name, "input": args})
                        decision = self.bus.ask(session_id, call["id"])
                        session["messages"].pop()
                        if decision != "allow":
                            output, ok = f"пользователь отклонил ({decision})", False
                            result = protocol.tool_result_part(
                                call["id"], name, output, ok=False, meta={"denied": True},
                                code="ev.denied", vars={"decision": decision})
                            session["messages"].append(protocol.message("tool", [result]))
                            self.store.save(session)
                            self.bus.emit(session_id, {"type": "tool_result", "part": result})
                            continue

                    if self.hooks:
                        allowed, reason = self.hooks.pre_tool(name, args, session_id)
                        if not allowed:
                            blocked = protocol.tool_result_part(
                                call["id"], name, f"заблокировано хуком: {reason}", ok=False,
                                meta={"hook": True}, code="ev.hookBlocked",
                                vars={"reason": reason})
                            session["messages"].append(protocol.message("tool", [blocked]))
                            self.store.save(session)
                            self.bus.emit(session_id, {"type": "tool_result", "part": blocked})
                            continue

                    self.bus.emit(session_id, {"type": "status", "state": "running", "tool": name})
                    started = time.time()
                    output, ok = tools.execute(ctx, name, args)
                    elapsed = int((time.time() - started) * 1000)
                    if self.hooks:
                        self.hooks.post_tool(name, args, output, ok, session_id, elapsed)
                    meta: dict[str, Any] = {"ms": elapsed}
                    shot = re.search(r"([A-Za-z]:\\[^\n]+\.(?:png|jpe?g))", output, re.IGNORECASE)
                    if shot and name in ("screen_shot", "browser_screenshot"):
                        meta["image"] = shot.group(1)
                    result = protocol.tool_result_part(call["id"], name, output, ok=ok,
                                                       meta=meta)
                    session["messages"].append(protocol.message("tool", [result]))
                    self.store.save(session)
                    self.bus.emit(session_id, {"type": "tool_result", "part": result})
                    if session.get("todos"):
                        self.bus.emit(session_id, {"type": "todos", "todos": session["todos"]})

                if self.bus.stop_signal(session_id).is_set():
                    break
            else:
                self.bus.emit(session_id, {"type": "error", "code": "ev.stepLimit",
                                           "vars": {"max_steps": max_steps},
                                           "text": f"лимит шагов ({max_steps}) — задача приостановлена"})

            self.store.save(session)
        except Exception as exc:  # noqa: BLE001
            self.bus.emit(session_id, {"type": "error", "code": "ev.turnFailed",
                                       "vars": {"e": str(exc)},
                                       "text": f"сбой оборота: {exc}"})
        finally:
            if self.hooks:
                self.hooks.fire("agent_end", session=session_id)
            with self._lock:
                self._running[session_id] = False
            self.bus.emit(session_id, {"type": "status", "state": "idle"})
            self.bus.emit(session_id, {"type": "done"})
