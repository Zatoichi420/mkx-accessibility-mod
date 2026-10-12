# Live test checklist (before tagging a release)

CI checks the built program against a stand-in game window, but it can't
cover the real game, real speech, or 150% display scaling. Do this pass on
the Windows PC with the real game before pushing a `v*` tag. It takes about
15 minutes. Report anything that fails, including what you heard.

The log is at `%LOCALAPPDATA%\MKXAccess\reader.log` (press
Windows+R, paste the folder path, press Enter). Each item below says which
log line confirms it, for when speech alone isn't conclusive.

## Before you start

- [ ] Close the old reader if it's running (a `python ... main.py` process
      from the MKX-Accessibility folder). Setup removes its Startup-folder
      shortcut, "MKX Accessibility Reader", so it won't come back at sign-in.
- [ ] Have a controller connected: the title screen asks for the A button.

## 1. Install

- [ ] Download Setup.exe from the CI run's artifact or the draft release,
      and run it. Note whether SmartScreen appears and whether the README's
      steps got you past it.
- [ ] The wizard reads sensibly with NVDA, and the start-at-sign-in checkbox
      is announced as checked.
- [ ] On Finish you hear "Accessibility reader ready. Waiting for the game."
- [ ] The Startup folder no longer has "MKX Accessibility Reader" in it.

## 2. Check

- [ ] Start menu, **Check accessibility reader**: NVDA reads the message box.
      It should say Self-test passed, Voice NVDA, a text recognition
      language, Reader running, Start at sign-in on. With no known screens
      yet, it must not say the library didn't load.

## 3. The game, with NVDA (most important)

- [ ] Start the game from Steam: you hear "Game window found."
- [ ] Log: `Window capture is blank (fullscreen game?); capturing the screen
      under the window instead.` then `Game capture size: 1920x1080` (or
      your screen's full size, **not** 1280x720). The old reader only saw
      the top-left part of the screen at 150% scaling.
- [ ] Title screen ("PRESS THE A BUTTON") is read. Try Enter and Space on
      the keyboard too, and note whether either gets past it.
- [ ] Main menu is read in full (One Player, Two Player, Online, Faction,
      Krypt, Options, Extras, Exit). Note whether moving the cursor speaks
      each item; if not, the highlight colour needs calibrating (send a few
      `library_misses` images).
- [ ] The rotating promo panels (Faction War, new fighter "Available now")
      don't make the reader repeat the menu every few seconds.
- [ ] Options, then Controls, Audio and PC Video: each screen is read.
- [ ] The Krypt: "Welcome to The Krypt" is read.
- [ ] Pause menu in a fight (Start or Escape) is read; the fight itself is
      quiet.
- [ ] Character select: note what is read when moving between fighters.
- [ ] F9 re-reads. F10 says "Reader off.", F10 again says "Reader on."
- [ ] Alt+Tab to another window: the reader goes quiet (log: `Game is not
      the focused window`). Alt+Tab back: the current screen is read again.
      With another game (Street Fighter, say) in front, nothing from it is
      read. The old reader read whatever was on the desktop.

## 4. Without NVDA

- [ ] If the display scaling is not 100%, note it here. The reader now
      captures each window at its own scaling, which fixed a stand-in game
      window being cut to its top-left corner at 150%.

- [ ] Quit NVDA (NVDA+Q) while the game is open: the next screen change is
      spoken in the Windows voice. Restart NVDA: speech moves back to NVDA.

## 4b. JAWS (if a JAWS licence or 40-minute demo is available)

- [ ] Quit NVDA and start JAWS. Start the game: "Game window found." is
      spoken by JAWS, in the JAWS voice, with no Windows voice on top.
      Log: `Speech output is now: JAWS`.
- [ ] Move through the main menu: each screen is spoken by JAWS.
- [ ] Start menu, **Check accessibility reader**: says Voice JAWS. The result
      is read once, by JAWS, not twice.
- [ ] Quit JAWS while the game is open: speech moves to the Windows voice.
      Start JAWS again: speech moves back to JAWS.
- [ ] F9 and F10 still work with JAWS running.

## 4c. Narrator

- [ ] With NVDA and JAWS both closed, turn on Narrator (Ctrl+Windows+Enter).
      Start the game: menus are spoken in the Windows voice. Note whether
      Narrator and the Windows voice talking at once is a problem.
- [ ] Turn Narrator off again (Ctrl+Windows+Enter).

## 5. Start, stop, restart

- [ ] Quit the game. Log: `Game window closed`. The reader keeps running.
      Start the game again: "Game window found." and reading resumes.
- [ ] Start menu, **Stop accessibility reader**: "Accessibility reader
      stopped."
- [ ] **Start accessibility reader** twice: the second time says "The
      accessibility reader is already running."
- [ ] Sign out and back in, or restart Windows: no announcement at sign-in.
      Start the game: "Game window found."

## 6. Uninstall

- [ ] Start menu, **Uninstall accessibility reader**: completes, and nothing
      is spoken at the next sign-in.
