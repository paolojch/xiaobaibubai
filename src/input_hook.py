"""Cross-platform global keyboard and mouse hook (Win32 ctypes on Windows, pynput on macOS)."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from PySide6.QtCore import QObject, Signal

if sys.platform == "win32":
    from ctypes import wintypes

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_QUIT = 0x0012

LLKHF_EXTENDED = 0x01
LLKHF_UP = 0x80
SM_SWAPBUTTON = 23

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04
VK_PACKET = 0xE7

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t

VK_LABELS: dict[int, str] = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x10: "Shift",
    0x11: "Ctrl",
    0x12: "Alt",
    0x13: "Pause",
    0x14: "Caps",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PgUp",
    0x22: "PgDn",
    0x23: "End",
    0x24: "Home",
    0x25: "←",
    0x26: "↑",
    0x27: "→",
    0x28: "↓",
    0x2C: "PrtSc",
    0x2D: "Ins",
    0x2E: "Del",
    0x5B: "Win",
    0x5C: "Win",
    0x5D: "Menu",
    0x6A: "Num*",
    0x6B: "Num+",
    0x6D: "Num-",
    0x6E: "Num.",
    0x6F: "Num/",
    0x90: "NumLk",
    0x91: "ScrLk",
    0xA0: "Shift",
    0xA1: "Shift",
    0xA2: "Ctrl",
    0xA3: "Ctrl",
    0xA4: "Alt",
    0xA5: "Alt",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}

VK_BUBBLE_ICONS: dict[int, str] = {
    0x08: "⌫",
    0x09: "⇥",
    0x0D: "↵",
    0x10: "⇧",
    0x11: "⌃",
    0x12: "⌥",
    0x14: "⇪",
    0x1B: "Esc",
    0x20: " ",
    0x5B: "⌘",
    0x5C: "⌘",
    0xA0: "⇧",
    0xA1: "⇧",
    0xA2: "⌃",
    0xA3: "⌃",
    0xA4: "⌥",
    0xA5: "⌥",
}


def is_ignored_vk(vk: int) -> bool:
    """Return True for non-keyboard, synthetic, or extended F13-F24 VKs that cause phantom holds."""
    if vk <= 0 or vk >= 0xFF:
        return True
    if 0x01 <= vk <= 0x06:
        return True
    if 0x7C <= vk <= 0x87:  # F13-F24 (commonly injected by remote/anti-sleep/gesture software)
        return True
    if vk == VK_PACKET:
        return True
    return False


def vk_to_label(vk: int, flags: int = 0) -> str:
    """Convert a Windows Virtual Key code into a compact readable label."""
    if vk == 0x0D and (flags & LLKHF_EXTENDED):
        return "NumEnter"
    if vk in VK_LABELS:
        return VK_LABELS[vk]
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x60 <= vk <= 0x69:
        return f"Num{vk - 0x60}"
    if sys.platform == "win32":
        try:
            ch = ctypes.windll.user32.MapVirtualKeyW(vk, 2) & 0xFFFF
            if 32 < ch < 127:
                return chr(ch).upper()
        except Exception:
            pass
    return f"Key{vk:02X}"


def vk_to_bubble_label(vk: int, flags: int = 0) -> str:
    """Convert a VK code to the video-matched keycap symbol shown on the cat's chest."""
    if vk in VK_BUBBLE_ICONS:
        return VK_BUBBLE_ICONS[vk]
    return vk_to_label(vk, flags)


# macOS Carbon kVK_* -> Windows VK_* mapping for consistent mirrored keyboard rig
MAC_KEYCODE_TO_VK: dict[int, int] = {
    0x00: 0x41, 0x0B: 0x42, 0x08: 0x43, 0x02: 0x44, 0x0E: 0x45, 0x03: 0x46,
    0x05: 0x47, 0x04: 0x48, 0x22: 0x49, 0x26: 0x4A, 0x28: 0x4B, 0x25: 0x4C,
    0x2E: 0x4D, 0x2D: 0x4E, 0x1F: 0x4F, 0x23: 0x50, 0x0C: 0x51, 0x0F: 0x52,
    0x01: 0x53, 0x11: 0x54, 0x20: 0x55, 0x09: 0x56, 0x0D: 0x57, 0x07: 0x58,
    0x10: 0x59, 0x06: 0x5A,
    0x1D: 0x30, 0x12: 0x31, 0x13: 0x32, 0x14: 0x33, 0x15: 0x34,
    0x17: 0x35, 0x16: 0x36, 0x1A: 0x37, 0x1C: 0x38, 0x19: 0x39,
    0x24: 0x0D, 0x30: 0x09, 0x31: 0x20, 0x33: 0x08, 0x35: 0x1B, 0x39: 0x14,
    0x37: 0x5B, 0x36: 0x5C, 0x38: 0xA0, 0x3C: 0xA1, 0x3A: 0xA4, 0x3D: 0xA5,
    0x3B: 0xA2, 0x3E: 0xA3,
    0x29: 0xBA, 0x18: 0xBB, 0x2B: 0xBC, 0x1B: 0xBD, 0x2F: 0xBE, 0x2C: 0xBF,
    0x32: 0xC0, 0x21: 0xDB, 0x2A: 0xDC, 0x1E: 0xDD, 0x27: 0xDE,
    0x7A: 0x70, 0x78: 0x71, 0x63: 0x72, 0x76: 0x73, 0x60: 0x74, 0x61: 0x75,
    0x62: 0x76, 0x64: 0x77, 0x65: 0x78, 0x6D: 0x79, 0x67: 0x7A, 0x6F: 0x7B,
    0x7B: 0x25, 0x7C: 0x27, 0x7D: 0x28, 0x7E: 0x26,
    0x73: 0x24, 0x77: 0x23, 0x74: 0x21, 0x79: 0x22, 0x75: 0x2E,
}

CHAR_TO_VK: dict[str, int] = {
    ";": 0xBA, ":": 0xBA, "=": 0xBB, "+": 0xBB, ",": 0xBC, "<": 0xBC,
    "-": 0xBD, "_": 0xBD, ".": 0xBE, ">": 0xBE, "/": 0xBF, "?": 0xBF,
    "`": 0xC0, "~": 0xC0, "[": 0xDB, "{": 0xDB, "\\": 0xDC, "|": 0xDC,
    "]": 0xDD, "}": 0xDD, "'": 0xDE, '"': 0xDE, " ": 0x20, "\r": 0x0D,
    "\n": 0x0D, "\t": 0x09,
}

PYNPUT_NAME_TO_VK: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0xA0, "shift_l": 0xA0, "shift_r": 0xA1,
    "ctrl": 0xA2, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt": 0xA4, "alt_l": 0xA4, "alt_r": 0xA5, "alt_gr": 0xA5,
    "caps_lock": 0x14, "esc": 0x1B, "space": 0x20,
    "page_up": 0x21, "page_down": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "delete": 0x2E, "insert": 0x2D,
    "cmd": 0x5B, "cmd_l": 0x5B, "cmd_r": 0x5C,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def _pynput_key_to_vk(key) -> int | None:
    """Translate a pynput keyboard key object to a Windows-compatible VK code."""
    vk_attr = getattr(key, "vk", None)
    if sys.platform == "darwin" and isinstance(vk_attr, int) and vk_attr in MAC_KEYCODE_TO_VK:
        return MAC_KEYCODE_TO_VK[vk_attr]
    char = getattr(key, "char", None)
    if isinstance(char, str) and len(char) == 1:
        upper = char.upper()
        if "A" <= upper <= "Z" or "0" <= upper <= "9":
            return ord(upper)
        if char in CHAR_TO_VK:
            return CHAR_TO_VK[char]
    name = getattr(key, "name", None)
    if isinstance(name, str) and name in PYNPUT_NAME_TO_VK:
        return PYNPUT_NAME_TO_VK[name]
    if isinstance(vk_attr, int) and 0 < vk_attr < 256:
        return vk_attr
    return None


if sys.platform == "win32":

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)


class GlobalInputHook(QObject):
    """Non-blocking global keyboard and mouse listener emitting Qt signals."""

    key_event = Signal(int, str, str, bool)  # vk, label, bubble_label, is_down
    mouse_button_event = Signal(str, bool, int, int)  # button, is_down, gx, gy
    mouse_moved = Signal(int, int)  # global screen gx, gy

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._running = False
        self._ready = threading.Event()
        self._last_move_ms = 0.0
        self._kb_listener = None
        self._mouse_listener = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._ready.clear()
        target = self._run_loop_win32 if sys.platform == "win32" else self._run_loop_pynput
        self._thread = threading.Thread(
            target=target, name="GlobalInputHook", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        self._running = False
        if sys.platform == "win32":
            if self._thread_id is not None:
                try:
                    ctypes.windll.user32.PostThreadMessageW(
                        wintypes.DWORD(self._thread_id), WM_QUIT, 0, 0
                    )
                except Exception:
                    pass
        else:
            for listener in (self._kb_listener, self._mouse_listener):
                if listener is not None:
                    try:
                        listener.stop()
                    except Exception:
                        pass
            self._kb_listener = None
            self._mouse_listener = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    @staticmethod
    def is_vk_pressed(vk: int) -> bool | None:
        """Query OS-level live key state; returns None when unsupported on current platform."""
        if sys.platform != "win32":
            return None
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk)) & 0x8000)
        except Exception:
            return None

    @staticmethod
    def is_mouse_button_pressed(button: str) -> bool | None:
        """Query OS-level live mouse button state (respecting swapped primary/secondary buttons)."""
        if sys.platform != "win32":
            return None
        try:
            user32 = ctypes.windll.user32
            swapped = bool(user32.GetSystemMetrics(SM_SWAPBUTTON))
            if button == "left":
                vk = VK_RBUTTON if swapped else VK_LBUTTON
            elif button == "right":
                vk = VK_LBUTTON if swapped else VK_RBUTTON
            elif button == "middle":
                vk = VK_MBUTTON
            else:
                return None
            return bool(user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return None

    def _run_loop_pynput(self) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception:
            self._ready.set()
            return

        def emit_key(key, is_down: bool) -> None:
            vk = _pynput_key_to_vk(key)
            if vk is None or is_ignored_vk(vk):
                return
            label = vk_to_label(vk, 0)
            bubble = vk_to_bubble_label(vk, 0)
            self.key_event.emit(vk, label, bubble, is_down)

        def on_move(x: float, y: float) -> None:
            now = time.monotonic() * 1000.0
            if now - self._last_move_ms >= 16.0:
                self._last_move_ms = now
                self.mouse_moved.emit(int(x), int(y))

        def on_click(x: float, y: float, button, pressed: bool) -> None:
            btn_name = getattr(button, "name", str(button)).lower()
            if "right" in btn_name:
                btn = "right"
            elif "middle" in btn_name:
                btn = "middle"
            else:
                btn = "left"
            self.mouse_button_event.emit(btn, bool(pressed), int(x), int(y))

        try:
            self._kb_listener = keyboard.Listener(
                on_press=lambda k: emit_key(k, True),
                on_release=lambda k: emit_key(k, False),
            )
            self._mouse_listener = mouse.Listener(
                on_move=on_move,
                on_click=on_click,
            )
            self._kb_listener.start()
            self._mouse_listener.start()
        except Exception:
            self._ready.set()
            return

        self._ready.set()
        while self._running:
            time.sleep(0.1)

    def _run_loop_win32(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            WPARAM,
            LPARAM,
        ]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL

        self._thread_id = kernel32.GetCurrentThreadId()

        def kb_callback(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0 and l_param:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
                    vk = int(info.vkCode)
                    if not is_ignored_vk(vk):
                        flags = int(info.flags)
                        label = vk_to_label(vk, flags)
                        bubble = vk_to_bubble_label(vk, flags)
                        is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN) and not (flags & LLKHF_UP)
                        self.key_event.emit(vk, label, bubble, is_down)
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        def mouse_callback(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0 and l_param:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                gx, gy = int(info.pt.x), int(info.pt.y)
                if w_param == WM_LBUTTONDOWN:
                    self.mouse_button_event.emit("left", True, gx, gy)
                elif w_param == WM_LBUTTONUP:
                    self.mouse_button_event.emit("left", False, gx, gy)
                elif w_param == WM_RBUTTONDOWN:
                    self.mouse_button_event.emit("right", True, gx, gy)
                elif w_param == WM_RBUTTONUP:
                    self.mouse_button_event.emit("right", False, gx, gy)
                elif w_param == WM_MBUTTONDOWN:
                    self.mouse_button_event.emit("middle", True, gx, gy)
                elif w_param == WM_MBUTTONUP:
                    self.mouse_button_event.emit("middle", False, gx, gy)
                elif w_param == WM_MOUSEMOVE:
                    now = time.monotonic() * 1000.0
                    if now - self._last_move_ms >= 16.0:
                        self._last_move_ms = now
                        self.mouse_moved.emit(gx, gy)
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        kb_proc = HOOKPROC(kb_callback)
        mouse_proc = HOOKPROC(mouse_callback)

        kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kb_proc, None, 0)
        mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, None, 0)
        self._ready.set()

        msg = wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if kb_hook:
            user32.UnhookWindowsHookEx(kb_hook)
        if mouse_hook:
            user32.UnhookWindowsHookEx(mouse_hook)
