"""Dump a C++ class/struct's field layout (name, offset, size, type) straight
from MK10.pdb via dbghelp's type-info API (SymGetTypeFromName + SymGetTypeInfo
TI_GET_CHILDREN) - no Ghidra needed, same technique as dump_pdb_symbols.py
but for struct layout instead of function/global symbol names.

Usage: python dump_type_layout.py ClassName [ClassName2 ...]
"""
import ctypes
import os
import sys

EXE_PATH = os.environ.get(
    "MK10_EXE_PATH",
    r"F:\SteamLibrary\steamapps\common\MK10\Binaries\Retail\MK10.exe",
)
SYM_DIR = os.path.dirname(EXE_PATH)

dbghelp = ctypes.WinDLL("dbghelp.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")

SymSetOptions = dbghelp.SymSetOptions
SymSetOptions.argtypes = [ctypes.c_ulong]

SymInitializeW = dbghelp.SymInitializeW
SymInitializeW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
SymInitializeW.restype = ctypes.c_int

SymLoadModuleExW = dbghelp.SymLoadModuleExW
SymLoadModuleExW.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
    ctypes.c_uint64, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
]
SymLoadModuleExW.restype = ctypes.c_uint64

SymGetTypeFromNameW = dbghelp.SymGetTypeFromNameW
SymGetTypeFromNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_wchar_p, ctypes.c_void_p]
SymGetTypeFromNameW.restype = ctypes.c_int

SymGetTypeInfo = dbghelp.SymGetTypeInfo
SymGetTypeInfo.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
SymGetTypeInfo.restype = ctypes.c_int

GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.restype = ctypes.c_void_p
GetLastError = kernel32.GetLastError
GetLastError.restype = ctypes.c_ulong
LocalFree = kernel32.LocalFree


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


BASE_SIZE = ctypes.sizeof(SYMBOL_INFOW)
MAX_NAME_CHARS = 2000
BUF_SIZE = BASE_SIZE + MAX_NAME_CHARS * 2

# TI_GET_* constants (dbghelp.h, IMAGEHLP_SYMBOL_TYPE_INFO enum order - note
# the real enumerator is TI_FINDCHILDREN, not "TI_GET_CHILDREN", and
# TI_GET_OFFSET is 10, not 8 - both wrong in an earlier draft of this script,
# which made every TI_FINDCHILDREN call fail with a useless generic error
# until traced back to these two.)
TI_GET_SYMTAG = 0
TI_GET_SYMNAME = 1
TI_GET_LENGTH = 2
TI_GET_TYPE = 3
TI_GET_TYPEID = 4
TI_GET_BASETYPE = 5
TI_GET_OFFSET = 10
TI_GET_CHILDRENCOUNT = 13
TI_FINDCHILDREN = 7

SymTagUDT = 11
SymTagBaseClass = 13
SymTagData = 7
SymTagPointerType = 14
SymTagArrayType = 15
SymTagBaseType = 16

BASIC_TYPE_NAMES = {
    0: "btNoType", 1: "void", 2: "char", 3: "wchar_t", 6: "int", 7: "uint",
    8: "float", 10: "bool", 13: "long", 14: "ulong", 29: "int64/uint64-ish",
}


class TI_FINDCHILDREN_PARAMS_HDR(ctypes.Structure):
    _fields_ = [("Count", ctypes.c_ulong), ("Start", ctypes.c_ulong)]


def get_type_info_ulong(hProcess, base, type_id, req):
    out = ctypes.c_ulong(0)
    ok = SymGetTypeInfo(hProcess, base, type_id, req, ctypes.byref(out))
    return out.value if ok else None


def get_type_info_ulonglong(hProcess, base, type_id, req):
    out = ctypes.c_uint64(0)
    ok = SymGetTypeInfo(hProcess, base, type_id, req, ctypes.byref(out))
    return out.value if ok else None


def get_type_info_long(hProcess, base, type_id, req):
    out = ctypes.c_long(0)
    ok = SymGetTypeInfo(hProcess, base, type_id, req, ctypes.byref(out))
    return out.value if ok else None


def get_type_name(hProcess, base, type_id):
    ptr = ctypes.c_wchar_p()
    ok = SymGetTypeInfo(hProcess, base, type_id, TI_GET_SYMNAME, ctypes.byref(ptr))
    if not ok or not ptr.value:
        return None
    name = ptr.value
    LocalFree(ptr)
    return name


def describe_type(hProcess, base, type_id, depth=0):
    """Best-effort human-readable type name for a field's TypeId."""
    if depth > 4 or type_id is None:
        return "?"
    tag = get_type_info_ulong(hProcess, base, type_id, TI_GET_SYMTAG)
    if tag == SymTagBaseType:
        bt = get_type_info_ulong(hProcess, base, type_id, TI_GET_BASETYPE)
        length = get_type_info_ulonglong(hProcess, base, type_id, TI_GET_LENGTH)
        return f"{BASIC_TYPE_NAMES.get(bt, f'basetype{bt}')}({length})"
    if tag == SymTagPointerType:
        inner_id = get_type_info_ulong(hProcess, base, type_id, TI_GET_TYPEID)
        return describe_type(hProcess, base, inner_id, depth + 1) + "*"
    if tag == SymTagUDT:
        name = get_type_name(hProcess, base, type_id)
        return name or "<anon UDT>"
    if tag == SymTagArrayType:
        inner_id = get_type_info_ulong(hProcess, base, type_id, TI_GET_TYPEID)
        return describe_type(hProcess, base, inner_id, depth + 1) + "[]"
    name = get_type_name(hProcess, base, type_id)
    return name or f"<tag{tag}>"


def dump_class(hProcess, base, class_name):
    sym_buf = ctypes.create_string_buffer(BUF_SIZE)
    sym = ctypes.cast(sym_buf, ctypes.POINTER(SYMBOL_INFOW)).contents
    sym.SizeOfStruct = BASE_SIZE
    sym.MaxNameLen = MAX_NAME_CHARS
    ok = SymGetTypeFromNameW(hProcess, base, class_name, sym_buf)
    if not ok:
        print(f"{class_name}: SymGetTypeFromNameW failed, err={GetLastError()}")
        return
    type_id = sym.TypeIndex
    length = get_type_info_ulonglong(hProcess, base, type_id, TI_GET_LENGTH)
    print(f"\n=== {class_name} (TypeId={type_id}, sizeof={length}) ===")

    count = get_type_info_ulong(hProcess, base, type_id, TI_GET_CHILDRENCOUNT)
    if not count:
        print("  (no children / not a UDT)")
        return

    hdr_size = ctypes.sizeof(TI_FINDCHILDREN_PARAMS_HDR)
    buf = ctypes.create_string_buffer(hdr_size + count * ctypes.sizeof(ctypes.c_ulong))
    hdr = TI_FINDCHILDREN_PARAMS_HDR.from_buffer(buf)
    hdr.Count = count
    hdr.Start = 0
    ok = SymGetTypeInfo(hProcess, base, type_id, TI_FINDCHILDREN, buf)
    if not ok:
        print(f"  TI_FINDCHILDREN failed, err={GetLastError()}")
        return
    child_ids = (ctypes.c_ulong * count).from_buffer(buf, hdr_size)

    for child_id in child_ids:
        tag = get_type_info_ulong(hProcess, base, child_id, TI_GET_SYMTAG)
        name = get_type_name(hProcess, base, child_id) or "<unnamed>"
        if tag == SymTagBaseClass:
            offset = get_type_info_long(hProcess, base, child_id, TI_GET_OFFSET)
            offset_str = f"+0x{offset:X}" if offset is not None else "+0x?"
            print(f"  [base class] {offset_str}  {name}")
            continue
        if tag != SymTagData:
            continue  # skip member functions etc, we only want fields
        offset = get_type_info_long(hProcess, base, child_id, TI_GET_OFFSET)
        offset_str = f"+0x{offset:04X}" if offset is not None else "+0x????"
        field_type_id = get_type_info_ulong(hProcess, base, child_id, TI_GET_TYPEID)
        type_desc = describe_type(hProcess, base, field_type_id)
        field_len = get_type_info_ulonglong(hProcess, base, field_type_id, TI_GET_LENGTH)
        print(f"  {offset_str}  {type_desc}  {name}  (size={field_len})")


def main():
    class_names = sys.argv[1:]
    if not class_names:
        print("Usage: python dump_type_layout.py ClassName [ClassName2 ...]")
        sys.exit(1)

    SymSetOptions(0x00000002 | 0x00000004 | 0x00000040)  # UNDNAME | DEFERRED_LOADS | LOAD_ANYTHING
    hProcess = GetCurrentProcess()
    if not SymInitializeW(hProcess, SYM_DIR, False):
        print("SymInitializeW failed, err=", GetLastError())
        sys.exit(1)
    base = SymLoadModuleExW(hProcess, None, EXE_PATH, None, 0, 0, None, 0)
    if base == 0:
        print("SymLoadModuleExW failed, err=", GetLastError())
        sys.exit(1)
    print(f"Module loaded at base 0x{base:X}")

    for name in class_names:
        try:
            dump_class(hProcess, base, name)
        except Exception as exc:
            print(f"{name}: exception {exc!r}")


if __name__ == "__main__":
    main()
