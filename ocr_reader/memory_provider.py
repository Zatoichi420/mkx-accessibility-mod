"""
Reads MKX's own UE3 object graph to get the exact current screen and the
exact selected menu index - instead of screenshotting the desktop and
guessing from pixels.

All offsets below are RVAs verified from the shipped MK10.pdb (see the
"complete memory-read recipe" section of PROGRESS.md). Read-only: this
opens the process with PROCESS_VM_READ only and never writes to it.

Run standalone to check it against a live game:
    python memory_provider.py --probe     # live state, refreshes until Ctrl+C
    python memory_provider.py --once      # one reading, then exit
    python memory_provider.py --classes   # list UI-ish classes found live
"""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

from game_a11y_core.state_provider import ScreenState, StateProvider

PROCESS_NAME = "MK10.exe"
LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_labels.json")

# --- Verified RVAs (MK10.pdb) ---
RVA_GOBJOBJECTS = 0x38004B0  # UObject::GObjObjects - TArray<UObject*>
RVA_FNAME_NAMES = 0x3800518  # FName::Names        - TArray<FNameEntry*>

# --- Verified struct offsets ---
# TArray<T> (sizeof 16). Data/Num/Max is the standard UE3 layout, inferred
# rather than PDB-confirmed (the PDB reports no child fields - they live in
# the allocator base). validate_layout() sanity-checks it at runtime.
TARRAY_DATA = 0x00
TARRAY_NUM = 0x08
TARRAY_MAX = 0x0C

UOBJECT_NAME = 0x48   # FName (Index int32 at +0x00)
UOBJECT_CLASS = 0x50  # UClass*

FNAMEENTRY_NAME = 0x10  # ANSI char[128]

UIGRIDSELECTION_MCURSORS = 0x30          # TArray<UIGridSelectionCursor>
UIGRIDSELECTIONCURSOR_SIZE = 0x10
CURSOR_SELECTIONTABLEINDEX = 0x00
CURSOR_BISACTIVE = 0x04
CURSOR_BISSELECTED = 0x08
CURSOR_BCURSORHIDDEN = 0x0C

# A plausible object count for a loaded UE3 game. Used only to catch a
# wrong TArray layout / stale base address early, loudly, instead of
# silently reading garbage for the rest of the session.
SANE_OBJECT_COUNT = (1_000, 5_000_000)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


TH32CS_SNAPPROCESS = 0x00000002


def _find_pid(process_name: str) -> Optional[int]:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1):
        return None
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.decode(errors="replace").lower() == process_name.lower():
                return entry.th32ProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)


def _find_module_base(pid: int, module_name: str) -> Optional[int]:
    """ASLR is active on this build, so the base must be resolved at
    runtime - never hardcode it (PROGRESS.md records the live-test that
    established this)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap in (0, -1):
        return None
    try:
        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        if not kernel32.Module32First(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szModule.decode(errors="replace").lower() == module_name.lower():
                return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value
            if not kernel32.Module32Next(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)


class MemoryStateProvider(StateProvider):
    # Class names whose instances identify "which screen am I on". Extend
    # as screens get mapped - unknown screens simply fall through to the
    # OCR provider rather than breaking anything.
    SCREEN_CLASSES = {
        "UIMainMenuScreen",
        "UIOnlineMainMenuScreen",
        "UIOptionsScreen",
        "UIPracticeOptionsScreen",
        "UIControllerConfigScreen",
        "UIFactionLandingScreen",
        "UITestYourLuckSelectScreen",
        "UIChatLobbyScreen",
        "UIOnlineConnectingScreen",
        "UIEndRoundScreen",
    }

    # Grid-cursor classes. All derive from UIGridSelection, so mCursors
    # sits at the same offset on each.
    GRID_CLASSES = {
        "UIGridSelection",
        "UIGridSelectionWidget",
        "UIGridSelectWidget",
        "MK10UIGridSelect",
        "UIMainMenuGridSelectWidget",
        "UIPlayerSelectGridSelectWidget",
        "UIOptionsGridSelectWidget",
        "UIChapterSelectGridSelectWidget",
        "UIFactionChallengesGridSelectWidget",
        "UITestYourLuckSelectGridSelectWidget",
        "UIKombatKardCustomizeGridSelectWidget",
        "UIMatchReplayGridSelectWidget",
        "MK10HeroCardGridSelect",
        "MK10ScenarioGridSelect",
        "UIChatLobbyGridSelect",
    }

    def __init__(self, process_name: str = PROCESS_NAME):
        self.process_name = process_name
        self._handle = None
        self._base = None
        self._names_data = 0
        self._names_num = 0
        # UClass* -> class name. Tens of thousands of objects share a few
        # hundred classes, so this cache is the difference between a walk
        # taking milliseconds and taking seconds.
        self._class_name_cache: Dict[int, str] = {}
        self._name_cache: Dict[int, str] = {}
        self._labels = self._load_labels()
        # A full GObjObjects walk touches every live UObject (tens of
        # thousands on a loaded level) - fine once, too slow to repeat on
        # a 0.5s poll cadence. Cache the screen/grid pointers found on the
        # last walk and just re-validate them (one class-name check each,
        # cache-hit cheap) on subsequent polls; only re-walk the full
        # array when a cached pointer goes stale (screen actually changed,
        # or the object was freed and the read fails).
        self._cached_screen: Tuple[int, str] = (0, "")
        self._cached_grid: int = 0

    @staticmethod
    def _load_labels() -> Dict[str, dict]:
        """Static per-screen label lists. Missing file or malformed JSON
        is survivable - the provider still reports screen + index, it
        just can't name the item."""
        try:
            with open(LABELS_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception:
            return {}

    # --- process attach ---

    def attach(self) -> bool:
        pid = _find_pid(self.process_name)
        if pid is None:
            return False
        base = _find_module_base(pid, self.process_name)
        if base is None:
            return False
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return False
        self._handle = handle
        self._base = base
        self._class_name_cache.clear()
        self._name_cache.clear()
        self._cached_screen = (0, "")
        self._cached_grid = 0
        names_ptr = self._base + RVA_FNAME_NAMES
        self._names_data = self._read_ptr(names_ptr + TARRAY_DATA) or 0
        self._names_num = self._read_i32(names_ptr + TARRAY_NUM) or 0
        return True

    def _ensure_attached(self) -> bool:
        if self._handle is not None and self._base is not None:
            return True
        return self.attach()

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
        self._handle = None
        self._base = None

    # --- raw reads ---

    def _read(self, address: int, size: int) -> Optional[bytes]:
        if not address or self._handle is None:
            return None
        buf = (ctypes.c_ubyte * size)()
        read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read)
        )
        if not ok or read.value != size:
            return None
        return bytes(buf)

    def _read_ptr(self, address: int) -> Optional[int]:
        raw = self._read(address, 8)
        return int.from_bytes(raw, "little") if raw else None

    def _read_i32(self, address: int) -> Optional[int]:
        raw = self._read(address, 4)
        return int.from_bytes(raw, "little", signed=True) if raw else None

    def _read_tarray(self, address: int) -> Tuple[int, int]:
        """Returns (data_ptr, count); (0, 0) on failure."""
        data = self._read_ptr(address + TARRAY_DATA)
        num = self._read_i32(address + TARRAY_NUM)
        if not data or num is None or num < 0:
            return 0, 0
        return data, num

    # --- name resolution ---

    def _name_from_index(self, index: int) -> Optional[str]:
        if index in self._name_cache:
            return self._name_cache[index]
        if not self._names_data or not (0 <= index < self._names_num):
            return None
        entry = self._read_ptr(self._names_data + 8 * index)
        if not entry:
            return None
        raw = self._read(entry + FNAMEENTRY_NAME, 128)
        if raw is None:
            return None
        name = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        self._name_cache[index] = name
        return name

    def _class_name(self, obj_ptr: int) -> Optional[str]:
        cls = self._read_ptr(obj_ptr + UOBJECT_CLASS)
        if not cls:
            return None
        cached = self._class_name_cache.get(cls)
        if cached is not None:
            return cached
        # A UClass is itself a UObject, so its own name lives at the same
        # offset - that's what makes this resolution one extra hop.
        name_index = self._read_i32(cls + UOBJECT_NAME)
        if name_index is None:
            return None
        name = self._name_from_index(name_index)
        if name:
            self._class_name_cache[cls] = name
        return name

    def object_name(self, obj_ptr: int) -> Optional[str]:
        idx = self._read_i32(obj_ptr + UOBJECT_NAME)
        return self._name_from_index(idx) if idx is not None else None

    # --- object graph ---

    def validate_layout(self) -> Tuple[bool, str]:
        """Catches a wrong TArray layout or stale base immediately, rather
        than letting the reader quietly narrate garbage. The TArray field
        layout is the one inferred (not PDB-confirmed) piece in this file,
        so it gets checked explicitly."""
        if not self._ensure_attached():
            return False, f"{self.process_name} not running / could not attach"
        data, num = self._read_tarray(self._base + RVA_GOBJOBJECTS)
        if not data:
            return False, "GObjObjects data pointer unreadable"
        low, high = SANE_OBJECT_COUNT
        if not (low <= num <= high):
            return False, f"GObjObjects count {num} implausible - TArray layout or RVA likely wrong"
        return True, f"GObjObjects: {num} objects, FName pool: {self._names_num} names"

    def iter_objects(self):
        data, num = self._read_tarray(self._base + RVA_GOBJOBJECTS)
        for i in range(num):
            ptr = self._read_ptr(data + 8 * i)
            if ptr:
                yield ptr

    def find_by_classes(self, class_names: set) -> List[Tuple[int, str]]:
        found = []
        for ptr in self.iter_objects():
            cname = self._class_name(ptr)
            if cname in class_names:
                found.append((ptr, cname))
        return found

    def class_histogram(self, substring: str = "UI") -> Dict[str, int]:
        """Diagnostic: what UI-ish classes actually have live instances
        right now. Use this to discover screen/grid class names that
        aren't in SCREEN_CLASSES/GRID_CLASSES yet."""
        hist: Dict[str, int] = {}
        for ptr in self.iter_objects():
            cname = self._class_name(ptr)
            if cname and substring.lower() in cname.lower():
                hist[cname] = hist.get(cname, 0) + 1
        return dict(sorted(hist.items(), key=lambda kv: -kv[1]))

    # --- the actual answer ---

    def read_cursor_index(self, grid_ptr: int) -> Optional[int]:
        data, num = self._read_tarray(grid_ptr + UIGRIDSELECTION_MCURSORS)
        if not data or num <= 0:
            return None
        # Cursor 0 is the local player's. (Two-player select screens have
        # a second cursor; not handled yet - see PROGRESS.md.)
        for i in range(num):
            cursor = data + i * UIGRIDSELECTIONCURSOR_SIZE
            active = self._read_i32(cursor + CURSOR_BISACTIVE)
            hidden = self._read_i32(cursor + CURSOR_BCURSORHIDDEN)
            if active and not hidden:
                return self._read_i32(cursor + CURSOR_SELECTIONTABLEINDEX)
        return self._read_i32(data + CURSOR_SELECTIONTABLEINDEX)

    def get_state(self) -> Optional[ScreenState]:
        if not self._ensure_attached():
            return None
        try:
            screen_ptr, screen_id = self._resolve_screen()
            grid_ptr = self._resolve_grid()
        except Exception:
            # A read failing mid-walk (process exiting, memory shifting)
            # must degrade to "no update", never kill the reader loop.
            self.close()
            return None

        if not screen_ptr and not grid_ptr:
            return None

        selected = self.read_cursor_index(grid_ptr) if grid_ptr else None
        if selected is None:
            selected = -1

        label_entry = self._labels.get(screen_id)
        items = label_entry["items"] if label_entry else []

        return ScreenState(
            screen_id=screen_id or "UnknownScreen",
            items=items,
            selected_index=selected,
            source="memory",
        )

    def _resolve_screen(self) -> Tuple[int, str]:
        ptr, name = self._cached_screen
        if ptr and self._class_name(ptr) == name:
            return ptr, name
        screens = self.find_by_classes(self.SCREEN_CLASSES)
        if not screens:
            self._cached_screen = (0, "")
            return 0, ""
        self._cached_screen = screens[0]
        return self._cached_screen

    def _resolve_grid(self) -> int:
        if self._cached_grid and self._class_name(self._cached_grid) in self.GRID_CLASSES:
            return self._cached_grid
        grids = self.find_by_classes(self.GRID_CLASSES)
        self._cached_grid = grids[0][0] if grids else 0
        return self._cached_grid


def _probe(once: bool, classes: bool) -> int:
    provider = MemoryStateProvider()
    ok, message = provider.validate_layout()
    print(f"[layout check] {'OK' if ok else 'FAILED'}: {message}")
    if not ok:
        return 1

    if classes:
        print("\nLive UI classes (instance counts):")
        for name, count in provider.class_histogram("UI").items():
            print(f"  {count:5d}  {name}")
        return 0

    while True:
        state = provider.get_state()
        if state is None:
            print("no state (screen not mapped, or process gone)")
        else:
            print(f"screen={state.screen_id:35s} selected_index={state.selected_index}")
        if once:
            return 0
        time.sleep(0.5)


if __name__ == "__main__":
    args = set(sys.argv[1:])
    sys.exit(_probe(once="--once" in args, classes="--classes" in args))
