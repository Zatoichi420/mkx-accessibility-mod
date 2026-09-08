# MKX Accessibility — plan and progress log

## Goal

NVDA screen-reader narration for Mortal Kombat X's pre-match UI: main menu,
mode select, character select, and options. Not gameplay narration, not
online/Kombat League — see "Out of scope" below, mirrored from the Deception
project's precedent.

## Install facts (scouted 2026-09-08)

- Steam appid `307780`, install dir name `MK10`, at
  `F:\SteamLibrary\steamapps\common\MK10`.
- Real binaries live in `Binaries\Retail\`: `MK10.exe`, `MK10Game.exe`,
  `MKXLauncher.exe`. Which one is the actual running/game process (vs. a
  launcher/stub) needs confirming in Phase 0 — `MK10Game.exe` is the likely
  candidate by name and size (~55 MB, close to `MK10.exe`'s ~56 MB).
- **No anti-cheat found anywhere in the install** (no EasyAntiCheat/BattlEye
  files or services). Unlike a lot of modern competitive games, external
  memory reading here isn't fighting a kernel-level anti-cheat — a real
  advantage over a typical "read a live PC game's memory" project.
- **`MK10.pdb` ships right next to the exe — 352 MB.** Shipping a PDB with a
  retail build is unusual and is the single biggest reason this project looks
  more tractable than Legacy Kollection, where the binary was stripped with
  no PDB and memory-hooking was a confirmed dead end (see that project's
  PROGRESS.md). A PDB this size means function/class names may be recoverable
  with a disassembler — the same kind of lead that let the Deception project
  find a single "active screen procedure pointer" to match against a symbol
  map, instead of reverse-engineering blind.
- `Config\Coalesced.ini` is present — that filename is the convention used by
  Unreal-Engine-3-family titles (MK9/Injustice/MKX all trace back to a
  modified UE3), which would suggest Scaleform/GFx as the UI middleware if
  confirmed. **Not confirmed**: quick ASCII/UTF-16 string scans of `MK10.exe`
  for "Unreal"/"Scaleform" came back empty (possibly packed/obfuscated
  strings, or scanned the wrong binary). Treat engine identity as a Phase 0
  lead, not a fact.

## What's being reused from the other three projects

- **From Legacy Kollection** (`ocr_reader/`): the whole OCR + dHash +
  hand-verified `known_screens/*.json` library architecture, NVDA Controller
  Client DLL speech backend, and the reliability patterns hardened there —
  startup retry + beep fallback, `speak()` return-code checking with
  self-heal, consecutive-poll-failure exit threshold, PID-lock-file
  duplicate-instance protection. This is the fallback path here too, and it's
  the *guaranteed-feasible* baseline regardless of how Phase 0 goes.
- **From Deadly Alliance / Deception**: the "read live game state directly,
  don't guess from pixels" philosophy — matching an active-screen identifier
  against a reverse-engineered symbol map for instant, always-correct
  announcements. Also worth copying their CLI/ops conventions: `--once` /
  `--probe` / `--install` flags, env-var config (host/port equivalents,
  voice, rate, speech backend), and a Task-Scheduler background-service
  install path (Windows-only here, so no per-OS branching needed). Deadly
  Alliance's `docs/HOW-IT-WORKS.md` and `docs/CALIBRATION.md` are good
  templates to copy the *shape* of, not the content.
- **From the C&C/OpenRA work**: mainly a discipline, not code — evaluate
  hook points closest to the real state (source-level in that project) before
  settling for an external/OCR approach. Not directly portable since there's
  no MKX source, but it's why Phase 0 exists instead of jumping straight to
  OCR.
- **Also worth adopting** (flagged previously from the Deadly Alliance repo,
  never done): its issue-template scaffolding (`region_calibration.md`,
  `screen_request.md`) for the "needs a review pass before going live" workflow
  on each newly captured screen — formalize this as templates here from the
  start instead of only tracking it in this file.

## Phase 0 findings (2026-09-08)

**Result: much more tractable than expected. No disassembler needed — the shipped PDB alone is enough to identify real hook targets.**

- **PDB approach, not Ghidra.** Instead of a full Ghidra load, used Windows' own `dbghelp.dll` (via a small ctypes script — no extra install) to call `SymLoadModuleExW`/`SymEnumSymbolsW` against `MK10.exe` + `MK10.pdb`. It resolved cleanly: **493,712 symbols total**, all with real demangled C++ names — the PDB genuinely matches this exe. Script kept at
  `dump_pdb_symbols.py` in the working scratchpad; worth moving into this repo's `tools/` as the project's own symbol-mining script since it'll be needed again for other screens.
- **Scaleform/GFx confirmed** as the UI middleware — thousands of
  `Scaleform::GFx::AS3::...` symbols (their ActionScript3 VM). Combined with
  `Config\Coalesced.ini` and the `tui_*.xxx` (renamed/cooked UE3 package)
  files in `Asset\`, this confirms the UE3-family engine lead from the
  earlier scan, even though plain string search for "Unreal" came back empty
  (names are apparently only reachable via the PDB's symbol table, not loose
  strings in the binary).
- **A real, named UI class hierarchy exists** — this is a heavily-renamed
  NetherRealm fork of UE3 (no `GEngine`/`GWorld`/`GObjects` by their usual UE3
  names — evidently renamed or kept as non-exported statics), but the UI
  layer itself is richly named and directly relevant:
  - `UIMainMenuScreen` — main menu screen class. Has `GetSelectionIndex()`,
    `SetNumMenuOptions()`, `SetMenuOptionText()`, `NUM_COLUMNS`,
    `GRID_SELECT_COLUMN`, `MainMenuNavTable` — everything needed to narrate
    "Item X of Y".
  - `UIGridSelection` / `UIGridSelectWidget` — the generic grid-cursor base
    class used everywhere: `MoveSelection()`, `GetSelectionColumn()`,
    `GetSelectionRow()`, `GetNavTableIndex()`, `GetIsCellLocked()`,
    `GetIsCellHidden()`.
  - Every screen that uses a grid subclasses this: `UIPlayerSelectGridSelectWidget`
    (character select), `UIChapterSelectGridSelectWidget`,
    `UIOptionsGridSelectWidget`, `MK10ScenarioGridSelect`,
    `UIKombatKardCustomizeGridSelectWidget`, `UIChatLobbyGridSelect`,
    `UITestYourLuckSelectGridSelectWidget`, and more — meaning **one narrator
    written against the `UIGridSelection` base API narrates every grid-based
    screen in the game**, not just the main menu.
  - `GameScreenBase` is the base class for screens generally (not just grids)
    — has `StartScreen`, `GetUIScreen`, `ElementSetText`/`ElementGetX/Y`,
    `AsyncLoadUIScreen`/`UnloadUIScreen`.
  - **`GUIScreenManager`** — a global instance of `UIScreenManager`, which
    holds a `TMapBase<FString, UIScreenManager::UIScreenData>` of
    loaded/active screens (`AddScreen`, `AsyncLoadScreen`,
    `SavePersistentScreens`). This is the single most promising lead for
    "what screen is the player on right now" — a named, symbol-resolved
    global, not a blind pointer-chase like Deception had to do. Working out
    its actual memory layout (via the PDB's type info, not just symbol
    names) is the next real reverse-engineering task, not yet done.
- **Community precedent for reading this exact process, confirmed by web
  search**: public Cheat Engine tables/trainers for MKX already exist
  (FearLess Revolution, MK Secrets forums, Cheat Happens) targeting
  `MK10.exe` specifically for gameplay values (health/energy/koins) — this
  independently confirms `MK10.exe` (not `MK10Game.exe`) is the right
  process to attach to, and that external memory reading against this game
  is a well-trodden, unremarkable thing to do.
- **Not yet done**: actually launching the game to confirm the live process
  name matches (`MK10.exe`) and to test attaching/reading against a running
  instance — the PDB work above was all static analysis against the files on
  disk. This is the natural next step but involves launching the full game
  (audio, screen, resources), so it's being held for an explicit go-ahead
  rather than done unprompted.

### Remaining Phase 0 work

1. Launch the game and confirm which process is live (`MK10.exe` expected
   per the above) and that `dbghelp` can attach to a *running* instance the
   same way it read the on-disk files.
2. Use the PDB's type information (not just symbol names — `SymGetTypeInfo`
   in the same dbghelp API) to work out the actual field layout of
   `UIScreenManager` and `UIGridSelection`, so `GUIScreenManager` and a
   live grid-widget instance can be read/interpreted correctly.
3. Scope the tool to **offline/local play only** and say so explicitly in
   the README/legal section, matching Deception's "online out of scope"
   precedent — don't attempt anything against the game's online/matchmaking
   path.

### Phase 1 — Guaranteed-feasible baseline (OCR + reference library)

Port the Legacy Kollection `ocr_reader/` architecture near-verbatim: capture
the MKX window → dHash → match against a hand-built `known_screens/*.json`
library (main menu, mode select, character-select grid, options) → speak via
the NVDA Controller Client DLL. Copy its hardened reliability patterns rather
than re-deriving them. This alone produces working menu narration even if
Phase 0 finds nothing usable, exactly as it did for Legacy Kollection when
memory-hooking dead-ended there.

### Phase 2 — Live memory reads (Phase 0 found strong leads — see above)

Layer in `ReadProcessMemory`-based reads keyed off `GUIScreenManager` and the
`UIGridSelection`/`UIMainMenuScreen` API surface found in Phase 0 — the
Deadly Alliance/Deception technique, with `ReadProcessMemory` against the
local `MK10.exe` process standing in for RetroArch's UDP network-command
transport (no emulator, no middleman needed). The OCR path from Phase 1
stays in place as the fallback for any screen not yet mapped, the same
division of labor Deception itself describes for its own unmapped screens.

### Phase 3 — Calibration and hardening

Build out `known_screens/` (and the symbol/address map, if Phase 2 landed)
for main menu, mode select, character select, and options, with a
documented per-screen review pass before going live — using the
`region_calibration.md` / `screen_request.md` issue templates adopted from
the Deadly Alliance repo.

## Out of scope for v1

Online play / Kombat League / matchmaking, live round-by-round fighting
narration, Krypt loot-grinding minutiae. Mirrors the precedent set in the
Deception project; revisit later if the baseline works.

## Resume point

Nothing implemented yet, but Phase 0's static analysis is largely done and
found real, named hook targets (see above) — this project is on a
noticeably better track than Legacy Kollection was at the same stage. Next
action: get sign-off to launch the actual game and confirm the live process
+ start pulling `UIScreenManager`/`UIGridSelection` type layouts, or start
Phase 1's OCR baseline in parallel.
