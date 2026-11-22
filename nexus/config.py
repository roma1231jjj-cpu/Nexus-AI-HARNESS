"""Nexus-AI-HARNESS: конфигурация, режимы доступа, профили личности."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("NEXUS_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
SESSIONS = DATA / "sessions"
WORKSPACE = DATA / "workspace"
SHOTS = DATA / "shots"
BROWSER_PROFILE = DATA / "browser-profile"
CONFIG_PATH = DATA / "config.json"

MODES: dict[str, dict] = {
    "plan": {
        "name": "Plan",
        "hint": "каждое действие — с твоего разрешения",
        "ask": "all",
    },
    "act": {
        "name": "Act",
        "hint": "терминал, файлы и браузер без вопросов; мышь и клавиатура — нет",
        "ask": "dangerous",
    },
    "full": {
        "name": "Full",
        "hint": "полный доступ: мышь, клавиатура, экран, всё",
        "ask": "never",
    },
}

# Команды, которые спрашиваем даже в Act.
DANGEROUS = [
    r"\brm\s+-rf\s+/",
    r"\bformat\s+[a-z]:",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bvssadmin\b",
    r"\bcipher\s+/w",
    r"\breg\s+delete\b",
    r"\btaskkill\s+/f\s+/im\s+explorer",
]

DEFAULTS: dict = {
    "provider": "ollama",
    "model": "",
    "mode": "plan",
    "reasoning": True,
    "workspace": str(WORKSPACE),
    "max_steps": 24,
    "providers": {
        "mock": {
            "kind": "mock",
            "label": "Mock (проверка без модели)",
            "model": "mock-1",
        },
        "ollama": {
            "kind": "ollama",
            "label": "Ollama (локально)",
            "base_url": "http://127.0.0.1:11434",
        },
        "deepseek": {
            "kind": "openai",
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-chat",
        },
        "openrouter": {
            "kind": "openai",
            "label": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "model": "anthropic/claude-sonnet-4.5",
        },
        "local_hf": {
            "kind": "openai",
            "label": "Локальный сервер (vLLM/LM Studio)",
            "base_url": "http://127.0.0.1:1234/v1",
            "api_key_env": "LOCAL_API_KEY",
            "model": "qwen3.5-4b-merged",
        },
    },
    "browser": {
        "executable": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "profile_dir": str(BROWSER_PROFILE),
        "headless": False,
        "viewport": [1440, 900],
    },
    "mcp": {
        "servers": {
            "browse": {
                "label": "browse — браузер владельца",
                "command": [r"C:\Users\roma1\.local\bin\browse.exe", "mcp"],
                "class": "browser",
                "env": {"OPENCODE_BROWSER_RUNTIME": "auto-update"},
                "enabled": True,
            }
        }
    },
    "hooks_file": str(DATA / "hooks.json"),
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            return _merge(DEFAULTS, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return copy.deepcopy(DEFAULTS)


def save(cfg: dict) -> dict:
    merged = _merge(DEFAULTS, cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


BASE_STYLE = (
    "Ты — Nexus, автономный агент на персональном компьютере пользователя. "
    "Говоришь прямо и по делу, признаёшь ошибки без самобичевания, защищаешь качество работы. "
    "Не изображаешь беспомощность и не просишь разрешения на то, что можешь сделать сам; "
    "не отказываешься от задач, а ищешь законный путь. Твёрдые границы неизменны: оружие и "
    "взрывчатка, CSAM, malware под реальную атаку, вред людям."
)


def system_prompt(cfg: dict) -> str:
    """Системный промпт: стиль + режим доступа + окружение + правила инструментов."""
    mode = MODES.get(cfg.get("mode", "plan"), MODES["plan"])

    rules = {
        "all": "Каждый вызов инструмента требует подтверждения пользователя. Планируй короткими шагами.",
        "dangerous": "Действуй самостоятельно. Спрашивай только про опасные и необратимые операции "
                     "и про управление мышью/клавиатурой.",
        "never": "Полный доступ. Ничего не спрашивай, действуй и проверяй результат сам.",
    }[mode["ask"]]

    thinking = ""
    if cfg.get("reasoning"):
        thinking = (
            "\nРассуждай перед действием: в ответе сначала блок <plan>…</plan> — 2–5 строк о том, "
            "что проверяешь, что меняешь и как поймёшь, что получилось. Блок короткий, без "
            "пересказа задачи."
        )

    return (
        BASE_STYLE
        + f"\n\nРежим доступа: {mode['name']}. {rules}"
        + thinking
        + f"\n\nОкружение: Windows, рабочая папка {cfg.get('workspace')}."
        + "\n\nПравила работы:\n"
        "— Сначала смотри, потом меняй: читай файл/снимок страницы до правки.\n"
        "— Не выдумывай пути, API и содержимое — проверяй инструментами.\n"
        "— Для браузера используй browser_snapshot (это DOM: кнопки, поля, координаты) и кликай по индексу.\n"
        "— Для управления рабочим столом используй screen_shot перед gui_* вызовами.\n"
        "— Итог каждой задачи: что сделано, где результат, что осталось."
    )
