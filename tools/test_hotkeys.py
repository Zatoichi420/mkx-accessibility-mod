"""Standalone hotkey test - speaks each detected keypress aloud via NVDA,
live, so it's directly usable without needing to read a log file
afterward. Run this by double-clicking test_hotkeys.bat (NOT via a tool
that launches it - see PROGRESS.md's "Important operational finding":
GetAsyncKeyState only works for a process started directly by you, not
one launched by Claude's automation. This script only means anything if
you're the one who started it).

Watches F1, F9, F10, Enter, and Escape for 60 seconds and announces each
one the moment it's detected.
"""
import ctypes
import os
import time
import win32api

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NVDA_DLL_PATH = os.path.join(SCRIPT_DIR, "..", "ocr_reader", "nvda_controller_client", "x64", "nvdaControllerClient.dll")

KEYS = {
    "F1": 0x70,
    "F9": 0x78,
    "F10": 0x79,
    "Enter": 0x0D,
    "Escape": 0x1B,
}

DURATION_SECONDS = 60


def main():
    lib = ctypes.windll.LoadLibrary(NVDA_DLL_PATH)
    if lib.nvdaController_testIfRunning() != 0:
        print("NVDA does not appear to be running - start NVDA first.")
        return

    def speak(text):
        lib.nvdaController_cancelSpeech()
        lib.nvdaController_speakText(text)
        print(text)

    for vk in KEYS.values():
        win32api.GetAsyncKeyState(vk)  # clear stale state

    speak(f"Hotkey test running for {DURATION_SECONDS} seconds. Press F1, F9, F10, Enter, or Escape.")

    end_time = time.monotonic() + DURATION_SECONDS
    detected_count = 0
    while time.monotonic() < end_time:
        for name, vk in KEYS.items():
            if win32api.GetAsyncKeyState(vk) & 0x1:
                detected_count += 1
                speak(f"{name} detected.")
        time.sleep(0.03)

    if detected_count == 0:
        speak("Hotkey test finished. No keys were detected the whole time - something is wrong.")
    else:
        speak(f"Hotkey test finished. Detected {detected_count} keypress or keypresses. Working correctly.")


if __name__ == "__main__":
    main()
