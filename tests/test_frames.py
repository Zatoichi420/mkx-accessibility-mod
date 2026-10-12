"""Frame normalisation: any 16:9 capture becomes the reference size, so
library images, bboxes and regions share one coordinate space."""

from PIL import Image

import frames


def test_normalize_rescales_any_16_9_size_to_reference():
    for size in [(1920, 1080), (2560, 1440), (1600, 900), (1280, 720), (960, 540), (3840, 2160)]:
        assert frames.normalize(Image.new("RGB", size)).size == frames.REFERENCE_SIZE


def test_library_view_is_whole_frame_for_mkx():
    full = frames.normalize(Image.new("RGB", (1280, 720)))
    assert frames.library_view(full).size == frames.REFERENCE_SIZE


def test_aspect_ratio_check():
    assert frames.aspect_ratio_ok((1920, 1080))
    assert frames.aspect_ratio_ok((1366, 768))
    assert not frames.aspect_ratio_ok((1280, 1024))
