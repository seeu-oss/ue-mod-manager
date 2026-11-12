"""体检与一键修复。

只做"能确定的事"：结构错位、无效包、chunk 撞车、残留链接、复制而非链接。
所有修复都不改源文件：改名只改部署出来的硬链接名，记录在 ~/.uemm/renames.json。
真正的资源级冲突（两个 mod 改同一张贴图）不在这里做——那要解析 pak 索引。
"""

import re
from pathlib import Path

from . import mods, store

SEV = {"error": 0, "warn": 1, "info": 2}


def _issue(kind, severity, params=None, fix=None):
    return {
        "kind": kind,
        "severity": severity,
        "params": params or {},
        "fix": fix,
        "fixable": fix is not None,
    }


def diagnose(game):
    """扫描当前游戏，返回问题清单。只读，不改任何东西。"""
    staging = mods.staging_dir(game)
    target = mods.mods_target(game)
    running = mods.running(game.get("exe"))

    if not staging or not staging.is_dir():
        return {"running": running, "issues": [_issue("no_staging", "error")]}

    items = mods.list_mods(game, include_conflicts=False)
    enabled = store.enabled_map(game["key"])

    bad_no_pak, bad_pak, hoist, relink, iostore = [], [], [], [], []

    for m in items:
        mid = m["id"]
        src_dir = staging / mid

        if m["verdict"] == "bad":
            (bad_no_pak if m["note_key"] == "no_pak" else bad_pak).append(mid)
            continue

        if m["note_key"] == "iostore" and enabled.get(mid, True):
            iostore.append(mid)

        if not enabled.get(mid, True):
            continue

        deep = [rel for rel in m["pak_names"] if "/" in rel]
        if deep:
            hoist.append(mid)

        dst_dir = target / mid
        if dst_dir.is_dir():
            mapping = store.renames(game["key"]).get(mid, {})
            copied = 0
            for rel, src, _s in mods.walk_files(src_dir):
                cand = dst_dir / mapping.get(rel, rel)
                if cand.is_file() and not mods.same_file(src, cand):
                    copied += 1
            if copied:
                relink.append(mid)

    # chunk 号撞车：只看启用中的 mod
    by_chunk = {}
    for m in items:
        if not enabled.get(m["id"], True):
            continue
        for pak in m["pak_names"]:
            n = mods.chunk_of(pak)
            if n is not None:
                by_chunk.setdefault(n, set()).add(m["id"])

    issues = []
    if bad_no_pak:
        issues.append(_issue("not_ue", "error", {"n": len(bad_no_pak)},
                             {"kind": "disable", "ids": bad_no_pak}))
    if bad_pak:
        issues.append(_issue("bad_pak", "error", {"n": len(bad_pak)},
                             {"kind": "disable", "ids": bad_pak}))
    if hoist:
        issues.append(_issue("nested", "warn", {"n": len(hoist)},
                             {"kind": "hoist", "ids": hoist}))
    for n, owners in sorted(by_chunk.items()):
        if len(owners) > 1:
            ids = sorted(owners)[1:]          # 按名字留一个，其余换号
            issues.append(_issue("chunk", "warn",
                                 {"n": n, "c": len(owners)},
                                 {"kind": "renumber", "chunk": n, "ids": ids}))
    if relink:
        issues.append(_issue("copy", "info", {"n": len(relink)},
                             {"kind": "relink", "ids": relink}))
    if iostore:
        issues.append(_issue("iostore", "warn", {"n": len(iostore)}, None))

    # 清单里有、暂存目录里已经没了的
    orphans = [mid for mid in mods.manifest_mods(game)
               if not (staging / mid).is_dir()]
    if orphans:
        issues.append(_issue("orphan", "info", {"n": len(orphans)},
                             {"kind": "clean", "ids": orphans}))

    issues.sort(key=lambda x: SEV.get(x["severity"], 9))
    return {"running": running, "issues": issues}


# --------------------------------------------------------------------------
# 修复
# --------------------------------------------------------------------------


def _used_chunks(game):
    used = set()
    staging = mods.staging_dir(game)
    if staging and staging.is_dir():
        for entry in staging.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                for rel, _p, _s in mods.walk_files(entry):
                    n = mods.chunk_of(rel)
                    if n is not None:
                        used.add(n)
    return used


def apply_fix(game, fix):
    """执行一个修复动作。返回 {ok, changed, code?}。"""
    if mods.running(game.get("exe")):
        return {"ok": False, "code": "game_running"}

    kind = (fix or {}).get("kind")
    ids = [i for i in (fix or {}).get("ids") or [] if mods.valid_mod_id(i)]
    staging = mods.staging_dir(game)
    target = mods.mods_target(game)

    if kind == "disable":
        n = 0
        for mid in ids:
            if mods.set_mod(game, mid, False).get("ok"):
                n += 1
        return {"ok": True, "changed": n}

    if kind == "hoist":
        n = 0
        for mid in ids:
            for rel, _p, _s in mods.walk_files(staging / mid):
                if rel.lower().endswith(".pak") and "/" in rel:
                    store.set_rename(game["key"], mid, rel, Path(rel).name)
                    n += 1
            if (target / mid).is_dir():
                mods.deploy_mod(game, mid)
        return {"ok": True, "changed": n}

    if kind == "renumber":
        chunk = int(fix.get("chunk") or 0)
        used = _used_chunks(game)

        def alloc():
            # 只在 100–999 里找空位：够用，且不会撞到基础游戏的 pakchunk0-99
            for n in range(100, 1000):
                if n not in used:
                    used.add(n)
                    return n
            n = max(used | {0}) + 1
            used.add(n)
            return n

        n = 0
        for mid in sorted(ids):
            for rel, _p, _s in mods.walk_files(staging / mid):
                if mods.chunk_of(rel) != chunk:
                    continue
                new_name = re.sub(r"pakchunk\d+", f"pakchunk{alloc()}",
                                  Path(rel).name, count=1, flags=re.I)
                store.set_rename(game["key"], mid, rel, new_name)
                n += 1
            if (target / mid).is_dir():
                mods.deploy_mod(game, mid)
        return {"ok": True, "changed": n}

    if kind == "clean":
        n = 0
        for mid in ids:
            mods.undeploy_mod(game, mid)
            n += 1
        return {"ok": True, "changed": n}

    if kind == "relink":
        n = 0
        for mid in ids:
            if mods.deploy_mod(game, mid).get("ok"):
                n += 1
        return {"ok": True, "changed": n}

    return {"ok": False, "code": "unknown_fix"}
