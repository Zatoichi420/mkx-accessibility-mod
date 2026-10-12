"""
`mkx-access --self-test`: the "is this working?" check, run from the
Start menu's "Check accessibility reader" shortcut.

Reports through a standard Windows message box, which every screen reader
reads out on its own. When neither NVDA nor JAWS is running, the summary is
also spoken through the Windows voice first - a message box is silent with no screen
reader at all, and "no speech" is exactly the problem this check exists to
diagnose. --quiet skips both (the CI smoke test uses that plus
--report-file).

Exit code 1 only for problems that make the reader useless or wrong: no
voice at all, or a screen library that failed to load or no longer
recognises its own screens. Missing text recognition is a warning - known
screens still work without it.
"""

import ctypes
import json
import os

import app_paths
from version import __version__

MB_ICONINFORMATION = 0x40
MB_ICONWARNING = 0x30
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000


def _shipped_library_count():
    """Verified screens shipped with the reader. A game whose library is
    still empty (everything read by live OCR) is not a broken install."""
    directory = app_paths.bundled_known_screens_dir()
    count = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if name.endswith(".json") and os.path.isfile(os.path.join(directory, name[:-5] + ".png")):
            try:
                with open(os.path.join(directory, name), encoding="utf-8") as f:
                    if json.load(f).get("canonical_text"):
                        count += 1
            except (OSError, ValueError):
                count += 1  # unreadable but shipped: the load check should flag it
    return count


def _check_library():
    from PIL import Image

    from main import load_library

    library = load_library()
    mismatches = []
    for entry in library.entries:
        try:
            with Image.open(entry["png_path"]) as img:
                result = library.match(img.convert("RGB"))
        except Exception as exc:
            mismatches.append(f"{entry['screen_id']} ({exc!r})")
            continue
        if result is None or result[0]["screen_id"] != entry["screen_id"]:
            got = result[0]["screen_id"] if result else "nothing"
            mismatches.append(f"{entry['screen_id']} matched {got}")
    return len(library.entries), mismatches


def _autostart_command():
    import winreg

    from main import AUTOSTART_VALUE_NAME

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return value
    except OSError:
        return None


def run_self_test(args, speaker):
    from game_a11y_core.lifecycle import find_window_for_process, named_mutex_exists
    from game_a11y_core.ocr import get_ocr_engine, ocr_language_tag
    from main import INSTANCE_MUTEX_NAME, PROCESS_NAME

    problems = []
    warnings = []
    report = {"version": __version__}

    voice = speaker.active_backend_name()
    report["speech"] = voice
    if voice is None:
        problems.append("No voice is available: neither NVDA nor JAWS is running, and the Windows voice couldn't be started.")

    report["nvda_dll_present"] = os.path.isfile(app_paths.nvda_dll_path())
    if not report["nvda_dll_present"]:
        problems.append("The NVDA connection file is missing from the install folder. Reinstall the reader.")

    try:
        ocr_ok = get_ocr_engine() is not None
        report["ocr_language"] = ocr_language_tag() if ocr_ok else None
    except Exception as exc:
        ocr_ok = False
        report["ocr_language"] = None
        report["ocr_error"] = repr(exc)
    if not ocr_ok:
        warnings.append("Windows text recognition is not installed, so only known screens can be read. See the read me.")

    try:
        count, mismatches = _check_library()
    except Exception as exc:
        count, mismatches = 0, [repr(exc)]
    report["library_entries"] = count
    report["library_mismatches"] = mismatches
    shipped = _shipped_library_count()
    report["library_shipped"] = shipped
    if count == 0 and shipped:
        problems.append("The screen library didn't load. Reinstall the reader.")
    elif mismatches:
        problems.append(f"{len(mismatches)} known screens failed their recognition check.")

    report["reader_running"] = named_mutex_exists(INSTANCE_MUTEX_NAME)
    report["game_running"] = find_window_for_process(PROCESS_NAME) is not None
    autostart = _autostart_command()
    report["autostart"] = autostart
    report["log_file"] = app_paths.log_file_path()
    report["problems"] = problems
    report["warnings"] = warnings

    lines = ["Self-test passed." if not problems else "Self-test found a problem."]
    lines += problems + warnings
    lines.append(f"Voice: {voice or 'none'}.")
    lines.append(f"Text recognition: {report['ocr_language'] or 'not installed'}.")
    lines.append(f"Known screens: {count}.")
    lines.append("Reader: running." if report["reader_running"] else "Reader: not running. Start it from the Start menu.")
    lines.append("Game: running." if report["game_running"] else "Game: not running.")
    lines.append("Start at sign-in: on." if autostart else "Start at sign-in: off.")
    lines.append(f"Version {__version__}. Log file: {report['log_file']}")
    summary = "\n".join(lines)
    print(summary.replace("\n", " | "))

    if args.report_file:
        with open(args.report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    if not args.quiet:
        # NVDA and JAWS read the message box themselves; only a separate
        # voice (or none) needs the summary spoken as well.
        if voice not in ("NVDA", "JAWS"):
            speaker.speak(" ".join(lines[:-1]))
        flags = (MB_ICONWARNING if problems or warnings else MB_ICONINFORMATION) | MB_SETFOREGROUND | MB_TOPMOST
        ctypes.windll.user32.MessageBoxW(None, summary, "Mortal Kombat X accessibility reader", flags)
        speaker.wait_until_done(2)

    return 1 if problems else 0
