"""pak 文件本身的格式知识：校验、判定、命名。

这里不碰目录结构，也不做部署 —— 只回答"这个文件是不是 UE 能读的 pak"。
"""

import os
import re
from pathlib import Path

PAK_EXT = (".pak", ".utoc", ".ucas", ".sig")

CHUNK_RE = re.compile(r"pakchunk(\d+)", re.IGNORECASE)

# UE 的补丁包后缀：_P.pak 优先级 +100，_2_P.pak 优先级 +300
PATCH_RE = re.compile(r"(?:_(\d+))?_p$", re.IGNORECASE)

# <项目>/Content/Paks 目录下 pak 的基础优先级（官方规则里的 3）
BASE_PRIORITY = 3

# UE 的 FPakInfo 写在文件末尾：magic(4) + version(4) + ...
PAK_MAGIC = b"\xe1\x12\x6f\x5a"

# 认识的 pak 版本范围。超出范围不下结论 —— 可能是更新引擎打的包。
KNOWN_VERSIONS = range(1, 13)


def pak_priority(name):
    """UE 的挂载优先级：基础 3 + 补丁后缀加成。

    _P.pak → 3 + 100；_2_P.pak → 3 + 300。数值越大越优先被查找，
    也就是越能覆盖别人。这是引擎的规则，不是我们的约定。
    """
    hit = PATCH_RE.search(Path(name).stem)
    if not hit:
        return BASE_PRIORITY
    n = int(hit.group(1) or 0)
    return BASE_PRIORITY + (n + 1) * 100


def is_patch_pak(name):
    return PATCH_RE.search(Path(name).stem) is not None


def pak_info(path: Path):
    """只读文件末尾 4KB 校验 pak 是否有效（pak 可能几十 GB，不能整读）。

    valid=True  版本号认识
    valid=False 连尾部魔数都没有，基本可以断定不是有效 pak
    valid=None  有魔数但版本号不在已知范围 —— 不下结论，只提示
    """
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
        return {"valid": False, "version": None}

    if version in KNOWN_VERSIONS:
        return {"valid": True, "version": version}
    return {"valid": None, "version": version}


def analyze_mod(mod_dir: Path, iostore: bool):
    """判断这个 mod 是不是 UE 游戏能直接用的东西。

    识别只给结论和证据，不做处置 —— 版本号读不准的时候宁可说"不知道"，
    也不要判成坏包让用户把好 mod 撤了。
    """
    files = walk_files(mod_dir)
    paks = [p for rel, p, _s in files if rel.lower().endswith(".pak")]
    container = any(rel.lower().endswith((".utoc", ".ucas")) for rel, _p, _s in files)

    if not paks and not container:
        return {"verdict": "bad", "note_key": "no_pak", "valid_paks": 0}

    version = None
    if paks:
        infos = [pak_info(p) for p in paks]
        valid = sum(1 for i in infos if i["valid"] is True)
        unknown_versions = [i["version"] for i in infos if i["valid"] is None]
        if valid == 0 and unknown_versions:
            return {"verdict": "warn", "note_key": "unknown_version",
                    "valid_paks": 0, "version": unknown_versions[0]}
        if valid == 0:
            return {"verdict": "bad", "note_key": "bad_pak", "valid_paks": 0}
        version = next((i["version"] for i in infos if i["valid"] is True), None)
    else:
        valid = 0

    extra = {"version": version} if version is not None else {}
    if iostore and not container:
        return {"verdict": "warn", "note_key": "iostore", "valid_paks": valid, **extra}
    if not paks and container:
        return {"verdict": "ok", "note_key": "ok", "valid_paks": 0, **extra}
    return {"verdict": "ok", "note_key": "ok", "valid_paks": valid, **extra}



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


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def valid_mod_id(mod_id):
    """只允许暂存目录下的一级目录名，挡掉 ../ 和路径分隔符。"""
    if not isinstance(mod_id, str) or not mod_id.strip():
        return False
    if mod_id in (".", ".."):
        return False
    if any(ch in mod_id for ch in '\\/:*?"<>|'):
        return False
    return Path(mod_id).name == mod_id


def chunk_of(name):
    hit = CHUNK_RE.search(Path(name).name)
    return int(hit.group(1)) if hit else None


def same_file(a: Path, b: Path):
    """两个路径是否指向同一份数据（硬链接）。"""
    try:
        return a.stat().st_ino == b.stat().st_ino and a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False
