# Mortal Kombat X Accessibility Reader

Speaks the menus of **Mortal Kombat X** (Windows, Steam, including the XL content) for blind and low-vision players. It reads each menu screen when it appears, and the highlighted item as you move through a menu. It speaks through NVDA or JAWS, and through the Windows voice for Narrator users or when no screen reader is running.

The game draws its menus as pictures, so screen readers can't see them on their own. This reader runs alongside the game, takes screenshots of it, recognises the text, and speaks it. It doesn't change the game or any of its files.

**Status:** pre-release. An earlier version of this reader read the main menu, the pause menu and The Krypt aloud in a live test on 2026-09-08. The installable version described here has been built and passes its automated tests, but hasn't been tried against the real game yet. Its library of known screens is still empty, so every screen is read with Windows text recognition. See [PROGRESS.md](PROGRESS.md).

## What it reads

- Every menu screen, using Windows text recognition (OCR), cleaned up against a list of the words this game uses. Each new screen is read in full and ends with what's selected, for example "Selected: Krypt". Moving the cursor reads just the new item.
- Press **F9** to hear a screen again.

### Known limits

- The title screen says "PRESS THE A BUTTON". It isn't known yet whether a keyboard key also works there. A controller does.
- The reader works out which item is highlighted from its colour, and the colour settings haven't been tuned for this game yet. If the highlighted item isn't announced as you move, F9 still reads the whole screen.
- Fights, online modes and Faction Wars aren't covered.

## What you need

- Windows 10 or 11, 64-bit.
- Mortal Kombat X on Steam.
- A screen reader is optional:
  - **NVDA** or **JAWS**: the reader speaks through it, in your voice and settings.
  - **Windows Narrator**: Narrator doesn't let other programs speak through it, so the reader uses the Windows voice alongside Narrator.
  - **No screen reader**: the reader uses the Windows voice.
  - If NVDA or JAWS starts, stops or restarts while you play, the reader switches voice on its own.
- **Windows text recognition** (OCR). It's normally installed along with English. If it's missing, the reader tells you; see [Troubleshooting](#troubleshooting).

## Install

1. Go to the [Releases page](https://github.com/Zatoichi420/mkx-accessibility-mod/releases/latest) and download the file whose name starts with `MKX-Access-Setup`.
2. Your browser may warn that the file isn't commonly downloaded. Choose to keep it.
3. Run the file. Because the installer isn't code-signed, Windows may show a **"Windows protected your PC"** screen. Activate the **More info** link, then the **Run anyway** button.
4. Follow the setup wizard. It doesn't ask for administrator rights. Its one option, ticked by default, is **Start the reader automatically when I sign in to Windows**. The reader stays silent until the game is open.
5. On the last page, leave **Start the accessibility reader now** ticked and choose **Finish**. You should hear "Accessibility reader ready. Waiting for the game."

**If you used the older version** (`install.bat`): Setup removes its "MKX Accessibility Reader" shortcut from your Startup folder, so it won't start at your next sign-in. If it's running right now, restart Windows or end its `python` process, so two readers don't talk at once.

## Using it

1. Start the game from Steam as usual. When the reader finds it you'll hear **"Game window found."**
2. Each new menu screen is read in full, and the highlighted item is read as you move.

Keys, which only work while the game is the focused window:

- **F9** reads the current screen, or the highlighted item, again.
- **F10** turns the reader off or on. It always tells you which.

If you switch away from the game (for example with Alt+Tab), the reader pauses, and reads the screen again when you come back. On some laptops you need to hold **Fn** for F9 and F10.

### Start menu entries

Press the Windows key and type **accessibility reader**:

- **Start accessibility reader** and **Stop accessibility reader**.
- **Check accessibility reader**: reports which voice is in use, whether text recognition is installed, whether the reader and the game are running, and whether it starts at sign-in. It shows the result in a message box your screen reader will read.
- **Read me**, and **Uninstall accessibility reader**.

## Troubleshooting

**Nothing is spoken at all.** Run **Check accessibility reader**. If it says the reader isn't running, run **Start accessibility reader**.

**You hear a low beep instead of speech.** No voice was available. Start NVDA or JAWS; the reader switches to it automatically.

**"Windows text recognition is not installed".** Open **PowerShell as administrator** and run:

```
Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"
```

Then use **Stop accessibility reader** and **Start accessibility reader**.

**A screen is read wrongly, or not at all.** Press F9 to try again. Screens the reader doesn't recognise are saved in its data folder so they can be added to the library later.

**The log file**: press **Windows+R**, type `%LOCALAPPDATA%\MKXAccess` and press Enter. The log is `reader.log`; unrecognised screens are in `library_misses`.

## Uninstall

Use **Uninstall accessibility reader** in the Start menu, or Settings, Apps, Installed apps. This also turns off starting at sign-in.

## Privacy

The reader works entirely on your PC and never connects to the internet. It takes screenshots of the game only, and keeps the 50 most recent unrecognised screens in its data folder. Nothing is sent anywhere.

## Reporting problems

Open an issue on [GitHub](https://github.com/Zatoichi420/mkx-accessibility-mod/issues). Say which screen you were on and what you heard or expected to hear, and attach `reader.log` if you can.

## Command-line options

The program is `mkx-access.exe` in the install folder:

- `--stop`: ask a running reader to stop, and wait until it has.
- `--self-test`: the check described above. Add `--quiet` for no dialog or speech, and `--report-file PATH` to save the results as JSON.
- `--background`: don't announce startup. Start-at-sign-in uses this.
- `--speech auto|nvda|jaws|sapi|none`: choose the voice. `auto` uses NVDA, then JAWS, then the Windows voice.
- `--ignore-focus`: keep reading when the game isn't the focused window.
- `--dev`: developer mode; **F2** saves the current screen as a library candidate.
- `--version`.

## For developers

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and how the code is organised. `game_a11y_core/` is shared with the [Legacy Kollection](https://github.com/Zatoichi420/mk-legacy-kollection-accessibility-mod) and [MK9](https://github.com/Zatoichi420/mk9-accessibility-mod) readers. `ocr_reader/memory_provider.py` and `tools/` are research into reading the game's memory with the PDB that ships with MKX. They aren't part of the reader; [PROGRESS.md](PROGRESS.md) explains why the first approach can't work and what to try next.

Be kind: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Licence

MIT; see [LICENSE](LICENSE). See [NOTICE](NOTICE) for trademarks and the bundled NVDA Controller Client (LGPL 2.1). Not affiliated with Warner Bros. or NetherRealm Studios. You need your own legally owned copy of the game.
