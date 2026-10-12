"""
Process/window discovery and single-instance locking. Shared verbatim
across the MK accessibility readers - extracted 2026-09-12, no game-
specific content. Lock/window paths are passed in by the caller rather
than hardcoded, since each game repo keeps its own reader.lock.
"""

import ctypes
import functools
import os

import win32api
import win32gui
import win32process


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


def acquire_single_instance_lock(lock_file_path):
    """Prevent two readers from running at once and talking over each other
    on NVDA. A PID lock file has no external dependency: a stale lock (the
    PID it names is no longer alive, e.g. after a hard kill) is detected and
    safely taken over."""
    my_pid = os.getpid()
    if os.path.exists(lock_file_path):
        try:
            with open(lock_file_path, "r", encoding="utf-8") as f:
                existing_pid = int(f.read().strip())
        except (ValueError, OSError):
            existing_pid = None
        if existing_pid is not None and existing_pid != my_pid and _pid_is_running(existing_pid):
            return False
    with open(lock_file_path, "w", encoding="utf-8") as f:
        f.write(str(my_pid))
    return True


def release_single_instance_lock(lock_file_path):
    try:
        if os.path.exists(lock_file_path):
            with open(lock_file_path, "r", encoding="utf-8") as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(lock_file_path)
    except OSError:
        pass


# --- Named kernel objects (added 2026-10 for the installed build) ---
#
# The PID lock file above needs a writable folder next to the script and can
# be fooled by Windows reusing a dead reader's PID for an unrelated process
# (the reader then refuses to start until that process ends). A named mutex
# has neither problem: Windows destroys it the moment its owner exits, however
# it exits. A named event gives `--stop` a way to ask a running reader to
# shut down cleanly instead of killing it. "Local\" scopes both to the
# signed-in user's session.

_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000
_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0


@functools.lru_cache(maxsize=None)
def _kernel32():
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenMutexW.restype = wintypes.HANDLE
    k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenEventW.restype = wintypes.HANDLE
    k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.ResetEvent.argtypes = [wintypes.HANDLE]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return k32


def acquire_named_mutex(name):
    """Returns a handle if this process now owns `name`, or None if another
    process already holds it. Keep the handle open for the process's life;
    close_handle() it (or just exit) to release."""
    k32 = _kernel32()
    handle = k32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == _ERROR_ALREADY_EXISTS:
        k32.CloseHandle(handle)
        return None
    return handle


def named_mutex_exists(name):
    k32 = _kernel32()
    handle = k32.OpenMutexW(_SYNCHRONIZE, False, name)
    if handle:
        k32.CloseHandle(handle)
        return True
    return False


def create_stop_event(name):
    """Manual-reset event, cleared on creation so a stale signal left over
    from an earlier --stop can't stop a freshly started reader."""
    k32 = _kernel32()
    handle = k32.CreateEventW(None, True, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    k32.ResetEvent(handle)
    return handle


def signal_stop_event(name):
    """True if a reader's stop event existed and was signalled."""
    k32 = _kernel32()
    handle = k32.OpenEventW(_EVENT_MODIFY_STATE, False, name)
    if not handle:
        return False
    try:
        return bool(k32.SetEvent(handle))
    finally:
        k32.CloseHandle(handle)


def wait_for_event(handle, seconds):
    """Sleep up to `seconds`, returning True early if the event is signalled.
    Use in place of time.sleep() so a stop request is noticed promptly."""
    return _kernel32().WaitForSingleObject(handle, max(0, int(seconds * 1000))) == _WAIT_OBJECT_0


def close_handle(handle):
    if handle:
        _kernel32().CloseHandle(handle)


def window_process_id(hwnd):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid


def foreground_process_id():
    """PID owning the window the user is currently in, or None."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    return window_process_id(hwnd)
