"""一键入口：桌面图标 + 开机自启。

都生成 VBS（无控制台窗口）。内容只用 ASCII，避免代码页问题。
测试用 UEMM_DESKTOP / UEMM_STARTUP 覆盖目标目录。
"""

import os
import sys
from pathlib import Path

DESKTOP_NAME = "UEMM 模组管理器.vbs"
STARTUP_NAME = "UEMM-server.vbs"


def _desktop_dir():
    override = os.environ.get("UEMM_DESKTOP")
    if override:
        return Path(override)
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x0010
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0:
            if buf.value:
                return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Desktop"


def _startup_dir():
    override = os.environ.get("UEMM_STARTUP")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return Path.home() / "Startup"


def _command():
    """返回 (工作目录, 启动命令)。打包后直接用 exe，源码跑用 pythonw -m uemm。"""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).parent), f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.is_file():
        pythonw = exe
    root = Path(__file__).resolve().parent.parent
    return str(root), f'"{pythonw}" -m uemm'


def _vbs(target, open_browser):
    workdir, cmd = _command()
    args = ' --open' if open_browser else ''
    lines = [
        'Set sh = CreateObject("WScript.Shell")',
        f'sh.CurrentDirectory = "{workdir}"',
        f'sh.Run "{cmd}{args}", 0, False',
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


def desktop_file():
    return _desktop_dir() / DESKTOP_NAME


def startup_file():
    return _startup_dir() / STARTUP_NAME


def install_desktop():
    _vbs(desktop_file(), open_browser=True)
    return str(desktop_file())


def remove_desktop():
    p = desktop_file()
    if p.exists():
        p.unlink()
        return True
    return False


def install_autostart():
    _vbs(startup_file(), open_browser=False)
    return str(startup_file())


def remove_autostart():
    p = startup_file()
    if p.exists():
        p.unlink()
        return True
    return False


def status():
    return {
        "desktop": desktop_file().is_file(),
        "desktop_path": str(desktop_file()),
        "autostart": startup_file().is_file(),
        "autostart_path": str(startup_file()),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
