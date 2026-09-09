# Mortal Kombat X — talking menus (screen-reader accessibility)

A planned tool to make **Mortal Kombat X** (Steam, appid `307780`, installed as `MK10`)
usable without sight — starting with the launcher/menus, mode select, character
select, and options, the same scope the sister projects below started with.

**Status: confirmed working live, 2026-09-08.** The reader narrates the
main menu, the pause menu, and Steam's own UI via live OCR — its
`known_screens/` reference library is still empty (nobody's hand-verified
an entry yet), so today everything is read via live OCR rather than a
pre-verified library, but it works end-to-end right now. F9 (re-read), F10
(on/off toggle), and F2 (capture a screen for the library) all work, as
long as the reader is started by you directly rather than by an outside
tool. In parallel, Phase 0/2's memory analysis has already found the
concrete field (`UIGridSelectionCursor::selectionTableIndex`) a future,
faster, exact narrator would read instead of guessing from pixels. See
[PROGRESS.md](PROGRESS.md) for the full log and
[CONTRIBUTING.md](CONTRIBUTING.md) for what would help most right now.

## Setup

Double-click **`install.bat`**. That's it — it installs the Python
dependencies, checks NVDA is running, and adds a shortcut to your Windows
Startup folder so the reader quietly starts itself every time you log in
and waits (using almost no resources) until it sees Mortal Kombat X
running. You never have to remember to launch anything, and there's
nothing to configure in Steam or anywhere else — unlike the GameCube
sister projects below, where digging into RetroArch's network-command
settings was the single biggest setup complaint, this has no equivalent
step: no external emulator, no config file to edit, no admin rights
needed (it uses your personal Startup folder, not Task Scheduler).

To remove it later, run `uninstall.bat` — it deletes the Startup shortcut
and nothing else (your `known_screens/` captures are untouched).

Prefer to run it by hand instead of auto-starting? `python ocr_reader/main.py`
works the same way `install.bat` runs it, just not automatic.

While it's running: **F9** re-reads the current screen, **F10** toggles the
reader on/off (announces itself either way, so silence never means "is
this broken?"), and **F2** saves the current screen as a candidate
[known_screens](ocr_reader/known_screens) entry. These only respond if you
started the reader yourself (double-click, or a real Windows login) — see
[PROGRESS.md](PROGRESS.md) if a hotkey ever seems unresponsive.

## Sister projects (same author, same overall approach)

- [mk-legacy-kollection-accessibility-mod](https://github.com/Zatoichi420/mk-legacy-kollection-accessibility-mod) —
  OCR + perceptual-hash screen-matching narrator, speaks via NVDA. Built because the
  Legacy Kollection's Dear ImGui launcher has no accessibility tree and its binary
  is stripped (no PDB) — memory hooking was a confirmed dead end there.
- [mortal-kombat-deadly-alliance-accessibility](https://github.com/Zatoichi420/mortal-kombat-deadly-alliance-accessibility) —
  reads the GameCube game's RAM live over RetroArch's network command interface,
  matches the active screen against a reverse-engineered symbol map, speaks via
  OS TTS. No OCR, no guessing — the more mature "read the real state" approach.
- [MK-deception-accessibility-mod](https://github.com/Zatoichi420/MK-deception-accessibility-mod) —
  same technique as Deadly Alliance, sister GameCube title.

MKX is a native Windows PC game, not an emulated one, so the RetroArch transport
those last two rely on doesn't exist here — but the underlying idea (find the
game's real screen/cursor state and read it directly, instead of OCR-guessing)
carries over via `ReadProcessMemory` against the game's own process. See
PROGRESS.md for what's already been scouted on this machine's actual MKX install
that makes this look more promising than the Legacy Kollection situation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for what would help most right now —
`known_screens/` library entries and highlight-color calibration are the
top two. Be kind: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Legal

No game code or assets included or ever will be. Read-only: this reads values
from the game's own memory/screen at runtime and speaks them, the same
no-modification stance as the sister projects. You need your own legally owned
copy of Mortal Kombat X. Not affiliated with or endorsed by Warner Bros. or
NetherRealm Studios. See [LICENSE](LICENSE) (MIT).
