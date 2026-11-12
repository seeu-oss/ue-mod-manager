"""UE 游戏与 Steam 库探测。

识别规则（UE4 / UE5 通用）：
  <游戏根>/
      Engine/                          ← 引擎目录，UE 游戏必有
      <项目名>/Content/Paks/           ← 资源包目录
      <项目名>/Binaries/Win64/*.exe    ← 可执行文件

mod 一律放进 <项目名>/Content/Paks/~mods/<mod 名>/
"""

import json
import os
import re
from pathlib import Path

STEAM_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\Steam",
    r"E:\Steam",
    "/usr/local/steam",
    str(Path.home() / ".steam/steam"),
    str(Path.home() / ".local/share/Steam"),
]

MODS_DIR_NAME = "~mods"


# --------------------------------------------------------------------------
# libraryfolders.vdf 解析（Valve KeyValues，只需要读 path）
# --------------------------------------------------------------------------

_TOKEN = re.compile(r'"([^"]*)"|([{}])')


def parse_library_paths(vdf_path: Path):
    """从 libraryfolders.vdf 里抽出所有库路径。

    KeyValues 结构长这样，只需要抓 "path" 的下一项：
        "libraryfolders" { "0" { "path" "D:\\steam" ... } }
    """
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    tokens = [m.group(0) for m in _TOKEN.finditer(text)]
    paths = []
    for i in range(len(tokens) - 1):
        key, value = tokens[i], tokens[i + 1]
        if not (key.startswith('"') and value.startswith('"')):
            continue
        if key.strip('"').lower() != "path":
            continue
        raw = value.strip('"').replace("\\\\", "\\")
        if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("/"):
            paths.append(raw)
    return paths


def steam_libraries(extra_roots=None):
    """返回所有 Steam 库的 steamapps/common 目录（去重、只保留存在的）。"""
    roots = list(extra_roots or [])
    roots += [os.environ.get("STEAM_ROOT", ""), *STEAM_ROOTS]

    found = []
    for root in roots:
        if not root:
            continue
        root_path = Path(root)
        vdf = root_path / "steamapps" / "libraryfolders.vdf"
        candidates = []
        if vdf.is_file():
            for p in parse_library_paths(vdf):
                candidates.append(Path(p.replace("\\\\", "\\")))
        candidates.append(root_path)

        for lib in candidates:
            common = lib / "steamapps" / "common"
            if common.is_dir() and common not in found:
                found.append(common)
    return found


# --------------------------------------------------------------------------
# UE 游戏识别
# --------------------------------------------------------------------------


def detect_ue(game_root: Path):
    """判断一个目录是不是 UE 游戏根目录，是则返回结构信息。"""
    if not game_root.is_dir():
        return None
    if not (game_root / "Engine").is_dir():
        return None

    project = None
    paks = None
    for entry in game_root.iterdir():
        if not entry.is_dir() or entry.name.lower() in ("engine", "saved"):
            continue
        candidate = entry / "Content" / "Paks"
        if candidate.is_dir():
            project, paks = entry.name, candidate
            break
    if not paks:
        return None

    exe = None
    binaries = game_root / project / "Binaries" / "Win64"
    if binaries.is_dir():
        shipping = sorted(binaries.glob("*Shipping*.exe"))
        any_exe = shipping or sorted(binaries.glob("*.exe"))
        if any_exe:
            exe = any_exe[0]

    return {
        "path": str(game_root),
        "project": project,
        "name": pretty_name(game_root.name),
        "paks": str(paks),
        "mods": str(paks / MODS_DIR_NAME),
        "exe": str(exe) if exe else None,
        "engine": str(game_root / "Engine"),
    }


def pretty_name(raw: str):
    """目录名转展示名：Ready Or Not -> Ready Or Not（保留原样，仅去下划线）。"""
    return raw.replace("_", " ").strip() or raw


# --------------------------------------------------------------------------
# Epic 库探测
# --------------------------------------------------------------------------

EPIC_MANIFEST_DIRS = [
    Path(os.environ.get("UEMM_EPIC_MANIFESTS") or
         Path(os.environ.get("ProgramData", r"C:/ProgramData"))
         / r"Epic\EpicGamesLauncher\Data\Manifests"),
]

EPIC_FALLBACK_DIRS = [
    Path(r"C:/Program Files/Epic Games"),
    Path(r"C:/Program Files (x86)/Epic Games"),
    Path(r"D:/Epic Games"),
    Path(r"E:/Epic Games"),
]


def epic_install_dirs():
    """Epic 已安装游戏的目录列表。

    优先读启动器的清单（*.item），拿不到就退回常见安装目录。
    """
    found = []
    seen = set()

    for base in EPIC_MANIFEST_DIRS:
        if not base.is_dir():
            continue
        try:
            items = list(base.glob("*.item"))
        except OSError:
            continue
        for item in items:
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            location = data.get("InstallLocation") or ""
            if not location:
                continue
            path = Path(location)
            key = str(path).lower()
            if key in seen or not path.is_dir():
                continue
            seen.add(key)
            found.append({"path": path, "name": data.get("DisplayName") or path.name})

    for base in EPIC_FALLBACK_DIRS:
        if not base.is_dir():
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            key = str(entry).lower()
            if entry.is_dir() and key not in seen:
                seen.add(key)
                found.append({"path": entry, "name": entry.name})

    return found


# --------------------------------------------------------------------------
# 引擎识别（用于告诉用户"这个游戏为什么不支持"）
# --------------------------------------------------------------------------

ENGINE_LABEL = {
    "ue": "Unreal Engine",
    "redengine": "REDengine",
    "unity": "Unity",
    "source2": "Source 2",
    "creation": "Creation Engine",
    "unknown": "未知",
}


def detect_engine(root: Path):
    """认出游戏用什么引擎。只做目录级判断，不读二进制。

    返回 {"engine": key, "label": str} 或 None（不像游戏目录）。
    """
    if not root.is_dir():
        return None
    try:
        subs = [x for x in root.iterdir() if x.is_dir()]
        files = [x for x in root.iterdir() if x.is_file()]
    except OSError:
        return None

    names = {x.name.lower() for x in subs}
    filenames = {x.name.lower() for x in files}

    if "engine" in names and any((s / "content" / "paks").is_dir() for s in subs):
        return {"engine": "ue", "label": ENGINE_LABEL["ue"]}

    # 赛博朋克：archive/pc/content 里全是 .archive
    archive_pc = root / "archive" / "pc" / "content"
    if archive_pc.is_dir() or "redprelauncher.exe" in filenames:
        return {"engine": "redengine", "label": ENGINE_LABEL["redengine"]}

    if "unityplayer.dll" in filenames or any(
            (root / (s.name + "_Data")).is_dir() for s in subs):
        return {"engine": "unity", "label": ENGINE_LABEL["unity"]}

    if (root / "game" / "bin" / "win64").is_dir():
        return {"engine": "source2", "label": ENGINE_LABEL["source2"]}

    data = root / "Data"
    if data.is_dir():
        try:
            if any(data.glob("*.esm")) or any(data.glob("*.esp")):
                return {"engine": "creation", "label": ENGINE_LABEL["creation"]}
        except OSError:
            pass

    # 有 exe 但认不出引擎，也算"我们看过了"
    if any(f.suffix.lower() == ".exe" for f in files):
        return {"engine": "unknown", "label": ENGINE_LABEL["unknown"]}

    return None


# 不是游戏、不该出现在列表里的目录
SKIP_DIRS = {
    "steamworks shared", "steam library", "steamvr", "proton",
    "steamlinuxruntime_sniper", "steamlinuxruntime_soldier",
}


def scan_unsupported(libraries=None):
    """返回"认出来了但不是 UE"的游戏，供界面解释为什么没被支持。"""
    out = []
    seen = set()
    roots = list(libraries if libraries is not None else steam_libraries())

    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.lower() in SKIP_DIRS:
                continue
            if entry.name.lower() in seen:
                continue
            if detect_ue(entry):
                continue                      # UE 的走主列表
            info = detect_engine(entry)
            if not info or info["engine"] == "unknown":
                continue          # 认不出引擎的不列，避免把工具软件当游戏
            seen.add(entry.name.lower())
            out.append({
                "name": entry.name,
                "path": str(entry),
                "engine": info["engine"],
                "engine_label": info["label"],
            })

    out.sort(key=lambda x: x["name"].lower())
    return out


def scan_games(libraries=None, extra_paths=None):
    """扫描所有 Steam 库 + 手动指定的路径，返回 UE 游戏列表。"""
    games = []
    seen = set()

    roots = list(libraries if libraries is not None else steam_libraries())
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            info = detect_ue(entry)
            if info and info["path"].lower() not in seen:
                seen.add(info["path"].lower())
                info["source"] = "steam"
                games.append(info)

    for item in epic_install_dirs():
        info = detect_ue(Path(item["path"]))
        if info and info["path"].lower() not in seen:
            seen.add(info["path"].lower())
            info["source"] = "epic"
            games.append(info)

    for raw in extra_paths or []:
        info = detect_ue(Path(raw))
        if info and info["path"].lower() not in seen:
            seen.add(info["path"].lower())
            info["source"] = "manual"
            games.append(info)

    games.sort(key=lambda g: g["name"].lower())
    return games


# --------------------------------------------------------------------------
# Vortex 模组目录探测
# --------------------------------------------------------------------------

VORTEX_HOME = Path(os.environ.get("APPDATA", "")) / "Vortex"
STAGING_MARKER = "__vortex_staging_folder"
MOD_FILE_EXT = (".pak", ".esp", ".esm", ".esl", ".bsa", ".ba2", ".lua", ".jar")


def _norm(s: str):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def looks_like_staging(folder: Path):
    """判断一个目录是不是 Vortex 的 mod 暂存目录。

    强信号是 Vortex 自己放的标记文件；没有标记时，要求里面至少有一个
    子目录包含 mod 文件（避免把 profiles / snapshots 这类目录误判）。
    """
    if not folder.is_dir():
        return False
    if (folder / STAGING_MARKER).is_file():
        return True
    try:
        children = [d for d in folder.iterdir() if d.is_dir()]
    except OSError:
        return False
    for child in children[:50]:
        try:
            for f in child.iterdir():
                if f.is_file() and f.suffix.lower() in MOD_FILE_EXT:
                    return True
        except OSError:
            continue
    return False


def _drive_roots():
    if os.name != "nt":
        return [Path.home()]
    roots = []
    for letter in "CDEFGH":
        p = Path(f"{letter}:\\")
        if p.is_dir():
            roots.append(p)
    return roots


def vortex_staging(game: dict):
    """找 Vortex 给这个游戏用的 mod 暂存目录。

    依次尝试：AppData 下的默认位置 → 各盘的常用自定义位置（Vortex Mods 等）。
    返回 (path, mod_count) 或 None。
    """
    names = {_norm(game.get("project", "")), _norm(game.get("name", ""))}
    names.discard("")

    candidates = []
    if VORTEX_HOME.is_dir():
        candidates += [d for d in VORTEX_HOME.iterdir() if d.is_dir() and _norm(d.name) in names]

    for root in _drive_roots():
        for pattern in ("Vortex Mods", "Vortex", "VortexMods", "Mods"):
            base = root / pattern
            if not base.is_dir():
                continue
            try:
                candidates += [d for d in base.iterdir() if d.is_dir() and _norm(d.name) in names]
            except OSError:
                continue

    best = None
    for folder in candidates:
        if not looks_like_staging(folder):
            continue
        try:
            count = len([d for d in folder.iterdir()
                         if d.is_dir() and not d.name.startswith("__")])
        except OSError:
            continue
        if count and (best is None or count > best[1]):
            best = (folder, count)
    return best


def probe_capabilities(game: dict):
    """判断这个游戏对 pak mod 的接受程度 —— UE 游戏之间差别很大。

    返回 {"level": ok|limited|unsupported, "flags": {...}, "notes": [...]}
    """
    root = Path(game["path"])
    project = root / game["project"]
    paks_raw = game.get("paks")
    paks = Path(paks_raw) if paks_raw else project / "Content" / "Paks"

    flags = {
        "iostore": game_uses_iostore(paks),
        "anti_cheat": any((root / n).exists() for n in
                          ("EasyAntiCheat", "BattlEye", "start_protected_game.exe")),
        "plugins_mods": (project / "Plugins" / "Mods").is_dir(),
        "modio": (paks / "mod.io").is_dir() or (project / "mod.io").is_dir(),
        "ue4ss": any((project / "Binaries" / "Win64" / n).exists()
                     for n in ("UE4SS.dll", "dwmapi.dll")),
        "mods_dir": (paks / "~mods").is_dir(),
    }

    notes = []
    level = "ok"

    if flags["plugins_mods"]:
        level = "unsupported"
        notes.append("plugins_mods")
    if flags["iostore"]:
        if level == "ok":
            level = "limited"
        notes.append("iostore")
    if flags["anti_cheat"]:
        if level == "ok":
            level = "limited"
        notes.append("anti_cheat")
    if flags["modio"]:
        notes.append("modio")
    if flags["ue4ss"]:
        notes.append("ue4ss")

    labels = {"ok": "可直接用", "limited": "有条件", "unsupported": "不支持"}
    return {"level": level, "label": labels[level], "flags": flags, "notes": notes}


def game_uses_iostore(paks_dir) -> bool:
    """游戏是否用 IoStore（.utoc/.ucas）。这类游戏光有 .pak 通常不生效。"""
    try:
        p = Path(paks_dir)
        if not p.is_dir():
            return False
        return any(f.suffix.lower() == ".utoc" for f in p.iterdir() if f.is_file())
    except OSError:
        return False
