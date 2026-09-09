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

### Live test (2026-09-08) — process confirmed, read access confirmed

Launched MKX via `steam://rungameid/307780` and confirmed with `tasklist`:
**`MK10.exe` is the only game process that appears** (no separate
`MK10Game.exe`/`MKXLauncher.exe` process stays running) — matches the PDB
naming and the community Cheat Engine tables exactly, as predicted.

Wrote a second small ctypes script (`tools/live_check.py` in this repo) that:
1. Snapshots the live process's modules (`CreateToolhelp32Snapshot`) to get
   `MK10.exe`'s *actual* loaded base address.
2. Opens the process with `PROCESS_VM_READ` and calls `ReadProcessMemory`
   at `live_base + RVA` for `GUIScreenManager`.

**Result: the read succeeded cleanly** (`ReadProcessMemory` returned success,
32 bytes back, no access-denied error) — confirms external memory reading
against this game works with zero friction, exactly as the existing
community Cheat Engine tables imply. One important correction to earlier
assumptions: **the module does NOT load at its preferred image base — ASLR
is active** (loaded at `0x7FF617000000` vs. the PE's preferred
`0x140000000`). Any real tool must resolve the live base at runtime (via
`CreateToolhelp32Snapshot`/`Module32First`, as the script does) and add the
PDB-derived RVA to *that*, never hardcode an absolute address.

The bytes read back for `GUIScreenManager` were all zero. Not a failure —
the game was likely still sitting on an unskipped intro/legal splash screen
(the sister GameCube projects' READMEs note the same thing: "nothing is
spoken during the intro logos... press Start to get past the logos"), and
there was no way to send it a "press Start" keypress from this session
(no input-injection tool available here). An all-zero read is also
consistent with `GUIScreenManager`'s internal screen map legitimately being
empty at that point. **Not yet confirmed**: reading a non-zero, meaningfully
populated value once the game is actually sitting at the main menu — that
needs either an input-injection tool added to the toolkit, or the user
playing for a few seconds while a probe script polls in the background.
Game was closed (`taskkill`) after the test rather than left idling.

### Type-layout findings (2026-09-08, second session) — the concrete read targets

Wrote `tools/dump_type_layout.py`: same dbghelp-via-ctypes technique as
`dump_pdb_symbols.py`, but calling `SymGetTypeFromNameW` +
`SymGetTypeInfo(..., TI_FINDCHILDREN, ...)` to pull actual field-by-field
struct layouts (name/offset/size/type) straight out of the PDB, instead of
just function/global names. (Debugging note kept in the script's comments:
the real dbghelp enumerator for "get a type's children" is `TI_FINDCHILDREN`
— there is no `TI_GET_CHILDREN` — and `TI_GET_OFFSET` is 10, not 8; getting
either wrong produces a useless generic `ERROR_INVALID_FUNCTION` with no
hint why. Worth remembering if this script is ever extended.)

Results — this is the concrete read plan for Phase 2:

- **`UIScreenManager`** (80 bytes) has exactly one field: `m_Screens` at
  `+0x00`, a `TMap<FString, UIScreenManager::UIScreenData>`. So
  `GUIScreenManager` (the global) *is* that map directly (no extra
  indirection) — walking it means walking a `TMap`, which needs its own
  layout dumped (`TMap`/`TMapBase`/`TArray` are engine container templates,
  not yet dumped — next thing to pull if this path is pursued).
- **`UIScreenManager::UIScreenData`** (152 bytes, the map's value type):
  `slotId` (+0x00), `screenGroup` (+0x04), `bPersistent` (+0x0C),
  `screenItem` (+0x18, an `MKItemNoDestroy` — Scaleform object handle),
  `cachedScreen` (+0x38, a `UIScreenCache`). This is a registry of loaded
  screens, not obviously a single "current screen" pointer — matches its
  method names (`AddScreen`, `SavePersistentScreens`). May need combining
  with `bPersistent`/`screenGroup` filtering, or may turn out to be the
  wrong lead entirely for "what's the ONE active screen" vs. "what's
  loaded" — genuinely unresolved, needs live data to tell.
- **`UIGridSelection`** (96 bytes) — the real prize:
  `mCursors` at `+0x30` is a `TArray<UIGridSelectionCursor>`, and
  **`UIGridSelectionCursor`** (16 bytes) is:
  `selectionTableIndex` (int, +0x00), `bIsActive` (+0x04), `bIsSelected`
  (+0x08), `bCursorHidden` (+0x0C). **`selectionTableIndex` is exactly the
  "which cell is currently selected" number a narrator needs** — this is
  the single most directly usable field found in the whole investigation.
  `mNavTable` at `+0x20` is a `TArray<UIGridSelectionNavTable>`, and
  **`UIGridSelectionNavTable`** (40 bytes) holds a `base` position plus
  `leftMove`/`rightMove`/`upMove`/`downMove` (each a `UIGridSelectionPosition`,
  presumably a row/column pair) — the adjacency graph, useful later for
  row/column narration but not required just to speak "item N".
- **`UIMainMenuScreen`** (680 bytes) confirmed `NUM_COLUMNS`/
  `GRID_SELECT_COLUMN` as static constants and `mNumMenuItems` (+0x58) as a
  real instance field, plus a long list of `MKItem`/`MKItemNoDestroy`
  (Scaleform movie-clip handle, 32 bytes each) fields for every visible UI
  element — including **`mPressStartMessageAnim`** (+0x180), which
  confirms the "press start" prompt is a real, named UI element in this
  screen's code. That's independent evidence the attract-mode loop (see
  below) does eventually reach an interactive title screen; it just wasn't
  reached in this session's live test.

**Not yet dumped** (natural next static-analysis step, no game needed):
`TMap`/`TArray`'s own template layout (needed to actually walk `m_Screens`
or `mCursors` from raw memory), `UIGridSelectionPosition`, `MKItem`/
`MKItemNoDestroy`/`MKClassInfo`.

### Input-injection attempt (2026-09-08, second session) — game launched but never reached an interactive screen

With the user away from the computer, tried to get further than the earlier
live test by driving the game with synthetic input instead of waiting for a
live session: `tools/send_key.py` (`SendInput`, not `SendKeys`/WM_CHAR,
since many fullscreen games ignore the latter) and `tools/capture_now.py`
(a standalone `PrintWindow` screenshot, reusing `ocr_reader/main.py`'s
capture code) let this session both act on and *see* the game without a
person present — screenshots were read back and visually inspected each
time.

Confirmed the game's window class is **`LaunchUnrealUWindowsClient`** —
independent confirmation of the UE3 lineage (this is a literal stock UE3
window class name), on top of the `Coalesced.ini`/Scaleform evidence
already found.

However: **over roughly 6 minutes of runtime, sending Enter/Space/Escape
and mouse clicks repeatedly, the game stayed on a rotating cinematic
montage** (a "MORTAL KOMBAT" title card interspersed with several different
gameplay/cutscene clips - snowy forest, a jungle scene, a temple courtyard -
cycling on a fixed ~15-20s timer) and never showed any visible UI text or
reached `UIMainMenuScreen`. None of the synthetic input appeared to have any
effect on this — the same clips played back in the same way whether or not
a key was sent, suggesting this is either a fixed-length unskippable intro
reel, or the game specifically requires a **gamepad** input to dismiss it
(a synthetic keyboard key was sent; no controller input was tried, and none
is available from this environment). This is a real, useful negative
result: don't assume a quick Enter-press gets past this next time — it may
need a controller, a longer wait for the reel to finish on its own, or
simply a person there to see what it's actually prompting for. Game was
closed (`taskkill`) afterward rather than left running unattended.

### Remaining Phase 0 / early Phase 2 work

1. Get a real "game is at the main menu" read of `GUIScreenManager`'s
   `m_Screens` and a live `UIGridSelection::mCursors[].selectionTableIndex`
   — needs a live session where the game actually reaches
   `UIMainMenuScreen` (see the input-injection note above for why that
   didn't happen unattended this time). Once there, `selectionTableIndex`
   is the read to try first.
2. Dump `TMap`/`TArray`'s own layout so `m_Screens`/`mCursors` can actually
   be walked from raw process memory (pure static analysis, no game
   needed — can be done before the next live session).
3. Scope the tool to **offline/local play only** and say so explicitly in
   the README/legal section, matching Deception's "online out of scope"
   precedent — don't attempt anything against the game's online/matchmaking
   path.

### Phase 1 — Guaranteed-feasible baseline (OCR + reference library)

**Done (2026-09-08), scaffolded and syntax-checked, not yet live-tested.**
Ported Legacy Kollection's `ocr_reader/main.py` and `screen_library.py`
near-verbatim (same dHash-based screen recognition, same NVDA Controller
Client speech backend, same hardened reliability patterns — NVDA startup
retry, `speak()` failure self-heal with audible beep, PID-lock duplicate-
instance protection, consecutive-poll-failure exit threshold). Also copied
`nvda_controller_client/` (the redistributable NVDA SDK) and the
`run_reader.bat`/`start_reader.vbs` launch scripts (superseded as the
*setup* mechanism by `install.bat`'s Startup-folder shortcut — see below —
but still what actually runs the reader either way). `requirements.txt`
matches Legacy Kollection's pinned versions
(pywin32, pillow, numpy, winsdk) — already installed in this machine's
Python and confirmed importable.

Game-specific changes from the Legacy Kollection original:
- `PROCESS_NAME` set to `MK10.exe` (confirmed live, see above).
- `known_screens/` starts **empty** — nobody has captured/hand-verified an
  MKX screen yet, so every screen currently falls back to live OCR and gets
  logged to `library_misses/` for later review, exactly as designed for an
  unpopulated library.
- The highlight-detection color thresholds (`BRIGHTNESS_THRESHOLD`,
  `BLUE_MINUS_RED_THRESHOLD`) are **carried over unchanged from Legacy
  Kollection and explicitly flagged `NEEDS_CALIBRATION`** in the code —
  they were tuned for that launcher's cyan/gold highlight style, not
  MKX's (unknown, Scaleform-rendered) style. Safe failure mode until
  recalibrated: highlight detection just won't fire, not fire wrong.

### Setup: `install.bat` / `uninstall.bat` (2026-09-08, third session)

User feedback on the Deadly Alliance/Deception sister projects: setup
wasn't easy, mainly because of digging into RetroArch's network-command
settings (an external tool's config, off by default, easy to get wrong).
MKX has no equivalent external tool, so the goal here was to remove
*every* manual step, not just match the sister projects' bar.

- **`install.bat`**: installs `requirements.txt`, checks (non-blocking) that
  NVDA is running, adds a shortcut to the user's **Startup folder**
  (`shell:startup`) that launches `ocr_reader/start_reader.vbs` hidden at
  every login, then starts it immediately for the current session too.
  No Steam launch options to configure (the reader already polls for the
  game window on its own — it doesn't need to be launched *at the same
  moment* as the game, just running before or during), no admin rights,
  no external tool's settings.
- **First attempt used `schtasks /create ... /sc onlogon`** (Task
  Scheduler) instead of a Startup-folder shortcut — **failed with "Access
  is denied"** even for a plain per-user logon trigger. Switched to a
  Startup-folder shortcut instead (created via a small VBScript,
  `ocr_reader/install_startup_shortcut.vbs`, since batch alone can't
  create `.lnk` files) — this never needs elevation, it's just a normal
  per-user folder write, and is arguably more transparent anyway (a person
  can see/delete the shortcut directly without knowing what Task Scheduler
  is). Worth remembering if a future session is tempted to reach for
  `schtasks` again: try the Startup-folder shortcut first.
- **`run_reader.bat` was also made portable**: tries the `py` launcher,
  then `python` on PATH, then falls back to this machine's own known
  install path as a last resort — not hardcoded to one path first, so this
  isn't tied to one specific machine if the repo is ever shared.
- **`uninstall.bat`**: deletes just that Startup shortcut. Doesn't touch
  `known_screens/` or any captured data.
- **Verified end-to-end on this machine**: ran `install.bat` for real
  (with the user's explicit go-ahead, since it's a persistent
  startup-folder/background-process change) — pip install succeeded, NVDA
  was detected running, the Startup shortcut was created and its
  target/arguments verified correct via PowerShell, and the reader
  actually started (`reader_log.txt` showed "NVDA connection OK", "Loaded
  0 verified screens", then polling "Waiting for game window..." — exactly
  the intended hands-off idle state). **It's currently live on this
  machine**, waiting for MKX to launch.

**Not yet done**: an actual live-test run against the game (needs the game
sitting at a real menu, which needs either input-injection or the user at
the controls — see the Phase 0 live-test note above for why that's still
pending), and capturing/verifying the first `known_screens/` entries.

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

## Live fix: PrintWindow capture goes dark in fullscreen (2026-09-08, fourth session)

With the user actually at the main menu (confirmed via Be My Eyes: main
menu, "KRYPT" highlighted, panels for a DLC character/"WHITE LOTUS"
faction/"COMING SOON"), the reader had gone silent. `reader_log.txt` had
stopped updating minutes earlier. Root cause: `capture_window()`'s
`PrintWindow`-based capture (via the game's own `hwnd`) works fine during
the windowed intro cinematics but **silently returns a zero-size capture
once MKX settles into its real fullscreen menu** - no error, which is
itself a bug (the codebase's own philosophy, inherited from Legacy
Kollection, is to never fail silently - `capture_window` returning `None`
just gets skipped with no log line or beep). `GetWindowRect` on the game's
window starts returning a bogus placeholder rect (large negative
coordinates) at the same point, the same underlying symptom.

Sighted assistance confirmed MKX's Options has **no windowed/borderless
display-mode toggle** - it's fullscreen-only, so "switch to windowed"
wasn't a viable fix. Tested instead whether a **plain whole-desktop grab**
(`PIL.ImageGrab.grab(all_screens=True)`, ordinary GDI `BitBlt` against the
desktop rather than `PrintWindow` against one window) could see through
it - captured a real, correct frame of the live fullscreen main menu on
the first try. **Fix applied**: `capture_window()` now always does a
full-desktop grab; `hwnd`/`find_window_for_process` are still used to
detect that the game is running at all, just not for capture geometry.
`tools/capture_now.py` updated the same way. Verified live: after
restarting the reader, it immediately produced a clean recognition
("Welcome to The Krypt! Krypt Gateway (0, 0) Continue") from the real
running game.

**Also added**: an F1 hotkey (`TOGGLE_HOTKEY_VK`) to mute/unmute the
reader without closing it (per the user's request) - always announces the
toggle itself even when muting, so silence never has two possible causes.

**Not yet fixed**: the underlying silent-failure pattern (capture returning
`None` with no log/beep) that made this take minutes to notice rather than
being immediately obvious - worth hardening later, e.g. beep after N
consecutive zero-size captures, matching the `_audible_alert()` pattern
already used for NVDA failures.

**Also noted, not a bug**: the "faction wars" thing the user saw on every
launch is a permanent panel on the main menu itself (globe icon, "LB"
button prompt), not a one-time popup - confirmed via a live desktop-grab
screenshot showing it sitting there normally alongside "AVAILABLE NOW" and
"WAY TO THE TEMPLE / PREMIER TOWER" panels, all part of the standard main
menu layout.

## Resume point (updated after second 2026-09-08 session)

Everything static-analysis-shaped that could be done without a person at
the controls has been done: Phase 1's OCR baseline is scaffolded, and
Phase 2 now has concrete read targets from the PDB's type info —
`UIGridSelectionCursor::selectionTableIndex` in particular is the field to
read for "which menu item is selected." What's blocking further progress
on both phases is the same thing an unattended session can't solve: **the
game does not reach an interactive menu on its own** — it sits on a
multi-minute, apparently input-immune cinematic attract reel (see the
"Input-injection attempt" note above). A real person needs to either wait
it out or provide input the synthetic keyboard approach didn't (possibly a
controller).

**When you're back, in order of what unblocks the most:**
1. Launch the game yourself and get it past the intro to the actual main
   menu (note whether keyboard alone ever does it, or whether you needed a
   controller/took longer than ~6 minutes — that's useful data either way).
2. Once at the main menu, either: let me poll `GUIScreenManager` and
   `UIGridSelection::mCursors[].selectionTableIndex` live while you move
   the cursor (fastest way to confirm the Phase 2 read targets above are
   right), and/or run `ocr_reader/main.py` and press F10 on a few screens
   to seed `known_screens/` (also gives real pixels to calibrate the
   highlight-color thresholds against).
3. Everything else in this file's Phase 0/1/2/3 sections still applies
   once past that point.
