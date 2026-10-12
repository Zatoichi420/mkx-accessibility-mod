#!/usr/bin/env python3
"""
Checks the BUILT program and installer on Windows (CI runs this after
packaging/build.py). Everything runs with --speech none, so "what the user
would have heard" is read back from the log's SPEAK: lines, and with
MKX_ACCESS_DATA_DIR pointed at a temp folder.

  1. --self-test passes and finds the screen library.
  2. Background start, waits for the game, --stop shuts it down cleanly.
  3. A second copy refuses to run alongside the first.
  4. End to end: a stand-in game window (fake_game.py) shows two synthetic
     library screens at 960x540; the reader must find it and speak each
     screen's verified text.
  5. Setup.exe installs silently (per-user, with start-at-sign-in), and the
     uninstaller removes the files and the sign-in entry again.

What this can't cover: the real game, real NVDA or Windows voice output, or
150% display scaling - see docs/LIVE-TEST-CHECKLIST.md for the human pass.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.join(ROOT, "dist", "mkx-access", "mkx-access.exe")
KNOWN = os.path.join(ROOT, "ocr_reader", "known_screens")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MKXAccess"

failures = []


def check(condition, message):
    print(("PASS " if condition else "FAIL ") + message, flush=True)
    if not condition:
        failures.append(message)
    return condition


def wait_for(predicate, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class DataDir:
    def __init__(self, name):
        self.path = tempfile.mkdtemp(prefix=f"mkla-{name}-")
        self.env = dict(os.environ, MKX_ACCESS_DATA_DIR=self.path)

    def log(self):
        try:
            with open(os.path.join(self.path, "reader.log"), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def run(self, *args, timeout=60):
        return subprocess.run([EXE, *args], env=self.env, timeout=timeout)

    def start(self, *args):
        return subprocess.Popen([EXE, *args], env=self.env)


def stop_and_wait(data, proc, label):
    result = data.run("--stop", "--quiet")
    check(result.returncode == 0, f"{label}: --stop exits 0 (got {result.returncode})")
    try:
        code = proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = None
    check(code == 0, f"{label}: reader exits cleanly after --stop (got {code})")


def test_self_test():
    data = DataDir("selftest")
    report_path = os.path.join(data.path, "report.json")
    result = data.run("--self-test", "--quiet", "--speech", "none", "--report-file", report_path)
    check(result.returncode == 0, f"--self-test exits 0 (got {result.returncode})")
    if check(os.path.isfile(report_path), "--self-test writes its report"):
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        print(json.dumps(report, indent=2))
        expected = sum(1 for n in os.listdir(KNOWN) if n.endswith(".json")
                       and json.load(open(os.path.join(KNOWN, n), encoding="utf-8")).get("canonical_text"))
        check(report["library_entries"] == expected, f"library loaded ({report['library_entries']} of {expected} screens)")
        check(report["library_mismatches"] == [], "every library screen recognises itself")
        check(report["nvda_dll_present"], "NVDA controller DLL is bundled")
    check("DPI awareness: per-monitor" in data.log(), "process made itself DPI-aware")


def test_background_and_stop():
    data = DataDir("background")
    proc = data.start("--background", "--speech", "none")
    check(wait_for(lambda: "Waiting for game window" in data.log(), 30), "background reader starts and waits for the game")
    check("SPEAK:" not in data.log(), "background start is silent until the game appears")

    second = data.run("--speech", "none", timeout=30)
    check(second.returncode == 0, "second copy exits immediately")
    check("already running" in data.log(), "second copy reports the reader is already running")
    check(proc.poll() is None, "first copy is still running")

    stop_and_wait(data, proc, "background")
    after = data.run("--stop", "--quiet")
    check(after.returncode == 0, "--stop with nothing running exits 0")


def make_test_screens(directory):
    """Two synthetic library screens, written to the reader's user library.
    This game's shipped library may still be empty, and the test is about
    the find-capture-match-speak pipeline, not any particular menu."""
    from PIL import Image, ImageDraw

    os.makedirs(directory, exist_ok=True)
    shapes = {
        "ci__screen_one": lambda d: d.rectangle((0, 0, 959, 1079), fill=(230, 230, 230)),
        "ci__screen_two": lambda d: [d.rectangle((0, y, 1919, y + 89), fill=(230, 230, 230)) for y in range(0, 1080, 180)],
    }
    expected = {}
    for name, draw in shapes.items():
        img = Image.new("RGB", (1920, 1080))
        draw(ImageDraw.Draw(img))
        img.save(os.path.join(directory, name + ".png"))
        text = ["CI TEST " + name.split("__")[1].replace("_", " ").upper()]
        with open(os.path.join(directory, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"screen_id": name, "canonical_text": text, "capture_size": [1920, 1080]}, f)
        expected[name] = ". ".join(text)
    return expected


def test_end_to_end_with_fake_game():
    data = DataDir("e2e")
    library = os.path.join(data.path, "known_screens")
    expected = make_test_screens(library)
    screens = list(expected)

    # A python.exe renamed to the game's process name, next to the original
    # so it still finds its DLLs and installed packages. In a virtual
    # environment python.exe is only a launcher that starts the real
    # interpreter as a second process, so the window would belong to a
    # process with another name: copy the real one and point it at the
    # environment's packages instead.
    real_python = getattr(sys, "_base_executable", None) or sys.executable
    game_env = dict(os.environ)
    if os.path.normcase(real_python) != os.path.normcase(sys.executable):
        import site
        game_env["PYTHONPATH"] = os.pathsep.join(site.getsitepackages())
    base_dir = os.path.dirname(real_python)
    fake_exe = os.path.join(base_dir, "MK10.exe")
    shutil.copy2(real_python, fake_exe)

    control = os.path.join(data.path, "show.txt")
    with open(control, "w", encoding="utf-8") as f:
        f.write(os.path.join(library, screens[0] + ".png"))
    game = subprocess.Popen([fake_exe, os.path.join(ROOT, "packaging", "ci", "fake_game.py"), control, "960", "540"],
                            env=game_env)
    reader = data.start("--speech", "none", "--ignore-focus")
    try:
        check(wait_for(lambda: "SPEAK: Game window found." in data.log(), 30), "reader finds the stand-in game window by process name")
        check(wait_for(lambda: "Game capture size: 960x540" in data.log(), 15), "capture is the real window size (960x540)")
        check(wait_for(lambda: f"SPEAK: {expected[screens[0]]}" in data.log(), 20), f"speaks {screens[0]} from the library")

        with open(control, "w", encoding="utf-8") as f:
            f.write(os.path.join(library, screens[1] + ".png"))
        check(wait_for(lambda: f"SPEAK: {expected[screens[1]]}" in data.log(), 20), f"speaks {screens[1]} after the screen changes")

        os.remove(control)  # fake game quits
        game.wait(timeout=15)
        check(wait_for(lambda: "Game window closed" in data.log(), 15), "notices the game closing")
        check(reader.poll() is None, "keeps running after the game closes (resident)")
    finally:
        print("---- e2e reader log ----\n" + data.log() + "------------------------")
        if game.poll() is None:
            game.kill()
        stop_and_wait(data, reader, "e2e")
        try:
            os.remove(fake_exe)
        except OSError:
            pass


def run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except OSError:
        return None


def test_installer():
    setups = glob.glob(os.path.join(ROOT, "dist", "MKX-Access-Setup-*.exe"))
    if not check(len(setups) == 1, "exactly one Setup.exe was built"):
        return
    install_dir = tempfile.mkdtemp(prefix="mkla-install-")
    log = os.path.join(install_dir + "-setup.log")
    result = subprocess.run([setups[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                             "/TASKS=autostart", f"/DIR={install_dir}", f"/LOG={log}"], timeout=300)
    check(result.returncode == 0, f"setup exits 0 (got {result.returncode})")
    installed_exe = os.path.join(install_dir, "mkx-access.exe")
    check(os.path.isfile(installed_exe), "program installed")
    for name in ("README.html", "LICENSE.txt", "NOTICE.txt"):
        check(os.path.isfile(os.path.join(install_dir, name)), f"{name} installed")
    value = run_value()
    check(value is not None and installed_exe.lower() in value.lower() and "--background" in value,
          f"start-at-sign-in entry points at the installed program ({value!r})")

    # An upgrade must drop library entries the new version no longer ships.
    stale = os.path.join(install_dir, "_internal", "known_screens", "retired__screen.json")
    with open(stale, "w", encoding="utf-8") as f:
        f.write("{}")
    again = subprocess.run([setups[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                            "/TASKS=autostart", f"/DIR={install_dir}"], timeout=300)
    check(again.returncode == 0 and not os.path.exists(stale), "upgrade removes retired library entries")

    uninstallers = glob.glob(os.path.join(install_dir, "unins*.exe"))
    if not check(len(uninstallers) == 1, "uninstaller present"):
        return
    subprocess.run([uninstallers[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
    # The uninstaller hands off to a temp copy of itself and returns early.
    check(wait_for(lambda: not os.path.exists(installed_exe), 120), "uninstall removes the program")
    check(wait_for(lambda: run_value() is None, 30), "uninstall removes the start-at-sign-in entry")


def _restore_run_value(value):
    """The installer test installs and uninstalls under the same sign-in
    entry name as a real install. On a developer's own PC, put their entry
    back afterwards (found 2026-10-12: running this removed it)."""
    if value is None:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, value)


def main():
    if not os.path.isfile(EXE):
        sys.exit(f"Build first: {EXE} not found")
    original_run_value = run_value()
    for test in (test_self_test, test_background_and_stop, test_end_to_end_with_fake_game, test_installer):
        print(f"\n=== {test.__name__} ===", flush=True)
        try:
            test()
        except Exception as exc:
            check(False, f"{test.__name__} raised {exc!r}")
    _restore_run_value(original_run_value)
    print(f"\n{len(failures)} failure(s)")
    for message in failures:
        print("  - " + message)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
