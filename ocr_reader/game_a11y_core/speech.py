"""
Speech output that picks a working voice on every utterance.

Added 2026-10 for the installable build. nvda_speaker.py (still here,
unchanged, used by the MKX reader) only ever spoke through NVDA: if NVDA
wasn't running within 60 seconds the reader beeped and quit, so a JAWS or
Narrator user - or an NVDA user whose NVDA started late - got nothing at
all. Speaker here instead checks, per utterance:

  1. NVDA, through the vendored NVDA Controller Client DLL, if NVDA is
     running right now.
  2. JAWS, through its own COM API (FreedomSci.JawsApi, which every JAWS
     install registers), if JAWS is running right now. Added 2026-10-11:
     without it a JAWS user heard the Windows voice talking over JAWS.
  3. Otherwise the built-in Windows voice (SAPI, via pywin32's COM support).
     This is also what Narrator users hear: Narrator has no public API that
     another program can send text to.

Checking every time (nvdaController_testIfRunning is a cheap local RPC call)
means the reader follows NVDA being started, restarted or closed mid-session
without any special handling. If neither voice works, it beeps - rate-limited,
same as nvda_speaker.py - since a beep is the one signal that still reaches
the user when speech itself is what's broken.

Every utterance is also printed as "SPEAK: ..." so the log records what the
user heard, which is the only way to diagnose "it said the wrong thing"
after the fact. mode="none" does only that (used by tests and CI).
"""

import ctypes
import os

try:
    import winsound
except ImportError:  # non-Windows (only the tests' pure-logic parts run there)
    winsound = None

MODES = ("auto", "nvda", "jaws", "sapi", "none")

# SpeechVoiceSpeakFlags
SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2


def _audible_alert():
    try:
        if winsound is not None:
            winsound.Beep(400, 300)
    except Exception:
        pass


class NvdaBackend:
    name = "NVDA"

    def __init__(self, dll_path):
        self.lib = None
        if not dll_path or not os.path.isfile(dll_path):
            print(f"NVDA controller DLL not found at {dll_path!r}; NVDA output disabled.")
            return
        try:
            lib = ctypes.windll.LoadLibrary(dll_path)
            lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            self.lib = lib
        except (OSError, AttributeError) as exc:
            print(f"Couldn't load the NVDA controller DLL ({exc!r}); NVDA output disabled.")

    def available(self):
        if self.lib is None:
            return False
        try:
            return self.lib.nvdaController_testIfRunning() == 0
        except Exception:
            return False

    def speak(self, text, interrupt):
        if interrupt:
            self.lib.nvdaController_cancelSpeech()
        return self.lib.nvdaController_speakText(text) == 0

    def wait_until_done(self, timeout_seconds):
        pass  # NVDA speaks from its own process; nothing to wait for here


# JAWS's main window class. Tolk and other screen-reader bridges use the
# same check: it exists exactly while JAWS is running.
JAWS_WINDOW_CLASS = "JFWUI2"
JAWS_PROG_ID = "FreedomSci.JawsApi"


def _jaws_window_present():
    try:
        return bool(ctypes.windll.user32.FindWindowW(JAWS_WINDOW_CLASS, None))
    except Exception:
        return False


def _jaws_dispatch():
    import win32com.client

    return win32com.client.Dispatch(JAWS_PROG_ID)


class JawsBackend:
    name = "JAWS"

    def __init__(self, is_running=_jaws_window_present, connect=_jaws_dispatch):
        self._is_running = is_running
        self._connect = connect
        self.api = None
        self._connect_logged = False

    def available(self):
        if not self._is_running():
            # JAWS closed (or was never started): drop the stale COM object
            # so a restarted JAWS gets a fresh connection.
            self.api = None
            return False
        if self.api is None:
            try:
                self.api = self._connect()
                self._connect_logged = False
            except Exception as exc:
                if not self._connect_logged:
                    print(f"JAWS is running but its API couldn't be reached: {exc!r}")
                    self._connect_logged = True
                return False
        return True

    def speak(self, text, interrupt):
        try:
            # SayString(text, flush): flush=True cuts off what JAWS is saying.
            return bool(self.api.SayString(text, bool(interrupt)))
        except Exception:
            self.api = None  # reconnect on the next utterance
            raise

    def wait_until_done(self, timeout_seconds):
        pass  # JAWS speaks from its own process; nothing to wait for here


class SapiBackend:
    name = "Windows voice"

    def __init__(self):
        self.voice = None
        try:
            import win32com.client
            self.voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as exc:
            print(f"Windows voice (SAPI) unavailable: {exc!r}")

    def available(self):
        return self.voice is not None

    def speak(self, text, interrupt):
        flags = SVSF_ASYNC | (SVSF_PURGE_BEFORE_SPEAK if interrupt else 0)
        self.voice.Speak(text, flags)
        return True

    def wait_until_done(self, timeout_seconds):
        # Async speech dies with the process - anything said right before
        # exiting ("Accessibility reader stopped.") has to be waited for.
        try:
            self.voice.WaitUntilDone(int(timeout_seconds * 1000))
        except Exception:
            pass


class Speaker:
    def __init__(self, nvda_dll_path, mode="auto", nvda_factory=NvdaBackend, sapi_factory=SapiBackend,
                 jaws_factory=JawsBackend):
        if mode not in MODES:
            raise ValueError(f"speech mode must be one of {MODES}, not {mode!r}")
        self.mode = mode
        self._nvda = nvda_factory(nvda_dll_path) if mode in ("auto", "nvda") else None
        self._jaws = jaws_factory() if mode in ("auto", "jaws") else None
        self._sapi_factory = sapi_factory if mode in ("auto", "sapi") else None
        self._sapi = None  # created on first need - most NVDA users never need it
        self.current = None
        self.consecutive_failures = 0

    def _sapi_backend(self):
        if self._sapi is None and self._sapi_factory is not None:
            self._sapi = self._sapi_factory()
        return self._sapi

    def _candidates(self):
        if self._nvda is not None:
            yield self._nvda
        if self._jaws is not None:
            yield self._jaws
        if self._sapi_factory is not None:
            yield self._sapi_backend()

    def active_backend_name(self):
        """Which voice would be used right now, or None if none works.
        For the self-test report."""
        if self.mode == "none":
            return "none (log only)"
        for backend in self._candidates():
            if backend.available():
                return backend.name
        return None

    def speak(self, text, interrupt=True):
        """Returns True if some voice accepted the text. interrupt=False
        queues behind whatever is still being said (used for full-screen
        reads so a fast-following selection change can't chop them)."""
        print(f"SPEAK: {text}")
        if self.mode == "none":
            return True
        for backend in self._candidates():
            if not backend.available():
                continue
            try:
                ok = backend.speak(text, interrupt)
            except Exception as exc:
                print(f"{backend.name} speech failed: {exc!r}")
                ok = False
            if ok:
                if backend is not self.current:
                    print(f"Speech output is now: {backend.name}")
                    self.current = backend
                self.consecutive_failures = 0
                return True
        self.consecutive_failures += 1
        if self.current is not None:
            print("Speech output is now: none available")
            self.current = None
        if self.consecutive_failures in (1, 10) or self.consecutive_failures % 60 == 0:
            _audible_alert()
        return False

    def using_screen_reader(self):
        """True when speech is going through NVDA or JAWS rather than a
        separate voice. The self-test uses this to avoid saying its result
        twice: the screen reader already reads the message box."""
        return self.current is not None and self.current.name in ("NVDA", "JAWS")

    def wait_until_done(self, timeout_seconds=10):
        if self.current is not None:
            self.current.wait_until_done(timeout_seconds)
