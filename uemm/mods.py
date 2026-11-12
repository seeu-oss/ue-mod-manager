"""mod 的扫描、部署、安装与冲突检查。

部署方式：硬链接（同卷免费、不需要管理员权限），失败时退回复制。
目标：<项目>/Content/Paks/~mods/<mod 名>/<pak 文件>
"""

import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

from . import store

PAK_EXT = (".pak", ".utoc", ".ucas", ".sig")
MANIFEST = ".uemm.json"
CHUNK_RE = re.compile(r"pakchunk(\d+)", re.IGNORECASE)

# UE 的 FPakInfo 写在文件末尾：magic(4) + version(4) + ...
PAK_MAGIC = b"\xe1\x12\x6f\x5a"

# 两个浏览器标签页同时操作时，避免并发写 manifest / 同一个目录
_LOCK = threading.RLock()


def _locked(fn):
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


def pak_info(path: Path):
    """只读文件末尾 4KB 校验 pak 是否有效（pak 可能几十 GB，不能整读）。"""
    try:
        size = path.stat().st_size
        if size < 64:
            return {"valid": False, "version": None}
        with open(path, "rb") as f:
            f.seek(max(0, size - 4096))
            tail = f.read()
    except OSError:
        return {"valid": False, "version": None}

    pos = tail.rfind(PAK_MAGIC)
    if pos < 0:
        return {"valid": False, "version": None}
    try:
        version = int.from_bytes(tail[pos + 4:pos + 8], "little", signed=True)
    except Exception:
        version = None
    return {"valid": bool(version and 1 <= version <= 12), "version": version}


def analyze_mod(mod_dir: Path, iostore: bool):
    """判断这个 mod 是不是 UE 游戏能直接用的东西。"""
    files = walk_files(mod_dir)
    paks = [p for rel, p, _s in files if rel.lower().endswith(".pak")]
    container = any(rel.lower().endswith((".utoc", ".ucas")) for rel, _p, _s in files)

    if not paks and not container:
        return {"verdict": "bad", "note_key": "no_pak", "valid_paks": 0}

    if paks:
        valid = sum(1 for p in paks if pak_info(p)["valid"])
        if valid == 0:
            return {"verdict": "bad", "note_key": "bad_pak", "valid_paks": 0}
    else:
        valid = 0

    if iostore and not container:
        return {"verdict": "warn", "note_key": "iostore", "valid_paks": valid}
    if not paks and container:
        return {"verdict": "ok", "note_key": "ok", "valid_paks": 0}
    return {"verdict": "ok", "note_key": "ok", "valid_paks": valid}


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def walk_files(root: Path):
    out = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            p = Path(dirpath) / n
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append((p.relative_to(root).as_posix(), p, size))
    out.sort(key=lambda x: x[0].lower())
    return out


def valid_mod_id(mod_id):
    """只允许暂存目录下的一级目录名，挡掉 ../ 和路径分隔符。"""
    if not isinstance(mod_id, str) or not mod_id.strip():
        return False
    if mod_id in (".", ".."):
        return False
    if any(ch in mod_id for ch in '\\/:*?"<>|'):
        return False
    return Path(mod_id).name == mod_id


def staging_dir(game):
    """生效的暂存目录：配置过就用配置的，否则用游戏同盘的默认位置（不一定存在）。"""
    raw = game.get("staging")
    if raw:
        return Path(raw)
    game_path = Path(game["path"])
    anchor = game_path.anchor or "/"
    return Path(anchor) / "UEMM" / game["project"]


def mods_target(game):
    return Path(game["paks"]) / "~mods"


def ensure_staging(game):
    """确保暂存目录存在（必须在游戏同盘，否则硬链接会失败）。"""
    staging = staging_dir(game)
    staging.mkdir(parents=True, exist_ok=True)
    if not game.get("staging"):
        store.update_game(game["key"], staging=str(staging))
    return staging


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


def list_mods(game, include_conflicts=True):
    staging = staging_dir(game)
    enabled = store.enabled_map(game["key"])
    target = mods_target(game)
    iostore = _game_iostore(game)
    mods = []

    if staging and staging.is_dir():
        for entry in sorted(staging.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            files = walk_files(entry)
            mapping = store.renames(game["key"]).get(entry.name, {})
            paks = [mapping.get(rel, rel) for rel, _p, _s in files
                    if rel.lower().endswith(".pak")]
            total = sum(s for _r, _p, s in files)
            deployed = (target / entry.name).is_dir()
            verdict = analyze_mod(entry, iostore)
            mods.append({
                "id": entry.name,
                "files": len(files),
                "paks": len(paks),
                "pak_names": paks,
                "size": total,
                "size_h": human(total),
                "enabled": bool(enabled.get(entry.name, True)),
                "deployed": deployed,
                "verdict": verdict["verdict"],
                "note_key": verdict["note_key"],
                "valid_paks": verdict["valid_paks"],
            })

    if include_conflicts:
        attach_conflicts(mods)
    return mods


_IOSTORE_CACHE = {}


def _game_iostore(game):
    key = game.get("path")
    if key not in _IOSTORE_CACHE:
        from . import detect
        _IOSTORE_CACHE[key] = detect.game_uses_iostore(game.get("paks"))
    return _IOSTORE_CACHE[key]


def attach_conflicts(mods):
    """标出互相抢同一个 pak 文件名、或抢同一个 chunk 号的 mod。"""
    by_name = {}
    by_chunk = {}
    for m in mods:
        for pak in m["pak_names"]:
            base = Path(pak).name.lower()
            by_name.setdefault(base, []).append(m["id"])
            hit = CHUNK_RE.search(base)
            if hit:
                by_chunk.setdefault(int(hit.group(1)), []).append(m["id"])

    for m in mods:
        m["conflicts"] = []

    for base, owners in by_name.items():
        if len(owners) > 1:
            for mid in owners:
                mod = next(x for x in mods if x["id"] == mid)
                mod["conflicts"].append({"kind": "same_pak", "name": base})

    for chunk, owners in by_chunk.items():
        if len(set(owners)) > 1:
            for mid in set(owners):
                mod = next(x for x in mods if x["id"] == mid)
                mod["conflicts"].append({"kind": "same_chunk", "n": chunk})


def load_order(game):
    """按 UE 的挂载顺序列出 pak：文件名排序，越靠后优先级越高。"""
    mods = list_mods(game, include_conflicts=False)
    rows = []
    for m in mods:
        if not m["enabled"]:
            continue
        for pak in m["pak_names"]:
            rows.append((Path(pak).name.lower(), m["id"], Path(pak).name))
    rows.sort()
    return [{"mod": mod, "pak": pak} for _k, mod, pak in rows]


# --------------------------------------------------------------------------
# 部署
# --------------------------------------------------------------------------


def _link(src: Path, dst: Path, stats):
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
    except OSError:
        stats["failed"] += 1
        return False
    try:
        os.link(src, dst)
        stats["linked"] += 1
        return True
    except OSError:
        pass
    try:
        shutil.copy2(src, dst)
        stats["copied"] += 1
        return True
    except OSError:
        stats["failed"] += 1
        return False


@_locked
def deploy_mod(game, mod_id):
    if not valid_mod_id(mod_id):
        return {"ok": False, "code": "invalid_mod_id", "error": f"非法的 mod 名：{mod_id}"}

    staging = staging_dir(game)
    src_dir = staging / mod_id
    if not src_dir.is_dir():
        return {"ok": False, "code": "mod_not_found", "error": f"找不到这个 mod：{mod_id}"}

    target = mods_target(game)
    dst_dir = target / mod_id
    target.mkdir(parents=True, exist_ok=True)
    if dst_dir.exists():
        try:
            shutil.rmtree(dst_dir)      # 只删链接，源文件不受影响
        except OSError:
            pass
    dst_dir.mkdir(parents=True, exist_ok=True)

    stats = {"linked": 0, "copied": 0, "failed": 0}
    placed = []
    mapping = store.renames(game["key"]).get(mod_id, {})
    used_out = set()
    for rel, src, _size in walk_files(src_dir):
        out_rel = mapping.get(rel, rel)
        if out_rel in used_out:            # 改名后撞车，退让出唯一名字
            base = Path(out_rel)
            out_rel = f"{base.parent.as_posix()}/{base.stem}-dup{len(used_out)}{base.suffix}".lstrip("./")
        used_out.add(out_rel)
        dst = dst_dir / out_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if _link(src, dst, stats):
            placed.append(out_rel)

    manifest = _manifest(target)
    manifest["mods"][mod_id] = placed
    _save_manifest(target, manifest)
    return {"ok": stats["failed"] == 0, "stats": stats, "files": len(placed)}


@_locked
def undeploy_mod(game, mod_id):
    if not valid_mod_id(mod_id):
        return {"ok": False, "code": "invalid_mod_id", "error": f"非法的 mod 名：{mod_id}"}
    target = mods_target(game)
    dst = target / mod_id
    removed = 0
    if dst.is_dir():
        try:
            shutil.rmtree(dst)
            removed = 1
        except OSError as e:
            return {"ok": False, "error": f"删除失败：{e}"}
    manifest = _manifest(target)
    manifest["mods"].pop(mod_id, None)
    _save_manifest(target, manifest)
    return {"ok": True, "removed": removed}


def set_mod(game, mod_id, on):
    store.set_enabled(game["key"], mod_id, on)
    return deploy_mod(game, mod_id) if on else undeploy_mod(game, mod_id)


@_locked
def deploy_all(game):
    """按状态把所有 mod 对齐一次。"""
    staging = staging_dir(game)
    if not staging or not staging.is_dir():
        return {"ok": False, "code": "mod_not_found", "error": "暂存目录不存在"}

    enabled = store.enabled_map(game["key"])
    total = {"linked": 0, "copied": 0, "failed": 0, "removed": 0, "orphans": 0}
    seen = set()
    for entry in sorted(staging.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        seen.add(entry.name)
        if enabled.get(entry.name, True):
            res = deploy_mod(game, entry.name)
            for k in ("linked", "copied", "failed"):
                total[k] += res.get("stats", {}).get(k, 0)
        else:
            res = undeploy_mod(game, entry.name)
            total["removed"] += res.get("removed", 0)

    # 暂存目录里已经删掉的 mod，~mods 里的链接要一起清掉
    target = mods_target(game)
    manifest = _manifest(target)
    for mod_id in list(manifest.get("mods", {})):
        if mod_id in seen:
            continue
        d = target / mod_id
        if d.is_dir():
            try:
                shutil.rmtree(d)
                total["orphans"] += 1
            except OSError:
                pass
        manifest["mods"].pop(mod_id, None)
    _save_manifest(target, manifest)

    return {"ok": total["failed"] == 0, "stats": total}


@_locked
def remove_all(game):
    target = mods_target(game)
    manifest = _manifest(target)
    removed = 0
    for mod in list(manifest.get("mods", {})):
        d = target / mod
        if d.is_dir():
            try:
                shutil.rmtree(d)
                removed += 1
            except OSError:
                pass
    _save_manifest(target, {"mods": {}})
    return {"ok": True, "removed": removed}


def _manifest(target: Path):
    try:
        with open(target / MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("mods", {})
        return data
    except Exception:
        return {"mods": {}}


def _save_manifest(target: Path, data):
    try:
        target.mkdir(parents=True, exist_ok=True)
        with open(target / MANIFEST, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def manifest_mods(game):
    return dict(_manifest(mods_target(game)).get("mods", {}))


def same_file(a: Path, b: Path):
    """两个路径是否指向同一份数据（硬链接）。"""
    try:
        return a.stat().st_ino == b.stat().st_ino and a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False


def chunk_of(name):
    hit = CHUNK_RE.search(Path(name).name)
    return int(hit.group(1)) if hit else None


# --------------------------------------------------------------------------
# 安装
# --------------------------------------------------------------------------


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s)).strip().strip(".")
    return s[:80] or "mod"


def unique_dir(parent: Path, base: str):
    dest = parent / base
    n = 2
    while dest.exists():
        dest = parent / f"{base} ({n})"
        n += 1
    return dest


def install_archive(game, raw, filename):
    """把 zip / 单个 pak 装进暂存目录，并立刻启用。"""
    staging = ensure_staging(game)
    name = Path(filename).name
    lower = name.lower()

    if lower.endswith((".7z", ".rar")):
        return {"ok": False, "code": "bad_format", "error": "7z / rar 不支持，先解压成 zip"}
    if not lower.endswith((".zip",) + PAK_EXT):
        return {"ok": False, "code": "bad_format",
                "error": f"不支持的格式：{Path(name).suffix or '(无扩展名)'}"}

    dest = unique_dir(staging, safe_name(Path(name).stem))
    tmp = None
    try:
        dest.mkdir(parents=True)
        if lower.endswith(".zip"):
            tmp, content = _extract_zip(raw)
            moved = paks = 0
            used = set()
            for rel, src, _size in walk_files(content):
                if rel.lower().endswith(PAK_EXT):
                    base = Path(rel).name
                    if base.lower() in used:
                        out = dest / rel            # 同名 pak 保留子目录，避免互相覆盖
                    else:
                        used.add(base.lower())
                        out = dest / base           # pak 必须在 ~mods 根层
                    paks += 1
                else:
                    out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(out))
                moved += 1
            if moved == 0:
                shutil.rmtree(dest, ignore_errors=True)
                return {"ok": False, "error": "压缩包里没有文件"}
        else:
            (dest / name).write_bytes(raw)
            paks = 1
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "code": "install_failed", "error": f"安装失败：{e}"}
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    verdict = analyze_mod(dest, _game_iostore(game))
    if verdict["verdict"] == "bad":
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "code": "not_ue_mod", "id": dest.name,
                "error": "不是 UE mod（没有 pak / utoc）"}

    result = set_mod(game, dest.name, True)
    return {"ok": result.get("ok", False), "id": dest.name, "paks": paks,
            "code": result.get("code"), "error": result.get("error")}


def _extract_zip(raw):
    tmp = Path(tempfile.mkdtemp(prefix="uemm_"))
    archive = tmp / "upload.zip"
    archive.write_bytes(raw)
    out = tmp / "x"
    out.mkdir()
    with zipfile.ZipFile(archive) as z:
        root = out.resolve()
        for member in z.infolist():
            target = (out / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"压缩包里有非法路径：{member.filename}")
        z.extractall(out)
    entries = list(out.iterdir())
    content = entries[0] if len(entries) == 1 and entries[0].is_dir() else out
    return tmp, content


# --------------------------------------------------------------------------
# 进程检测（游戏是否在运行）
# --------------------------------------------------------------------------


def running(exe_path):
    """游戏是否在跑。Windows 用进程快照，其它平台读 /proc。"""
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
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    k32.CloseHandle.argtypes = [wt.HANDLE]

    snap = k32.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
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
