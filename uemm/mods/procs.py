"""进程检测：游戏是否正在运行。

改文件前必须确认游戏没开，否则 pak 会被占用、部署到一半失败。
Windows 走进程快照（不弹黑窗），其它平台读 /proc。
"""

import os
from pathlib import Path

_IMAGE_NAME = 260


def running(exe_path):
    """游戏是否在跑。"""
    if not exe_path:
        return False
    exe = Path(exe_path).name.lower()
    try:
        if os.name == "nt":
            return _running_windows(exe)
        return _running_posix(exe)
    except Exception:
        return False


def _running_windows(exe_name):
    import ctypes
    import ctypes.wintypes as wt

    class ENTRY(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * _IMAGE_NAME),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    k32.CloseHandle.argtypes = [wt.HANDLE]

    invalid = ctypes.c_void_p(-1).value
    snap = k32.CreateToolhelp32Snapshot(2, 0)      # TH32CS_SNAPPROCESS
    if not snap or snap == invalid:
        return False
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name:
                return True
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        k32.CloseHandle(snap)


def _running_posix(exe_name):
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmd = (p / "cmdline").read_bytes().lower()
        except OSError:
            continue
        if exe_name.encode() in cmd:
            return True
    return False
