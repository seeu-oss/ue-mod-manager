"""打包入口：PyInstaller 用它生成单文件 UEMM.exe。

平时开发用 `python -m uemm`，两者行为一致。
出错时弹一个系统对话框，避免 --noconsole 下双击没反应。
"""

import ctypes
import sys
import traceback


def show_error(text):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "UE Mod Manager", 0x10)
    except Exception:
        try:
            print(text)
        except Exception:
            pass


def main():
    try:
        from uemm.__main__ import main as run
        # 双击（没有参数）时默认开浏览器；带了参数就原样交给命令行解析，
        # 否则 UEMM.exe --port 8795 / --scan 会被悄悄忽略。
        args = sys.argv[1:]
        run(args if args else ["--open"])
    except SystemExit:
        raise
    except Exception:
        show_error("启动失败：\n\n" + traceback.format_exc())


if __name__ == "__main__":
    sys.exit(main())
