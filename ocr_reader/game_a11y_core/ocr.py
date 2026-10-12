"""
Live OCR via Windows' built-in OCR engine (winsdk). Shared verbatim
across the MK accessibility readers - never game-specific.

2026-10: the engine is now created once and reused instead of once per
poll, falls back to English when the user's own profile languages have no
OCR support installed, and get_ocr_engine()/ocr_language_tag() let a caller
find out (and tell the user) that OCR isn't available at all. Previously
ocr_image() just returned [] in that case, so every unrecognised screen
was silently skipped with nothing to say why.
"""

import io

from PIL import Image
from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

FALLBACK_LANGUAGE_TAG = "en-US"

_engine = None
_engine_checked = False


def get_ocr_engine():
    """The OCR engine, or None if Windows has no OCR language installed
    that we can use. Cached after the first call (installing a language
    pack takes effect on the reader's next start)."""
    global _engine, _engine_checked
    if not _engine_checked:
        _engine_checked = True
        _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            try:
                language = Language(FALLBACK_LANGUAGE_TAG)
                if OcrEngine.is_language_supported(language):
                    _engine = OcrEngine.try_create_from_language(language)
            except Exception as exc:
                print(f"OCR fallback to {FALLBACK_LANGUAGE_TAG} failed: {exc!r}")
    return _engine


def ocr_language_tag():
    engine = get_ocr_engine()
    if engine is None:
        return None
    try:
        return engine.recognizer_language.language_tag
    except Exception:
        return "unknown"


async def ocr_image(img: Image.Image):
    engine = get_ocr_engine()
    if engine is None:
        return []

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        text = line.text.strip()
        if not text or not line.words:
            continue
        xs = [w.bounding_rect.x for w in line.words]
        ys = [w.bounding_rect.y for w in line.words]
        rights = [w.bounding_rect.x + w.bounding_rect.width for w in line.words]
        bottoms = [w.bounding_rect.y + w.bounding_rect.height for w in line.words]
        bbox = (min(xs), min(ys), max(rights), max(bottoms))
        lines.append({"text": text, "bbox": bbox, "y": min(ys), "x": min(xs)})
    lines.sort(key=lambda l: (l["y"], l["x"]))
    return lines
