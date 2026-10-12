import io
import os

import pytest

import app_paths
import main


def test_prune_keeps_only_the_newest(tmp_path):
    for i in range(7):
        for ext in (".png", ".json"):
            (tmp_path / f"2026101{i}_120000_screen{ext}").write_text("x")
    main.prune_library_misses(str(tmp_path), keep=3)
    remaining = sorted(os.listdir(tmp_path))
    assert len(remaining) == 6
    assert remaining[0].startswith("20261014")


def test_prune_ignores_missing_folder(tmp_path):
    main.prune_library_misses(str(tmp_path / "nope"))


def test_args_defaults():
    args = main.parse_args([])
    assert not (args.stop or args.self_test or args.background or args.dev or args.ignore_focus)
    assert args.speech == "auto"


def test_stop_and_self_test_are_exclusive(capsys):
    with pytest.raises(SystemExit):
        main.parse_args(["--stop", "--self-test"])


def test_log_lines_are_timestamped():
    out = io.StringIO()
    tee = main._TimestampedTee(out)
    tee.write("first\nsec")
    tee.write("ond\n")
    lines = out.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(" first") and lines[1].endswith(" second")
    assert lines[0][:4].isdigit()


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv(app_paths.DATA_DIR_ENV_VAR, str(tmp_path))
    assert app_paths.data_dir() == str(tmp_path)
    assert app_paths.log_file_path() == str(tmp_path / "reader.log")


def test_source_checkout_uses_one_library_folder():
    assert not app_paths.FROZEN
    assert app_paths.library_dirs() == [app_paths.bundled_known_screens_dir()]


def test_nvda_dll_is_where_the_build_expects_it():
    assert os.path.isfile(app_paths.nvda_dll_path())


def test_clean_ocr_line_drops_highlight_ornaments_only():
    from main import clean_ocr_line

    assert clean_ocr_line("—4 ONLINE ARCADE") == "ONLINE ARCADE"
    assert clean_ocr_line("ONLINE ARCADE —4") == "ONLINE ARCADE"
    assert clean_ocr_line("1:36") == "1:36"
    assert clean_ocr_line("16") == "16"
    assert clean_ocr_line("HRS MINS") == "HRS MINS"
    assert clean_ocr_line("MORTAL KOMBAT 3") == "MORTAL KOMBAT 3"


def test_title_matches_tolerates_ocr_noise_but_not_other_titles():
    from main import title_matches

    assert title_matches("MAIN MENU", ["MAIN MENIJ"])
    assert title_matches("PLAY", ["PLAY"])
    assert title_matches("GAME LIBRARY", ["GAME LIBRARV"])
    assert not title_matches("PLAY", ["OPTIONS"])
    assert not title_matches("GAME LIBRARY", [])


def test_reading_quality_separates_menus_from_noise():
    import main
    import menu_ocr

    menu_ocr.load_vocabulary(main.load_library())
    noise = [
        ["WINNING", "Kl", "WINS OUY, WINS", "7", "WINS 7 WINS, 500000 WINS WINS", "100,000", "WINS, 80000"],
        ["LØNÆSI, STREAKS", "OUY", "7", "SAN", "Tuc, WINS, 80000", "700000", "SOOOOO", "100000 gosooo"],
        ["99"],
        ["•OOIUiNS", "—oo ms—"],
    ]
    real = [
        ["MORTAL KOMBAT II", "RESUME", "MOVES LIST", "ON-SCREEN MOVE LIST, OFF"],
        ["KANO", "EXTORTIONIST THIEF KANO LIVES A LIFE OF CRIME AND INJUSTICE"],
        ["Baraka is the leader of the Tarkatans, a nomadic race"],
        ["KOMBAT KARD", "PLAYER STATS", "PLAYER NAME", "VEGASOJ", "TIME PLAYED", "1:36", "HRS", "FAVORITE REPLAYS", "16"],
    ]
    for texts in noise:
        assert not main.same_as_spoken_quality(texts), texts
    for texts in real:
        assert main.same_as_spoken_quality(texts), texts


def test_grid_selection_names_the_boxed_cell():
    from PIL import Image, ImageDraw

    import main

    grid = {"color_min": [0, 151, 0], "color_max": [109, 255, 109], "ring": 10,
            "cells": [{"name": "KANO", "bbox": [595, 178, 840, 526]}, {"name": "RAIDEN", "bbox": [600, 540, 835, 870]}]}
    full = Image.new("RGB", (1920, 1080), (90, 90, 90))
    assert main.grid_selection(full, grid) is None
    ImageDraw.Draw(full).rectangle((594, 539, 836, 871), outline=(0, 200, 0), width=8)
    assert main.grid_selection(full, grid) == "RAIDEN"
