"""本地 HTTP 服务：界面和 API 都走这里，只监听 127.0.0.1。"""

import json
import os
import threading
import time
import traceback
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import detect, dialogs, doctor, entry, i18n, mods, store
from .web import render

# --------------------------------------------------------------------------
# 本地服务的安全边界
#
# 这个服务只应该被本机浏览器里的界面调用。之前没有做任何校验，结果是：
#   · 任意网页都能向 127.0.0.1 发跨站 POST（text/plain 可以绕过预检），
#     删掉部署链接、甚至把进程关掉；
#   · Host 头不校验，DNS 重绑定就能读到游戏路径这类信息。
# 下面三件事一起做：校验 Host / 校验 Origin / 只收 application/json。
# --------------------------------------------------------------------------

MAX_BODY = 2 * 1024 ** 3          # 单个请求体上限 2 GB，避免被撑爆内存

LOOPBACK = ("127.0.0.1", "localhost", "[::1]")


def origin_allowed(host_header, origin_header, port):
    """Host 必须是本机回环地址；带 Origin 时必须同源。"""
    host = (host_header or "").strip().lower()
    if host not in {f"{h}:{port}" for h in LOOPBACK}:
        return False
    origin = (origin_header or "").strip().rstrip("/").lower()
    if origin and origin not in {f"http://{h}:{port}" for h in LOOPBACK}:
        return False
    return True


def log_exception():
    """完整堆栈只写本地日志，不回给调用方。"""
    try:
        path = store.APP_HOME / "error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


class PayloadTooLarge(Exception):
    pass



def initial_scan():
    """只在进程启动时扫一次；之后要新游戏靠界面上的「重新扫描」。"""
    before = set(store.config()["games"].keys())
    found = detect.scan_games()
    for info in found:
        store.add_game(info)
    return len(set(store.config()["games"].keys()) - before)


VORTEX_DOWNLOADS = Path(os.environ.get("APPDATA", "")) / "Vortex" / "downloads"


def vortex_archives(limit=50):
    """Vortex 下载目录里的压缩包，新的排前面。"""
    if not VORTEX_DOWNLOADS.is_dir():
        return []
    # Vortex 按游戏分子目录存放（downloads/<game>/*.zip），所以要递归找
    try:
        items = [p for p in VORTEX_DOWNLOADS.rglob("*")
                 if p.is_file() and p.suffix.lower() in (".zip", ".pak")]
        items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []

    out = []
    for item in items:
        out.append({"name": item.name, "size": mods.human(item.stat().st_size),
                    "path": str(item)})
        if len(out) >= limit:
            break
    return out


def zip_paks(path):
    """只读 zip 的中央目录，拿到 pak / utoc 文件名（不解压、不读整个文件）。"""
    try:
        with zipfile.ZipFile(path) as z:
            return {Path(n).name.lower() for n in z.namelist()
                    if n.lower().endswith((".pak", ".utoc", ".ucas"))}
    except Exception:
        return set()


def game_payload(key):
    game = store.get_game(key)
    if not game:
        return None
    game = dict(game)
    game["key"] = key
    game["staging"] = str(mods.staging_dir(game))
    return game


class Handler(BaseHTTPRequestHandler):
    server_version = "UEMM"

    def log_message(self, fmt, *args):
        pass

    # ---- 输出 ----

    def send_bytes(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, code=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_bytes(code, payload, "application/json; charset=utf-8")

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise PayloadTooLarge(length)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            return json.loads(raw.decode("utf-8") or "{}"), raw
        except Exception:
            return {}, raw

    def guard(self):
        port = self.server.server_address[1]
        return origin_allowed(self.headers.get("Host"),
                              self.headers.get("Origin"), port)

    def forbidden(self):
        self.send_json({"ok": False, "code": "forbidden",
                        "error": "只接受来自本机界面的请求"}, 403)

    # ---- 路由 ----

    def do_GET(self):
        path = urlparse(self.path).path
        if not self.guard():
            return self.forbidden()
        if path in ("/", "/index.html"):
            lang = i18n.pick(self.headers.get("Accept-Language"))
            self.send_bytes(200, render(lang).encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/favicon.ico":
            icon = Path(__file__).resolve().parent.parent / "docs" / "icon.ico"
            if icon.is_file():
                self.send_bytes(200, icon.read_bytes(), "image/x-icon")
            else:
                self.send_bytes(204, b"", "image/x-icon")
        elif path == "/api/ping":
            self.send_json({"app": "uemm", "version": __import__("uemm").__version__,
                            "port": self.server.server_address[1]})

        elif path == "/api/entry":
            self.send_json(entry.status())

        elif path == "/api/games":
            self.send_json({"games": self.game_list(),
                            "unsupported": self.unsupported_games()})
        else:
            self.send_json({"error": "not found"}, 404)

    @staticmethod
    def game_list():
        out = []
        for g in store.games():
            g = dict(g)
            g["staging"] = str(mods.staging_dir(g))
            cap = detect.probe_capabilities(g)
            g["support"] = {"level": cap["level"], "label": cap["label"],
                            "notes": cap["notes"]}
            out.append(g)
        return out

    @staticmethod
    def unsupported_games():
        """认出来但不是 UE 的游戏，让用户知道"我们看过了"。"""
        try:
            return detect.scan_unsupported()
        except Exception:
            return []

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.guard():
            return self.forbidden()

        # 跨站请求无法伪造 application/json（会触发预检），所以正常界面走 JSON，
        # 只有拖文件上传那一路是原始字节。
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if path != "/api/install" and ctype != "application/json":
            return self.send_json({"ok": False, "code": "bad_content_type",
                                   "error": "只接受 application/json"}, 415)

        try:
            body, raw = self.read_body()
        except PayloadTooLarge:
            return self.send_json({"ok": False, "code": "too_large",
                                   "error": "文件超过 2 GB，请手动放进暂存目录"}, 413)
        except ValueError:
            return self.send_json({"ok": False, "code": "bad_request",
                                   "error": "Content-Length 不合法"}, 400)
        try:
            if path == "/api/games":
                self.send_json({"games": self.game_list(),
                                "unsupported": self.unsupported_games()})

            elif path == "/api/state":
                self.state(body)

            elif path == "/api/scan":
                self.scan()

            elif path == "/api/add_game":
                self.add_game(body)

            elif path == "/api/pick_game":
                self.pick_game()

            elif path == "/api/remove_game":
                key = body.get("key")
                if not store.get_game(key):
                    return self.send_json({"ok": False, "error": "游戏不存在"})
                store.remove_game(key)
                self.send_json({"ok": True})

            elif path == "/api/save_staging":
                self.save_staging(body)

            elif path == "/api/adopt_vortex":
                self.adopt_vortex(body)

            elif path == "/api/import_vortex":
                self.import_vortex(body)

            elif path == "/api/toggle":
                self.toggle(body)

            elif path == "/api/deploy":
                self.deploy(body)

            elif path == "/api/entry":
                self.entry_action(body)

            elif path == "/api/doctor":
                self.doctor(body)

            elif path == "/api/doctor_fix":
                self.doctor_fix(body)

            elif path == "/api/undeploy":
                game = game_payload(body.get("key"))
                if not game:
                    return self.send_json({"ok": False, "error": "游戏不存在"})
                self.send_json(mods.remove_all(game))

            elif path == "/api/install":
                self.install(body, raw)

            elif path == "/api/open":
                self.open_folder(body)

            elif path == "/api/quit":
                self.send_json({"ok": True})
                threading.Timer(0.3, lambda: os._exit(0)).start()

            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as e:
            log_exception()
            self.send_json({"ok": False, "code": "internal_error", "error": str(e)}, 500)

    # ---- 各接口实现 ----

    def state(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"code": "game_not_found", "error": "游戏不存在"})
        running = mods.running(game.get("exe"))
        vortex = detect.vortex_staging(game)
        self.send_json({
            "game": game,
            "running": running,
            "iostore": mods._game_iostore(game),
            "compat": detect.probe_capabilities(game),
            "vortex": {"path": str(vortex[0]), "mods": vortex[1]} if vortex else None,
            "vortex_archives": vortex_archives(),
            "mods": mods.list_mods(game),
            "order": mods.load_order(game),
        })

    def scan(self):
        found = detect.scan_games()
        before = set(store.config()["games"].keys())
        for info in found:
            store.add_game(info)
        added = len(set(store.config()["games"].keys()) - before)
        self.send_json({"ok": True, "found": len(found), "added": added,
                        "games": self.game_list()})

    def add_game(self, body):
        raw = (body.get("path") or "").strip().strip('"')
        if not raw:
            return self.send_json({"ok": False, "error": "没有填路径"})
        info = detect.detect_ue(Path(raw))
        if not info:
            return self.send_json({"ok": False, "code": "bad_game_dir",
                                   "error": "这个目录不像 UE 游戏"})
        key = store.add_game(info)
        self.send_json({"ok": True, "key": key, "name": info["name"]})

    def pick_game(self):
        """弹系统文件夹选择框，选中 UE 游戏就直接加进来。"""
        if not dialogs.available():
            return self.send_json({"ok": False, "code": "no_dialog", "error": "当前环境不支持对话框"})
        folder = dialogs.pick_folder("选择 UE 游戏根目录（含 Engine 的那一层）")
        if not folder:
            return self.send_json({"ok": False, "cancelled": True, "error": "cancelled"})
        info = detect.detect_ue(Path(folder))
        if not info:
            return self.send_json({"ok": False, "code": "bad_game_dir",
                                   "error": "这个目录不像 UE 游戏"})
        key = store.add_game(info)
        self.send_json({"ok": True, "key": key, "name": info["name"]})

    def save_staging(self, body):
        key = body.get("key")
        game = game_payload(key)
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        path = (body.get("path") or "").strip().strip('"')
        if not path:
            return self.send_json({"ok": False, "code": "empty_path", "error": "路径为空"})
        p = Path(path)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return self.send_json({"ok": False, "error": f"无法创建目录：{e}"})
        if p.anchor.lower() != Path(game["path"]).anchor.lower():
            return self.send_json({"ok": False, "code": "same_drive",
                                   "error": f"暂存目录必须和游戏同盘（游戏在 {Path(game['path']).anchor}）"})
        store.update_game(key, staging=str(p))
        self.send_json({"ok": True})

    def adopt_vortex(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        found = detect.vortex_staging(game)
        if not found:
            return self.send_json({"ok": False, "code": "no_vortex", "error": "没有找到 Vortex 的模组目录"})
        store.update_game(game["key"], staging=str(found[0]), staging_source="vortex")
        self.send_json({"ok": True, "path": str(found[0]), "mods": found[1]})

    def import_vortex(self, body):
        """把 Vortex 下载目录里最新的压缩包直接装进来（跳过已装过的）。"""
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        if mods.running(game.get("exe")):
            return self.send_json({"ok": False, "code": "game_running", "error": "游戏正在运行"})

        staging = mods.staging_dir(game)
        have_paks = {pak.lower()
                     for m in mods.list_mods(game, include_conflicts=False)
                     for pak in m["pak_names"]}
        installed, skipped, errors = 0, 0, []
        for item in vortex_archives(20):
            src = Path(item["path"])
            stem = mods.safe_name(src.stem)
            if (staging / stem).exists():
                skipped += 1
                continue

            if src.suffix.lower() == ".zip":
                paks = zip_paks(src)
                if not paks:
                    skipped += 1      # 扩展包 / 翻译包，没有 pak，直接跳过
                    continue
                if paks <= have_paks:
                    skipped += 1      # 同名 pak 已经装过，不重复装
                    continue
            try:
                if src.stat().st_size > 600 * 1024 * 1024:
                    errors.append(f"{src.name}: 超过 600MB，请手动拖入")
                    continue
                raw = src.read_bytes()
            except OSError as e:
                errors.append(str(e))
                continue
            res = mods.install_archive(game, raw, item["name"])
            if res.get("ok"):
                installed += 1
            else:
                errors.append(res.get("error") or "install failed")

        payload = {"ok": installed > 0, "installed": installed,
                   "skipped": skipped, "errors": errors[:3]}
        if not installed:
            payload["code"] = "install_failed" if errors else "nothing_new"
        self.send_json(payload)

    def toggle(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        if mods.running(game.get("exe")):
            return self.send_json({"ok": False, "code": "game_running", "error": "游戏正在运行"})
        mod_id = body.get("id")
        if not mod_id:
            return self.send_json({"ok": False, "code": "invalid_mod_id", "error": "缺少 mod 名"})
        self.send_json(mods.set_mod(game, mod_id, bool(body.get("enabled"))))

    def deploy(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        if mods.running(game.get("exe")):
            return self.send_json({"ok": False, "code": "game_running", "error": "游戏正在运行"})
        self.send_json(mods.deploy_all(game))

    def entry_action(self, body):
        kind = body.get("kind")
        on = bool(body.get("on"))
        try:
            if kind == "desktop":
                path = entry.install_desktop() if on else entry.remove_desktop()
            elif kind == "autostart":
                path = entry.install_autostart() if on else entry.remove_autostart()
            else:
                return self.send_json({"ok": False, "code": "bad_entry"})
        except Exception as e:
            return self.send_json({"ok": False, "code": "entry_failed", "error": str(e)})
        payload = entry.status()
        payload.update(ok=True, path=str(path))
        self.send_json(payload)

    def doctor(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        try:
            self.send_json(doctor.diagnose(game))
        except Exception as e:
            self.send_json({"ok": False, "code": "doctor_failed", "error": str(e)})

    def doctor_fix(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        try:
            res = doctor.apply_fix(game, body.get("fix") or {})
        except Exception as e:
            return self.send_json({"ok": False, "code": "fix_failed", "error": str(e)})
        res["report"] = doctor.diagnose(game)
        self.send_json(res)

    def install(self, body, raw):
        key = self.headers.get("X-Game")
        game = game_payload(key)
        if not game:
            return self.send_json({"ok": False, "code": "game_not_found", "error": "游戏不存在"})
        if mods.running(game.get("exe")):
            return self.send_json({"ok": False, "code": "game_running", "error": "游戏正在运行"})
        if len(raw) < 8:
            return self.send_json({"ok": False, "code": "no_file", "error": "没收到文件内容"})
        filename = unquote(self.headers.get("X-Filename") or "mod.zip")
        self.send_json(mods.install_archive(game, raw, filename))

    def open_folder(self, body):
        game = game_payload(body.get("key"))
        if not game:
            return self.send_json({"ok": False, "error": "游戏不存在"})
        which = body.get("which")
        folder = {"staging": mods.staging_dir(game), "mods": mods.mods_target(game)}.get(which)
        if not folder:
            return self.send_json({"ok": False, "error": "未知目录"})
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            return self.send_json({"ok": False, "error": str(e)})
        self.send_json({"ok": True})


def probe(port, timeout=1.5):
    """这个端口上跑的是不是我们自己。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "uemm"
    except Exception:
        return False


def serve(port=8780, open_browser=False):
    if probe(port):
        url = f"http://127.0.0.1:{port}/"
        print(f"UE Mod Manager 已在运行  →  {url}")
        if open_browser:
            import webbrowser
            webbrowser.open(url)
        return

    httpd = None
    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("找不到可用端口")

    initial_scan()
    url = f"http://127.0.0.1:{port}/"
    print(f"UE Mod Manager  →  {url}")
    print("按 Ctrl+C 退出")

    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
