"""
Selection-highlight detection by pixel color sampling. The *logic* here
is shared verbatim across the MK accessibility readers, but the actual
threshold values are real per-game calibration, not generic defaults -
see HighlightCalibration. As of 2026-09-12, Legacy Kollection's values
were sampled against that game's real cyan/gold menu style; MKX's are
still an uncalibrated placeholder carried over from Legacy Kollection
(MKX's Scaleform UI hasn't been sampled - see that project's PROGRESS.md).
Never assume a HighlightCalibration copied from one game is valid for
another without sampling that game's own menu pixels.
"""

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class HighlightCalibration:
    brightness_threshold: int  # sum of R+G+B, to isolate text pixels from dark background
    blue_minus_red_threshold: int  # margin required to call it "selected", avoids borderline noise


def is_line_highlighted(img_array, bbox, calibration: HighlightCalibration):
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    pad = 4
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(img_array.shape[1], x2 + pad)
    y2 = min(img_array.shape[0], y2 + pad)
    crop = img_array[y1:y2, x1:x2].reshape(-1, 3)
    if crop.size == 0:
        return None
    brightness = crop.sum(axis=1)
    bright_pixels = crop[brightness > calibration.brightness_threshold]
    if len(bright_pixels) < 10:
        return None
    mean_r = bright_pixels[:, 0].mean()
    mean_b = bright_pixels[:, 2].mean()
    return (mean_b - mean_r) > calibration.blue_minus_red_threshold


def find_highlighted_text(img: Image.Image, lines, calibration: HighlightCalibration):
    img_array = np.array(img.convert("RGB"))
    for line in lines:
        if is_line_highlighted(img_array, line["bbox"], calibration):
            return line["text"]
    return None


def find_highlighted_text_from_entry(img: Image.Image, entry, calibration: HighlightCalibration):
    """Same idea as find_highlighted_text, but sampling colors at the
    reference library's stored bbox positions instead of running live OCR -
    works because highlight detection is pure pixel-color sampling, not
    text recognition. Skips any stored line missing a bbox, or explicitly
    flagged "skip_highlight" (e.g. a decorative/logo line with an
    unconfirmed, estimated bbox not safe to sample)."""
    capture_size = entry.get("capture_size")
    if capture_size and tuple(capture_size) != img.size:
        # The stored bboxes are absolute pixels from whatever window size
        # was active when this screen was captured. Screen *recognition*
        # (dHash) tolerates a resized window because it resizes to a fixed
        # small grid, but sampling a pixel-color bbox at the wrong scale
        # would silently check the wrong region instead of the highlight -
        # skip rather than risk a wrong/missed highlight read. Entries
        # captured before this field existed have no capture_size and are
        # sampled as before (can't validate what wasn't recorded).
        return None
    img_array = np.array(img.convert("RGB"))
    for line in entry.get("ocr_lines_raw", []):
        bbox = line.get("bbox")
        text = line.get("text")
        if not bbox or not text or line.get("skip_highlight"):
            continue
        if is_line_highlighted(img_array, bbox, calibration):
            return text
    return None
