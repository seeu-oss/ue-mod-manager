"""安装：把用户拖进来的 zip / 单个 pak 放进暂存目录。

只负责"落到暂存目录"，不负责部署；装完调用 deploy.set_mod 打开开关。
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .deploy import ensure_staging, game_iostore, set_mod
from .paks import PAK_EXT, analyze_mod, walk_files


def safe_name(s):
    """把压缩包名变成能当目录名的字符串。"""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s)).strip().strip(".")
    return s[:80] or "mod"


def unique_dir(parent: Path, base: str):
    dest = parent / base
    n = 2
    while dest.exists():
        dest = parent / f"{base} ({n})"
        n += 1
    return dest


def zip_paks(path):
    """只读 zip 的中央目录，拿到 pak / utoc 文件名（不解压、不读整个文件）。"""
    try:
        with zipfile.ZipFile(path) as z:
            return {Path(n).name.lower() for n in z.namelist()
                    if n.lower().endswith((".pak", ".utoc", ".ucas"))}
    except Exception:
        return set()


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

    verdict = analyze_mod(dest, game_iostore(game))
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
