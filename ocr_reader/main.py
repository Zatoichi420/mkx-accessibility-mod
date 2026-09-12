"""
Mortal Kombat X accessibility reader (Phase 1 baseline).

Continuously captures the game window and speaks its contents via NVDA.
On each poll, first tries to recognize the current screen against the
hand-verified reference library (known_screens/, matched by perceptual
image hash - see game_a11y_core/screen_library.py, "the hook"): a match
speaks that screen's pre-verified canonical_text instead of live OCR,
which is both faster and immune to OCR failure modes on stylized game
fonts.

If no library entry matches, falls back to live OCR as a best-effort read,
and logs the miss to library_misses/ so it can be reviewed and folded into
the library later.

This was originally ported near-verbatim from the MK Legacy Kollection
accessibility project's ocr_reader/main.py. As of 2026-09-12 the parts
that were never actually game-specific - capture, live OCR, NVDA speech,
the screen library, process lifecycle/locking, hotkeys, and the
StateProvider seam - live in game_a11y_core/, shared with that sister
project (and MK9 eventually) via mk-a11y-core; see that repo's README for
how it's kept in sync. Only the game-specific bits (process name, capture
strategy, highlight-color calibration, and this project's own memory-read
provider) stay here.

This project's PROGRESS.md has a memory-read recipe worked out: reading
MKX's UI state directly out of process memory (a PDB shipped with the
retail build named real classes like UIMainMenuScreen and
UIGridSelection), which lets memory_provider.py be exact and instant
instead of guessing from pixels. The OCR/library baseline below is what
runs for any screen memory_provider.py hasn't been taught yet.

known_screens/ starts empty for this project - nobody has captured and
hand-verified any MKX screens yet (see PROGRESS.md's resume point). Until
it's populated, every screen falls back to live OCR and gets logged to
library_misses/ for review.

F10 toggles the reader on/off without closing it (e.g. to go quiet while a
sighted friend plays two-player, or to stop narration without losing your
place in the game) - it always announces the toggle itself even while
"off", so silence never means "is this even running?". F9 forces an
immediate re-read of whatever's on screen right now (fallback for screens/
dialogs that don't fit the above). F2 captures the current screen
(screenshot + live OCR) into known_screens/ as a *candidate* new library
entry - it still needs a canonical_text field hand-verified from the image
before screen_library.py will treat it as trustworthy.
"""

import asyncio
import os
import re
import time

import win32gui

from game_a11y_core.capture import DesktopGrabCapture
from game_a11y_core.highlight import HighlightCalibration, find_highlighted_text, find_highlighted_text_from_entry
from game_a11y_core.hotkeys import HotkeyConfig, was_key_pressed_since_last_check
from game_a11y_core.lifecycle import acquire_single_instance_lock, find_window_for_process, release_single_instance_lock
from game_a11y_core.nvda_speaker import wait_for_nvda
from game_a11y_core.ocr import ocr_image
from game_a11y_core.screen_capture_tools import log_library_miss, save_known_screen
from game_a11y_core.screen_library import ScreenLibrary

from memory_provider import MemoryStateProvider

# Confirmed live 2026-09-08 (see PROGRESS.md): MK10.exe is the actual
# running game process, not a launcher/stub - MKXLauncher.exe hands off to
# it directly and doesn't stay running.
PROCESS_NAME = "MK10.exe"
POLL_INTERVAL_SECONDS = 0.5
HOTKEYS = HotkeyConfig(reread_vk=0x78, capture_vk=0x71, toggle_vk=0x79)  # F9, F2, F10
# When auto-started alongside the game (see run_reader.bat/start_reader.vbs),
# there's no terminal to Ctrl+C from, so exit on our own once the game window
# has been gone this long (covers "player closed the game").
EXIT_AFTER_WINDOW_GONE_SECONDS = 120
STABLE_POLLS_REQUIRED = 2  # OCR/highlight can be slightly noisy frame-to-frame; require it to settle before speaking
# If OCR is noisy enough to never repeat two polls identically for an
# uncatalogued screen, "stabilized" alone could wait forever and the screen
# never gets announced. Once we've seen this many consecutive "something's
# different" polls without it settling, speak the latest OCR reading once as
# best-effort rather than staying silent - library matches don't need this,
# they're pre-verified text, not noisy live OCR.
FORCE_SPEAK_AFTER_UNSTABLE_POLLS = 8
# A single bad poll is tolerated (see the try/except in the main loop), but
# if failures never stop (not just "the window is gone", which has its own
# handling above), give up and exit so a future relaunch's duplicate-instance
# check can start a fresh, healthy reader instead of this one retrying
# forever as a zombie that blocks it from doing so.
EXIT_AFTER_CONSECUTIVE_POLL_FAILURES = 240

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NVDA_DLL_PATH = os.path.join(SCRIPT_DIR, "game_a11y_core", "nvda_controller_client", "x64", "nvdaControllerClient.dll")
KNOWN_SCREENS_DIR = os.path.join(SCRIPT_DIR, "known_screens")
LIBRARY_MISSES_DIR = os.path.join(SCRIPT_DIR, "library_misses")
LOCK_FILE_PATH = os.path.join(SCRIPT_DIR, "reader.lock")

CAPTURE = DesktopGrabCapture()

# NEEDS_CALIBRATION: these values were copied from the MK Legacy Kollection
# project (calibrated for that launcher's cyan-selected/gold-unselected
# style) purely as a starting point - MKX's Scaleform UI almost certainly
# uses a different highlight color scheme and has NOT been sampled yet.
# Capture a real MKX menu screenshot, sample the selected vs. unselected
# text pixel colors, and update these before trusting highlight detection
# in this game. Until then, is_line_highlighted() will likely just never
# fire (safe failure mode: no highlight spoken, not a wrong one).
HIGHLIGHT_CALIBRATION = HighlightCalibration(brightness_threshold=300, blue_minus_red_threshold=30)


def humanize_screen_id(screen_id):
    """"UIMainMenuScreen" -> "Main Menu". Only used for the screen-level
    announcement; the memory provider's own screen_labels.json supplies
    the actual item text."""
    name = re.sub(r"^UI", "", screen_id)
    name = re.sub(r"Screen$", "", name)
    name = re.sub(r"(?<!^)(?=[A-Z])", " ", name).strip()
    return name or screen_id


def main():
    print("MKX accessibility reader starting...")

    if not acquire_single_instance_lock(LOCK_FILE_PATH):
        print("Another reader instance is already running; exiting.")
        return

    try:
        speaker = wait_for_nvda(NVDA_DLL_PATH)
        print("NVDA connection OK.")

        library = ScreenLibrary(KNOWN_SCREENS_DIR)
        print(f"Loaded {len(library.entries)} verified screens into the recognition library.")

        # Primary path for screens with a verified memory-read label
        # (screen_labels.json): exact selected index straight from the
        # game's own UE3 object graph, no screenshot or OCR involved.
        # Falls through to the library/OCR path below for anything not
        # yet mapped there - see PROGRESS.md's memory-read recipe.
        memory_provider = MemoryStateProvider()

        speaker.speak("Accessibility reader ready.")

        hwnd = None
        hwnd_ever_found = False
        window_missing_since = None
        consecutive_poll_failures = 0
        reader_enabled = True

        # screen_key identifies "what's currently on screen" for change detection:
        # ("lib", screen_id) when the library recognized it, ("ocr", tuple_of_lines)
        # when falling back to live OCR. screen_payload is the text to actually speak.
        last_spoken_screen_key = None
        pending_screen_key = None
        pending_screen_seen_count = 0
        pending_screen_unstable_count = 0

        last_spoken_highlight = None
        pending_highlight = None
        pending_highlight_seen_count = 0

        def reset_tracking():
            nonlocal last_spoken_screen_key, pending_screen_key
            nonlocal pending_screen_seen_count, pending_screen_unstable_count
            nonlocal last_spoken_highlight, pending_highlight, pending_highlight_seen_count
            last_spoken_screen_key = None
            pending_screen_key = None
            pending_screen_seen_count = 0
            pending_screen_unstable_count = 0
            last_spoken_highlight = None
            pending_highlight = None
            pending_highlight_seen_count = 0

        while True:
            try:
                if was_key_pressed_since_last_check(HOTKEYS.toggle_vk):
                    reader_enabled = not reader_enabled
                    # Bypass reader_enabled here on purpose - the toggle
                    # itself must always be audible, even when turning the
                    # reader off, or silence could mean either "it's off"
                    # or "it's broken" with no way to tell which.
                    speaker.speak("Reader on." if reader_enabled else "Reader off.")
                    reset_tracking()
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                if not reader_enabled:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                if hwnd is None or not win32gui.IsWindow(hwnd):
                    hwnd = find_window_for_process(PROCESS_NAME)
                    if hwnd is None:
                        if hwnd_ever_found:
                            if window_missing_since is None:
                                window_missing_since = time.monotonic()
                            elif time.monotonic() - window_missing_since > EXIT_AFTER_WINDOW_GONE_SECONDS:
                                print("Game window gone for a while; exiting.")
                                return
                        print("Waiting for game window...")
                        time.sleep(2)
                        continue
                    hwnd_ever_found = True
                    window_missing_since = None
                    print(f"Found game window: hwnd={hwnd}")
                    speaker.speak("Game window found.")
                    reset_tracking()

                img = CAPTURE.grab(hwnd)
                if img is None:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                # mem_state.items is only populated for screens listed in
                # screen_labels.json - an unmapped screen (or the process
                # not being attachable) falls straight through to the
                # existing library/OCR path below, unchanged.
                mem_state = memory_provider.get_state()
                mem_mapped = mem_state is not None and mem_state.items

                force_reread = was_key_pressed_since_last_check(HOTKEYS.reread_vk)
                force_capture = was_key_pressed_since_last_check(HOTKEYS.capture_vk)

                if force_capture:
                    lines = asyncio.run(ocr_image(img))
                    highlighted_text = find_highlighted_text(img, lines, HIGHLIGHT_CALIBRATION)
                    name = save_known_screen(img, lines, highlighted_text, KNOWN_SCREENS_DIR)
                    print(f"Captured candidate library screen: {name}")
                    speaker.speak("Captured: " + name.replace("_", " ") + ". Needs review before it will be read automatically.")
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                match_result = library.match(img)

                if force_reread:
                    if mem_mapped:
                        print(f"Manual re-read (F9): memory-read match '{mem_state.screen_id}'.")
                        to_speak = mem_state.spoken_selection() or humanize_screen_id(mem_state.screen_id)
                        screen_key = ("mem", mem_state.screen_id)
                        highlighted_text = mem_state.spoken_selection()
                    elif match_result:
                        entry, distance = match_result
                        print(f"Manual re-read (F9): library match '{entry['screen_id']}' (distance={distance}).")
                        highlighted_text = find_highlighted_text_from_entry(img, entry, HIGHLIGHT_CALIBRATION)
                        to_speak = highlighted_text if highlighted_text else ". ".join(entry["canonical_text"])
                        screen_key = ("lib", entry["screen_id"])
                    else:
                        lines = asyncio.run(ocr_image(img))
                        screen_texts = [l["text"] for l in lines]
                        highlighted_text = find_highlighted_text(img, lines, HIGHLIGHT_CALIBRATION)
                        print("Manual re-read (F9): no library match, using live OCR.")
                        to_speak = highlighted_text if highlighted_text else (". ".join(screen_texts) if screen_texts else "No text detected.")
                        screen_key = ("ocr", tuple(screen_texts))
                    speaker.speak(to_speak)
                    last_spoken_screen_key = screen_key
                    pending_screen_key = None
                    pending_screen_seen_count = 0
                    pending_screen_unstable_count = 0
                    last_spoken_highlight = highlighted_text
                    pending_highlight = None
                    pending_highlight_seen_count = 0
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                # --- Determine what's on screen this poll, memory-first, then library, then OCR ---
                if mem_mapped:
                    screen_key = ("mem", mem_state.screen_id)
                    screen_payload = humanize_screen_id(mem_state.screen_id)
                    screen_ocr_texts = None  # not applicable in memory mode
                    highlighted_text = mem_state.spoken_selection()
                elif match_result:
                    entry, distance = match_result
                    screen_key = ("lib", entry["screen_id"])
                    screen_payload = ". ".join(entry["canonical_text"])
                    screen_ocr_texts = None  # not applicable in library mode
                    highlighted_text = find_highlighted_text_from_entry(img, entry, HIGHLIGHT_CALIBRATION)
                else:
                    lines = asyncio.run(ocr_image(img))
                    screen_texts = [l["text"] for l in lines]
                    screen_key = ("ocr", tuple(screen_texts))
                    screen_payload = ". ".join(screen_texts) if screen_texts else None
                    screen_ocr_texts = screen_texts
                    highlighted_text = find_highlighted_text(img, lines, HIGHLIGHT_CALIBRATION)

                # --- Screen-level change detection (e.g. main menu -> submenu) ---
                if screen_key == last_spoken_screen_key:
                    pending_screen_key = None
                    pending_screen_seen_count = 0
                    pending_screen_unstable_count = 0
                else:
                    pending_screen_unstable_count += 1
                    if screen_key == pending_screen_key:
                        pending_screen_seen_count += 1
                    else:
                        pending_screen_key = screen_key
                        pending_screen_seen_count = 1

                    stabilized = pending_screen_seen_count >= STABLE_POLLS_REQUIRED
                    gave_up_waiting = (
                        not stabilized
                        and screen_key[0] == "ocr"
                        and pending_screen_unstable_count >= FORCE_SPEAK_AFTER_UNSTABLE_POLLS
                    )
                    if (stabilized or gave_up_waiting) and screen_payload:
                        print(
                            "Screen changed (stable):" if stabilized
                            else "Screen changed (best-effort, OCR never stabilized):",
                            screen_key,
                        )
                        # interrupt=False: let a still-playing announcement
                        # finish rather than chopping it mid-sentence - see
                        # game_a11y_core/nvda_speaker.py.
                        speaker.speak(screen_payload, interrupt=False)
                        if screen_key[0] == "ocr":
                            log_library_miss(img, screen_ocr_texts, LIBRARY_MISSES_DIR)
                        last_spoken_screen_key = screen_key
                        pending_screen_key = None
                        pending_screen_seen_count = 0
                        pending_screen_unstable_count = 0
                        # The screen-read already covered whatever's highlighted on it.
                        last_spoken_highlight = highlighted_text
                        pending_highlight = None
                        pending_highlight_seen_count = 0

                # --- Highlight-change detection (cursor moved within the same screen) ---
                screen_just_changed = screen_key != last_spoken_screen_key
                if not screen_just_changed:
                    if highlighted_text == last_spoken_highlight:
                        pending_highlight = None
                        pending_highlight_seen_count = 0
                    elif highlighted_text == pending_highlight:
                        pending_highlight_seen_count += 1
                        if pending_highlight_seen_count >= STABLE_POLLS_REQUIRED and highlighted_text:
                            print("Highlight changed (stable):", highlighted_text)
                            speaker.speak(highlighted_text)
                            last_spoken_highlight = highlighted_text
                            pending_highlight = None
                            pending_highlight_seen_count = 0
                    else:
                        pending_highlight = highlighted_text
                        pending_highlight_seen_count = 1

                time.sleep(POLL_INTERVAL_SECONDS)
            except Exception as exc:
                # A single bad poll (e.g. the game window died mid-capture)
                # must never kill the whole reader - with no console attached
                # in normal use, an uncaught exception here means NVDA just
                # goes silent with no indication anything went wrong. Log it
                # and keep polling instead - but if failures never stop (not
                # just the window being gone, handled separately above), give
                # up and exit so a future relaunch's duplicate-instance check
                # can start a fresh, healthy reader instead of this one
                # retrying forever as a zombie that blocks it from doing so.
                consecutive_poll_failures += 1
                print(f"Poll cycle failed ({consecutive_poll_failures} in a row), skipping and continuing: {exc!r}")
                if consecutive_poll_failures >= EXIT_AFTER_CONSECUTIVE_POLL_FAILURES:
                    print("Too many consecutive poll failures; exiting so a relaunch can recover.")
                    return
                time.sleep(POLL_INTERVAL_SECONDS)
            else:
                consecutive_poll_failures = 0
    finally:
        release_single_instance_lock(LOCK_FILE_PATH)


if __name__ == "__main__":
    main()
