"""Провайдеры моделей: Ollama, любой OpenAI-совместимый шлюз, mock для офлайна.

Единый интерфейс: stream(...) выдаёт события:
    {"type": "text", "text": "..."}                  — кусок ответа
    {"type": "tool_call", "call": {id, name, args}}  — модель просит инструмент
    {"type": "done"}                                  — конец
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Iterator


class ProviderError(RuntimeError):
    pass


def _post_stream(url: str, payload: dict[str, Any], headers: dict[str, str],
                 timeout: int = 300):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:800]
        raise ProviderError(f"{exc.code} {exc.reason}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"нет связи с {url}: {exc.reason}") from exc


# ------------------------------------------------------------------ список моделей
def list_models(cfg: dict[str, Any], provider_id: str | None = None) -> list[str]:
    providers = cfg.get("providers", {})
    names: list[str] = []
    for pid, conf in providers.items():
        if provider_id and pid != provider_id:
            continue
        try:
            if conf.get("kind") == "ollama":
                names += _ollama_models(conf)
            elif conf.get("kind") == "openai":
                names += _openai_models(conf)
        except Exception:
            continue
    return sorted(set(names))


def _ollama_models(conf: dict[str, Any]) -> list[str]:
    url = conf.get("base_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=4) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m["name"] for m in data.get("models", [])]


def _openai_models(conf: dict[str, Any]) -> list[str]:
    key = os.environ.get(conf.get("api_key_env", ""), "")
    if conf.get("api_key_env") and not key:
        return []
    url = conf.get("base_url", "").rstrip("/") + "/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("id", "") for m in data.get("data", []) if m.get("id")]


# ------------------------------------------------------------------ стриминг
def stream(cfg: dict[str, Any], messages: list[dict[str, Any]],
           tools: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    pid = cfg.get("provider") or "ollama"
    conf = (cfg.get("providers") or {}).get(pid) or {}
    kind = conf.get("kind", "ollama")
    model = cfg.get("model") or conf.get("model") or ""

    if not model:
        raise ProviderError("модель не выбрана")
    if kind == "ollama":
        yield from _stream_ollama(conf, model, messages, tools)
    elif kind == "openai":
        yield from _stream_openai(conf, model, messages, tools)
    elif kind == "mock":
        yield from _stream_mock(messages)
    else:
        raise ProviderError(f"неизвестный тип провайдера: {kind}")


def _stream_ollama(conf: dict[str, Any], model: str, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    url = conf.get("base_url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": m["role"], "content": m.get("content", "")} for m in messages],
        "stream": True,
        "options": {"temperature": 0.4, "num_ctx": 16384},
    }
    if tools:
        payload["tools"] = tools
    calls: list[dict[str, Any]] = []
    with _post_stream(url, payload, {}, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = chunk.get("message") or {}
            if msg.get("content"):
                yield {"type": "text", "text": msg["content"]}
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                item = {
                    "id": call.get("id") or f"call_{int(time.time() * 1000)}_{len(calls)}",
                    "name": fn.get("name", ""),
                    "args": args or {},
                }
                calls.append(item)
                yield {"type": "tool_call", "call": item}
            if chunk.get("done"):
                break
    yield {"type": "done"}


def _stream_openai(conf: dict[str, Any], model: str, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    key = os.environ.get(conf.get("api_key_env", ""), "")
    if conf.get("api_key_env") and not key:
        raise ProviderError(f"не задан {conf['api_key_env']}")
    url = conf.get("base_url", "").rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    partial: dict[int, dict[str, Any]] = {}
    with _post_stream(url, payload, {"Authorization": f"Bearer {key}"}, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield {"type": "text", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = partial.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
    for slot in partial.values():
        if not slot["name"]:
            continue
        try:
            args = json.loads(slot["args"] or "{}")
        except json.JSONDecodeError:
            args = {"raw": slot["args"]}
        yield {"type": "tool_call",
               "call": {"id": slot["id"] or f"call_{int(time.time() * 1000)}",
                        "name": slot["name"], "args": args}}
    yield {"type": "done"}


def _stream_mock(messages: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Офлайн-заглушка: проверка UI и цикла без модели и без ключей."""
    last = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last = msg.get("content", "")
            break
    already = any(m.get("role") == "tool" for m in messages)

    # Самопроверка контура: просим инструмент, чтобы проверить разрешения и карточки
    if "тест-инструмент" in last.lower() and not already:
        yield {"type": "tool_call",
               "call": {"id": f"call_mock_{int(time.time() * 1000)}",
                        "name": "fs_list", "args": {"path": "."}}}
        yield {"type": "done"}
        return
    answer = (
        "Провайдер mock активен — это проверка контура, а не модели.\n\n"
        f"Запрос: {last[:200]}\n\n"
        "Цикл сессии, стриминг и карточки инструментов работают. "
        "Выбери Ollama-модель или OpenAI-совместимый провайдер в шапке, чтобы получить настоящий ответ."
    )
    for word in answer.split(" "):
        yield {"type": "text", "text": word + " "}
        time.sleep(0.01)
    yield {"type": "done"}
