"""
The seam between "what is on screen right now" and how we found out.

Two backends implement this:
  - MemoryStateProvider (memory_provider.py) - reads the game's own UE3
    object graph. Exact, cheap, immune to resolution/animation/OCR
    quality. Only knows screens that have been mapped.
  - OcrStateProvider - the existing capture+OCR+dHash path in main.py,
    which works on any screen but guesses.

The point of the seam is that screens can convert from guessed to exact
one at a time, rather than as a single big rewrite - and while a screen
has both, the two can be cross-checked against each other during
development.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ScreenState:
    """What's on screen, however we determined it.

    `selected_index` is the whole point: it's what a blind player
    actually needs and what the OCR path can only infer from pixel
    colours. -1 means "this backend couldn't determine a selection",
    which is different from "there is no selection".
    """

    screen_id: str
    items: List[str] = field(default_factory=list)
    selected_index: int = -1
    source: str = "unknown"  # "memory" | "ocr" - useful when cross-checking

    @property
    def selected_label(self) -> Optional[str]:
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None

    def spoken_selection(self) -> Optional[str]:
        """Terse form for a selection change: "Krypt, 5 of 8"."""
        label = self.selected_label
        if label is None:
            return None
        if not self.items:
            return label
        return f"{label}, {self.selected_index + 1} of {len(self.items)}"


class StateProvider:
    """Interface. Implementations must not raise on a transient failure -
    return None instead, so a bad poll degrades to "no update" rather
    than killing the reader loop (a lesson from the OCR path's own
    poll-failure handling)."""

    def get_state(self) -> Optional[ScreenState]:
        raise NotImplementedError

    def close(self) -> None:
        pass
