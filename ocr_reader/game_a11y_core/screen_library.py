"""
Reference-library screen recognition ("the hook").

Loads known_screens/ (each a hand-verified screenshot + canonical_text)
and, given a freshly captured frame, answers "have we seen this exact
screen before, and if so what should be spoken for it?" via a perceptual
image hash (dHash) instead of re-running OCR every time.

Caveat worth remembering if match quality is ever poor: dHash resizes
the whole input image to a small fixed grid, so it implicitly assumes the
captured frame and the library image are framed the same way (same crop/
aspect ratio, no letterboxing on one but not the other). Live captures
(full game window) and web-sourced reference images (often tightly
cropped) may not agree on framing for the same on-screen content -
if this shows up as matches that should hit but don't, cropping both to
a consistent region before hashing is the first thing to try.

**Confirmed instance of exactly that problem**, from Legacy Kollection:
the launcher's own main menu renders a rotating/ambient background image
behind the static PLAY/THE KRYPT/KOMBAT KARD text that has nothing to do
with menu state - five captures of the identical menu, taken at different
moments, hashed 39-66 bits apart (out of 256) purely from background-art
differences, versus 3-7 bits apart once cropped to the static left-hand
text column. This is why entries can carry an optional "roi"
([x1,y1,x2,y2]) in their JSON: the hash (both stored and at match time) is
computed only within that box. Omit it to hash the full frame -
appropriate for a screen that renders one flat scene with no separate
ambient layer (e.g. the classic/PS1 emulated screens).
"""

import json
import os

import numpy as np
from PIL import Image

# dHash grid size: (HASH_SIZE+1) x HASH_SIZE pixels -> HASH_SIZE*HASH_SIZE bits.
HASH_SIZE = 16

# Hamming-distance threshold (out of HASH_SIZE*HASH_SIZE bits) below which we
# trust a match enough to speak its canonical_text instead of falling back
# to live OCR. Kept conservative on purpose: a missed match just costs a
# live-OCR read (today's behavior); a wrong match speaks the wrong screen's
# text, which is worse.
MATCH_DISTANCE_THRESHOLD = 24


def compute_dhash(img: Image.Image, roi=None) -> int:
    if roi is not None:
        img = img.crop(tuple(roi))
    small = img.convert("L").resize((HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS)
    pixels = np.asarray(small, dtype=np.int16)
    diff = pixels[:, 1:] > pixels[:, :-1]
    bits = diff.flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class ScreenLibrary:
    def __init__(self, directory):
        """`directory` is required (each game's own known_screens/ path) -
        this class used to default it to a path computed from its own
        __file__, which broke the moment it became a shared module vendored
        into more than one project's ocr_reader/ folder."""
        self.entries = []
        self._load(directory)

    def _load(self, directory):
        if not os.path.isdir(directory):
            return
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            json_path = os.path.join(directory, name)
            png_path = os.path.join(directory, name[:-5] + ".png")
            if not os.path.isfile(png_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                canonical_text = data.get("canonical_text")
                if not canonical_text:
                    continue  # not yet verified - skip rather than risk speaking raw/blank OCR
                if any(not isinstance(t, str) or not t.strip() for t in canonical_text):
                    # A blank/whitespace-only element joins into "", which is
                    # falsy just like an empty list - the entry would load
                    # "successfully" but never actually be spoken, silently,
                    # forever. Treat it the same as missing canonical_text.
                    print(f"Skipping library entry '{name}': canonical_text has a blank line.")
                    continue
                roi = data.get("roi")
                img = Image.open(png_path)
                img_hash = compute_dhash(img, roi)
            except Exception as exc:
                print(f"Skipping library entry '{name}': failed to load ({exc!r}).")
                continue
            self.entries.append({
                "screen_id": data.get("screen_id", name[:-5]),
                "canonical_text": canonical_text,
                "notes": data.get("notes", ""),
                "roi": roi,
                "hash": img_hash,
                "capture_size": data.get("capture_size"),
                "ocr_lines_raw": data.get("ocr_lines_raw", []),
            })

    def match(self, frame: Image.Image, max_distance=MATCH_DISTANCE_THRESHOLD):
        if not self.entries:
            return None
        best = None
        best_distance = None
        # Each entry may hash a different region (its own roi), so the
        # frame's hash depends on which roi is used - but many entries
        # share the same roi (or no roi), so cache by roi within this call
        # rather than recomputing an identical crop+hash for each of them.
        # This runs twice a second and scales with library size, so it's
        # worth avoiding the redundant work as the library grows.
        hash_cache = {}
        for entry in self.entries:
            if entry["roi"] and entry["capture_size"] and tuple(entry["capture_size"]) != tuple(frame.size):
                # This entry's roi is an absolute-pixel box calibrated for a
                # specific frame size. PIL's crop() doesn't raise on an
                # out-of-bounds box, it silently returns whatever pixels are
                # there - so cropping it against a differently-sized live
                # frame wouldn't just miss (safe, falls back to OCR), it
                # could hash the wrong region and coincidentally land within
                # the match threshold, confidently speaking the wrong
                # screen's canonical_text. Skip this entry as a candidate
                # rather than risk that; entries with no roi hash the whole
                # frame, which dHash already tolerates a resize of.
                continue
            roi_key = tuple(entry["roi"]) if entry["roi"] else None
            frame_hash = hash_cache.get(roi_key)
            if frame_hash is None:
                frame_hash = compute_dhash(frame, entry["roi"])
                hash_cache[roi_key] = frame_hash
            distance = hamming_distance(frame_hash, entry["hash"])
            if best_distance is None or distance < best_distance:
                best = entry
                best_distance = distance
        if best is not None and best_distance <= max_distance:
            return best, best_distance
        return None
