"""
Capture strategies. Each game picks the one that actually works for its
window/fullscreen behavior - see each project's main.py for which and why.

PrintWindowCapture: works for a game that renders into a normal GDI-
capturable window (confirmed for Legacy Kollection's launcher, which never
goes exclusive-fullscreen). DesktopGrabCapture: needed for a game whose
fullscreen mode makes PrintWindow return a silent zero-size capture
(confirmed live for MKX/MK10.exe - see that project's PROGRESS.md).
"""

import ctypes
from abc import ABC, abstractmethod

import win32gui
import win32ui
from PIL import Image, ImageGrab


class CaptureStrategy(ABC):
    @abstractmethod
    def grab(self, hwnd):
        """Return a PIL Image of the current screen, or None if a frame
        isn't available right now (window gone, capture failed, etc.)."""
        raise NotImplementedError


class PrintWindowCapture(CaptureStrategy):
    PW_RENDERFULLCONTENT = 0x00000002

    def grab(self, hwnd):
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

        hwnd_dc = None
        mfc_dc = None
        save_dc = None
        save_bitmap = None
        try:
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(save_bitmap)

            ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), self.PW_RENDERFULLCONTENT)

            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            return Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr, "raw", "BGRX", 0, 1,
            )
        finally:
            # Always release GDI resources, even if a call above raised - leaving
            # any of these held leaks a handle every poll (twice a second) and
            # can eventually exhaust the process's GDI handle quota.
            if save_bitmap is not None:
                win32gui.DeleteObject(save_bitmap.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            if hwnd_dc is not None:
                win32gui.ReleaseDC(hwnd, hwnd_dc)


class DesktopGrabCapture(CaptureStrategy):
    """Confirmed live 2026-09-08 against MKX (see that project's
    PROGRESS.md): grabs the whole desktop instead of using PrintWindow on
    `hwnd` directly. PrintWindow worked during that game's windowed intro
    cinematics but went silently dark (zero-size capture, no error) once
    the game settled into its real fullscreen main menu - GetWindowRect on
    the game's own window also starts returning a bogus placeholder rect
    (large negative coordinates) at that point, the same underlying
    symptom. `hwnd` is accepted here only so this class has the same
    interface as PrintWindowCapture; it's unused - the caller still needs a
    hwnd to know the game is running at all, just not for capture
    geometry."""

    def grab(self, hwnd):
        return ImageGrab.grab(all_screens=True)
