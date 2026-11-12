"""原生文件夹选择框（Windows Shell API，不依赖 tkinter）。

打包后的 exe 里没有 tkinter，所以这里直接用 ctypes 调 shell32。

注意：SHBrowseForFolderW 返回的是 PIDL 指针，必须显式声明 restype，
否则 64 位下会被默认的 c_int 截断，导致崩溃或非法内存访问。
"""

import ctypes
import ctypes.wintypes as wt
import os


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wt.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wt.LPWSTR),
        ("lpszTitle", wt.LPCWSTR),
        ("ulFlags", wt.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", wt.LPARAM),
        ("iImage", ctypes.c_int),
    ]


BIF_RETURNONLYFSDIRS = 0x00000001
BIF_NEWDIALOGSTYLE = 0x00000040
BIF_EDITBOX = 0x00000010


def available():
    return os.name == "nt" and os.environ.get("UEMM_NO_DIALOG") != "1"


def pick_folder(title="选择文件夹"):
    """弹出系统文件夹选择框，返回路径；取消或不支持时返回 None。"""
    if not available():
        return None

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    except OSError:
        return None

    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFOW)]
    shell32.SHGetPathFromIDListW.restype = wt.BOOL
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wt.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoUninitialize.argtypes = []

    try:
        ole32.CoInitialize(None)
        initialized = True
    except Exception:
        initialized = False

    display = ctypes.create_unicode_buffer(260)
    info = _BROWSEINFOW()
    info.hwndOwner = None
    info.pidlRoot = None
    info.pszDisplayName = ctypes.cast(display, wt.LPWSTR)
    info.lpszTitle = title
    info.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX

    pidl = None
    try:
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return None
        path = ctypes.create_unicode_buffer(260)
        ok = shell32.SHGetPathFromIDListW(pidl, path)
        return path.value if ok and path.value else None
    except Exception:
        return None
    finally:
        if pidl:
            try:
                ole32.CoTaskMemFree(pidl)
            except Exception:
                pass
        if initialized:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass
