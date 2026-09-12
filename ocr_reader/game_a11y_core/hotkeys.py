"""
Hotkey polling and per-game hotkey configuration.

HotkeyConfig replaces two independent, silently-diverged hardcoded
conventions: Legacy Kollection had no toggle at all, while MKX had grown
F10=toggle after the two projects split. Both games now build one of
these with the same values (F9=re-read, F2=capture, F10=toggle) so a
missing toggle is a deliberate choice (toggle_vk=None) rather than an
accident of which project you happen to be looking at.
"""

from dataclasses import dataclass
from typing import Optional

import win32api


def was_key_pressed_since_last_check(vk):
    """Edge-triggered, not level-triggered: GetAsyncKeyState's low-order bit
    latches "this key was pressed at some point since the last call for this
    vk" and clears on read. A plain "is it down right now" check (the high
    bit alone) can miss a real keypress entirely if it happens to fall
    between two ~0.5s polls - a normal keyboard tap is often under 150ms,
    well inside that gap. The latch bit can't miss it: it stays set across
    any number of polls until someone reads it."""
    return (win32api.GetAsyncKeyState(vk) & 0x1) != 0


@dataclass
class HotkeyConfig:
    reread_vk: int
    capture_vk: int
    toggle_vk: Optional[int] = None

    @property
    def has_toggle(self) -> bool:
        return self.toggle_vk is not None
