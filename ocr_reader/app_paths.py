"""
Where the reader reads its bundled files from and writes its own files to.

Two different places, on purpose:

- RESOURCE_DIR holds what ships with the reader (the known_screens/ library
  and the NVDA controller DLL). Running from source that's this folder;
  running as the packaged program it's PyInstaller's bundle folder, which
  sits under the install directory and must be treated as read-only.
- DATA_DIR holds everything the reader writes (log, unrecognised-screen
  captures, developer F2 captures): %LOCALAPPDATA%\\MKXAccess.
  Before 2026-10 the reader wrote all of this next to its own script, which
  only worked because it was always run from a source checkout - an
  installed copy can't rely on its own folder being writable.

Set MKX_ACCESS_DATA_DIR to point DATA_DIR somewhere else (the tests
and CI smoke tests do this so they never touch a real user profile).
"""

import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR_ENV_VAR = "MKX_ACCESS_DATA_DIR"
DATA_DIR_NAME = "MKXAccess"


def data_dir():
    override = os.environ.get(DATA_DIR_ENV_VAR)
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, DATA_DIR_NAME)


def bundled_known_screens_dir():
    return os.path.join(RESOURCE_DIR, "known_screens")


def user_known_screens_dir():
    """Where F2 (developer mode) saves candidate screens, and an extra
    directory the library also loads from. From a source checkout that's the
    repo's own known_screens/, same as always, so a capture can be reviewed
    and committed. Installed, it's under DATA_DIR - the bundle is read-only,
    and a reviewed screen dropped here is picked up on the next start
    without rebuilding."""
    if FROZEN:
        return os.path.join(data_dir(), "known_screens")
    return bundled_known_screens_dir()


def library_dirs():
    dirs = [bundled_known_screens_dir()]
    user_dir = user_known_screens_dir()
    if os.path.normcase(os.path.abspath(user_dir)) != os.path.normcase(os.path.abspath(dirs[0])):
        dirs.append(user_dir)
    return dirs


def nvda_dll_path():
    return os.path.join(RESOURCE_DIR, "game_a11y_core", "nvda_controller_client", "x64", "nvdaControllerClient.dll")


def log_file_path():
    return os.path.join(data_dir(), "reader.log")


def library_misses_dir():
    return os.path.join(data_dir(), "library_misses")
