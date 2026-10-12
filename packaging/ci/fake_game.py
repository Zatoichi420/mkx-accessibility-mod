"""
A stand-in for the game, for the CI end-to-end test (smoke_test.py).

Run under a copy of python.exe renamed MK10.exe, so the
reader finds it by process name exactly as it finds the real game. Shows a
borderless window displaying a library screenshot, rebuilt as the full
1920x1080 frame it was cropped from and then scaled to the window size -
so the test also covers a resolution other than the development PC's.

    MK10.exe fake_game.py CONTROL_FILE WIDTH HEIGHT

CONTROL_FILE holds the path of the library PNG to show; rewrite it to
switch screens. Delete it to quit.
"""

import os
import sys
import tkinter as tk

from PIL import Image, ImageTk

REFERENCE_SIZE = (1920, 1080)


def full_frame(png_path, size):
    with Image.open(png_path) as img:
        view = img.convert("RGB")
    full = Image.new("RGB", REFERENCE_SIZE)
    full.paste(view, (0, 0))
    return full.resize(size, Image.LANCZOS)


def main():
    control_file, width, height = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    root = tk.Tk()
    root.title("Fake MKX")
    root.overrideredirect(True)  # borderless, like the real game: window == client area
    root.geometry(f"{width}x{height}+0+0")
    root.attributes("-topmost", True)
    label = tk.Label(root, borderwidth=0, highlightthickness=0)
    label.pack(fill="both", expand=True)
    state = {"shown": None, "photo": None}

    def poll():
        if not os.path.exists(control_file):
            root.destroy()
            return
        with open(control_file, encoding="utf-8") as f:
            wanted = f.read().strip()
        if wanted and wanted != state["shown"]:
            state["photo"] = ImageTk.PhotoImage(full_frame(wanted, (width, height)))
            label.configure(image=state["photo"])
            state["shown"] = wanted
            print(f"showing {wanted}", flush=True)
        root.after(200, poll)

    poll()
    root.mainloop()


if __name__ == "__main__":
    main()
