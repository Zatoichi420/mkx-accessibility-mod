"""Dump/search MK10.exe's PDB symbols using Windows' built-in dbghelp.dll —
no Ghidra or third-party tools needed. Requires no install: dbghelp.dll ships
with every Windows install; the PDB just has to sit next to the exe (as it
does in a stock MK10 install).

Usage: python dump_pdb_symbols.py [PATTERN ...]
  No args        -> just prints the total symbol count.
  One+ patterns  -> case-insensitive regex search, each reported separately.

Set MK10_EXE_PATH to override the default Steam install path.
"""
import ctypes
import os
import sys
import re

EXE_PATH = os.environ.get(
    "MK10_EXE_PATH",
    r"F:\SteamLibrary\steamapps\common\MK10\Binaries\Retail\MK10.exe",
)
SYM_DIR = os.path.dirname(EXE_PATH)
PATTERNS = sys.argv[1:] if len(sys.argv) > 1 else [None]

dbghelp = ctypes.WinDLL("dbghelp.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")

SymSetOptions = dbghelp.SymSetOptions
SymSetOptions.argtypes = [ctypes.c_ulong]
SymSetOptions.restype = ctypes.c_ulong

SymInitializeW = dbghelp.SymInitializeW
SymInitializeW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
SymInitializeW.restype = ctypes.c_int

SymLoadModuleExW = dbghelp.SymLoadModuleExW
SymLoadModuleExW.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
    ctypes.c_uint64, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
]
SymLoadModuleExW.restype = ctypes.c_uint64

SymCleanup = dbghelp.SymCleanup
SymCleanup.argtypes = [ctypes.c_void_p]
SymCleanup.restype = ctypes.c_int

SymUnloadModule64 = dbghelp.SymUnloadModule64
SymUnloadModule64.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
SymUnloadModule64.restype = ctypes.c_int

GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.restype = ctypes.c_void_p
GetLastError = kernel32.GetLastError
GetLastError.restype = ctypes.c_ulong


class SYMBOL_INFOW(ctypes.Structure):
    _fields_ = [
        ("SizeOfStruct", ctypes.c_ulong),
        ("TypeIndex", ctypes.c_ulong),
        ("Reserved", ctypes.c_uint64 * 2),
        ("Index", ctypes.c_ulong),
        ("Size", ctypes.c_ulong),
        ("ModBase", ctypes.c_uint64),
        ("Flags", ctypes.c_ulong),
        ("Value", ctypes.c_uint64),
        ("Address", ctypes.c_uint64),
        ("Register", ctypes.c_ulong),
        ("Scope", ctypes.c_ulong),
        ("Tag", ctypes.c_ulong),
        ("NameLen", ctypes.c_ulong),
        ("MaxNameLen", ctypes.c_ulong),
        ("Name", ctypes.c_wchar * 1),
    ]


NAME_OFFSET = SYMBOL_INFOW.Name.offset
BASE_SIZE = ctypes.sizeof(SYMBOL_INFOW)
MAX_NAME_CHARS = 4000
BUF_SIZE = BASE_SIZE + MAX_NAME_CHARS * 2

SYMOPT_UNDNAME = 0x00000002
SYMOPT_DEFERRED_LOADS = 0x00000004
SYMOPT_LOAD_ANYTHING = 0x00000040
SYMOPT_CASE_INSENSITIVE = 0x00000001
SYMOPT_EXACT_SYMBOLS = 0x00000400

SymSetOptions(SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS | SYMOPT_LOAD_ANYTHING | SYMOPT_CASE_INSENSITIVE)

hProcess = GetCurrentProcess()
ok = SymInitializeW(hProcess, SYM_DIR, False)
if not ok:
    print("SymInitializeW failed, GetLastError=", GetLastError())
    sys.exit(1)

base = SymLoadModuleExW(hProcess, None, EXE_PATH, None, 0, 0, None, 0)
if base == 0:
    print("SymLoadModuleExW failed, GetLastError=", GetLastError())
    SymCleanup(hProcess)
    sys.exit(1)

print(f"Module loaded at base 0x{base:X}")

matches = {p: [] for p in PATTERNS}
total = [0]

CALLBACK_TYPE = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.POINTER(SYMBOL_INFOW), ctypes.c_ulong, ctypes.c_void_p)
compiled = {p: (re.compile(p, re.IGNORECASE) if p else None) for p in PATTERNS}


def callback(sym_info_ptr, size, ctx):
    total[0] += 1
    info = sym_info_ptr.contents
    addr = ctypes.addressof(info)
    name = ctypes.wstring_at(addr + NAME_OFFSET, info.NameLen).rstrip()
    for p, rx in compiled.items():
        if rx is None or rx.search(name):
            matches[p].append((info.Address - base, name))
    return 1  # continue enumeration


cb = CALLBACK_TYPE(callback)

SymEnumSymbolsW = dbghelp.SymEnumSymbolsW
SymEnumSymbolsW.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_wchar_p, CALLBACK_TYPE, ctypes.c_void_p]
SymEnumSymbolsW.restype = ctypes.c_int

mask = "*"
ok = SymEnumSymbolsW(hProcess, base, mask, cb, None)
if not ok:
    print("SymEnumSymbolsW failed, GetLastError=", GetLastError())

print(f"Total symbols enumerated: {total[0]}")
for p in PATTERNS:
    lst = matches[p]
    print(f"\n=== Matches for pattern {p!r}: {len(lst)} ===")
    for off, name in lst[:200]:
        print(f"  +0x{off:X}  {name}")

SymUnloadModule64(hProcess, base)
SymCleanup(hProcess)
