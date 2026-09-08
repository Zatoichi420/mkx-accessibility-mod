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

## Phased plan

### Phase 0 — Research & feasibility (do this before writing any reader code)

1. Confirm which binary is the actual live game process to attach to
   (`MK10Game.exe` vs `MK10.exe`) — launch the game and check with
   Task Manager / `tasklist`.
2. Load `MK10.exe` + `MK10.pdb` into Ghidra and search resolved symbols for
   menu/frontend/UI-scene class and function names. This is the cheapest,
   highest-value thing to try given the PDB exists at all. If it hits, the
   goal is a Deception-style "read one pointer, match a symbol map" approach:
   what screen am I on, what's highlighted, how many items.
3. Check the MKX PC modding/speedrunning community for existing Cheat Engine
   tables/trainers (known to exist for health/timer/character-ID values) —
   even without menu offsets, a table confirms module-base/ASLR handling and
   saves real time versus starting from zero.
4. If Scaleform/GFx is confirmed as the UI middleware, spend ~30 minutes
   checking whether movie/clip names are recoverable — Scaleform UIs often
   carry human-readable label strings that would make identifying menu state
   far easier than raw pointer-chasing.
5. Regardless of what's found, scope the tool to **offline/local play only**
   and say so explicitly in the README/legal section, matching Deception's
   "online out of scope" precedent — don't attempt anything against the
   game's online/matchmaking path.

### Phase 1 — Guaranteed-feasible baseline (OCR + reference library)

Port the Legacy Kollection `ocr_reader/` architecture near-verbatim: capture
the MKX window → dHash → match against a hand-built `known_screens/*.json`
library (main menu, mode select, character-select grid, options) → speak via
the NVDA Controller Client DLL. Copy its hardened reliability patterns rather
than re-deriving them. This alone produces working menu narration even if
Phase 0 finds nothing usable, exactly as it did for Legacy Kollection when
memory-hooking dead-ended there.

### Phase 2 — Live memory reads (only if Phase 0 finds usable
addresses/symbols)

Layer in `ReadProcessMemory`-based reads of the menu cursor index and item
count — the Deadly Alliance/Deception technique, with `ReadProcessMemory`
against the local `MK10Game.exe` process standing in for RetroArch's UDP
network-command transport (no emulator, no middleman needed). The OCR path
from Phase 1 stays in place as the fallback for any screen not yet mapped,
the same division of labor Deception itself describes for its own unmapped
screens.

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

Nothing implemented yet. Next action is Phase 0, step 1 — confirm the real
game process name, then get `MK10.exe`/`MK10.pdb` into Ghidra.
