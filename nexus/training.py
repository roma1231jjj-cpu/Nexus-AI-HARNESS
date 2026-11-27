"""Обучение внутри Nexus: разделы материала, приём материалов, сбор датасета, запуск QLoRA.

Хранилище: data/training/<категория>/*.jsonl — записи в формате CONVENTIONS.md
({"messages":[{"role","content"}...],"meta":{...}}). Собранный датасет:
data/training/dataset/{train,val}.jsonl, лог прогона: data/training/run.log.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .config import DATA, ROOT

TRAIN_DIR = DATA / "training"
DATASET_DIR = TRAIN_DIR / "dataset"
RUN_LOG = TRAIN_DIR / "run.log"
RUN_META = TRAIN_DIR / "run.json"

FINETUNE_ROOT = Path(os.environ.get("NEXUS_FINETUNE_ROOT", r"D:\finetune"))
FINETUNE_PY = FINETUNE_ROOT / ".venv" / "Scripts" / "python.exe"
FINETUNE_SCRIPT = FINETUNE_ROOT / "scripts" / "train_qlora.py"

# ---------------------------------------------------------------- разделы материала
# group = раздел в интерфейсе, hint = что за материал сюда кладут
CATEGORIES: list[dict[str, str]] = [
    {"id": "school_math", "name": "Математика", "group": "Школа", "hint": "алгебра, геометрия, задачи с решением по шагам"},
    {"id": "school_phys", "name": "Физика", "group": "Школа", "hint": "задачи, формулы, разбор явлений"},
    {"id": "school_chem", "name": "Химия", "group": "Школа", "hint": "реакции, уравнения, расчёты"},
    {"id": "school_bio", "name": "Биология", "group": "Школа", "hint": "термины, процессы, схемы"},
    {"id": "school_rus", "name": "Русский и литература", "group": "Школа", "hint": "разборы, сочинения, правила"},
    {"id": "school_hist", "name": "История и общество", "group": "Школа", "hint": "даты, причины, эссе"},
    {"id": "school_lang", "name": "Английский", "group": "Школа", "hint": "перевод, грамматика, разговорные ответы"},
    {"id": "music", "name": "Музыка", "group": "Творчество", "hint": "теория, гармония, сольфеджио, DAW, партии"},
    {"id": "artist", "name": "Рисунок и визуал", "group": "Творчество", "hint": "композиция, цвет, арт-дирекшн"},
    {"id": "svg", "name": "SVG и схемы", "group": "Творчество", "hint": "векторная графика, иконки, диаграммы"},
    {"id": "slides", "name": "Презентации", "group": "Работа", "hint": "outline, HTML-слайды, pptx-структура"},
    {"id": "docs", "name": "Документы и резюме", "group": "Работа", "hint": "письма, CV, ТЗ, отчёты"},
    {"id": "code_python", "name": "Python", "group": "Код", "hint": "функции, тесты, рефакторинг, ошибки"},
    {"id": "code_java", "name": "Java", "group": "Код", "hint": "классы, коллекции, Spring-основы"},
    {"id": "code_rust", "name": "Rust", "group": "Код", "hint": "владение, Result, трейты"},
    {"id": "code_web", "name": "JS / HTML / CSS", "group": "Код", "hint": "DOM, интерфейсы, стили"},
    {"id": "code_sql", "name": "SQL и данные", "group": "Код", "hint": "запросы, схемы, миграции"},
    {"id": "tools", "name": "Tool calling", "group": "Агенты", "hint": "вызовы инструментов, JSON-аргументы, API"},
    {"id": "agents", "name": "Агентские петли", "group": "Агенты", "hint": "планирование, шаги, проверка результата"},
    {"id": "structured", "name": "Структурированные ответы", "group": "Агенты", "hint": "строгий JSON, схемы, таблицы"},
    {"id": "phone", "name": "Телефон-ассистент", "group": "Агенты", "hint": "короткие команды, быстрые ответы"},
    {"id": "tone", "name": "Тон и характер", "group": "Характер", "hint": "как говорить: прямо, с достоинством, без воды"},
    {"id": "no_refusal", "name": "Без отказов", "group": "Характер", "hint": "не отказываться, искать законный путь"},
    {"id": "law_constitution", "name": "Конституция", "group": "Право", "hint": "права и свободы, устройство власти, статьи Конституции"},
    {"id": "law_labor", "name": "Трудовое право", "group": "Право", "hint": "приём, увольнение, зарплата, отпуска, споры"},
    {"id": "law_civil", "name": "Договоры и собственность", "group": "Право", "hint": "сделки, договоры, неустойка, вред, наследство"},
    {"id": "law_family", "name": "Семейное право", "group": "Право", "hint": "брак, раздел имущества, алименты, дети"},
    {"id": "law_criminal", "name": "Уголовное и админ", "group": "Право", "hint": "составы, оборона, штрафы, ДТП, протоколы"},
    {"id": "law_courts", "name": "Суд, иски, приставы", "group": "Право", "hint": "иски, претензии, сроки, госпошлина, взыскание"},
    {"id": "law_docs", "name": "Юридические документы", "group": "Право", "hint": "шаблоны: претензия, иск, жалоба, заявление"},
    {"id": "user", "name": "Мои данные", "group": "Личное", "hint": "ваши тексты, переписки, заметки, факты о проектах"},
    {"id": "translation", "name": "Перевод", "group": "Языки", "hint": "ru↔en, стили перевода, термины"},
    {"id": "other", "name": "Другое", "group": "Другое", "hint": "то, что не подошло к разделам выше"},
]
CATEGORY_IDS = {c["id"] for c in CATEGORIES}

MAX_CHARS = 12000


# ---------------------------------------------------------------- служебное
def ensure_dirs() -> None:
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)


def _norm_record(raw: Any, category: str, source: str) -> dict[str, Any] | None:
    """Привести материал к формату CONVENTIONS.md: messages + meta."""
    if not isinstance(raw, dict):
        return None
    messages = raw.get("messages")
    if isinstance(messages, list) and messages:
        clean = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role", "")).strip()
            content = m.get("content")
            if role not in ("system", "user", "assistant") or not isinstance(content, str):
                continue
            if not content.strip():
                continue
            clean.append({"role": role, "content": content.strip()})
        if not clean:
            return None
        return {"messages": clean, "meta": {"category": category, "source": source}}
    # одиночный текст: «карточка материала» — заголовок → содержимое
    text = raw.get("text") or raw.get("content")
    if isinstance(text, str) and text.strip():
        return {
            "messages": [
                {"role": "user", "content": raw.get("title") or f"Материал по теме: {category}"},
                {"role": "assistant", "content": text.strip()[:MAX_CHARS]},
            ],
            "meta": {"category": category, "source": source},
        }
    return None


def _append(category: str, records: list[dict[str, Any]], source: str) -> int:
    ensure_dirs()
    if category not in CATEGORY_IDS:
        raise ValueError(f"неизвестный раздел: {category}")
    folder = TRAIN_DIR / category
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}-{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}.jsonl"
    seen, written = set(), 0
    with path.open("w", encoding="utf-8") as fh:
        for raw in records:
            rec = _norm_record(raw, category, source)
            if rec is None:
                continue
            digest = hashlib.sha1(json.dumps(rec, ensure_ascii=False).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    if written == 0:
        path.unlink(missing_ok=True)
    return written


def add_text(category: str, name: str, text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    return _append(category, [{"title": name or "материал", "text": text}], f"upload:{name or 'paste'}")


def add_jsonl(category: str, name: str, text: str) -> dict[str, int]:
    """Материал в JSONL: каждая строка — объект с messages (или text)."""
    records, bad = [], 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    written = _append(category, records, f"jsonl:{name or 'upload'}") if records else 0
    return {"written": written, "bad_lines": bad}


# ---------------------------------------------------------------- статистика
def stats() -> dict[str, Any]:
    ensure_dirs()
    out = []
    total = 0
    for cat in CATEGORIES:
        folder = TRAIN_DIR / cat["id"]
        records = chars = files = 0
        updated = 0.0
        if folder.is_dir():
            for path in folder.glob("*.jsonl"):
                files += 1
                updated = max(updated, path.stat().st_mtime)
                for line in path.open(encoding="utf-8", errors="ignore"):
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    records += 1
                    chars += sum(len(m.get("content", "")) for m in rec.get("messages", []))
        total += records
        out.append({**cat, "records": records, "chars": chars, "files": files,
                    "updated": updated})
    return {"categories": out, "total_records": total,
            "dataset": _dataset_info(), "run": status()}


def _dataset_info() -> dict[str, Any]:
    info = {}
    for split in ("train", "val"):
        path = DATASET_DIR / f"{split}.jsonl"
        if path.exists():
            info[split] = {"path": str(path), "records": _count_lines(path),
                           "updated": path.stat().st_mtime}
        else:
            info[split] = {"path": str(path), "records": 0, "updated": 0}
    return info


def _count_lines(path: Path) -> int:
    with path.open(encoding="utf-8", errors="ignore") as fh:
        return sum(1 for line in fh if line.strip())


# ---------------------------------------------------------------- сборка датасета
def compose(categories: list[str], val_ratio: float = 0.03) -> dict[str, Any]:
    ensure_dirs()
    picked = [c for c in categories if c in CATEGORY_IDS] or list(CATEGORY_IDS)
    records: list[dict[str, Any]] = []
    per_cat: dict[str, int] = {}
    seen: set[str] = set()
    for cat in picked:
        folder = TRAIN_DIR / cat
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.jsonl")):
            for line in path.open(encoding="utf-8", errors="ignore"):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                digest = hashlib.sha1(json.dumps(rec, ensure_ascii=False).encode()).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                records.append(rec)
                per_cat[cat] = per_cat.get(cat, 0) + 1
    random.Random(42).shuffle(records)
    cut = max(1, int(len(records) * val_ratio)) if len(records) >= 34 else 0
    val, train = records[:cut], records[cut:]
    for split, rows in (("train", train), ("val", val)):
        path = DATASET_DIR / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for rec in rows:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"train": len(train), "val": len(val), "categories": per_cat,
            "train_path": str(DATASET_DIR / "train.jsonl"),
            "val_path": str(DATASET_DIR / "val.jsonl")}


# ---------------------------------------------------------------- запуск обучения
# только настоящие полосы обучения: "... 12/5064 [00:10<01:02,  8.7s/it]"
# (полосы загрузки весов и токенизации имеют it/s и в счёт шагов не идут)
TQDM = re.compile(r"\|\s*(\d+)/(\d+)\s*\[([0-9:]+)<([0-9:]+),\s*[0-9.]+s/it\]")
LOSS = re.compile(r"\{'loss': '([0-9.]+)'")

# run.log растёт на гигабайты: держим разобранный хвост и читаем только
# добавившиеся байты, а не весь файл на каждый запрос /api/training/status.
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, Any] = {"path": "", "offset": 0, "tail": "",
                             "samples": [], "losses": [], "total": 0}


def _progress() -> tuple[int, int, list[tuple[int, float]], list[float]]:
    path = RUN_LOG
    if not path.exists():
        return 0, 0, [], []
    with _PROGRESS_LOCK:
        try:
            size = path.stat().st_size
        except OSError:
            return 0, 0, [], []
        if _PROGRESS["path"] != str(path) or size < _PROGRESS["offset"]:
            _PROGRESS.update({"path": str(path), "offset": 0, "tail": "",
                              "samples": [], "losses": [], "total": 0})
        if size > _PROGRESS["offset"]:
            try:
                with path.open("rb") as fh:
                    fh.seek(_PROGRESS["offset"])
                    raw = fh.read()
                _PROGRESS["offset"] = size
            except OSError:
                return 0, 0, [], []
            text = _PROGRESS["tail"] + raw.decode("utf-8", errors="ignore")
            lines = text.replace("\r", "\n").split("\n")
            _PROGRESS["tail"] = lines.pop() if lines else ""
            for line in lines:
                m = TQDM.search(line)
                if m:
                    steps, total = int(m.group(1)), int(m.group(2))
                    _PROGRESS["total"] = total
                    _PROGRESS["samples"].append((steps, _hms(m.group(3))))
                    _PROGRESS["samples"] = _PROGRESS["samples"][-20:]
                lm = LOSS.search(line)
                if lm:
                    try:
                        _PROGRESS["losses"].append(float(lm.group(1)))
                        _PROGRESS["losses"] = _PROGRESS["losses"][-120:]
                    except ValueError:
                        pass
        samples = list(_PROGRESS["samples"])
        losses = list(_PROGRESS["losses"])
        total = int(_PROGRESS["total"] or 0)
        steps = samples[-1][0] if samples else 0
        return steps, total, samples, losses


def _alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="replace").stdout
    except OSError:
        return False
    # Сравниваем точный PID: подстрока "123" в "1234" больше не считается жизнью.
    for line in out.splitlines():
        fields = [part.strip().strip('"') for part in line.split('","')]
        if len(fields) >= 2 and fields[1] == str(pid):
            return True
    return False


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _num(params: dict[str, Any], key: str, default, lo, hi, cast=int):
    try:
        value = cast(params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def start(params: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    if status().get("running"):
        return {"error": "обучение уже идёт", "code": "ev.trainRunning", "vars": {}}
    if not FINETUNE_SCRIPT.exists() or not FINETUNE_PY.exists():
        return {"error": f"не найден скрипт обучения: {FINETUNE_SCRIPT}",
                "code": "ev.trainNoFinetune", "vars": {"path": str(FINETUNE_SCRIPT)}}
    if "categories" in params and not isinstance(params.get("categories"), list):
        return {"error": "категории должны быть списком", "code": "ev.trainBadCategories", "vars": {}}
    if "categories" in params and not params.get("categories"):
        return {"error": "не выбрано ни одной категории", "code": "ev.trainNoCategories", "vars": {}}
    numeric = {
        "val_ratio": (float, 0.0, 0.5), "seq": (int, 128, 4096),
        "ga": (int, 1, 64), "epochs": (int, 1, 10), "lr": (float, 1e-6, 1e-3),
        "r": (int, 1, 128), "save_steps": (int, 10, 10000),
        "max_steps": (int, -1, 1_000_000),
    }
    for key, (cast, lo, hi) in numeric.items():
        if key not in params or params[key] in (None, ""):
            continue
        try:
            value = cast(params[key])
            if isinstance(params[key], bool) or not lo <= value <= hi:
                raise ValueError
        except (TypeError, ValueError):
            return {"error": f"параметр {key}: ожидается число от {lo} до {hi}",
                    "code": "ev.trainBadParam", "vars": {"field": key}}
    for key in ("run_name", "out", "base_model"):
        if key in params and params[key] is not None and not isinstance(params[key], str):
            return {"error": f"параметр {key} должен быть строкой",
                    "code": "ev.trainBadParam", "vars": {"field": key}}
    categories = params.get("categories") or [c["id"] for c in CATEGORIES]
    unknown = [c for c in categories if c not in CATEGORY_IDS]
    if unknown:
        return {"error": "неизвестные категории: " + ", ".join(map(str, unknown[:5])),
                "code": "ev.trainBadCategories", "vars": {"names": ", ".join(map(str, unknown[:5]))}}
    counts = compose(categories, _num(params, "val_ratio", 0.03, 0.0, 0.5, float))
    if counts["train"] < 8:
        return {"error": f"мало материала: {counts['train']} примеров (нужно минимум 8)",
                "code": "ev.trainTooFew", "vars": {"n": counts["train"]}}

    name = str(params.get("run_name") or f"nexus-{time.strftime('%Y%m%d-%H%M')}").strip()
    if not NAME_RE.match(name) or ".." in name:
        return {"error": "имя запуска: только буквы, цифры, точка, дефис и подчёркивание",
                "code": "ev.trainBadName", "vars": {}}
    out = Path(str(params.get("out") or (FINETUNE_ROOT / "models" / "adapters"))).resolve()
    if not out.is_relative_to(FINETUNE_ROOT.resolve()):
        return {"error": "папка адаптеров должна быть внутри finetune", "code": "ev.trainBadOut", "vars": {}}
    cmd = [
        str(FINETUNE_PY), "-u", str(FINETUNE_SCRIPT),
        "--train", counts["train_path"], "--val", counts["val_path"],
        "--run-name", name,
        "--seq", str(_num(params, "seq", 768, 128, 4096)),
        "--bs", "1", "--ga", str(_num(params, "ga", 8, 1, 64)),
        "--epochs", str(_num(params, "epochs", 1, 1, 10)),
        "--lr", str(_num(params, "lr", 0.0002, 1e-6, 1e-3, float)),
        "--r", str(_num(params, "r", 16, 1, 128)),
        "--save-steps", str(_num(params, "save_steps", 100, 10, 10000)),
        "--logging-steps", "5",
        "--max-steps", str(_num(params, "max_steps", -1, -1, 1_000_000)),
        "--out", str(out),
    ]
    if params.get("base_model"):
        cmd += ["--model", str(params["base_model"])]

    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    log = RUN_LOG.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                cwd=str(FINETUNE_ROOT), env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        return {"error": f"не удалось запустить обучение: {exc}",
                "code": "ev.trainStartFailed", "vars": {"error": str(exc)}}
    finally:
        log.close()
    meta = {"pid": proc.pid, "run_name": name, "categories": categories,
            "params": params, "started": time.time(), "cmd": cmd,
            "adapter": str((FINETUNE_ROOT / "models" / "adapters") / name)}
    RUN_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"started": True, **meta, "dataset": counts}


def stop() -> dict[str, Any]:
    meta = _meta()
    pid = meta.get("pid")
    if pid and _alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
        return {"stopped": True, "pid": pid}
    return {"stopped": False}


def _meta() -> dict[str, Any]:
    if RUN_META.exists():
        try:
            return json.loads(RUN_META.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def status() -> dict[str, Any]:
    meta = _meta()
    pid = int(meta.get("pid") or 0)
    steps = total = 0
    loss = None
    per_step = 0.0
    eta = 0.0
    last_losses: list[float] = []
    steps, total, samples, last_losses = _progress()
    if last_losses:
        loss = last_losses[-1]
    if samples:
        window = samples[-11:]
        if len(window) >= 2 and window[-1][1] > window[0][1]:
            per_step = (window[-1][1] - window[0][1]) / max(1, window[-1][0] - window[0][0])
        if per_step and total:
            eta = (total - steps) * per_step
    running = bool(pid) and _alive(pid)
    return {
        "running": running,
        "pid": pid,
        "steps": steps,
        "total": total,
        "percent": round(100 * steps / total, 2) if total else 0.0,
        "loss": loss,
        "loss_series": last_losses[-120:],
        "per_step_s": round(per_step, 1),
        "eta_s": int(eta),
        "run_name": meta.get("run_name"),
        "adapter": meta.get("adapter"),
        "started": meta.get("started"),
        "log": str(RUN_LOG),
    }


def _hms(value: str) -> float:
    parts = [int(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]
