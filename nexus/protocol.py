"""Протокол сессии в духе opencode: session → message → parts.

Part — атомарная единица содержимого: текст, рассуждение, вызов инструмента,
результат инструмента, шаг плана, запрос подтверждения.
"""

from __future__ import annotations

import time
import uuid
from typing import Any


def nid(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:20]
    return f"{prefix}{raw}" if prefix else raw


def now() -> float:
    return time.time()


def text_part(text: str, *, synthetic: bool = False) -> dict[str, Any]:
    return {"id": nid("prt_"), "type": "text", "text": text, "synthetic": synthetic, "time": now()}


def reasoning_part(text: str) -> dict[str, Any]:
    return {"id": nid("prt_"), "type": "reasoning", "text": text, "time": now()}


def tool_call_part(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": call_id, "type": "tool_call", "tool": name, "input": args, "time": now()}


def tool_result_part(call_id: str, name: str, output: str, *, ok: bool = True,
                     meta: dict[str, Any] | None = None, code: str = "",
                     vars: dict[str, Any] | None = None) -> dict[str, Any]:
    part = {
        "id": nid("prt_"),
        "type": "tool_result",
        "call_id": call_id,
        "tool": name,
        "output": output,
        "ok": ok,
        "meta": meta or {},
        "time": now(),
    }
    if code:
        part["code"] = code
        part["vars"] = vars or {}
    return part


def approval_part(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": nid("prt_"), "type": "approval", "call_id": call_id, "tool": name,
            "input": args, "time": now()}


def error_part(text: str, *, code: str = "", vars: dict[str, Any] | None = None) -> dict[str, Any]:
    part = {"id": nid("prt_"), "type": "error", "text": text, "time": now()}
    if code:
        part["code"] = code
        part["vars"] = vars or {}
    return part


def message(role: str, parts: list[dict[str, Any]] | None = None,
            meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": nid("msg_"),
        "role": role,
        "parts": parts or [],
        "meta": meta or {},
        "time": now(),
    }


def new_session(title: str = "Новая сессия", *, auto_title: bool = True) -> dict[str, Any]:
    return {
        "id": nid("ses_"),
        "title": title,
        "auto_title": auto_title,
        "created": now(),
        "updated": now(),
        "mode": "plan",
        "provider": "",
        "model": "",
        "personas": [],
        "messages": [],
        "todos": [],
    }


def to_chat(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Свести parts в плоский формат chat-API (OpenAI/Ollama-совместимый)."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        texts = [p["text"] for p in msg.get("parts", []) if p.get("type") == "text" and p.get("text")]
        calls = [p for p in msg.get("parts", []) if p.get("type") == "tool_call"]
        results = [p for p in msg.get("parts", []) if p.get("type") == "tool_result"]

        if role == "user":
            if texts:
                out.append({"role": "user", "content": "\n\n".join(texts)})
            continue

        if role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": "\n\n".join(texts)}
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["tool"], "arguments": _json(c.get("input") or {})},
                    }
                    for c in calls
                ]
            if entry["content"] or calls:
                out.append(entry)
            continue

        if role == "tool":
            for res in results:
                out.append({
                    "role": "tool",
                    "tool_call_id": res.get("call_id", ""),
                    "name": res.get("tool", ""),
                    "content": res.get("output", ""),
                })
    return out


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
