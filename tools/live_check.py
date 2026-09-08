import ctypes
from ctypes import wintypes
import sys

PID = int(sys.argv[1])
RVAS = {
    "GUIScreenManager": 0x33BF070,
}

kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010


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


CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
CreateToolhelp32Snapshot.restype = wintypes.HANDLE

Module32First = kernel32.Module32First
Module32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32)]
Module32First.restype = wintypes.BOOL

Module32Next = kernel32.Module32Next
Module32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32)]
Module32Next.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle

snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, PID)
if snap == -1 or snap == 0:
    print("CreateToolhelp32Snapshot failed, err=", ctypes.get_last_error())
    sys.exit(1)

me = MODULEENTRY32()
me.dwSize = ctypes.sizeof(MODULEENTRY32)
base = None
size = None
if Module32First(snap, ctypes.byref(me)):
    while True:
        name = me.szModule.decode(errors="replace")
        if name.lower() == "mk10.exe":
            base = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value
            size = me.modBaseSize
            print(f"Found MK10.exe module: base=0x{base:X} size=0x{size:X}")
        if not Module32Next(snap, ctypes.byref(me)):
            break
CloseHandle(snap)

if base is None:
    print("MK10.exe module not found in process snapshot")
    sys.exit(1)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

hProc = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, PID)
if not hProc:
    print("OpenProcess failed, err=", ctypes.get_last_error())
    sys.exit(1)

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL

PREFERRED_IMAGE_BASE = 0x140000000

for name, rva in RVAS.items():
    live_addr = base + rva
    buf = (ctypes.c_ubyte * 32)()
    nread = ctypes.c_size_t(0)
    ok = ReadProcessMemory(hProc, ctypes.c_void_p(live_addr), buf, 32, ctypes.byref(nread))
    if ok:
        raw = bytes(buf)
        as_ptr = int.from_bytes(raw[0:8], "little")
        print(f"{name}: live_addr=0x{live_addr:X} (preferred_base_delta={base - PREFERRED_IMAGE_BASE:+X}) bytes_read={nread.value}")
        print(f"  raw: {raw.hex()}")
        print(f"  first 8 bytes as little-endian pointer: 0x{as_ptr:X}")
    else:
        print(f"{name}: ReadProcessMemory FAILED at 0x{live_addr:X}, err={ctypes.get_last_error()}")

CloseHandle(hProc)
