"""Инструменты агента: файлы, терминал, браузер, рабочий стол.

Каждый инструмент: JSON-схема для модели + исполнитель + класс риска.
Классы: read | write | exec | browser | gui.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import config
from .config import SHOTS, DANGEROUS

MAX_OUTPUT = 12000
MAX_READ_BYTES = 4 * 1024 * 1024
MAX_LIMIT = 2000


def _outside_allowed() -> bool:
    return os.environ.get("NEXUS_ALLOW_OUTSIDE", "") == "1"


def _blocked(target: Path) -> str:
    """Файлы, которые инструменты не должны менять: политика и автостарт."""
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    protected = {config.DATA / "hooks.json", config.DATA / "config.local.json",
                 config.DATA / "config.json", config.DATA / "token"}
    if resolved in {p.resolve() for p in protected}:
        return "этот файл защищён: настройки и хуки меняются только вручную"
    appdata = os.environ.get("APPDATA")
    if appdata:
        startup = (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" /
                   "Programs" / "Startup")
        if resolved.is_relative_to(startup):
            return "автозагрузка защищена: сюда пишет только пользователь"
    return ""


class Ctx:
    """Контекст выполнения: рабочая папка, браузер, снимки."""

    def __init__(self, workspace: Path, hub: Any, session: dict[str, Any]) -> None:
        self.workspace = workspace
        self.hub = hub
        self.session = session

    def resolve(self, path: str | None) -> Path:
        raw = Path(path or ".")
        target = raw if raw.is_absolute() else self.workspace / raw
        target = target.expanduser().resolve()
        root = self.workspace.resolve()
        if not _outside_allowed() and not target.is_relative_to(root):
            raise PermissionError(
                f"путь вне рабочей папки: {target}. Рабочая папка — {root}; "
                "для доступа вне её задай NEXUS_ALLOW_OUTSIDE=1")
        return target


def _read(ctx: Ctx, path: str, offset: int = 1, limit: int = 400) -> str:
    target = ctx.resolve(path)
    if not target.exists():
        return f"нет файла: {target}"
    if target.is_dir():
        return _list(ctx, path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        return f"не прочитать {target}: {exc}"
    if size > MAX_READ_BYTES:
        return (f"файл {target} слишком большой ({size} байт). "
                "Читай через shell (findstr/Select-String) или укажи точный диапазон.")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(int(offset) - 1, 0)
    limit = max(1, min(int(limit), MAX_LIMIT))
    chunk = lines[start:start + limit]
    head = f"{target} · строки {start + 1}-{start + len(chunk)} из {len(lines)}"
    return head + "\n" + "\n".join(f"{start + i + 1:>5}  {line}" for i, line in enumerate(chunk))


def _write(ctx: Ctx, path: str, content: str) -> str:
    target = ctx.resolve(path)
    blocked = _blocked(target)
    if blocked:
        return blocked
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"записано {len(content)} символов → {target}"


def _edit(ctx: Ctx, path: str, old: str, new: str) -> str:
    target = ctx.resolve(path)
    if not target.exists():
        return f"нет файла: {target}"
    blocked = _blocked(target)
    if blocked:
        return blocked
    text = target.read_text(encoding="utf-8", errors="replace")
    nl = "\r\n" if "\r\n" in text else "\n"
    hay = text.replace("\r\n", "\n").replace("\r", "\n")
    needle = old.replace("\r\n", "\n").replace("\r", "\n")
    if not needle:
        return "пустой фрагмент для замены"
    count = hay.count(needle)
    if count == 0:
        return "фрагмент не найден — прочитай файл и повтори с точным текстом"
    if count > 1:
        return (f"фрагмент встречается {count} раз — уточни old, "
                "добавив соседние строки, чтобы правка не попала не туда")
    updated = hay.replace(needle, new.replace("\r\n", "\n").replace("\r", "\n"), 1)
    if nl == "\r\n":
        updated = updated.replace("\n", "\r\n")
    target.write_bytes(updated.encode("utf-8"))
    return f"заменено в {target}"


def _list(ctx: Ctx, path: str = ".") -> str:
    target = ctx.resolve(path)
    if not target.exists():
        return f"нет пути: {target}"
    if target.is_file():
        return f"{target} · {target.stat().st_size} байт"
    rows = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:200]:
        mark = "/" if item.is_dir() else ""
        size = "" if item.is_dir() else f"  {item.stat().st_size:>9} б"
        rows.append(f"{item.name}{mark}{size}")
    return f"{target} ({len(rows)}):\n" + "\n".join(rows)


def _glob(ctx: Ctx, pattern: str, path: str = ".") -> str:
    base = ctx.resolve(path)
    # маска не должна выходить за пределы выбранной папки через ..
    if any(part == ".." for part in re.split(r"[\\/]", pattern)):
        raise PermissionError("маска не может содержать ..")
    try:
        hits = sorted(str(p.relative_to(base)) for p in base.glob(pattern))[:200]
    except (NotImplementedError, ValueError) as exc:
        raise ValueError(f"некорректная маска: {pattern}") from exc
    return "\n".join(hits) if hits else f"по маске {pattern} ничего не найдено в {base}"


_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "shots", "dist", "build"}


def _grep(ctx: Ctx, pattern: str, path: str = ".", glob: str = "*") -> str:
    base = ctx.resolve(path)
    rx = re.compile(pattern, re.IGNORECASE)
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            file = Path(root) / name
            if not file.match(glob):
                continue
            try:
                if not file.is_file() or file.stat().st_size > 2_000_000:
                    continue
                for num, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{file.relative_to(base)}:{num}: {line.strip()[:160]}")
                        if len(out) >= 120:
                            return "\n".join(out)
            except OSError:
                continue
    return "\n".join(out) if out else f"совпадений нет: {pattern}"


def _shell(ctx: Ctx, command: str, timeout: int = 120, cwd: str | None = None) -> str:
    workdir = str(ctx.resolve(cwd) if cwd else ctx.workspace)
    shell_exe = os.environ.get("COMSPEC", "cmd.exe")
    # chcp 65001: чтобы русский вывод консоли не превращался в кашу
    proc = subprocess.run(
        f"chcp 65001>nul & {command}",
        shell=True, executable=shell_exe,
        cwd=workdir, capture_output=True, timeout=timeout,
    )
    out = _decode(proc.stdout).strip()
    err = _decode(proc.stderr).strip()
    body = out if out else ""
    if err:
        body += ("\n[stderr]\n" if body else "[stderr]\n") + err
    body = body[:MAX_OUTPUT] or "(пустой вывод)"
    return f"exit={proc.returncode} cwd={workdir}\n{body}"


def _decode(raw: bytes) -> str:
    for codec in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _todo_write(ctx: Ctx, items: list[dict[str, Any]]) -> str:
    clean = []
    for item in items[:20]:
        clean.append({"text": str(item.get("text", ""))[:200],
                      "status": str(item.get("status", "pending"))})
    ctx.session["todos"] = clean
    return "план обновлён: " + ", ".join(f"{i['status']}:{i['text'][:40]}" for i in clean)


# ------------------------------------------------------------------ рабочий стол
def _screen(ctx: Ctx) -> str:
    from . import gui  # noqa: PLC0415

    path = SHOTS / f"screen-{int(time.time())}.png"
    info = gui.screenshot(path)
    mono = gui.screen_info()
    return (f"снимок экрана: {info['path']} ({info['width']}x{info['height']}), "
            f"виртуальный стол {mono['width']}x{mono['height']} в ({mono['x']},{mono['y']}). "
            "Клик по пикселям — gui_click.")

def _gui_click(ctx: Ctx, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    from . import gui  # noqa: PLC0415

    return json.dumps(gui.click(x, y, button, clicks), ensure_ascii=False)


def _gui_move(ctx: Ctx, x: int, y: int) -> str:
    from . import gui  # noqa: PLC0415

    gui.move(x, y)
    return f"курсор в {x},{y}"


def _gui_drag(ctx: Ctx, x1: int, y1: int, x2: int, y2: int) -> str:
    from . import gui  # noqa: PLC0415

    return json.dumps(gui.drag(x1, y1, x2, y2), ensure_ascii=False)


def _gui_type(ctx: Ctx, text: str) -> str:
    from . import gui  # noqa: PLC0415

    return json.dumps(gui.type_text(text), ensure_ascii=False)


def _gui_press(ctx: Ctx, combo: str) -> str:
    from . import gui  # noqa: PLC0415

    return json.dumps(gui.press(combo), ensure_ascii=False)


def _gui_scroll(ctx: Ctx, amount: int, x: int | None = None, y: int | None = None) -> str:
    from . import gui  # noqa: PLC0415

    return json.dumps(gui.scroll(amount, x, y), ensure_ascii=False)


def _gui_windows(ctx: Ctx) -> str:
    from . import gui  # noqa: PLC0415

    rows = [f"{w['title'][:70]}  {w['rect']}" for w in gui.windows()][:25]
    return "\n".join(rows) or "окон не найдено"


def _gui_focus(ctx: Ctx, title: str) -> str:
    from . import gui  # noqa: PLC0415

    return json.dumps(gui.focus(title), ensure_ascii=False)


# ------------------------------------------------------------------ браузер
def _browser_open(ctx: Ctx, url: str) -> str:
    info = ctx.hub.goto(url)
    return f"открыто: {info['url']} · {info['title']}"


def _browser_snapshot(ctx: Ctx, text_limit: int = 2000) -> str:
    data = ctx.hub.snapshot(text_limit=text_limit)
    lines = [f"URL: {data['url']}", f"TITLE: {data['title']}"]
    if data.get("headings"):
        lines.append("ЗАГОЛОВКИ: " + " | ".join(data["headings"][:8]))
    lines.append("ЭЛЕМЕНТЫ (индекс · тег · подпись · [x,y,w,h]):")
    for el in (data.get("elements") or [])[:100]:
        extra = f" name={el['name']}" if el.get("name") else ""
        href = f" href={el['href']}" if el.get("href") else ""
        lines.append(f"[{el['i']}] {el['tag']}{'[' + el['type'] + ']' if el.get('type') else ''} "
                     f"«{el['text'][:70]}»{extra}{href} {el['box']}")
    lines.append("ТЕКСТ:\n" + (data.get("text") or "")[:text_limit])
    return "\n".join(lines)[:MAX_OUTPUT]


def _browser_click(ctx: Ctx, index: int | None = None, selector: str | None = None) -> str:
    info = ctx.hub.click(index=index, selector=selector)
    return f"клик по {info['clicked']} → {info['url']}"


def _browser_type(ctx: Ctx, text: str, index: int | None = None,
                  selector: str | None = None, press_enter: bool = False) -> str:
    info = ctx.hub.type_text(text, index=index, selector=selector, press_enter=press_enter)
    return f"введено «{info['typed']}» → {info['url']}"


def _browser_press(ctx: Ctx, combo: str) -> str:
    return json.dumps(ctx.hub.press(combo), ensure_ascii=False)


def _browser_eval(ctx: Ctx, expression: str) -> str:
    value = ctx.hub.evaluate(expression)
    return json.dumps(value, ensure_ascii=False)[:MAX_OUTPUT]


def _browser_close(ctx: Ctx) -> str:
    info = ctx.hub.close()
    return "браузер агента закрыт" if info.get("closed") else "браузер уже был закрыт"


def _browser_shot(ctx: Ctx) -> str:
    path = SHOTS / f"page-{int(time.time())}.png"
    info = ctx.hub.screenshot(path)
    return f"снимок страницы: {info['path']} · viewport {info['viewport']}"


# ------------------------------------------------------------------ реестр
def _tool(name: str, cls: str, schema: dict[str, Any], fn: Callable[..., str],
          risky: bool = False) -> dict[str, Any]:
    return {"name": name, "class": cls, "risky": risky,
            "schema": {"type": "function", "function": {"name": name, **schema}}, "fn": fn}


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"description": "", "parameters": {"type": "object", "properties": props, "required": required}}


TOOLS: dict[str, dict[str, Any]] = {}


def register(name: str, cls: str, description: str, parameters: dict[str, Any],
             fn: Callable[..., str], risky: bool = False) -> None:
    """Регистрация внешнего инструмента (MCP и прочие плагины)."""
    TOOLS[name] = _tool(name, cls, {"description": description, "parameters": parameters}, fn, risky)


def _register() -> None:
    add = TOOLS.__setitem__

    add("fs_read", _tool("fs_read", "read", _obj({
        "path": {"type": "string", "description": "путь к файлу"},
        "offset": {"type": "integer", "description": "с какой строки (1..)"},
        "limit": {"type": "integer", "description": "сколько строк"},
    }, ["path"]), _read))

    add("fs_write", _tool("fs_write", "write", _obj({
        "path": {"type": "string"},
        "content": {"type": "string"},
    }, ["path", "content"]), _write))

    add("fs_edit", _tool("fs_edit", "write", _obj({
        "path": {"type": "string"},
        "old": {"type": "string", "description": "точный фрагмент из файла"},
        "new": {"type": "string"},
    }, ["path", "old", "new"]), _edit))

    add("fs_list", _tool("fs_list", "read", _obj({
        "path": {"type": "string"},
    }, []), _list))

    add("fs_glob", _tool("fs_glob", "read", _obj({
        "pattern": {"type": "string", "description": "например **/*.py"},
        "path": {"type": "string"},
    }, ["pattern"]), _glob))

    add("fs_grep", _tool("fs_grep", "read", _obj({
        "pattern": {"type": "string", "description": "регулярное выражение"},
        "path": {"type": "string"},
        "glob": {"type": "string", "description": "маска файлов, по умолчанию *"},
    }, ["pattern"]), _grep))

    add("shell", _tool("shell", "exec", _obj({
        "command": {"type": "string", "description": "команда cmd.exe"},
        "cwd": {"type": "string"},
        "timeout": {"type": "integer"},
    }, ["command"]), _shell, risky=True))

    add("todo_write", _tool("todo_write", "read", _obj({
        "items": {"type": "array", "description": "список {text,status}",
                  "items": {"type": "object", "properties": {
                      "text": {"type": "string"},
                      "status": {"type": "string", "enum": ["pending", "active", "done", "blocked"]}}}},
    }, ["items"]), _todo_write))

    add("screen_shot", _tool("screen_shot", "gui", _obj({}, []), _screen))
    add("gui_click", _tool("gui_click", "gui", _obj({
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "button": {"type": "string", "enum": ["left", "right", "middle"]},
        "clicks": {"type": "integer"},
    }, ["x", "y"]), _gui_click))
    add("gui_move", _tool("gui_move", "gui", _obj({
        "x": {"type": "integer"}, "y": {"type": "integer"},
    }, ["x", "y"]), _gui_move))
    add("gui_drag", _tool("gui_drag", "gui", _obj({
        "x1": {"type": "integer"}, "y1": {"type": "integer"},
        "x2": {"type": "integer"}, "y2": {"type": "integer"},
    }, ["x1", "y1", "x2", "y2"]), _gui_drag))
    add("gui_type", _tool("gui_type", "gui", _obj({
        "text": {"type": "string"},
    }, ["text"]), _gui_type))
    add("gui_press", _tool("gui_press", "gui", _obj({
        "combo": {"type": "string", "description": "например ctrl+t, enter, alt+tab"},
    }, ["combo"]), _gui_press))
    add("gui_scroll", _tool("gui_scroll", "gui", _obj({
        "amount": {"type": "integer", "description": "＋ вверх, − вниз (120 = один щелчок)"},
        "x": {"type": "integer"}, "y": {"type": "integer"},
    }, ["amount"]), _gui_scroll))
    add("gui_windows", _tool("gui_windows", "gui", _obj({}, []), _gui_windows))
    add("gui_focus", _tool("gui_focus", "gui", _obj({
        "title": {"type": "string", "description": "часть заголовка окна"},
    }, ["title"]), _gui_focus))

    add("browser_open", _tool("browser_open", "browser", _obj({
        "url": {"type": "string"},
    }, ["url"]), _browser_open))
    add("browser_snapshot", _tool("browser_snapshot", "browser", _obj({
        "text_limit": {"type": "integer"},
    }, []), _browser_snapshot))
    add("browser_click", _tool("browser_click", "browser", _obj({
        "index": {"type": "integer", "description": "индекс из browser_snapshot"},
        "selector": {"type": "string", "description": "CSS-селектор, если индекса нет"},
    }, []), _browser_click))
    add("browser_type", _tool("browser_type", "browser", _obj({
        "text": {"type": "string"},
        "index": {"type": "integer"},
        "selector": {"type": "string"},
        "press_enter": {"type": "boolean"},
    }, ["text"]), _browser_type))
    add("browser_press", _tool("browser_press", "browser", _obj({
        "combo": {"type": "string"},
    }, ["combo"]), _browser_press))
    add("browser_eval", _tool("browser_eval", "browser", _obj({
        "expression": {"type": "string", "description": "JS-выражение в странице"},
    }, ["expression"]), _browser_eval))
    add("browser_screenshot", _tool("browser_screenshot", "browser", _obj({}, []), _browser_shot))
    add("browser_close", _tool("browser_close", "browser", _obj({}, []), _browser_close))


_register()


def schemas() -> list[dict[str, Any]]:
    return [tool["schema"] for tool in TOOLS.values()]


def is_dangerous(command: str) -> bool:
    lowered = command.lower()
    return any(re.search(pattern, lowered) for pattern in DANGEROUS)


def execute(ctx: Ctx, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    tool = TOOLS.get(name)
    if tool is None:
        return f"нет такого инструмента: {name}", False
    try:
        result = tool["fn"](ctx, **args)
        return str(result), True
    except TypeError as exc:
        return f"неверные аргументы {name}: {exc}", False
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}", False
