"""部署：把暂存目录里的 mod 挂到游戏的 ~mods 下，或者摘掉。

部署方式只有一种 —— 硬链接（同卷零成本）；跨卷或文件系统不支持时退回复制。
清单 `.uemm.json` 记在 ~mods 里，用于"全部撤下"和残留清理。
"""

import json
import os
import shutil
import threading
from pathlib import Path

from .. import detect, store
from .paks import analyze_mod, chunk_of, human, valid_mod_id, walk_files

MANIFEST = ".uemm.json"

# 两个浏览器标签页同时操作时，避免并发写 manifest / 同一个目录
_LOCK = threading.RLock()


def _locked(fn):
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


# --------------------------------------------------------------------------
# 路径推导
# --------------------------------------------------------------------------


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


def game_iostore(game):
    """游戏是否用 IoStore。不缓存 —— 游戏更新后缓存会变成错的。"""
    return detect.game_uses_iostore(game.get("paks"))


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


def list_mods(game, include_conflicts=True):
    staging = staging_dir(game)
    enabled = store.enabled_map(game["key"])
    target = mods_target(game)
    iostore = game_iostore(game)
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


def attach_conflicts(mods):
    """标出互相抢同一个 pak 文件名、或抢同一个 chunk 号的 mod。"""
    by_name = {}
    by_chunk = {}
    for m in mods:
        for pak in m["pak_names"]:
            base = Path(pak).name.lower()
            by_name.setdefault(base, []).append(m["id"])
            n = chunk_of(base)
            if n is not None:
                by_chunk.setdefault(n, []).append(m["id"])

    for m in mods:
        m["conflicts"] = []

    index = {m["id"]: m for m in mods}
    for base, owners in by_name.items():
        if len(owners) > 1:
            for mid in owners:
                index[mid]["conflicts"].append({"kind": "same_pak", "name": base})

    for chunk, owners in by_chunk.items():
        if len(set(owners)) > 1:
            for mid in set(owners):
                index[mid]["conflicts"].append({"kind": "same_chunk", "n": chunk})


def load_order(game):
    """按 UE 的挂载顺序列出 pak：文件名排序，越靠后优先级越高。"""
    rows = []
    for m in list_mods(game, include_conflicts=False):
        if not m["enabled"]:
            continue
        for pak in m["pak_names"]:
            rows.append((Path(pak).name.lower(), m["id"], Path(pak).name))
    rows.sort()
    return [{"mod": mod, "pak": pak} for _key, mod, pak in rows]


# --------------------------------------------------------------------------
# 部署 / 摘除
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


def _unique_rel(rel: str, taken: set):
    """改名后撞车时给个不重名的相对路径。"""
    if rel not in taken:
        return rel
    base = Path(rel)
    name = f"{base.stem}-dup{len(taken)}{base.suffix}"
    return name if base.parent == Path(".") else f"{base.parent.as_posix()}/{name}"


@_locked
def deploy_mod(game, mod_id):
    if not valid_mod_id(mod_id):
        return {"ok": False, "code": "invalid_mod_id", "error": f"非法的 mod 名：{mod_id}"}

    src_dir = staging_dir(game) / mod_id
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
        out_rel = _unique_rel(mapping.get(rel, rel), used_out)
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
    """开关一个 mod。操作失败要把开关状态退回去，否则界面显示开着、实际没文件。"""
    previous_map = store.enabled_map(game["key"])
    had_record = mod_id in previous_map
    previous = previous_map.get(mod_id, True)

    store.set_enabled(game["key"], mod_id, on)
    result = deploy_mod(game, mod_id) if on else undeploy_mod(game, mod_id)
    if not result.get("ok"):
        if had_record:
            store.set_enabled(game["key"], mod_id, previous)
        else:
            store.clear_enabled(game["key"], mod_id)
        result["rolled_back"] = True
    return result


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


# --------------------------------------------------------------------------
# 清单
# --------------------------------------------------------------------------


def _manifest(target: Path):
    try:
        with open(target / MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("mods", {})
        return data
    except Exception:
        return {"mods": {}}


def _save_manifest(target: Path, data):
    """先写临时文件再原子替换：写一半断电也不会把清单写坏。"""
    try:
        target.mkdir(parents=True, exist_ok=True)
        tmp = target / (MANIFEST + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target / MANIFEST)
    except OSError:
        pass


def manifest_mods(game):
    return dict(_manifest(mods_target(game)).get("mods", {}))
