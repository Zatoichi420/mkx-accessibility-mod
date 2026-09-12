"""
Live OCR via Windows' built-in OCR engine (winsdk). Shared verbatim
across the MK accessibility readers - never game-specific.
"""

import io

from PIL import Image
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream


async def ocr_image(img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return []

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
