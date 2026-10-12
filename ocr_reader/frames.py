"""
Turning a raw capture into the frames the reader works with.

Every capture is rescaled to REFERENCE_SIZE, so library entries, bboxes
and regions are in one coordinate space whatever the game's resolution.
For MKX the library view is the whole frame (LIBRARY_BOX); the Legacy
Kollection reader, where this module comes from, crops a top-left box for
compatibility with screenshots taken under an old DPI bug.
"""

import ctypes

from PIL import Image

REFERENCE_SIZE = (1920, 1080)
LIBRARY_BOX = (0, 0, 1920, 1080)
ASPECT_TOLERANCE = 0.02


def enable_dpi_awareness():
    """Call once, first thing, before any window or GDI calls. Returns a
    description of what was enabled, for the log."""
    attempts = (
        ("per-monitor v2", lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))),
        ("per-monitor", lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0),
        ("system", lambda: ctypes.windll.user32.SetProcessDPIAware()),
    )
    for name, attempt in attempts:
        try:
            if attempt():
                return name
        except Exception:
            continue
    return "unavailable"


def aspect_ratio_ok(size):
    width, height = size
    if not width or not height:
        return False
    expected = REFERENCE_SIZE[0] / REFERENCE_SIZE[1]
    return abs((width / height) / expected - 1) <= ASPECT_TOLERANCE


def normalize(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    if img.size != REFERENCE_SIZE:
        img = img.resize(REFERENCE_SIZE, Image.LANCZOS)
    return img


def library_view(full: Image.Image) -> Image.Image:
    return full.crop(LIBRARY_BOX)
