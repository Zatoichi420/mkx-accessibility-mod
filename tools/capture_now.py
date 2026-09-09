"""One-shot screenshot of the live game, saved to disk so it can be
inspected without being physically at the screen (e.g. via an image-
capable tool reading the PNG). Usage: python capture_now.py out.png

Grabs the whole desktop rather than using PrintWindow on the game's window
handle - confirmed live 2026-09-08 that PrintWindow goes silently dark once
MKX is showing its real fullscreen menus (works fine during the windowed
intro cinematics, then just returns a zero-size capture with no error once
fullscreen kicks in - GetWindowRect on the window also starts returning a
bogus placeholder rect at the same point). A desktop grab isn't affected by
whatever that fullscreen mode actually is. Still checks the process is
running first so this fails clearly rather than screenshotting some other
foreground window.
"""
import sys
import win32api
import win32gui
import win32process
from PIL import ImageGrab

PROCESS_NAME = "MK10.exe"
OUT_PATH = sys.argv[1] if len(sys.argv) > 1 else "capture.png"


def find_window_for_process(process_name):
    target_hwnd = None

    def callback(hwnd, _):
        nonlocal target_hwnd
        if not win32gui.IsWindowVisible(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = None
        try:
            handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
            exe_name = win32process.GetModuleFileNameEx(handle, 0)
        except Exception:
            return True
        finally:
            if handle is not None:
                win32api.CloseHandle(handle)
        if exe_name.lower().endswith(process_name.lower()) and target_hwnd is None:
            target_hwnd = hwnd
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass
    return target_hwnd


hwnd = find_window_for_process(PROCESS_NAME)
if hwnd is None:
    print(f"{PROCESS_NAME} window not found - is the game running?")
    sys.exit(1)

img = ImageGrab.grab(all_screens=True)
img.save(OUT_PATH)
print(f"Saved {OUT_PATH}, size={img.size}")
