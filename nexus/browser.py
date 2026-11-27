"""Браузер агента: свой профиль с данными пользователя (Chrome/Chromium через Playwright).

Всё выполняется в отдельном потоке: sync-API Playwright нельзя дёргать из разных потоков.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

SNAPSHOT_JS = r"""
() => {
  const sel = 'a,button,input,textarea,select,summary,label,[role=button],[role=link],[role=tab],[role=menuitem],[contenteditable=""],[contenteditable=true],[onclick]';
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 3 || r.height < 3) return false;
    const s = getComputedStyle(el);
    return !(s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0');
  };
  document.querySelectorAll('[data-nexus-idx]')
    .forEach((el) => el.removeAttribute('data-nexus-idx'));
  const items = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    el.setAttribute('data-nexus-idx', String(items.length));
    const r = el.getBoundingClientRect();
    const label = (el.innerText || el.value || el.getAttribute('aria-label') ||
                   el.getAttribute('placeholder') || el.getAttribute('title') || '')
                   .replace(/\s+/g, ' ').trim().slice(0, 90);
    items.push({
      i: items.length,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      text: label,
      name: el.getAttribute('name') || '',
      href: (el.getAttribute('href') || '').slice(0, 120),
      box: [Math.round(r.left + window.scrollX), Math.round(r.top + window.scrollY),
            Math.round(r.width), Math.round(r.height)]
    });
    if (items.length > 150) break;
  }
  const heads = [...document.querySelectorAll('h1,h2,h3')].slice(0, 12)
    .map(h => h.innerText.trim().slice(0, 80)).filter(Boolean);
  return {
    url: location.href,
    title: document.title,
    headings: heads,
    text: (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, 2500),
    elements: items
  };
}
"""

SELECTOR = ("a,button,input,textarea,select,summary,label,[role=button],[role=link],"
            "[role=tab],[role=menuitem],[contenteditable=''],[contenteditable=true],[onclick]")


class BrowserHub:
    """Один поток, одна очередь задач, один браузер с постоянным профилем."""

    def __init__(self, cfg_browser: dict[str, Any]) -> None:
        self.cfg = cfg_browser
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pw = None
        self._ctx = None
        self._page = None
        self._handles: list[Any] = []
        self._lock = threading.Lock()
        self._thread_lock = threading.Lock()
        self._signature: tuple | None = None
        self._last_dialog: dict[str, Any] | None = None
        self._hung = False

    # ---------------------------------------------------------------- инфраструктура
    def _ensure_thread(self) -> None:
        # Без замка два параллельных вызова создавали два Playwright-потока
        # и роняли sync API внутри asyncio/greenlet.
        with self._thread_lock:
            if self._hung:
                raise RuntimeError("браузер завис на предыдущем вызове; перезапусти демон Nexus")
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name="nexus-browser", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            fn, box = self._queue.get()
            try:
                box["result"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                box["done"].set()

    def call(self, fn: Callable[[], Any], timeout: float = 90.0) -> Any:
        self._ensure_thread()
        box: dict[str, Any] = {"done": threading.Event()}
        self._queue.put((fn, box))
        if not box["done"].wait(timeout):
            # Задача осталась в Playwright-потоке; новые вызовы в очередь не
            # кладём, иначе они тоже зависнут. Явная ошибка вместо тишины.
            self._hung = True
            raise TimeoutError("браузер не ответил вовремя; перезапусти демон Nexus")
        if "error" in box:
            raise RuntimeError(box["error"])
        return box.get("result")

    # ---------------------------------------------------------------- браузер
    def _signature_of(self) -> tuple:
        viewport = tuple(self.cfg.get("viewport") or [1440, 900])
        return (str(self.cfg.get("profile_dir")), bool(self.cfg.get("headless", False)),
                str(self.cfg.get("executable") or ""), viewport)

    def _launch(self) -> None:
        signature = self._signature_of()
        if self._page is not None and signature == self._signature:
            return
        if self._page is not None:
            self._shutdown()

        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        if self._pw is None:
            self._pw = sync_playwright().start()
        profile = Path(self.cfg.get("profile_dir", "data/browser-profile"))
        profile.mkdir(parents=True, exist_ok=True)
        exe = self.cfg.get("executable") or None
        viewport = self.cfg.get("viewport") or [1440, 900]
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-size={viewport[0]},{viewport[1]}",
        ]
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=exe,
                headless=bool(self.cfg.get("headless", False)),
                args=args,
                viewport=None,
                no_viewport=True,
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if "processsingleton" in message or "user data directory" in message or "profile" in message:
                raise RuntimeError(
                    f"профиль браузера уже занят: {profile}. "
                    "Закрой оставшийся Chrome/Edge с этим профилем или перезапусти демон.") from exc
            raise
        self._ctx.set_default_timeout(20000)
        self._ctx.on("page", self._on_page)
        self._ctx.on("close", self._on_context_close)
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        self._attach(self._page)
        self._signature = signature

    def _attach(self, page: Any) -> None:
        def on_dialog(dialog: Any) -> None:
            # confirm()/alert() иначе вешают страницу до таймаута.
            self._last_dialog = {"type": getattr(dialog, "type", ""),
                                 "message": str(getattr(dialog, "message", ""))[:500]}
            try:
                dialog.accept()
            except Exception:  # noqa: BLE001
                try:
                    dialog.dismiss()
                except Exception:  # noqa: BLE001
                    pass

        try:
            page.on("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass

    def _on_page(self, page: Any) -> None:
        # target=_blank: работаем с новой вкладкой, иначе снапшот и клики
        # остаются на старой странице.
        self._page = page
        self._attach(page)
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass

    def _on_context_close(self, _ctx: Any = None) -> None:
        self._page = None
        self._ctx = None

    def _shutdown(self) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = None
        self._page = None
        self._handles = []
        self._signature = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    def start(self) -> dict[str, Any]:
        def job():
            self._launch()
            return {"ok": True, "url": self._page.url}

        return self.call(job, timeout=120)

    def goto(self, url: str) -> dict[str, Any]:
        def job():
            self._launch()
            self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(0.4)
            return {"url": self._page.url, "title": self._page.title()}

        return self.call(job, timeout=120)

    def _snapshot_locked(self, text_limit: int = 2500) -> dict[str, Any]:
        self._launch()
        data = self._page.evaluate(SNAPSHOT_JS)
        handles = self._page.query_selector_all("[data-nexus-idx]")
        # Индексы снапшота и хэндлы теперь из одного набора: скрытые элементы
        # не сдвигают нумерацию.
        handles.sort(key=lambda h: int(h.get_attribute("data-nexus-idx") or 0))
        self._handles = handles
        data["text"] = (data.get("text") or "")[:text_limit]
        if self._last_dialog:
            data["dialog"] = self._last_dialog
            self._last_dialog = None
        return data

    def snapshot(self, text_limit: int = 2500) -> dict[str, Any]:
        def job():
            return self._snapshot_locked(text_limit)

        return self.call(job)

    def element(self, index: int) -> Any:
        if index < 0 or index >= len(self._handles):
            raise IndexError(f"нет элемента с индексом {index} (в снимке {len(self._handles)})")
        return self._handles[index]

    def click(self, index: int | None = None, selector: str | None = None,
              human: bool = True) -> dict[str, Any]:
        def job():
            self._launch()
            last = None
            for attempt in range(2):
                if selector:
                    el = self._page.wait_for_selector(selector, timeout=15000)
                elif index is not None:
                    el = self.element(index)
                else:
                    raise ValueError("нужен index или selector")
                try:
                    el.scroll_into_view_if_needed(timeout=8000)
                    box = el.bounding_box()
                    if human and box:
                        # «фантомно» ведём настоящий курсор в центр элемента
                        from . import gui  # noqa: PLC0415

                        cx = int(box["x"] + box["width"] / 2)
                        cy = int(box["y"] + box["height"] / 2)
                        wx = cx + self._page.evaluate("window.screenX")
                        wy = cy + self._page.evaluate("window.screenY")
                        gui.move(wx, wy)
                        time.sleep(0.05)
                    el.click(timeout=15000)
                    time.sleep(0.6)
                    return {"clicked": index if index is not None else selector, "url": self._page.url}
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    if attempt or index is None:
                        raise
                    # DOM перерисовался: хэндл протух. Обновляем индексы один
                    # раз и повторяем — модель не должна сдаваться.
                    low = str(exc).lower()
                    if "not attached" not in low and "detached" not in low and "element is not" not in low:
                        raise
                    self._snapshot_locked()
            raise RuntimeError(str(last))

        return self.call(job, timeout=120)

    def type_text(self, text: str, index: int | None = None, selector: str | None = None,
                  press_enter: bool = False) -> dict[str, Any]:
        def job():
            self._launch()
            last = None
            for attempt in range(2):
                if selector:
                    el = self._page.wait_for_selector(selector, timeout=15000)
                elif index is not None:
                    el = self.element(index)
                else:
                    el = self._page.locator(":focus")
                try:
                    el.click(timeout=10000)
                    el.fill("")
                    el.type(text, delay=18)
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    if attempt or index is None:
                        raise
                    low = str(exc).lower()
                    if "not attached" not in low and "detached" not in low and "element is not" not in low:
                        raise
                    self._snapshot_locked()
            else:
                raise RuntimeError(str(last))
            if press_enter:
                self._page.keyboard.press("Enter")
                time.sleep(0.5)
            return {"typed": text[:60], "url": self._page.url}

        return self.call(job, timeout=120)

    def press(self, combo: str) -> dict[str, Any]:
        def job():
            self._launch()
            self._page.keyboard.press(combo)
            time.sleep(0.3)
            return {"pressed": combo}

        return self.call(job)

    def evaluate(self, expression: str) -> Any:
        def job():
            self._launch()
            return self._page.evaluate(expression)

        return self.call(job)

    def screenshot(self, path: Path) -> dict[str, Any]:
        def job():
            self._launch()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(path=str(path), full_page=False)
            size = self._page.evaluate("[innerWidth, innerHeight]")
            return {"path": str(path), "viewport": size}

        return self.call(job)

    def close(self) -> dict[str, Any]:
        def job():
            if self._ctx is not None:
                self._ctx.close()
            if self._pw is not None:
                self._pw.stop()
            self._ctx = self._page = None
            self._pw = None
            return {"ok": True}

        return self.call(job, timeout=60)
