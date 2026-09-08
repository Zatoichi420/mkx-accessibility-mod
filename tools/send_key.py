"""Send a real SendInput keypress (not SendKeys/WM_CHAR - many games ignore
that and only respond to raw input) to whichever window is currently
foreground. Usage: python send_key.py VK_HEX [hold_ms]
e.g. python send_key.py 0D      (Enter)
     python send_key.py 20      (Space)
"""
import ctypes
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]


def send_key(vk, hold_ms=80):
    extra = ctypes.c_ulong(0)
    ii_down = Input_I()
    ii_down.ki = KeyBdInput(vk, 0, 0, 0, ctypes.pointer(extra))
    cmd_down = Input(INPUT_KEYBOARD, ii_down)
    user32.SendInput(1, ctypes.pointer(cmd_down), ctypes.sizeof(cmd_down))
    time.sleep(hold_ms / 1000.0)
    ii_up = Input_I()
    ii_up.ki = KeyBdInput(vk, 0, KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
    cmd_up = Input(INPUT_KEYBOARD, ii_up)
    user32.SendInput(1, ctypes.pointer(cmd_up), ctypes.sizeof(cmd_up))


def foreground_window_title():
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return hwnd, buf.value


if __name__ == "__main__":
    vk = int(sys.argv[1], 16)
    hold_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    hwnd, title = foreground_window_title()
    print(f"Foreground window: hwnd=0x{hwnd:X} title={title!r}")
    send_key(vk, hold_ms)
    print(f"Sent VK 0x{vk:X}")
