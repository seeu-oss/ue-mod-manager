"""python -m uemm"""

import argparse
import os
import sys

from . import __version__, detect, server, store


def main(argv=None):
    # --noconsole 打包后 sys.stdout 是 None，print 会抛异常
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser(prog="uemm", description="UE Mod Manager")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 8780）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--scan", action="store_true", help="只扫描游戏并打印结果，不启动服务")
    parser.add_argument("--version", action="version", version=f"UEMM {__version__}")
    args = parser.parse_args(argv)

    if args.scan:
        games = detect.scan_games()
        if not games:
            print("没有找到 UE 游戏")
            return 0
        for g in games:
            key = store.add_game(g)
            print(f"{g['name']}\n  {g['path']}\n  key={key}\n  ~mods={g['mods']}")
        return 0

    if not store.games():
        print("首次运行，扫描 Steam 库…")
        found = detect.scan_games()
        for g in found:
            store.add_game(g)
        print(f"发现 {len(found)} 个 UE 游戏")

    port = args.port or store.config().get("port", 8780)
    server.serve(port=port, open_browser=args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
