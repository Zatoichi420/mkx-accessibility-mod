"""
F2-capture and library-miss logging helpers. Shared verbatim across the
MK accessibility readers - never game-specific. Paths are passed in by
the caller rather than hardcoded, since each game repo keeps its own
known_screens/ and library_misses/.
"""

import json
import os
import re
import time


def slugify(text, max_words=6):
    words = re.findall(r"[a-z0-9]+", text.lower())[:max_words]
    return "_".join(words) if words else "blank_screen"


def save_known_screen(img, lines, highlighted_text, known_screens_dir):
    """Save a screenshot + its live OCR text into known_screens_dir as a
    *candidate* library entry. It won't be used for recognition/speech by
    screen_library.py until a canonical_text field is added by hand after
    reviewing the saved image (raw OCR text is not trusted for speech)."""
    os.makedirs(known_screens_dir, exist_ok=True)
    screen_texts = [l["text"] for l in lines]
    slug = slugify(" ".join(screen_texts))

    name = slug
    suffix = 2
    while os.path.exists(os.path.join(known_screens_dir, name + ".png")):
        name = f"{slug}_{suffix}"
        suffix += 1

    img.convert("RGB").save(os.path.join(known_screens_dir, name + ".png"))
    data = {
        "screen_id": name,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "live_capture",
        "canonical_text": None,  # needs hand verification before this entry is used for recognition
        "highlighted": highlighted_text,
        "capture_size": list(img.size),  # validated against the live frame before trusting stored bboxes - see find_highlighted_text_from_entry
        "ocr_lines_raw": [{"text": l["text"], "bbox": l["bbox"]} for l in lines],
    }
    with open(os.path.join(known_screens_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return name


def log_library_miss(img, screen_texts, library_misses_dir):
    """A screen was stably read via live OCR because it didn't match
    anything in the library. Save it so it can be reviewed and folded into
    known_screens/ (with hand-verified canonical_text) later."""
    os.makedirs(library_misses_dir, exist_ok=True)
    slug = slugify(" ".join(screen_texts)) if screen_texts else "blank_screen"
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_{slug}"
    img.convert("RGB").save(os.path.join(library_misses_dir, name + ".png"))
    with open(os.path.join(library_misses_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"ocr_text": screen_texts}, f, indent=2)
