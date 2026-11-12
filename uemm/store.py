"""配置与状态持久化。

配置放在 ~/.uemm/config.json，状态放在 ~/.uemm/state.json。
两者分开：配置是用户改的（游戏列表、路径），状态是程序改的（哪些 mod 开着）。
"""

import hashlib
import json
import os
from pathlib import Path

APP_HOME = Path(os.environ.get("UEMM_HOME") or (Path.home() / ".uemm"))
CONFIG_PATH = APP_HOME / "config.json"
STATE_PATH = APP_HOME / "state.json"
RENAME_PATH = APP_HOME / "renames.json"

DEFAULT_CONFIG = {"port": 8780, "games": {}}


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg.update(_load(CONFIG_PATH, {}))
    cfg.setdefault("games", {})
    return cfg


def save_config(cfg):
    _save(CONFIG_PATH, cfg)


def state():
    return _load(STATE_PATH, {})


def save_state(st):
    _save(STATE_PATH, st)


def game_key(info):
    """稳定且可读的 key：项目名 + 路径短哈希。"""
    digest = hashlib.sha1(info["path"].lower().encode("utf-8")).hexdigest()[:6]
    slug = "".join(c if c.isalnum() else "-" for c in info["project"].lower())
    return f"{slug}-{digest}"


def games():
    """配置里的游戏，附带是否仍然存在。"""
    cfg = config()
    out = []
    for key, g in cfg["games"].items():
        g = dict(g)
        g["key"] = key
        g["exists"] = Path(g.get("path", "")).is_dir()
        out.append(g)
    out.sort(key=lambda x: x.get("name", "").lower())
    return out


def get_game(key):
    return config()["games"].get(key)


def add_game(info, staging=None):
    """把探测到的游戏写进配置。

    暂存目录优先级：显式传入 > 已保存的 > Vortex 的模组目录 > 留空（用默认位置）。
    """
    from . import detect

    cfg = config()
    key = game_key(info)
    old = cfg["games"].get(key, {})

    staging_path = staging or old.get("staging")
    source = old.get("staging_source", "custom")

    if not staging_path:
        found = detect.vortex_staging(info)
        if found:
            staging_path = str(found[0])
            source = "vortex"

    entry = {
        "name": info.get("name") or info["project"],
        "path": info["path"],
        "project": info["project"],
        "paks": info["paks"],
        "mods": info["mods"],
        "exe": info.get("exe"),
        "source": info.get("source") or old.get("source") or "manual",
        "staging": staging_path,
        "staging_source": source if staging_path else "auto",
    }
    cfg["games"][key] = entry
    save_config(cfg)
    return key


def remove_game(key):
    cfg = config()
    cfg["games"].pop(key, None)
    save_config(cfg)
    st = state()
    st.pop(key, None)
    save_state(st)


def update_game(key, **fields):
    cfg = config()
    if key not in cfg["games"]:
        return False
    cfg["games"][key].update(fields)
    save_config(cfg)
    return True


def enabled_map(key):
    return state().get(key, {})


def set_enabled(key, mod_id, on):
    st = state()
    st.setdefault(key, {})[mod_id] = bool(on)
    save_state(st)


# --------------------------------------------------------------------------
# 部署时的改名映射（只改链接名，不动源文件）
# 结构：{game_key: {mod_id: {相对路径: 新的相对路径}}}
# --------------------------------------------------------------------------


def renames(key):
    return _load(RENAME_PATH, {}).get(key, {})


def set_rename(key, mod_id, rel, out_rel):
    data = _load(RENAME_PATH, {})
    data.setdefault(key, {}).setdefault(mod_id, {})[rel] = out_rel
    _save(RENAME_PATH, data)


def clear_rename(key, mod_id, rel=None):
    data = _load(RENAME_PATH, {})
    mods = data.get(key, {}).get(mod_id)
    if not mods:
        return
    if rel is None:
        mods.clear()
    else:
        mods.pop(rel, None)
    _save(RENAME_PATH, data)
