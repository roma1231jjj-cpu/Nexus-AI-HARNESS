"""Управление рабочим столом Windows: экран, мышь, клавиатура, окна.

Только stdlib + ctypes (SendInput), скриншоты — через mss, если установлен.
Координаты — физические пиксели виртуального рабочего стола (все мониторы).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path
from typing import Any

try:  # DPI-awareness до создания любых окон, иначе клики уезжают
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # pragma: no cover
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUT_UNION)]


VK: dict[str, int] = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "minus": 0xBD, "-": 0xBD, "equal": 0xBB, "=": 0xBB, "plus": 0xBB, "+": 0xBB,
    "comma": 0xBC, ",": 0xBC, "period": 0xBE, ".": 0xBE, "dot": 0xBE,
    "slash": 0xBF, "/": 0xBF, "semicolon": 0xBA, ";": 0xBA, "quote": 0xDE, "'": 0xDE,
    "bracketleft": 0xDB, "[": 0xDB, "bracketright": 0xDD, "]": 0xDD,
    "backslash": 0xDC, "\\": 0xDC, "grave": 0xC0, "`": 0xC0,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "printscreen": 0x2C,
}
# Буквы и цифры: без них ctrl+c/ctrl+v/ctrl+s нажимали только Ctrl.
VK.update({chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)})
VK.update({chr(code): code for code in range(ord("0"), ord("9") + 1)})


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        # UIPI, secure desktop, UAC: инструмент не должен врать об успехе.
        raise OSError(f"SendInput принял {sent} из {len(inputs)} событий "
                      f"(GetLastError={ctypes.GetLastError()})")


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    item = INPUT(type=INPUT_MOUSE)
    item.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    return item


def _key(vk: int, up: bool = False, scan: int = 0, unicode: bool = False) -> INPUT:
    item = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_UNICODE if unicode else 0)
    item.ki = KEYBDINPUT(0 if unicode else vk, scan, flags, 0, 0)
    return item


# ------------------------------------------------------------------ экран
def screen_info() -> dict[str, Any]:
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return {"x": x, "y": y, "width": w, "height": h}


def screenshot(path: Path) -> dict[str, Any]:
    try:
        import mss  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("нужны пакеты mss и pillow: pip install mss pillow") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[0])
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    # Ужимаем, чтобы модель не давилась гигапикселями
    max_w = 1600
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)))
    img.save(path, "PNG", optimize=True)
    return {"path": str(path), "width": img.width, "height": img.height}


# ------------------------------------------------------------------ мышь
def move(x: int, y: int, steps: int = 8) -> None:
    sx, sy = cursor()
    for i in range(1, steps + 1):
        nx = sx + (x - sx) * i / steps
        ny = sy + (y - sy) * i / steps
        user32.SetCursorPos(int(nx), int(ny))
        time.sleep(0.008)


def cursor() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def click(x: int | None = None, y: int | None = None, button: str = "left",
          clicks: int = 1) -> dict[str, Any]:
    if x is not None and y is not None:
        move(x, y)
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    for _ in range(max(1, clicks)):
        _send(_mouse(down), _mouse(up))
        time.sleep(0.05)
    return {"cursor": cursor(), "button": button, "clicks": clicks}


def drag(x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
    move(x1, y1)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.05)
    move(x2, y2, steps=14)
    time.sleep(0.05)
    _send(_mouse(MOUSEEVENTF_LEFTUP))
    return {"from": [x1, y1], "to": [x2, y2]}


def scroll(amount: int, x: int | None = None, y: int | None = None) -> dict[str, Any]:
    if x is not None and y is not None:
        move(x, y)
    _send(_mouse(MOUSEEVENTF_WHEEL, data=int(amount)))
    return {"scroll": amount}


# ------------------------------------------------------------------ клавиатура
def type_text(text: str) -> dict[str, Any]:
    typed = 0
    for ch in text:
        if ch == "\n":
            press("enter")
            typed += 1
            continue
        if ch == "\t":
            press("tab")
            typed += 1
            continue
        # SendInput ждёт UTF-16 code units; эмодзи — суррогатная пара,
        # поэтому кодируем целиком, а не по одному code point.
        units = ch.encode("utf-16-le")
        for i in range(0, len(units), 2):
            code = units[i] | (units[i + 1] << 8)
            _send(_key(0, scan=code, unicode=True), _key(0, up=True, scan=code, unicode=True))
        typed += 1
        time.sleep(0.002)
    return {"typed": typed}


def press(combo: str) -> dict[str, Any]:
    parts = [p.strip().lower() for p in combo.replace("+", " ").split() if p.strip()]
    if not parts:
        return {"error": "пустая комбинация"}
    unknown = [p for p in parts if p not in VK]
    if unknown:
        # Раньше неизвестная клавиша молча выбрасывалась: ctrl+c нажимал
        # только Ctrl. Теперь это явная ошибка.
        return {"error": f"неизвестная клавиша: {', '.join(unknown)} (в {combo})"}
    codes = [VK[p] for p in parts]
    for code in codes:
        _send(_key(code))
        time.sleep(0.01)
    for code in reversed(codes):
        _send(_key(code, up=True))
        time.sleep(0.01)
    return {"pressed": combo}


# ------------------------------------------------------------------ окна
def windows() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append({
            "hwnd": int(hwnd),
            "title": buf.value,
            "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
        })
        return True

    user32.EnumWindows(EnumProc(callback), 0)
    return found


def focus(title_part: str) -> dict[str, Any]:
    for win in windows():
        if title_part.lower() in win["title"].lower():
            if not user32.SetForegroundWindow(win["hwnd"]):
                return {"error": f"Windows не разрешила переключить окно: {win['title']}"}
            time.sleep(0.15)
            return {"focused": win["title"], "rect": win["rect"]}
    return {"error": f"окно не найдено: {title_part}"}
