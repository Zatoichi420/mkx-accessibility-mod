"""The screen library is what decides which pre-verified text gets spoken,
so a wrong match means confidently reading the wrong screen. These replay
the library's own screenshots through the matcher - the same offline check
PROGRESS.md section 5.5 did by hand, now run on every build."""

import glob
import itertools
import json
import os
import shutil

import pytest
from PIL import Image

import app_paths
from game_a11y_core.screen_library import MATCH_DISTANCE_THRESHOLD, ScreenLibrary, compute_dhash, hamming_distance

KNOWN_SCREENS = app_paths.bundled_known_screens_dir()


def _verified_json_files():
    files = []
    for path in sorted(glob.glob(os.path.join(KNOWN_SCREENS, "*.json"))):
        with open(path, encoding="utf-8") as f:
            if json.load(f).get("canonical_text"):
                files.append(path)
    return files


@pytest.fixture(scope="module")
def library():
    return ScreenLibrary(KNOWN_SCREENS)


def _synthetic_library(tmp_path):
    """Two made-up screens with clearly different layouts."""
    from PIL import ImageDraw

    for name, boxes in (("menu_a", [(100, 100, 700, 200), (100, 300, 700, 400)]),
                        ("menu_b", [(1000, 600, 1800, 700), (1200, 100, 1800, 300)])):
        img = Image.new("RGB", (1920, 1080), (20, 20, 20))
        draw = ImageDraw.Draw(img)
        for b in boxes:
            draw.rectangle(b, fill=(230, 210, 120))
        img.save(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.json").write_text(json.dumps({"screen_id": name, "canonical_text": [name.upper()],
                                                           "capture_size": [1920, 1080]}), encoding="utf-8")
    return ScreenLibrary(str(tmp_path))


def test_every_verified_entry_loads(library):
    assert len(library.entries) == len(_verified_json_files())


def test_every_entry_recognises_its_own_screenshot(library):
    for entry in library.entries:
        with Image.open(entry["png_path"]) as img:
            result = library.match(img.convert("RGB"))
        assert result is not None, f"{entry['screen_id']} didn't match its own screenshot"
        assert result[0]["screen_id"] == entry["screen_id"]
        assert result[1] == 0


def test_no_two_screens_are_confusable(library):
    images = {e["screen_id"]: Image.open(e["png_path"]).convert("RGB") for e in library.entries}
    for a, b in itertools.permutations(library.entries, 2):
        frame = images[b["screen_id"]]
        if a["roi"] and a["capture_size"] and tuple(a["capture_size"]) != frame.size:
            continue
        distance = hamming_distance(compute_dhash(frame, a["roi"]), a["hash"])
        assert distance > MATCH_DISTANCE_THRESHOLD, f"{b['screen_id']} would be read as {a['screen_id']} (distance {distance})"


def test_synthetic_screens_match_themselves_and_not_each_other(tmp_path):
    lib = _synthetic_library(tmp_path)
    assert len(lib.entries) == 2
    for entry in lib.entries:
        with Image.open(entry["png_path"]) as img:
            assert lib.match(img.convert("RGB"))[0]["screen_id"] == entry["screen_id"]
    a, b = lib.entries
    assert hamming_distance(a["hash"], b["hash"]) > MATCH_DISTANCE_THRESHOLD


def test_add_directory_loads_a_second_folder(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(); second.mkdir()
    _synthetic_library(first)
    lib = ScreenLibrary(str(first))
    (second / "extra.json").write_text(json.dumps({"screen_id": "extra", "canonical_text": ["EXTRA"]}), encoding="utf-8")
    shutil.copy(first / "menu_a.png", second / "extra.png")
    lib.add_directory(str(second))
    assert len(lib.entries) == 3


def test_missing_directory_is_ignored(tmp_path):
    lib = ScreenLibrary(str(tmp_path / "does-not-exist"))
    lib.add_directory(str(tmp_path / "also-missing"))
    assert lib.entries == []
