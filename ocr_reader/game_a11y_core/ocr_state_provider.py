"""
Wraps the existing capture -> library-match -> live-OCR-fallback pipeline
behind the StateProvider interface (state_provider.py).

Added 2026-09-12 as part of the Phase 0 shared-core extraction. Not yet
wired into either game's main poll loop - both main.py files still speak
directly from their own library/OCR results, exactly as before, so this
class changes no runtime behavior yet. It exists so a memory-reading
backend (once one lands - see each project's PROGRESS.md) has a peer
already speaking the same ScreenState language to cross-check against,
per the seam's stated purpose in state_provider.py, without forcing a
rewrite of the tested poll loop in the same change that introduced it.
"""

import asyncio

from .highlight import HighlightCalibration, find_highlighted_text, find_highlighted_text_from_entry
from .ocr import ocr_image
from .screen_library import ScreenLibrary
from .state_provider import ScreenState, StateProvider


class OcrStateProvider(StateProvider):
    def __init__(self, library: ScreenLibrary, calibration: HighlightCalibration, capture_strategy):
        self.library = library
        self.calibration = calibration
        self.capture_strategy = capture_strategy
        self.hwnd = None  # set by the caller once a window handle is known

    def get_state(self):
        if self.hwnd is None:
            return None
        img = self.capture_strategy.grab(self.hwnd)
        if img is None:
            return None

        match_result = self.library.match(img)
        if match_result:
            entry, _distance = match_result
            items = list(entry["canonical_text"])
            highlighted = find_highlighted_text_from_entry(img, entry, self.calibration)
            selected_index = items.index(highlighted) if highlighted in items else -1
            return ScreenState(
                screen_id=entry["screen_id"],
                items=items,
                selected_index=selected_index,
                source="ocr-library",
            )

        lines = asyncio.run(ocr_image(img))
        screen_texts = [l["text"] for l in lines]
        if not screen_texts:
            return None
        highlighted = find_highlighted_text(img, lines, self.calibration)
        selected_index = screen_texts.index(highlighted) if highlighted in screen_texts else -1
        return ScreenState(
            screen_id="ocr:" + "|".join(screen_texts)[:80],
            items=screen_texts,
            selected_index=selected_index,
            source="ocr-live",
        )

    def close(self):
        pass
