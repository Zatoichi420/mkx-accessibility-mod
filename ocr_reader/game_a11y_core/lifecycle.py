"""
Process/window discovery and single-instance locking. Shared verbatim
across the MK accessibility readers - extracted 2026-09-12, no game-
specific content. Lock/window paths are passed in by the caller rather
than hardcoded, since each game repo keeps its own reader.lock.
"""

import ctypes
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
