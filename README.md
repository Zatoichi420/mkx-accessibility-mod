# Mortal Kombat X — talking menus (screen-reader accessibility)

A planned tool to make **Mortal Kombat X** (Steam, appid `307780`, installed as `MK10`)
usable without sight — starting with the launcher/menus, mode select, character
select, and options, the same scope the sister projects below started with.

**Status: Phase 1 baseline running, Phase 0 research well underway.** A
working OCR + reference-library narrator (ported from Legacy Kollection,
see `ocr_reader/`) is in place, though its `known_screens/` library is
still empty — nobody has captured/verified an MKX screen yet, so today it
falls back to live OCR for everything. In parallel, Phase 0's static/live
memory analysis has already found real, named hook targets for a faster,
exact Phase 2 narrator. See [PROGRESS.md](PROGRESS.md) for the full log.

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

## Legal

No game code or assets included or ever will be. Read-only: this reads values
from the game's own memory/screen at runtime and speaks them, the same
no-modification stance as the sister projects. You need your own legally owned
copy of Mortal Kombat X. Not affiliated with or endorsed by Warner Bros. or
NetherRealm Studios.
