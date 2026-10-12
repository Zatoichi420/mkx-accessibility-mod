"""Reader.track_screen end to end, with speech captured and OCR faked.

Added 2026-10-11 after a live test found every library-matched screen
crashing (a function-local import shadowed the module) - nothing exercised
track_screen itself until then."""

import os
import types

import pytest
from PIL import Image

import frames
import main
import menu_ocr


class Recorder:
    def __init__(self):
        self.said = []

    def speak(self, text, interrupt=True):
        self.said.append(text)
        return True

    def wait_until_done(self, timeout_seconds=10):
        pass


@pytest.fixture
def reader(tmp_path, monkeypatch):
    monkeypatch.setenv("MKX_ACCESS_DATA_DIR", str(tmp_path))
    args = types.SimpleNamespace(ignore_focus=True, dev=False)
    r = main.Reader(args, Recorder(), main.load_library(), None)
    return r


def test_library_screen_is_spoken_once_after_settling(reader, monkeypatch, tmp_path):
    from PIL import ImageDraw

    from game_a11y_core.screen_library import ScreenLibrary

    img = Image.new("RGB", frames.REFERENCE_SIZE, (20, 20, 20))
    ImageDraw.Draw(img).rectangle((100, 100, 900, 300), fill=(230, 210, 120))
    img.save(tmp_path / "main_menu.png")
    (tmp_path / "main_menu.json").write_text(
        '{"screen_id": "main_menu", "canonical_text": ["MAIN MENU", "STORY", "LADDER"]}', encoding="utf-8")
    reader.library = ScreenLibrary(str(tmp_path))
    monkeypatch.setattr(main.Reader, "verified_match", lambda self, full, view: self.library.match(view))
    view = frames.library_view(img)
    for _ in range(4):
        reader.track_screen(img, view, reader.verified_match(img, view))
    assert reader.speaker.said == ["MAIN MENU. STORY. LADDER"]


def _lines(*texts, highlighted=None):
    out = []
    for i, t in enumerate(texts):
        out.append({"text": t, "bbox": (100, 200 + 60 * i, 400, 230 + 60 * i), "x": 100, "y": 200 + 60 * i, "parts": []})
    return out


def test_unknown_menu_moving_highlight_says_only_the_item(reader, monkeypatch):
    items = ["PAUSE", "RESUME", "MOVES LIST", "CONTROLS", "QUIT GAME"]
    state = {"hl": "RESUME"}
    monkeypatch.setattr(menu_ocr, "read_menu_text", lambda img, clean=None, vocabulary=None: _lines(*items))
    monkeypatch.setattr(menu_ocr, "find_highlight", lambda img, lines, cal, vocabulary=None: state["hl"])
    full = Image.new("RGB", frames.REFERENCE_SIZE)
    view = frames.library_view(full)
    for _ in range(3):
        reader.track_screen(full, view, None)
    assert reader.speaker.said == ["PAUSE. RESUME. MOVES LIST. CONTROLS. QUIT GAME. Selected: RESUME"]
    state["hl"] = "CONTROLS"
    for _ in range(3):
        reader.track_screen(full, view, None)
    assert reader.speaker.said[-1] == "CONTROLS"
    assert len(reader.speaker.said) == 2


def test_screen_that_never_settles_goes_quiet(reader, monkeypatch):
    counter = {"n": 0}

    def noisy(img, clean=None, vocabulary=None):
        counter["n"] += 1
        return _lines(f"00 WINS {counter['n']}", "FIGHT")

    monkeypatch.setattr(menu_ocr, "read_menu_text", noisy)
    monkeypatch.setattr(menu_ocr, "find_highlight", lambda *a, **k: None)
    monkeypatch.setattr(main.Reader, "unknown_screen_lines", lambda self, full: (noisy(full), False))
    full = Image.new("RGB", frames.REFERENCE_SIZE)
    view = frames.library_view(full)
    for _ in range(80):
        reader.track_screen(full, view, None)
    assert len(reader.speaker.said) <= 1
