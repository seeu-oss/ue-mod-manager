# GitHub 仓库资料

建仓库时直接抄这里。

## 仓库名

```
ue-mod-manager
```

## 简介（About，英文，一句话）

```
Mod manager for Unreal Engine games: hardlink deployment, no UAC, pak validation and chunk-conflict fixes.
```

## 简介（中文版，备用）

```
虚幻引擎游戏的 mod 管理器：硬链接部署、零 UAC、pak 校验与 chunk 冲突修复。
```

## Topics（逐个添加）

```
unreal-engine
ue5
ue4
mod-manager
modding
ready-or-not
palworld
pak
hardlink
windows
python
```

## Release v0.3.1 标题

```
v0.3.1 — health check, one-click fixes, desktop launcher
```

## Release 说明

```
首个公开版本。

- 硬链接部署：不复制文件、不占双倍空间、不需要管理员权限、不弹 UAC
- 体检 + 一键修复：pak 错层、chunk 号撞车、非 UE 包、坏包、残留链接、复制而非链接
- pak 校验：只读文件末尾 4 KB，几十 GB 的包也是瞬间完成
- 自动识别 Steam / Epic 库里的 UE 游戏，非 UE 的标注引擎
- 接管 Vortex 的暂存目录与下载目录，零搬运
- 6 种语言：中文 / English / 日本語 / 한국어 / Русский / Español

下载 UEMM.exe（9.3 MB，单文件，无需 Python）。首次运行 Windows 会提示"未知发布者"，
点「更多信息 → 仍要运行」即可——这是没有代码签名证书的小工具都会遇到的提示。
```
