"""One-shot screenshot of the live MK10.exe window, saved to disk so it can
be inspected without being physically at the screen (e.g. via an image-
capable tool reading the PNG). Usage: python capture_now.py out.png
"""
import ctypes
import sys
import win32api
import win32gui
import win32process
import win32ui
from PIL import Image

PW_RENDERFULLCONTENT = 0x00000002
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
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
                target_hwnd = hwnd
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass
    return target_hwnd


def capture_window(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    hwnd_dc = mfc_dc = save_dc = save_bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bitmap)
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        bmpinfo = save_bitmap.GetInfo()
        bmpstr = save_bitmap.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1)
        return img
    finally:
        if save_bitmap is not None:
            win32gui.DeleteObject(save_bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)


hwnd = find_window_for_process(PROCESS_NAME)
if hwnd is None:
    print("Window not found")
    sys.exit(1)
img = capture_window(hwnd)
if img is None:
    print("Capture failed (zero size?)")
    sys.exit(1)
img.save(OUT_PATH)
print(f"Saved {OUT_PATH}, size={img.size}")
