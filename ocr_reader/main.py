"""
Mortal Kombat X accessibility reader (Phase 1 baseline).

Continuously captures the game window and speaks its contents via NVDA.
On each poll, first tries to recognize the current screen against the
hand-verified reference library (known_screens/, matched by perceptual
image hash - see screen_library.py, "the hook"): a match speaks that
screen's pre-verified canonical_text instead of live OCR, which is both
faster and immune to OCR failure modes on stylized game fonts.

If no library entry matches, falls back to live OCR as a best-effort read,
and logs the miss to library_misses/ so it can be reviewed and folded into
the library later.

This is ported near-verbatim from the MK Legacy Kollection accessibility
project's ocr_reader/main.py - same architecture, same hardened reliability
patterns (NVDA startup retry, speak() failure self-heal, PID lock, poll-
failure exit threshold). See that project for the reasoning behind each of
them; only the game-specific bits (process name, highlight-color
calibration) differ here, and the latter is UNCALIBRATED - see the
NEEDS_CALIBRATION comment below. This project's PROGRESS.md also has a
Phase 2 in progress: reading MKX's UI state directly out of process memory
(a PDB shipped with the retail build named real classes like
UIMainMenuScreen and UIGridSelection - see PROGRESS.md), which would let a
narrator built on that be exact and instant instead of guessing from
pixels. This OCR/library baseline exists so there's a working narrator
regardless of how that investigation goes, exactly as it did for Legacy
Kollection when memory-hooking dead-ended there.

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
import ctypes
import io
import json
import os
import re
import time
import winsound

import numpy as np
import win32api
import win32gui
import win32process
from PIL import Image, ImageGrab
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

from screen_library import ScreenLibrary

# Confirmed live 2026-09-08 (see PROGRESS.md): MK10.exe is the actual
# running game process, not a launcher/stub - MKXLauncher.exe hands off to
# it directly and doesn't stay running.
PROCESS_NAME = "MK10.exe"
POLL_INTERVAL_SECONDS = 0.5
REREAD_HOTKEY_VK = 0x78  # VK_F9
CAPTURE_HOTKEY_VK = 0x71  # VK_F2
TOGGLE_HOTKEY_VK = 0x79  # VK_F10 - mute/unmute the reader without closing it
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
NVDA_DLL_PATH = os.path.join(SCRIPT_DIR, "nvda_controller_client", "x64", "nvdaControllerClient.dll")
KNOWN_SCREENS_DIR = os.path.join(SCRIPT_DIR, "known_screens")
LIBRARY_MISSES_DIR = os.path.join(SCRIPT_DIR, "library_misses")
LOCK_FILE_PATH = os.path.join(SCRIPT_DIR, "reader.lock")


def find_window_for_process(process_name):
    target_hwnd = None

    def callback(hwnd, _):
        nonlocal target_hwnd
        if not win32gui.IsWindowVisible(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = None
        try:
            handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
            exe_name = win32process.GetModuleFileNameEx(handle, 0)
        except Exception:
            return True
        finally:
            if handle is not None:
                win32api.CloseHandle(handle)
        if exe_name.lower().endswith(process_name.lower()) and target_hwnd is None:
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
                target_hwnd = hwnd
        return True  # always continue - returning False here triggers a spurious pywin32 exception

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass  # some pywin32 versions raise a bogus error even on clean completion
    return target_hwnd


def capture_window(hwnd):
    """Confirmed live 2026-09-08 (see PROGRESS.md): grabs the whole desktop
    instead of using PrintWindow on `hwnd` directly. PrintWindow worked
    during the game's windowed intro cinematics but went silently dark
    (zero-size capture, no error) once the game settled into its real
    fullscreen main menu - GetWindowRect on the game's own window also
    starts returning a bogus placeholder rect (large negative coordinates)
    at that point, which is the same underlying symptom: whatever mode
    MKX's fullscreen actually is, this window handle stops being a usable
    GDI capture source for it. A screen shows the true fullscreen content
    fine (verified against the game live), so `hwnd` is now only used to
    detect that the game is running at all, not for capture geometry -
    this game has no in-game windowed/borderless option to fall back to
    instead (confirmed via sighted assistance), so this isn't optional.
    """
    return ImageGrab.grab(all_screens=True)


async def ocr_image(img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return []

    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        text = line.text.strip()
        if not text or not line.words:
            continue
        xs = [w.bounding_rect.x for w in line.words]
        ys = [w.bounding_rect.y for w in line.words]
        rights = [w.bounding_rect.x + w.bounding_rect.width for w in line.words]
        bottoms = [w.bounding_rect.y + w.bounding_rect.height for w in line.words]
        bbox = (min(xs), min(ys), max(rights), max(bottoms))
        lines.append({"text": text, "bbox": bbox, "y": min(ys), "x": min(xs)})
    lines.sort(key=lambda l: (l["y"], l["x"]))
    return lines


# NEEDS_CALIBRATION: these values were copied from the MK Legacy Kollection
# project (calibrated for that launcher's cyan-selected/gold-unselected
# style) purely as a starting point - MKX's Scaleform UI almost certainly
# uses a different highlight color scheme and has NOT been sampled yet.
# Capture a real MKX menu screenshot, sample the selected vs. unselected
# text pixel colors, and update these before trusting highlight detection
# in this game. Until then, is_line_highlighted() will likely just never
# fire (safe failure mode: no highlight spoken, not a wrong one).
BRIGHTNESS_THRESHOLD = 300  # sum of R+G+B, to isolate text pixels from dark background
BLUE_MINUS_RED_THRESHOLD = 30  # margin required to call it "selected", avoids borderline noise


def is_line_highlighted(img_array, bbox):
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
    bright_pixels = crop[brightness > BRIGHTNESS_THRESHOLD]
    if len(bright_pixels) < 10:
        return None
    mean_r = bright_pixels[:, 0].mean()
    mean_b = bright_pixels[:, 2].mean()
    return (mean_b - mean_r) > BLUE_MINUS_RED_THRESHOLD


def find_highlighted_text(img: Image.Image, lines):
    img_array = np.array(img.convert("RGB"))
    for line in lines:
        if is_line_highlighted(img_array, line["bbox"]):
            return line["text"]
    return None


def find_highlighted_text_from_entry(img: Image.Image, entry):
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
        if is_line_highlighted(img_array, bbox):
            return text
    return None


def slugify(text, max_words=6):
    words = re.findall(r"[a-z0-9]+", text.lower())[:max_words]
    return "_".join(words) if words else "blank_screen"


def save_known_screen(img, lines, highlighted_text):
    """Save a screenshot + its live OCR text into known_screens/ as a
    *candidate* library entry. It won't be used for recognition/speech by
    screen_library.py until a canonical_text field is added by hand after
    reviewing the saved image (raw OCR text is not trusted for speech)."""
    os.makedirs(KNOWN_SCREENS_DIR, exist_ok=True)
    screen_texts = [l["text"] for l in lines]
    slug = slugify(" ".join(screen_texts))

    name = slug
    suffix = 2
    while os.path.exists(os.path.join(KNOWN_SCREENS_DIR, name + ".png")):
        name = f"{slug}_{suffix}"
        suffix += 1

    img.convert("RGB").save(os.path.join(KNOWN_SCREENS_DIR, name + ".png"))
    data = {
        "screen_id": name,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "live_capture",
        "canonical_text": None,  # needs hand verification before this entry is used for recognition
        "highlighted": highlighted_text,
        "capture_size": list(img.size),  # validated against the live frame before trusting stored bboxes - see find_highlighted_text_from_entry
        "ocr_lines_raw": [{"text": l["text"], "bbox": l["bbox"]} for l in lines],
    }
    with open(os.path.join(KNOWN_SCREENS_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return name


def log_library_miss(img, screen_texts):
    """A screen was stably read via live OCR because it didn't match
    anything in the library. Save it so it can be reviewed and folded into
    known_screens/ (with hand-verified canonical_text) later."""
    os.makedirs(LIBRARY_MISSES_DIR, exist_ok=True)
    slug = slugify(" ".join(screen_texts)) if screen_texts else "blank_screen"
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_{slug}"
    img.convert("RGB").save(os.path.join(LIBRARY_MISSES_DIR, name + ".png"))
    with open(os.path.join(LIBRARY_MISSES_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"ocr_text": screen_texts}, f, indent=2)


def _audible_alert():
    """A beep is audible even when NVDA itself is the thing that's broken -
    the one signal that can reach the user when the tool whose entire job is
    producing audio has stopped doing so. Never let a failure here (e.g. no
    sound device) become a second exception on top of the first."""
    try:
        winsound.Beep(400, 300)
    except Exception:
        pass


class NvdaSpeaker:
    def __init__(self):
        self.lib = ctypes.windll.LoadLibrary(NVDA_DLL_PATH)
        res = self.lib.nvdaController_testIfRunning()
        if res != 0:
            raise RuntimeError(f"NVDA does not appear to be running: {ctypes.WinError(res)}")
        self.consecutive_failures = 0

    def speak(self, text):
        """Returns True if NVDA accepted the request, False otherwise.
        nvdaController_speakText/_cancelSpeech return an error_status_t but
        ctypes never raises on a nonzero value, so without checking it
        ourselves, NVDA restarting or the RPC channel dropping mid-session
        makes every future speak() call a silent no-op forever. On failure
        this beeps (rate-limited, not every poll) so there's an audible sign
        something is wrong, and self-heals automatically the next time NVDA
        accepts a call again - no restart needed."""
        self.lib.nvdaController_cancelSpeech()
        res = self.lib.nvdaController_speakText(text)
        if res == 0:
            self.consecutive_failures = 0
            return True
        self.consecutive_failures += 1
        print(f"NVDA speak failed (error {res}), consecutive failures={self.consecutive_failures}")
        if self.consecutive_failures in (1, 10) or self.consecutive_failures % 60 == 0:
            _audible_alert()
        return False


def wait_for_nvda(max_wait_seconds=60, retry_interval_seconds=2):
    """NVDA can still be finishing its own startup (voice packs, add-ons)
    when Steam launches the game near-instantly via launch options. A
    one-shot check turns that ordinary timing race into "the reader crashes
    before it ever starts, silently, for the whole session" - retry instead."""
    deadline = time.monotonic() + max_wait_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            return NvdaSpeaker()
        except Exception as exc:
            last_error = exc
            print(f"NVDA not ready yet ({exc!r}), retrying...")
            time.sleep(retry_interval_seconds)
    print(f"Giving up waiting for NVDA after {max_wait_seconds}s: {last_error!r}")
    _audible_alert()
    time.sleep(0.2)
    _audible_alert()
    raise RuntimeError("NVDA never became available") from last_error


def _pid_is_running(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        STILL_ACTIVE = 259
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def acquire_single_instance_lock():
    """Prevent two readers from running at once and talking over each other
    on NVDA. A PID lock file has no external dependency: a stale lock (the
    PID it names is no longer alive, e.g. after a hard kill) is detected and
    safely taken over."""
    my_pid = os.getpid()
    if os.path.exists(LOCK_FILE_PATH):
        try:
            with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
                existing_pid = int(f.read().strip())
        except (ValueError, OSError):
            existing_pid = None
        if existing_pid is not None and existing_pid != my_pid and _pid_is_running(existing_pid):
            return False
    with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(str(my_pid))
    return True


def release_single_instance_lock():
    try:
        if os.path.exists(LOCK_FILE_PATH):
            with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(LOCK_FILE_PATH)
    except OSError:
        pass


def was_key_pressed_since_last_check(vk):
    """Edge-triggered, not level-triggered: GetAsyncKeyState's low-order bit
    latches "this key was pressed at some point since the last call for this
    vk" and clears on read. A plain "is it down right now" check (the high
    bit alone) can miss a real keypress entirely if it happens to fall
    between two ~0.5s polls - a normal keyboard tap is often under 150ms,
    well inside that gap. The latch bit can't miss it: it stays set across
    any number of polls until someone reads it."""
    return (win32api.GetAsyncKeyState(vk) & 0x1) != 0


def main():
    print("MKX accessibility reader starting...")

    if not acquire_single_instance_lock():
        print("Another reader instance is already running; exiting.")
        return

    try:
        speaker = wait_for_nvda()
        print("NVDA connection OK.")

        library = ScreenLibrary()
        print(f"Loaded {len(library.entries)} verified screens into the recognition library.")

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
                if was_key_pressed_since_last_check(TOGGLE_HOTKEY_VK):
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

                img = capture_window(hwnd)
                if img is None:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                force_reread = was_key_pressed_since_last_check(REREAD_HOTKEY_VK)
                force_capture = was_key_pressed_since_last_check(CAPTURE_HOTKEY_VK)

                if force_capture:
                    lines = asyncio.run(ocr_image(img))
                    highlighted_text = find_highlighted_text(img, lines)
                    name = save_known_screen(img, lines, highlighted_text)
                    print(f"Captured candidate library screen: {name}")
                    speaker.speak("Captured: " + name.replace("_", " ") + ". Needs review before it will be read automatically.")
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                match_result = library.match(img)

                if force_reread:
                    if match_result:
                        entry, distance = match_result
                        print(f"Manual re-read (F9): library match '{entry['screen_id']}' (distance={distance}).")
                        highlighted_text = find_highlighted_text_from_entry(img, entry)
                        to_speak = highlighted_text if highlighted_text else ". ".join(entry["canonical_text"])
                        screen_key = ("lib", entry["screen_id"])
                    else:
                        lines = asyncio.run(ocr_image(img))
                        screen_texts = [l["text"] for l in lines]
                        highlighted_text = find_highlighted_text(img, lines)
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

                # --- Determine what's on screen this poll, library-first ---
                if match_result:
                    entry, distance = match_result
                    screen_key = ("lib", entry["screen_id"])
                    screen_payload = ". ".join(entry["canonical_text"])
                    screen_ocr_texts = None  # not applicable in library mode
                    highlighted_text = find_highlighted_text_from_entry(img, entry)
                else:
                    lines = asyncio.run(ocr_image(img))
                    screen_texts = [l["text"] for l in lines]
                    screen_key = ("ocr", tuple(screen_texts))
                    screen_payload = ". ".join(screen_texts) if screen_texts else None
                    screen_ocr_texts = screen_texts
                    highlighted_text = find_highlighted_text(img, lines)

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
                        speaker.speak(screen_payload)
                        if screen_key[0] == "ocr":
                            log_library_miss(img, screen_ocr_texts)
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
        release_single_instance_lock()


if __name__ == "__main__":
    main()
