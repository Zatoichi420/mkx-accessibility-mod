"""
NVDA speech, via the vendored NVDA Controller Client DLL
(nvda_controller_client/, shipped unmodified from NV Access).

Shared verbatim across the MK accessibility readers - this part was
never game-specific. Extracted 2026-09-12 from the Legacy Kollection and
MKX projects' own main.py copies, which had carried an identical bug:
speak() called nvdaController_cancelSpeech() unconditionally before every
utterance, so a full screen-text reading could be chopped mid-sentence by
an immediately following selection-change announcement. Fixed here, once,
via the `interrupt` parameter - callers doing a full screen-text read pass
interrupt=False (queue behind whatever's still being spoken); selection
changes and one-off announcements (toggle, capture confirmation, manual
re-read) keep the old interrupt=True default, since those should cut in
immediately.
"""

import ctypes
import time
import winsound


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
    def __init__(self, dll_path):
        self.lib = ctypes.windll.LoadLibrary(dll_path)
        res = self.lib.nvdaController_testIfRunning()
        if res != 0:
            raise RuntimeError(f"NVDA does not appear to be running: {ctypes.WinError(res)}")
        self.consecutive_failures = 0

    def speak(self, text, interrupt=True):
        """Returns True if NVDA accepted the request, False otherwise.
        nvdaController_speakText/_cancelSpeech return an error_status_t but
        ctypes never raises on a nonzero value - NVDA's own official example
        code doesn't check it either - so without checking it ourselves, NVDA
        restarting or the RPC channel dropping mid-session makes every future
        speak() call a silent no-op forever: the poll loop keeps running,
        screen recognition keeps working, nothing is ever raised for the
        existing try/except to catch, and the user just gets total silence
        with no distinguishing symptom. On failure this beeps (rate-limited,
        not every poll) so there's an audible sign something is wrong, and
        self-heals automatically the next time NVDA accepts a call again -
        no restart needed.

        interrupt=True cancels whatever NVDA is currently saying first
        (the old, only behavior); interrupt=False lets it finish and queues
        this text behind it - use this for a full screen-text reading so a
        fast-following selection announcement doesn't cut it off mid-word."""
        if interrupt:
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


def wait_for_nvda(dll_path, max_wait_seconds=60, retry_interval_seconds=2):
    """NVDA can still be finishing its own startup (voice packs, add-ons)
    when Steam launches the game near-instantly via launch options. A
    one-shot check turns that ordinary timing race into "the reader crashes
    before it ever starts, silently, for the whole session" - retry instead."""
    deadline = time.monotonic() + max_wait_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            return NvdaSpeaker(dll_path)
        except Exception as exc:
            last_error = exc
            print(f"NVDA not ready yet ({exc!r}), retrying...")
            time.sleep(retry_interval_seconds)
    print(f"Giving up waiting for NVDA after {max_wait_seconds}s: {last_error!r}")
    _audible_alert()
    time.sleep(0.2)
    _audible_alert()
    raise RuntimeError("NVDA never became available") from last_error
