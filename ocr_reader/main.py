"""
Mortal Kombat X accessibility reader.

Continuously captures the game window and speaks its contents. On each
poll, first tries to recognize the current screen against the
hand-verified reference library (known_screens/, matched by perceptual
image hash - see game_a11y_core/screen_library.py, "the hook"): a match
speaks that screen's pre-verified canonical_text instead of live OCR,
which is both faster and immune to this game's various OCR failure modes
(stylized/compressed fonts that Windows OCR mangles or misses entirely -
see PROGRESS.md for why this replaced the original OCR-only
design).

If no library entry matches, falls back to live OCR as a best-effort read,
and logs the miss to library_misses/ (in the data folder, newest 50 kept)
so it can be reviewed and folded into the library later.

Within either mode, the currently-highlighted item (if the screen is a
list/tab style menu) is tracked separately via color: this game renders
the selected item in a distinct cyan/blue with a glow, vs. gold/yellow for
unselected items - see docs/PROGRESS.md for the calibration.

2026-10, installable build - what changed and why:
  - Runs resident. Started at sign-in (--background, from the installer's
    autostart option) it waits quietly for the game, reads while it's open,
    and goes back to waiting when it closes, instead of exiting 120s after
    the game closed (that only made sense when Steam relaunched it each
    time via the old start_reader.vbs launch option).
  - Speech falls back from NVDA to the Windows voice (game_a11y_core/
    speech.py) instead of beeping and quitting when NVDA isn't running.
  - Hotkeys and reading only act while the game is the focused window.
    Now that the reader runs all the time, F10 pressed in some other app
    must not toggle it, and the game's attract-mode screens shouldn't talk
    over whatever else the user is doing. Switching back to the game
    re-announces the current screen.
  - DPI-aware, with every capture normalized to a 1920x1080 reference
    before matching (frames.py). Until now each capture was silently only
    the top-left two-thirds of the screen on the development PC, and
    would have been framed differently again on anyone else's.
  - Single instance via a named mutex and --stop via a named event
    (game_a11y_core/lifecycle.py); writes only to the data folder
    (app_paths.py); F2 capture needs --dev.

Hotkeys (only while the game is focused): F9 re-reads the current screen.
F10 toggles the reader on/off and always announces the new state. F2, in
--dev mode only, saves the current screen as a *candidate* library entry -
it still needs canonical_text hand-verified from the image before
screen_library.py will speak it.
"""

import argparse
import asyncio
import ctypes
import os
import sys
import time

import app_paths
import frames
import menu_ocr
from version import __version__

PROG_NAME = "mkx-access"
PROCESS_NAME = "MK10.exe"
INSTANCE_MUTEX_NAME = "Local\\MKXAccess.Reader"
STOP_EVENT_NAME = "Local\\MKXAccess.Stop"
# Must match the value name the installer writes (packaging/installer.iss).
AUTOSTART_VALUE_NAME = "MKXAccess"

POLL_INTERVAL_SECONDS = 0.3
# Unknown screens: when the whole frame has barely changed since the last
# OCR (typically just the highlight moving), reuse that OCR's lines and only
# re-sample highlight colours - fast enough to keep up with a controller.
# Still re-OCR at least this often, so a changed value (ON -> OFF) is caught.
OCR_REUSE_MAX_HASH_DISTANCE = 10
OCR_REUSE_MAX_AGE_SECONDS = 2.0
# A screen that never stops changing (a fight, an attract animation) gets
# one best-effort reading, then silence and slower OCR until something
# steady appears again.
NOISY_OCR_EVERY_N_POLLS = 5
# Coming back to a screen read this recently (Back out of a submenu, or the
# pause menu after its Moves List panel closes) announces just its title and
# the highlighted item, not the whole screen again. F9 still reads it all.
RECENT_SCREEN_SECONDS = 60.0
WINDOW_SEARCH_INTERVAL_SECONDS = 2.0
STABLE_POLLS_REQUIRED = 2  # OCR/highlight can be slightly noisy frame-to-frame; require it to settle before speaking
# Classic-game OCR can be noisy enough to never repeat two polls in a row
# identically (see docs/PROGRESS.md) - without this, an uncatalogued screen
# could stay silent forever waiting for exact stability. After this many
# consecutive polls of "something changed, just not the same way twice",
# speak the latest OCR reading once as best-effort instead of waiting.
FORCE_SPEAK_AFTER_UNSTABLE_POLLS = 8
# A single bad poll is tolerated, but if failures never stop, announce it and
# exit rather than retrying forever in silence.
EXIT_AFTER_CONSECUTIVE_POLL_FAILURES = 240
STOP_WAIT_SECONDS = 15
REFOCUS_REREAD_AFTER_SECONDS = 5.0
MAX_LIBRARY_MISSES_KEPT = 50
LOG_ROTATE_BYTES = 2_000_000

OCR_MISSING_MESSAGE = (
    "Windows text recognition is not installed, so only screens the reader already knows will be read. "
    "The read me explains how to add it."
)

# NEEDS_CALIBRATION: these are the Legacy Kollection launcher's values
# (selected text cyan, unselected gold). MKX's menu text is off-white on
# both selected and unselected rows in the screenshots so far, so this
# probably never fires here: the highlighted item then isn't announced on
# its own, but nothing wrong is said either, and F9 reads the whole screen.
# Sample a selected and an unselected row from a live 1920x1080 capture.
HIGHLIGHT_BRIGHTNESS_THRESHOLD = 300
HIGHLIGHT_BLUE_MINUS_RED_THRESHOLD = 30


# --- Output / logging -------------------------------------------------------

class _TimestampedTee:
    """Writes every line to the log file (and the console, when there is
    one), prefixed with a timestamp. The packaged reader has no console at
    all, so the log is the only record of what it did and said."""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]
        self._at_line_start = True

    def write(self, text):
        if not text:
            return 0
        pieces = []
        for chunk in text.splitlines(keepends=True):
            if self._at_line_start:
                pieces.append(time.strftime("%Y-%m-%d %H:%M:%S "))
            pieces.append(chunk)
            self._at_line_start = chunk.endswith("\n")
        out = "".join(pieces)
        for stream in self.streams:
            try:
                stream.write(out)
                stream.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def _attach_parent_console():
    """The packaged reader is a windowed program (so autostart never flashes
    a console). For --help/--version/--self-test run from a command prompt,
    borrow that prompt's console so the output is visible there."""
    try:
        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            stream = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stdout = stream
            sys.stderr = stream
    except Exception:
        pass


def _setup_output(argv):
    if sys.stdout is None and any(a in argv for a in ("-h", "--help", "--version", "--self-test")):
        _attach_parent_console()
    # A windowed program has no stdout/stderr at all; argparse and print()
    # would raise on None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout


def _open_log():
    try:
        os.makedirs(app_paths.data_dir(), exist_ok=True)
        path = app_paths.log_file_path()
        try:
            if os.path.getsize(path) > LOG_ROTATE_BYTES:
                os.replace(path, path + ".old")
        except OSError:
            pass  # no log yet, or another reader process has it open
        log = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return
    console = sys.stdout if getattr(sys.stdout, "name", None) != os.devnull else None
    tee = _TimestampedTee(log, console)
    sys.stdout = tee
    sys.stderr = tee


# --- Command line -----------------------------------------------------------

def parse_args(argv):
    from game_a11y_core.speech import MODES

    parser = argparse.ArgumentParser(
        prog=PROG_NAME,
        description="Speaks the menus of Mortal Kombat X through NVDA or JAWS, "
        "or through the Windows voice when neither is running.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--stop", action="store_true", help="ask a running reader to shut down, and wait until it has")
    action.add_argument("--self-test", action="store_true", help="check speech, text recognition and the screen library, and report the result")
    parser.add_argument("--background", action="store_true", help="started automatically at sign-in: don't announce startup")
    parser.add_argument("--quiet", action="store_true", help="with --stop or --self-test: no speech or dialog, exit code only")
    parser.add_argument("--speech", choices=MODES, default="auto", help="voice to use (default: auto = NVDA or JAWS if running, else the Windows voice)")
    parser.add_argument("--dev", action="store_true", help="developer mode: F2 saves the current screen as a candidate library entry")
    parser.add_argument("--ignore-focus", action="store_true", help="read the game even when it isn't the focused window")
    parser.add_argument("--report-file", help="with --self-test: also write the results as JSON to this file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


# --- Helpers ----------------------------------------------------------------

def prune_library_misses(directory, keep=MAX_LIBRARY_MISSES_KEPT):
    """Unrecognised screens are saved for later review, but an installed
    reader runs for months - keep only the newest `keep` (file names start
    with a timestamp, so name order is age order)."""
    try:
        stems = sorted(n[:-4] for n in os.listdir(directory) if n.endswith(".png"))
    except OSError:
        return
    for stem in stems[:-keep] if keep else stems:
        for ext in (".png", ".json"):
            try:
                os.remove(os.path.join(directory, stem + ext))
            except OSError:
                pass


def load_library():
    from game_a11y_core.screen_library import ScreenLibrary

    dirs = app_paths.library_dirs()
    library = ScreenLibrary(dirs[0])
    for extra in dirs[1:]:
        library.add_directory(extra)
    return library


def clean_ocr_line(text):
    """Drop stray symbol tokens at either end of an OCR line. Added
    2026-10-11 after a live test: the glowing ornament beside a highlighted
    menu item OCRs as "—4" or similar, so "ONLINE ARCADE" became
    "—4 ONLINE ARCADE" whenever it was highlighted - which changed the
    screen's identity and re-read the whole screen on every cursor move.
    Only tokens with a symbol and no letters are dropped, and only while
    some lettered text remains, so "1:36" or "16" alone are kept."""
    tokens = text.split()

    def junk(token):
        return not any(c.isalpha() for c in token) and any(not c.isalnum() for c in token)

    while len(tokens) > 1 and junk(tokens[0]) and any(c.isalpha() for c in "".join(tokens[1:])):
        tokens.pop(0)
    while len(tokens) > 1 and junk(tokens[-1]) and any(c.isalpha() for c in "".join(tokens[:-1])):
        tokens.pop()
    return " ".join(tokens)


def foreground_description():
    """'process.exe: window title' of the foreground window, for the log."""
    try:
        import win32api
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "no foreground window"
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        name = f"pid {pid}"
        handle = None
        try:
            handle = win32api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            name = os.path.basename(win32process.GetModuleFileNameEx(handle, 0))
        except Exception:
            pass
        finally:
            if handle is not None:
                win32api.CloseHandle(handle)
        return f"{name}: {win32gui.GetWindowText(hwnd)!r}"
    except Exception as exc:
        return f"unknown ({exc!r})"


def grid_selection(full, grid):
    """Name of the grid cell the selection box surrounds, or None. Scores
    each cell by how much of a thin ring around it is the box colour; the
    box's cell scores far above the rest (live: 0.19-0.75 against 0.06 or
    less), and nothing scores during a fight."""
    import numpy as np

    arr = np.asarray(full.convert("RGB")).astype(np.int16)
    lo, hi = np.array(grid["color_min"]), np.array(grid["color_max"])
    ring = int(grid.get("ring", 10))
    scores = []
    for cell in grid["cells"]:
        x1, y1, x2, y2 = cell["bbox"]
        sub = arr[max(0, y1 - ring):y2 + ring, max(0, x1 - ring):x2 + ring]
        if not sub.size:
            continue
        match = np.all((sub >= lo) & (sub <= hi), axis=2)
        inner = np.zeros(match.shape, dtype=bool)
        inner[2 * ring:-2 * ring, 2 * ring:-2 * ring] = True
        scores.append((float(match[~inner].mean()), cell["name"]))
    if not scores:
        return None
    scores.sort(reverse=True)
    best, name = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    return name if best >= 0.1 and best >= 2.5 * runner_up else None


NOISE_QUALITY_MIN = 0.6


def same_as_spoken_quality(texts):
    """Is this unknown-screen reading worth speaking? Mostly-garbage
    readings (attract-mode score tables, fight HUDs) aren't."""
    return menu_ocr.reading_quality(texts or ()) >= NOISE_QUALITY_MIN


def title_matches(expected, ocr_lines):
    """True if `expected` (e.g. "PLAY") is among the OCR'd title lines,
    comparing letters only and tolerating a little OCR noise (the stylised
    title fonts lose or swap a letter now and then)."""
    import difflib

    def letters(text):
        return "".join(c for c in text.upper() if c.isalpha())

    want = letters(expected)
    joined = letters(" ".join(ocr_lines))
    if not want or not joined:
        return False
    if want in joined:
        return True
    return difflib.SequenceMatcher(None, want, joined).ratio() >= 0.75


def read_screen_text(img):
    """Live OCR with clean_ocr_line applied to every line."""
    from game_a11y_core.ocr import ocr_image

    lines = asyncio.run(ocr_image(img))
    for line in lines:
        line["text"] = menu_ocr.snap(clean_ocr_line(line["text"]))
    return [line for line in lines if line["text"]]


# --- The reader -------------------------------------------------------------

class Reader:
    def __init__(self, args, speaker, library, stop_event):
        from game_a11y_core.capture import AutoCapture
        from game_a11y_core.highlight import HighlightCalibration
        from game_a11y_core.hotkeys import HotkeyConfig
        from game_a11y_core.ocr import get_ocr_engine, ocr_language_tag

        self.args = args
        self.speaker = speaker
        self.library = library
        self.stop_event = stop_event
        self.capture = AutoCapture()
        self.calibration = HighlightCalibration(
            brightness_threshold=HIGHLIGHT_BRIGHTNESS_THRESHOLD,
            blue_minus_red_threshold=HIGHLIGHT_BLUE_MINUS_RED_THRESHOLD,
        )
        self.hotkeys = HotkeyConfig(reread_vk=0x78, capture_vk=0x71, toggle_vk=0x79)  # F9, F2, F10
        self.capture_dir = app_paths.user_known_screens_dir()
        self.misses_dir = app_paths.library_misses_dir()

        self.ocr_available = get_ocr_engine() is not None
        if self.ocr_available:
            print(f"Text recognition (OCR) language: {ocr_language_tag()}")
        else:
            print("Text recognition (OCR) is not available - only library screens will be read.")
        self.ocr_warning_spoken = False

        self.hwnd = None
        self.game_pid = None
        self.last_capture_size = None
        self.waiting_logged = False
        self.game_focused = True
        self.unfocused_since = None
        self.reader_enabled = True
        self.consecutive_poll_failures = 0
        self.title_check_cache = {}
        menu_ocr.load_vocabulary(library)
        self.ocr_cache = None  # (frame dhash, monotonic time, lines)
        self.noisy_streak = 0
        self.noisy_skip = 0
        self.reset_tracking()

    def reset_tracking(self):
        # screen_key identifies "what's currently on screen" for change detection:
        # ("lib", screen_id) when the library recognized it, ("ocr", tuple_of_lines)
        # when falling back to live OCR.
        self.last_spoken_screen_key = None
        self.pending_screen_key = None
        self.pending_screen_seen_count = 0
        self.pending_screen_unstable_count = 0
        self.last_spoken_highlight = None
        self.pending_highlight = None
        self.pending_highlight_seen_count = 0
        self.last_spoken_live = None
        self.pending_live = None
        self.pending_live_seen_count = 0

    def run(self):
        from game_a11y_core.lifecycle import wait_for_event

        while True:
            if wait_for_event(self.stop_event, 0):
                print("Stop requested; exiting.")
                return 0
            try:
                delay = self.poll_once()
            except Exception as exc:
                # A single bad poll (e.g. the game window died mid-capture)
                # must never kill the whole reader. But if failures never
                # stop, say so out loud and exit - retrying forever in
                # silence is indistinguishable from working-but-quiet.
                self.consecutive_poll_failures += 1
                print(f"Poll cycle failed ({self.consecutive_poll_failures} in a row), skipping and continuing: {exc!r}")
                if self.consecutive_poll_failures >= EXIT_AFTER_CONSECUTIVE_POLL_FAILURES:
                    print("Too many consecutive poll failures; exiting.")
                    self.speaker.speak("The accessibility reader stopped after repeated errors. Start it again from the Start menu.")
                    self.speaker.wait_until_done()
                    return 1
                delay = POLL_INTERVAL_SECONDS
            else:
                self.consecutive_poll_failures = 0
            if wait_for_event(self.stop_event, delay):
                print("Stop requested; exiting.")
                return 0

    def poll_once(self):
        """One cycle. Returns how long to wait before the next one."""
        import win32gui

        from game_a11y_core.hotkeys import was_key_pressed_since_last_check
        from game_a11y_core.lifecycle import find_window_for_process, foreground_process_id, window_process_id

        # Read (and so clear) every hotkey latch every poll, even when the
        # press will be ignored - otherwise F10 pressed in another app would
        # sit latched and fire the moment the game is focused again.
        hk = self.hotkeys
        toggle_pressed = hk.has_toggle and was_key_pressed_since_last_check(hk.toggle_vk)
        reread_pressed = was_key_pressed_since_last_check(hk.reread_vk)
        capture_pressed = was_key_pressed_since_last_check(hk.capture_vk)

        # --- Find the game ---
        if self.hwnd is None or not win32gui.IsWindow(self.hwnd):
            if self.hwnd is not None:
                print("Game window closed; waiting for the game to start again.")
                self.hwnd = None
                self.game_pid = None
            hwnd = find_window_for_process(PROCESS_NAME)
            if hwnd is None:
                if not self.waiting_logged:
                    print("Waiting for game window...")
                    self.waiting_logged = True
                return WINDOW_SEARCH_INTERVAL_SECONDS
            self.hwnd = hwnd
            self.game_pid = window_process_id(hwnd)
            self.waiting_logged = False
            self.game_focused = True
            print(f"Found game window: hwnd={hwnd} pid={self.game_pid}")
            self.speaker.speak("Game window found.")
            if not self.ocr_available and not self.ocr_warning_spoken:
                self.speaker.speak(OCR_MISSING_MESSAGE, interrupt=False)
                self.ocr_warning_spoken = True
            self.reset_tracking()

        # --- Only act while the game is the focused window ---
        if not self.args.ignore_focus:
            try:
                focused = foreground_process_id() == self.game_pid
            except Exception:
                focused = True  # can't tell - fail towards reading, not silence
            if not focused:
                if self.game_focused:
                    print(f"Game is not the focused window ({foreground_description()}); pausing until it is.")
                    self.game_focused = False
                    self.unfocused_since = time.monotonic()
                return POLL_INTERVAL_SECONDS
            if not self.game_focused:
                away = time.monotonic() - (self.unfocused_since or 0)
                self.game_focused = True
                # 2026-10-11 live test: with a controller, focus flickered
                # away and back many times, and every return re-read the
                # whole screen. Only a real absence (Alt+Tab and back)
                # re-announces the screen now; a blip just carries on.
                if away >= REFOCUS_REREAD_AFTER_SECONDS:
                    print(f"Game focused again after {away:.1f}s; re-reading the screen.")
                    self.reset_tracking()
                else:
                    print(f"Game focused again after {away:.1f}s; continuing.")

        if toggle_pressed:
            self.reader_enabled = not self.reader_enabled
            # Always audible, even when turning the reader off, or silence
            # could mean either "it's off" or "it's broken".
            self.speaker.speak("Reader on." if self.reader_enabled else "Reader off.")
            self.reset_tracking()
            return POLL_INTERVAL_SECONDS

        if not self.reader_enabled:
            return POLL_INTERVAL_SECONDS

        raw = self.capture.grab(self.hwnd)
        if raw is None:
            return POLL_INTERVAL_SECONDS
        if raw.size != self.last_capture_size:
            self.last_capture_size = raw.size
            print(f"Game capture size: {raw.size[0]}x{raw.size[1]}")
            if not frames.aspect_ratio_ok(raw.size):
                print("Warning: game window isn't 16:9 - screen recognition may miss. Use a 16:9 resolution or fullscreen.")
        # full: the whole screen at the reference size (OCR, misses).
        # view: the top-left crop the library was captured with (matching,
        # library highlight bboxes). See frames.py for why there are two.
        full = frames.normalize(raw)
        view = frames.library_view(full)

        if capture_pressed and self.args.dev:
            self.save_candidate_screen(full, view)
            return POLL_INTERVAL_SECONDS

        match_result = self.verified_match(full, view)

        if reread_pressed:
            self.manual_reread(full, view, match_result)
            return POLL_INTERVAL_SECONDS

        self.track_screen(full, view, match_result)
        return POLL_INTERVAL_SECONDS

    def verified_match(self, full, view):
        """library.match(), plus a title check for entries that carry one.
        Added 2026-10-11: menus are now hashed on their fixed title area only
        (the moving highlight kept pushing whole-menu hashes past the match
        threshold, so the Play menu flipped between its library text and
        noisy OCR on every cursor move). A small hashed area is easier to
        confuse with a look-alike menu, so the title is also read by OCR and
        must match before the entry's text is trusted. The result is cached
        per hash value, so the OCR runs once per screen, not every poll."""
        from game_a11y_core.screen_library import compute_dhash

        result = self.library.match(view)
        if not result:
            return None
        entry = result[0]
        check = entry.get("title_check")
        if not check:
            return result
        key = (entry["screen_id"], compute_dhash(view, entry.get("roi")))
        ok = self.title_check_cache.get(key)
        if ok is None:
            lines = read_screen_text(full.crop(tuple(check["bbox"])))
            ok = title_matches(check["text"], [l["text"] for l in lines])
            if len(self.title_check_cache) > 256:
                self.title_check_cache.clear()
            self.title_check_cache[key] = ok
            if not ok:
                print(f"Title check failed for {entry['screen_id']}: read {[l['text'] for l in lines]!r}")
        return result if ok else None

    def unknown_screen_lines(self, full):
        """OCR lines for a screen the library doesn't know, reusing the last
        OCR when only something small (the highlight) changed."""
        from game_a11y_core.screen_library import compute_dhash, hamming_distance

        frame_hash = compute_dhash(full)
        now = time.monotonic()
        if self.ocr_cache is not None:
            cached_hash, cached_at, cached_lines = self.ocr_cache
            if (hamming_distance(frame_hash, cached_hash) <= OCR_REUSE_MAX_HASH_DISTANCE
                    and now - cached_at < OCR_REUSE_MAX_AGE_SECONDS):
                return cached_lines, True
        lines = menu_ocr.read_menu_text(full, clean_ocr_line)
        self.ocr_cache = (frame_hash, now, lines)
        return lines, False

    def announcement_for(self, screen_key, payload, highlighted, live):
        """What to say for a newly settled screen. Returns (text, reason);
        reason is None for the full screen."""
        def title_and_item(title):
            parts = [title] if title and title != highlighted else []
            if highlighted:
                parts.append(highlighted)
            if live:
                parts.append(live)
            return ". ".join(parts)

        now = time.monotonic()
        for key, seen_at in getattr(self, "recent_screens", []):
            if now - seen_at > RECENT_SCREEN_SECONDS or key[0] != screen_key[0]:
                continue
            same = key == screen_key or (key[0] == "ocr" and menu_ocr.same_screen(key[1], screen_key[1]))
            if same and highlighted:
                title = screen_key[1][0] if screen_key[0] == "ocr" and screen_key[1] else None
                if screen_key[0] == "lib":
                    entry = next((e for e in self.library.entries if e["screen_id"] == screen_key[1]), None)
                    title = entry["canonical_text"][0] if entry else None
                return title_and_item(title), "a recently read screen: title and highlighted item"
        last = self.last_spoken_screen_key
        if (screen_key[0] == "ocr" and last and last[0] == "ocr" and highlighted
                and screen_key[1] and last[1] and screen_key[1][0] == last[1][0]
                and len(set(last[1]) - set(screen_key[1])) >= 2):
            # Same page title, so a list scrolled (the Krypt documentary
            # keeps the highlighted chapter in one place and moves the rest):
            # say the newly highlighted item and any new descriptive
            # sentences, not every list item that scrolled into view.
            previous = set(last[1])
            sentences = [t for t in screen_key[1] if t not in previous and any(c.islower() for c in t)]
            return menu_ocr.join_texts([highlighted] + sentences), "the newly highlighted item on a scrolled list"
        if screen_key[0] == "ocr" and last and last[0] == "ocr":
            previous = set(last[1])
            shared = [t for t in screen_key[1] if t in previous]
            new = [t for t in screen_key[1] if t not in previous]
            if len(shared) >= 3 and new:
                parts = ([highlighted] if highlighted and highlighted not in new else []) + new
                return menu_ocr.join_texts(parts), "only what changed from the previous screen"
        # A full reading ends by saying where the cursor is, so the first
        # thing heard on a new menu includes what Enter would choose.
        if highlighted and highlighted != payload:
            payload = f"{payload}. Selected: {highlighted}"
        return payload, None

    def remember_screen(self, screen_key):
        now = time.monotonic()
        recent = [(k, t) for k, t in getattr(self, "recent_screens", []) if now - t <= RECENT_SCREEN_SECONDS and k != screen_key]
        recent.append((screen_key, now))
        self.recent_screens = recent[-8:]

    def remember_rows(self, lines):
        """Merge this reading with the current screen's row memory: rows read
        now replace what's remembered at the same position; remembered rows
        missing now are added back."""
        from menu_ocr import _overlap, order_for_reading

        from menu_ocr import _quality

        memory = getattr(self, "row_memory", None) or []
        merged = []
        for line in lines:
            # Keep whichever reading of this row is better: the highlighted
            # (glowing) version of a row usually OCRs worse than the plain one.
            best = dict(line)
            for old in memory:
                if _overlap(old["bbox"], line["bbox"]) > 0.3 and _quality(old["text"], None) > _quality(line["text"], None):
                    best = dict(old, bbox=line["bbox"])
            merged.append(best)
        for old in memory:
            if not any(_overlap(old["bbox"], l["bbox"]) > 0.3 for l in lines):
                merged.append(dict(old))
        merged = order_for_reading([dict(l, x=l["bbox"][0], y=l["bbox"][1]) for l in merged])
        self.row_memory = [dict(l) for l in merged]
        return merged

    def live_text(self, full, entry):
        """Text of an entry's live regions right now, or None."""
        parts = []
        for region in entry.get("live_regions") or ():
            lines = read_screen_text(full.crop(tuple(region["bbox"])))
            parts.extend(l["text"] for l in lines)
            if lines and region.get("platform_icon"):
                try:
                    import platform_icons  # Legacy Kollection only
                except ImportError:
                    platform_icons = None
                platform = platform_icons.classify(full) if platform_icons else None
                if platform:
                    parts.append(platform)
        return menu_ocr.join_texts(parts) if parts else None

    def entry_highlight(self, full, entry):
        """Which of a library entry's lines is highlighted, sampled on the
        FULL frame. Added 2026-10-11 after a live test: library bboxes are in
        library-view coordinates, which are identical to full-frame ones
        (the view is a crop at 0,0 with no scaling - see frames.py). Sampling
        the cropped view instead made any item below y=720 invisible, so
        moving onto the main menu's OPTIONS or QUIT was never announced."""
        from game_a11y_core.highlight import find_highlighted_text_from_entry

        if entry.get("selection_grid"):
            return grid_selection(full, entry["selection_grid"])
        if tuple(entry.get("capture_size") or ()) == frames.LIBRARY_BOX[2:]:
            entry = dict(entry, capture_size=list(full.size))
        return find_highlighted_text_from_entry(full, entry, self.calibration)

    def save_candidate_screen(self, full, view):
        from game_a11y_core.highlight import find_highlighted_text
        from game_a11y_core.ocr import ocr_image
        from game_a11y_core.screen_capture_tools import save_known_screen

        # OCR the whole screen so the reviewer gets every line; the library
        # image itself is the cropped view, so the new entry matches the same
        # way as every existing one. <name>.full.png is the whole screen, for
        # the reviewer only (the library loader ignores it).
        lines = asyncio.run(ocr_image(full))
        highlighted_text = find_highlighted_text(full, lines, self.calibration)
        name = save_known_screen(view, lines, highlighted_text, self.capture_dir)
        full.save(os.path.join(self.capture_dir, name + ".full.png"))
        print(f"Captured candidate library screen: {os.path.join(self.capture_dir, name)}")
        self.speaker.speak("Captured: " + name.replace("_", " ") + ". Needs review before it will be read automatically.")

    def manual_reread(self, full, view, match_result):
        from game_a11y_core.highlight import find_highlighted_text, find_highlighted_text_from_entry
        from game_a11y_core.ocr import ocr_image

        if match_result:
            entry, distance = match_result
            print(f"Manual re-read (F9): library match '{entry['screen_id']}' (distance={distance}).")
            highlighted_text = self.entry_highlight(full, entry)
            live = self.live_text(full, entry)
            to_speak = highlighted_text if highlighted_text else menu_ocr.join_texts(entry["canonical_text"])
            if live:
                to_speak += ". " + live
            screen_key = ("lib", entry["screen_id"])
            self.last_spoken_live = live
            self.pending_live = None
            self.pending_live_seen_count = 0
        else:
            lines = menu_ocr.read_menu_text(full, clean_ocr_line)
            self.ocr_cache = None
            screen_texts = [l["text"] for l in lines]
            highlighted_text = menu_ocr.find_highlight(full, lines, self.calibration)
            print("Manual re-read (F9): no library match, using live OCR.")
            if highlighted_text:
                to_speak = highlighted_text
            elif screen_texts:
                to_speak = menu_ocr.join_for_speech(lines)
            elif not self.ocr_available:
                to_speak = "This screen isn't known, and text recognition is not installed."
            else:
                to_speak = "No text detected."
            screen_key = ("ocr", tuple(screen_texts))
        self.speaker.speak(to_speak)
        self.last_spoken_screen_key = screen_key
        self.pending_screen_key = None
        self.pending_screen_seen_count = 0
        self.pending_screen_unstable_count = 0
        self.last_spoken_highlight = highlighted_text
        self.pending_highlight = None
        self.pending_highlight_seen_count = 0

    def track_screen(self, full, view, match_result):
        from game_a11y_core.highlight import find_highlighted_text, find_highlighted_text_from_entry
        from game_a11y_core.ocr import ocr_image
        from game_a11y_core.screen_capture_tools import log_library_miss

        # --- Determine what's on screen this poll, library-first ---
        if match_result:
            entry, _distance = match_result
            self.noisy_streak = 0
            self.ocr_cache = None
            screen_key = ("lib", entry["screen_id"])
            screen_payload = menu_ocr.join_texts(entry["canonical_text"])
            screen_ocr_texts = None  # not applicable in library mode
            highlighted_text = self.entry_highlight(full, entry)
            live = self.live_text(full, entry) if entry.get("live_regions") else None
            if live:
                screen_payload = menu_ocr.join_texts([screen_payload, live])
        else:
            if self.noisy_streak >= 2:
                # Looks like a fight: OCR only every few polls.
                self.noisy_skip = (self.noisy_skip + 1) % NOISY_OCR_EVERY_N_POLLS
                if self.noisy_skip:
                    return
            lines, reused = self.unknown_screen_lines(full)
            # Identity ignores the key-hint bar at the bottom: it names the
            # highlighted item ("Enter: ADDITIONAL SETTINGS"), so it changes
            # with every cursor move.
            body = tuple(l["text"] for l in lines if not menu_ocr.is_hint(l["bbox"]))
            screen_key = ("ocr", body)
            # The same menu with the highlight moved can OCR a line or two
            # differently: keep treating it as the screen already spoken (or
            # already pending), so the move is announced as just the item.
            # Only against the screen already spoken: a NEW screen must read
            # identically twice before it's spoken, or a panel still sliding
            # in gets read half-drawn.
            same = False
            known = self.last_spoken_screen_key
            pending = self.pending_screen_key
            if known and known[0] == "ocr" and menu_ocr.same_screen(known[1], body):
                screen_key = known
                same = True
            elif pending and pending[0] == "ocr" and menu_ocr.same_screen(pending[1], body, menu_ocr.SETTLED_MIN_OVERLAP):
                # Close enough to the pending reading to count as the same
                # settled screen (text inside a playing video changes every
                # poll), but stricter than above, so a panel still sliding
                # in doesn't count as settled.
                screen_key = pending
            # Row memory: the highlighted item's glowing text often doesn't
            # OCR at all, but it read fine a moment ago when it wasn't
            # highlighted. Fill rows missing from this reading from the
            # screen's earlier readings, so the highlight check (colour, at
            # the row's position) can still find and name it.
            if same:
                lines = self.remember_rows(lines)
            else:
                self.row_memory = [dict(l) for l in lines]
            screen_texts = [l["text"] for l in lines]
            content = [l for l in lines if not menu_ocr.is_hint(l["bbox"])]
            hints = menu_ocr.join_for_speech([l for l in lines if menu_ocr.is_hint(l["bbox"])])
            last = self.last_spoken_screen_key
            if (content and last and last[0] == "ocr" and last[1] and content[0]["text"] == last[1][0]
                    and not same):
                # Same page title as what was just read (moving between
                # fighters on KOMBATANTS): don't repeat the title.
                content = content[1:]
            screen_payload = menu_ocr.join_for_speech(content) if screen_texts else None
            # The key-hint bar is read when it first appears or changes,
            # not again with every item.
            if hints and hints != getattr(self, "last_hints", None):
                screen_payload = menu_ocr.join_texts([screen_payload, hints]) if screen_payload else hints
            self.pending_hints = hints
            screen_ocr_texts = screen_texts
            highlighted_text = menu_ocr.find_highlight(full, lines, self.calibration)
            live = None

        # --- Screen-level change detection (e.g. main menu -> submenu) ---
        if screen_key == self.last_spoken_screen_key:
            self.pending_screen_key = None
            self.pending_screen_seen_count = 0
            self.pending_screen_unstable_count = 0
        else:
            self.pending_screen_unstable_count += 1
            if screen_key == self.pending_screen_key:
                self.pending_screen_seen_count += 1
            else:
                self.pending_screen_key = screen_key
                self.pending_screen_seen_count = 1

            stabilized = self.pending_screen_seen_count >= STABLE_POLLS_REQUIRED
            # Library matches are pre-verified text; only noisy live OCR
            # needs the best-effort "it never settled, speak it anyway" path.
            gave_up_waiting = (
                not stabilized
                and screen_key[0] == "ocr"
                and self.pending_screen_unstable_count >= FORCE_SPEAK_AFTER_UNSTABLE_POLLS
            )
            suppress = False
            if screen_key[0] == "ocr" and (stabilized or gave_up_waiting) and not same_as_spoken_quality(screen_ocr_texts):
                # Ignore it entirely: don't let a blank or junk frame between
                # two screens count as a screen, or coming back to the same
                # menu afterwards would read it all again.
                print(f"Reading looks like noise (quality {menu_ocr.reading_quality(screen_ocr_texts or ()):.2f}); ignoring:", screen_key)
                self.pending_screen_key = None
                self.pending_screen_seen_count = 0
                return
            if gave_up_waiting:
                self.noisy_streak += 1
                if self.noisy_streak > 1 or not menu_ocr.looks_like_text(screen_ocr_texts or ()):
                    suppress = True
            elif stabilized:
                self.noisy_streak = 0
            if suppress:
                print("Screen keeps changing and reads as noise (a fight?); staying quiet:", screen_key)
                self.last_spoken_screen_key = screen_key
                self.pending_screen_key = None
                self.pending_screen_seen_count = 0
                self.pending_screen_unstable_count = 0
                self.last_spoken_highlight = highlighted_text
            elif (stabilized or gave_up_waiting) and screen_payload:
                print(
                    "Screen changed (stable):" if stabilized
                    else "Screen changed (best-effort, OCR never stabilized):",
                    screen_key,
                )
                payload, how = self.announcement_for(screen_key, screen_payload, highlighted_text, live)
                if how:
                    print(f"  announcing {how}")
                self.remember_screen(screen_key)
                if screen_key[0] == "ocr":
                    self.last_hints = getattr(self, "pending_hints", None)
                # interrupt=False: let a still-playing announcement finish
                # rather than chopping it mid-sentence.
                self.speaker.speak(payload, interrupt=False)
                if screen_key[0] == "ocr":
                    log_library_miss(full, screen_ocr_texts, self.misses_dir)
                    prune_library_misses(self.misses_dir)
                self.last_spoken_screen_key = screen_key
                self.pending_screen_key = None
                self.pending_screen_seen_count = 0
                self.pending_screen_unstable_count = 0
                # The screen-read already covered whatever's highlighted on it.
                self.last_spoken_highlight = highlighted_text
                self.pending_highlight = None
                self.pending_highlight_seen_count = 0
                self.last_spoken_live = live
                self.pending_live = None
                self.pending_live_seen_count = 0

        # --- Highlight-change detection (cursor moved within the same screen) ---
        spoke_highlight = False
        if screen_key == self.last_spoken_screen_key:
            if highlighted_text == self.last_spoken_highlight:
                self.pending_highlight = None
                self.pending_highlight_seen_count = 0
            elif highlighted_text == self.pending_highlight:
                self.pending_highlight_seen_count += 1
                if self.pending_highlight_seen_count >= STABLE_POLLS_REQUIRED and highlighted_text:
                    print("Highlight changed (stable):", highlighted_text)
                    self.speaker.speak(highlighted_text)
                    spoke_highlight = True
                    self.last_spoken_highlight = highlighted_text
                    self.pending_highlight = None
                    self.pending_highlight_seen_count = 0
            else:
                self.pending_highlight = highlighted_text
                self.pending_highlight_seen_count = 1

        # --- Live-region change detection (e.g. the Game Library's selected
        # game). Same two-poll stability rule; an empty read (text mid-
        # animation) is never spoken. Doesn't cut off a highlight announced
        # in the same poll (switching tabs changes both).
        if screen_key == self.last_spoken_screen_key and screen_key[0] == "lib":
            if live == self.last_spoken_live or not live:
                self.pending_live = None
                self.pending_live_seen_count = 0
            elif live == self.pending_live:
                self.pending_live_seen_count += 1
                if self.pending_live_seen_count >= STABLE_POLLS_REQUIRED:
                    print("Live region changed (stable):", live)
                    self.speaker.speak(live, interrupt=not spoke_highlight)
                    self.last_spoken_live = live
                    self.pending_live = None
                    self.pending_live_seen_count = 0
            else:
                self.pending_live = live
                self.pending_live_seen_count = 1


def run_reader(args, speaker):
    from game_a11y_core.lifecycle import (
        acquire_named_mutex,
        close_handle,
        create_stop_event,
        find_window_for_process,
    )

    instance = acquire_named_mutex(INSTANCE_MUTEX_NAME)
    if instance is None:
        print("Another reader instance is already running; exiting.")
        if not args.background:
            speaker.speak("The accessibility reader is already running.")
            speaker.wait_until_done()
        return 0

    stop_event = create_stop_event(STOP_EVENT_NAME)
    try:
        library = load_library()
        print(f"Loaded {len(library.entries)} verified screens into the recognition library.")
        reader = Reader(args, speaker, library, stop_event)
        if not args.background:
            game_running = find_window_for_process(PROCESS_NAME) is not None
            speaker.speak("Accessibility reader ready." + ("" if game_running else " Waiting for the game."))
        return reader.run()
    finally:
        close_handle(stop_event)
        close_handle(instance)


def stop_running_reader(speaker, quiet):
    from game_a11y_core.lifecycle import named_mutex_exists, signal_stop_event

    def say(text):
        if not quiet:
            speaker.speak(text)
            speaker.wait_until_done()

    if not named_mutex_exists(INSTANCE_MUTEX_NAME):
        print("--stop: no reader is running.")
        say("The accessibility reader was not running.")
        return 0

    signalled = False
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while named_mutex_exists(INSTANCE_MUTEX_NAME) and time.monotonic() < deadline:
        # Retried, not sent once: a reader that has only just started may
        # own its mutex for a moment before its stop event exists.
        if not signalled:
            signalled = signal_stop_event(STOP_EVENT_NAME)
        time.sleep(0.2)

    if named_mutex_exists(INSTANCE_MUTEX_NAME):
        print(f"--stop: reader still running after {STOP_WAIT_SECONDS}s.")
        say("The accessibility reader did not stop. Try again, or restart Windows.")
        return 1
    print("--stop: reader stopped.")
    say("Accessibility reader stopped.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Before anything touches a window - see frames.py for what went wrong
    # without it.
    dpi_mode = frames.enable_dpi_awareness() if sys.platform == "win32" else "n/a"
    _setup_output(argv)
    args = parse_args(argv)
    _open_log()
    print(f"DPI awareness: {dpi_mode}")

    from game_a11y_core.speech import Speaker

    mode = "stop" if args.stop else "self-test" if args.self_test else "reader"
    print(f"{PROG_NAME} {__version__} starting ({mode}; args: {' '.join(argv) or 'none'})")
    speaker = Speaker(app_paths.nvda_dll_path(), mode=args.speech)

    if args.stop:
        return stop_running_reader(speaker, args.quiet)
    if args.self_test:
        from self_test import run_self_test

        return run_self_test(args, speaker)
    return run_reader(args, speaker)


if __name__ == "__main__":
    sys.exit(main())
