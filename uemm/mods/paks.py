"""pak 文件本身的格式知识：校验、判定、命名。

这里不碰目录结构，也不做部署 —— 只回答"这个文件是不是 UE 能读的 pak"。
"""

import os
import re
from pathlib import Path

PAK_EXT = (".pak", ".utoc", ".ucas", ".sig")

CHUNK_RE = re.compile(r"pakchunk(\d+)", re.IGNORECASE)

# UE 的 FPakInfo 写在文件末尾：magic(4) + version(4) + ...
PAK_MAGIC = b"\xe1\x12\x6f\x5a"


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
