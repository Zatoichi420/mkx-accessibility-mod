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
from contextlib import contextmanager

import win32gui
import win32ui
from PIL import Image, ImageGrab


class CaptureStrategy(ABC):
    @abstractmethod
    def grab(self, hwnd):
        """Return a PIL Image of the current screen, or None if a frame
        isn't available right now (window gone, capture failed, etc.)."""
        raise NotImplementedError


@contextmanager
def _dpi_context_of(hwnd):
    """Run the enclosed calls in the target window's own DPI awareness.

    Added 2026-10-11. GetClientRect and PrintWindow only agree on the
    image's size when the caller and the window use the same DPI awareness.
    The reader makes itself DPI-aware (frames.enable_dpi_awareness), which
    fixed a DPI-aware game captured by an unaware reader. But with display
    scaling on, a DPI-*unaware* window then reports its scaled-up size while
    PrintWindow draws it at its unscaled size: the image lands in the
    top-left corner of a mostly black bitmap and no library screen matches.
    Reproduced at 150% scaling with packaging/ci/fake_game.py (a Tk window,
    which is DPI-unaware). Borrowing the window's own awareness for the
    duration of the capture is correct in both directions, and a no-op when
    the two already agree. Falls through silently on Windows versions
    without these calls (before Windows 10 1607).
    """
    user32 = ctypes.windll.user32
    previous = None
    try:
        user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetWindowDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        context = user32.GetWindowDpiAwarenessContext(hwnd)
        if context:
            previous = user32.SetThreadDpiAwarenessContext(context)
    except (AttributeError, OSError):
        previous = None
    try:
        yield
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)


class PrintWindowCapture(CaptureStrategy):
    PW_RENDERFULLCONTENT = 0x00000002

    def grab(self, hwnd):
        with _dpi_context_of(hwnd):
            return self._grab(hwnd)

    def _grab(self, hwnd):
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None
        # PrintWindow draws the WHOLE window, title bar and borders included,
        # starting at the bitmap's top-left. Found live 2026-10-12 (Legacy
        # Kollection, windowed mode): a client-sized bitmap held the title bar
        # plus the game shifted down ~30px, so no library screen matched.
        # Draw the full window, then crop out the client area. In fullscreen
        # or borderless the offsets are 0 and nothing changes.
        win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
        client_x, client_y = win32gui.ClientToScreen(hwnd, (0, 0))
        offset_x = client_x - win_left
        offset_y = client_y - win_top
        full_width = max(win_right - win_left, offset_x + width)
        full_height = max(win_bottom - win_top, offset_y + height)

        hwnd_dc = None
        mfc_dc = None
        save_dc = None
        save_bitmap = None
        try:
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, full_width, full_height)
            save_dc.SelectObject(save_bitmap)

            ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), self.PW_RENDERFULLCONTENT)

            bmpinfo = save_bitmap.GetInfo()
            bmpstr = save_bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr, "raw", "BGRX", 0, 1,
            )
            return image.crop((offset_x, offset_y, offset_x + width, offset_y + height))
        finally:
            # Always release GDI resources, even if a call above raised - leaving
            # any of these held leaks a handle every poll (twice a second) and
            # can eventually exhaust the process's GDI handle quota.
            # Each release on its own: one failing (seen with MK9's
            # fullscreen window, "DeleteDC failed") must not skip the rest.
            for release in (
                lambda: save_bitmap is not None and win32gui.DeleteObject(save_bitmap.GetHandle()),
                lambda: save_dc is not None and save_dc.DeleteDC(),
                lambda: mfc_dc is not None and mfc_dc.DeleteDC(),
                lambda: hwnd_dc is not None and win32gui.ReleaseDC(hwnd, hwnd_dc),
            ):
                try:
                    release()
                except Exception:
                    pass


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


class AutoCapture(CaptureStrategy):
    """PrintWindow first; if it gives nothing or a black frame (an exclusive
    fullscreen DirectX game, as MKX was confirmed to be), grab the screen
    area under the game's window instead, and keep using that once it has
    been needed. Added 2026-10-12 for MK9 (MKKE.exe); MKX (MK10.exe) is exclusive fullscreen too."""

    BLACK_MEAN = 6

    def __init__(self):
        self.window = PrintWindowCapture()
        self.use_screen = False

    @staticmethod
    def _black(img):
        import numpy as np

        return img is None or float(np.asarray(img.convert("L").resize((64, 36))).mean()) < AutoCapture.BLACK_MEAN

    def _screen(self, hwnd):
        with _dpi_context_of(hwnd):
            left, top = win32gui.ClientToScreen(hwnd, (0, 0))
            _, _, width, height = win32gui.GetClientRect(hwnd)
        if width <= 0 or height <= 0:
            return ImageGrab.grab(all_screens=True)
        return ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)

    def grab(self, hwnd):
        if not self.use_screen:
            try:
                img = self.window.grab(hwnd)
            except Exception as exc:
                print(f"Window capture failed ({exc!r}).")
                img = None
            if not self._black(img):
                return img
            self.use_screen = True
            print("Window capture is blank (fullscreen game?); capturing the screen under the window instead.")
        img = self._screen(hwnd)
        return None if img is None else img.convert("RGB")
