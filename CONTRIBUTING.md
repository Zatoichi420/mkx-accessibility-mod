# Contributing

Thanks for helping make Mortal Kombat X playable without sight. Contributions of
every size are welcome — a typo fix, a hand-verified `known_screens/` entry, a
tested memory offset, or just a report that it did or didn't work on your setup.

This is a small project maintained in spare time. Please be patient with review,
and be kind in issues and PRs — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Things that would genuinely help

| Area | What's needed |
|---|---|
| **`known_screens/` library entries** | It's still empty. Narration works via live OCR everywhere already (main menu, pause menu, Steam's own UI, all confirmed working 2026-09-08), but OCR on this game's stylized font is rough. Capture a screen with F2, hand-verify its `canonical_text` against the real screen, and it'll be read cleanly and instantly from then on instead of guessed at live. See [PROGRESS.md](PROGRESS.md) for the reference-library format (same design as the sister Legacy Kollection project). |
| **Highlight-color calibration** | `HIGHLIGHT_BRIGHTNESS_THRESHOLD`/`HIGHLIGHT_BLUE_MINUS_RED_THRESHOLD` in `ocr_reader/main.py` are placeholder values carried over from the Legacy Kollection reader and marked `NEEDS_CALIBRATION` — nobody has sampled MKX's actual selected-vs-unselected menu-text colors yet, and the 2026-09 captures were cut off at 150% scaling. |
| **The title screen's controller prompt** | The "MORTAL KOMBAT XL" title screen shows "PRESS THE A BUTTON" — confirmed live 2026-09-08 via screenshot. Unconfirmed whether there's a keyboard equivalent (Enter/Space were tried unsuccessfully, but under conditions that may not have delivered real input at all — see PROGRESS.md's "hotkeys don't work on a Claude-started reader" finding). Needs someone with a controller, or a keyboard-only player confirming which key (if any) works. |
| **Phase 2: live memory reads** | A PDB shipped with the retail build named real UI classes — `UIGridSelectionCursor::selectionTableIndex` is the concrete field for "which menu item is selected" (see PROGRESS.md). The first attempt (`ocr_reader/memory_provider.py`, walking `GObjObjects`) can't work: the UI classes aren't UObjects. The next lead is `GUIScreenManager`'s `TMap<FString, UIScreenData>`, which needs `TMap`'s layout and a live session. This would make narration exact and instant instead of OCR-guessed. |
| **Character select, options, and other screens** | Only the main menu, pause menu, and Steam's own UI have been exercised live so far. Chapter select, Kombat Kard customize, faction screens, and others are architecturally covered by the same `UIGridSelection`-family classes (see PROGRESS.md) but untested. |
| **Testing on other MKX versions/builds** | Everything so far is against one specific Steam build (`MK10.pdb`/`MK10.exe` — see PROGRESS.md for the exact facts recorded). A PDB mismatch on a different build would need re-verifying the symbol/offset findings. |

### Out of scope for this repo

Mirrors the precedent set by the sister GameCube projects — see below:

- **Online play / Kombat League / matchmaking** — not attempted, not planned.
- **Live round-by-round fight narration** — this project narrates menus, not gameplay.
- **The Krypt's loot-grinding minutiae** — the Krypt's own menu narration is in scope; deep unlock-tracking isn't.

## Development setup

You need Mortal Kombat X on Steam (appid `307780`), Windows, and Python 3.12.

```
git clone https://github.com/Zatoichi420/mkx-accessibility-mod
cd mkx-accessibility-mod
py -3.12 -m pip install -r requirements.txt -r requirements-dev.txt
py -3.12 -m pytest tests
py -3.12 ocr_reader\main.py --dev
py -3.12 packaging\build.py
```

**Important**: run the reader from a terminal *you* opened yourself, not
from a script or tool that launches it programmatically. Its F9/F10/F2
hotkeys rely on `GetAsyncKeyState`, which does not see input for a process
started by outside automation (confirmed 2026-09-08, see PROGRESS.md).

`tools/` has the PDB/memory-analysis scripts (`dump_pdb_symbols.py`,
`dump_type_layout.py`, `live_check.py`) and small debugging utilities
(`capture_now.py`, `send_key.py`, `test_hotkeys.py`) used for the Phase 0/2
findings in PROGRESS.md.

## How the code is organised

- `ocr_reader/main.py` — the reader: find the game, capture it, recognise
  the screen (library or OCR fallback), speak on change; also `--stop`,
  `--self-test` and the other command-line options.
- `ocr_reader/menu_ocr.py` — OCR clean-up: two passes, snapping to
  `vocabulary.txt`, row repair and merging, the noise gate, highlight rescue.
- `ocr_reader/game_a11y_core/` — capture, OCR, speech (NVDA, JAWS, Windows
  voice), the screen library matcher and process lifecycle, shared with the
  Legacy Kollection and MK9 readers.
- `ocr_reader/known_screens/` — hand-verified screen captures and their
  canonical text. Empty so far.
- `ocr_reader/memory_provider.py`, `ocr_reader/screen_labels.json` — the
  memory-read research probe. Not used by the reader.
- `packaging/` — PyInstaller build, Inno Setup installer, and the CI smoke
  test (`packaging/ci/smoke_test.py`) that checks the built program.
- `tools/` — PDB/memory research scripts and one-off debugging utilities.

## Style

- Match the surrounding code — plain Python, standard library plus what's
  already in `requirements.txt`. No new runtime dependencies for
  `ocr_reader/main.py`/`screen_library.py` without discussing it first.
- Comment *why*, not what — a hidden constraint, a subtle invariant, or the
  reasoning behind a threshold value, not a restatement of the code.
- If you add a memory offset or struct layout, cite how you got it (a PDB
  symbol name, a live-tested read, a screenshot) so it's traceable later.

## Submitting changes

1. Fork, branch off `main`.
2. Make the change, and run `py -3.12 -m pytest tests`. Test it against the running game if it touches the
   reader — say what you tested in the PR ("navigated the main menu and
   options, heard the right text" / "captured and verified a new
   `known_screens` entry for the character-select screen").
3. Open a PR. Small, focused PRs merge faster.
4. New `known_screens/` entries: include the screenshot and say how you
   verified the `canonical_text` (played the game and read it yourself,
   sighted-assisted, etc.).

By contributing you agree your work is licensed under the project's
[MIT License](LICENSE).

## A note on scope and the game

This project ships **no game code or assets** and never will. It reads pixels
from the screen (and, eventually, values from the game's own process memory)
at runtime and speaks them — the same no-modification stance as the sister
projects. You need your own legally owned copy of Mortal Kombat X. Please
don't attach installers or extracted game files to issues or PRs — they'll be
removed. See the licence note in the [README](README.md#licence).
