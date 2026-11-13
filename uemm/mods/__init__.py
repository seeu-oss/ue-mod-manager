"""mod 子系统。

分四层，每层只做一件事：

    paks.py     pak 文件格式（校验、判定、命名）
    deploy.py   目录与硬链接（暂存目录、部署、清单）
    install.py  压缩包落盘（zip / 单个 pak → 暂存目录）
    procs.py    游戏是否在运行

对外只暴露这一层，server / doctor 都从这里取，不直接摸内部文件。
"""

from .deploy import (
    MANIFEST,
    attach_conflicts,
    deploy_all,
    deploy_mod,
    ensure_staging,
    game_iostore,
    list_mods,
    load_order,
    manifest_mods,
    mods_target,
    remove_all,
    set_mod,
    staging_dir,
    undeploy_mod,
)
from .install import install_archive, safe_name, unique_dir, zip_paks
from .paks import (
    CHUNK_RE,
    PAK_EXT,
    PAK_MAGIC,
    analyze_mod,
    chunk_of,
    human,
    pak_info,
    same_file,
    valid_mod_id,
    walk_files,
)
from .procs import running

__all__ = [
    # paks
    "PAK_EXT", "PAK_MAGIC", "CHUNK_RE", "pak_info", "analyze_mod",
    "walk_files", "human", "valid_mod_id", "chunk_of", "same_file",
    # deploy
    "MANIFEST", "staging_dir", "mods_target", "ensure_staging", "game_iostore",
    "list_mods", "attach_conflicts", "load_order", "deploy_mod", "undeploy_mod",
    "set_mod", "deploy_all", "remove_all", "manifest_mods",
    # install
    "safe_name", "unique_dir", "zip_paks", "install_archive",
    # procs
    "running",
]
