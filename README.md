# UE Mod Manager

一个只做虚幻引擎（UE4 / UE5）游戏的开源 mod 管理器。免费、无账号、不联网、不上传任何数据。

很多 UE 游戏的 mod 形态其实极其简单：**把 `.pak`（以及配套的 `.utoc` / `.ucas`）放进 `Content/Paks/~mods/`**，游戏就会加载。Vortex 对这类游戏支持得很别扭，MO2 则完全不碰。这个工具把这件事做干净。

![界面](docs/screenshot.png)

## 它解决什么

| 痛点 | 这个工具怎么做 |
|---|---|
| 装 mod 要手动翻目录、备份原文件 | 用**硬链接**部署，游戏目录里看不到副本，原文件永远不动 |
| 每次部署弹 UAC | 硬链接在 NTFS 上**不需要管理员权限**，全程无提权 |
| 想关掉某个 mod 得手动删文件 | 拨一下开关，立刻建/删链接 |
| 不知道哪个 mod 装了会没用 | **校验 pak 文件头**，判断是不是 UE 能直接吃的包 |
| 不知道 mod 之间有没有冲突 | 自动检测同名 pak、重复 chunk 号，并给出实际挂载顺序 |
| 不清楚哪个 mod 最后生效 | 「挂载顺序」面板按 UE 的真实加载顺序列出，越靠下优先级越高 |
| 英文不好 / 不想看翻译 | 界面自带 6 种语言，跟随浏览器语言自动切换，也可以手动选 |

## 拖进来就装

不用点按钮、不用选文件、不用挑游戏：**把 zip 拖到窗口的任意位置**，松手就装好并自动部署，页面会出现蓝色的拖放提示。

一次拖多个也行，按顺序装。

## 接着 Vortex 的资源用

两个层次，都是零搬运：

1. **共用模组库**：检测到你用 Vortex 管理过这个游戏，就提示「直接接入」，点一下把它的暂存目录当自己的用，原来下的 mod 全部出现。
2. **扫它的下载目录**：Vortex 下载完的 zip 都堆在 `%APPDATA%\Vortex\downloads\<游戏>\`，界面会显示「Vortex downloads: N」，点一下把没装过的直接装进来。

## 多语言

简体中文 / English / 日本語 / 한국어 / Русский / Español。

默认按浏览器的 `Accept-Language` 选，右上角可以随时切换，选择记在本地。**所有文案都在 `uemm/i18n.py`**，加一门语言就是加一个字典，测试会检查各语言键是否对齐。

## 自动到什么程度

| 行为 | 时机 |
|---|---|
| 识别游戏 | **只在启动时扫一次**（Steam + Epic）。想找新装的游戏，点「重新扫描」，不会在后台反复读你的硬盘 |
| 推导安装路径 | 选游戏就完成：`~mods` 从游戏目录算，暂存目录自动放在同一块盘 |
| 接管已有 mod 库 | 检测到 Vortex 的暂存目录时，页面出现「直接接入」，点一下就读进来，不搬文件 |

## 支持等级：先看标，再动手

游戏列表里每个游戏都带一个等级，扫描后立刻可见，不用点进去才知道能不能用。

| 等级 | 含义 | 触发条件 |
|---|---|---|
| 可直接用 | pak 直投能生效 | 没有下面的任何阻碍 |
| 有条件 | 能装，但要满足额外条件 | 游戏用 IoStore（要 `.utoc/.ucas`），或带反作弊 |
| 不支持 | 装了也没用 | mod 是插件体系（`Plugins/Mods`），根本不看 `~mods` |

判断全部来自游戏目录里的真实文件，不是内置游戏名单 —— 所以新游戏、冷门游戏也能判。

## 支持的启动器

| 来源 | 识别方式 |
|---|---|
| Steam | `libraryfolders.vdf` → 所有库 → 扫 `steamapps/common` |
| Epic | 启动器清单 `ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item` 里的 `InstallLocation`，读不到时退回常见安装目录 |
| 手动 | 「添加游戏目录」，指向含 `Engine` 的那一层 |

## 哪些游戏能用（先说清楚，省得下载了发现不支持）

判断标准只有三条，全中才算"完美可用"：

1. **虚幻引擎**（UE4 / UE5）
2. **直接读 `~mods` 里的 pak**（不需要额外 mod 加载器）
3. **没有反作弊拦着**

只中前两条的叫「有条件」，中了第三条反例的叫「不支持」。界面会自动给每个认出来的游戏打标，判断依据是游戏目录里的真实文件，不是内置名单。

### 能用的

| 游戏 | 说明 |
|---|---|
| Ready or Not | 本工具的主要验证对象 |
| Palworld / 幻兽帕鲁 | `Pal/Content/Paks/~mods` |
| STALKER 2 | `Stalker2/Content/Paks/~mods` |
| Hogwarts Legacy / 霍格沃茨之遗 | `Phoenix/Content/Paks/~mods` |
| Lies of P / 匹诺曹的谎言 | `LiesofP/Content/Paks/~mods` |
| Atomic Heart | `AtomicHeart/Content/Paks/~mods` |
| Borderlands 3 / 无主之地 3 | `Borderlands3/Content/Paks/~mods` |
| Star Wars Jedi: Fallen Order | `SwGame/Content/Paks/~mods` |
| FF7 Remake / 最终幻想 7 重制版 | `End/Content/Paks/~mods` |

UE5 游戏如果 Paks 里有 `.utoc`，mod 也必须带 `.utoc/.ucas`，界面会标「有条件」。

### 不能用的（常见误区）

| 游戏 | 引擎 | 为什么不行 |
|---|---|---|
| **Cyberpunk 2077 / 赛博朋克 2077** | REDengine 4 | 完全不同的生态：`archive/pc/mod/*.archive` + REDmod + RED4ext + CET，没有 pak，也没有 `~mods` |
| Baldur's Gate 3 | Divinity 4.0 | 用 `.pak` 但目录和格式都不同（`Data/`），不是 UE |
| Elden Ring / 装甲核心 | FromSoft 自研 | 不是 UE |
| CS2 / Dota 2 | Source 2 | 不是 UE |
| Squad | UE4 | mod 是引擎插件（`Plugins/Mods`），还有 EAC |
| Satisfactory | UE5 | 需要 SML 加载器，不是丢 pak |
| Fortnite / PUBG / Valorant | UE | 反作弊 + 纯在线，不允许 mod |

认出来但不支持的，界面会在游戏列表下面折叠一行「未支持的游戏（N）」，写明引擎 —— 这是为了让你知道**工具检查过了，是真的不行**，不是漏了。

## 不是所有 UE 游戏都一样

这一点必须说清楚：**硬链接部署对所有游戏都一样，但游戏认不认这个 pak，差别很大。**

| 形态 | 表现 | 本工具 |
|---|---|---|
| 纯 pak 直投 | mod 就是一个 `.pak`，放进 `~mods` 就生效（Ready or Not 这类 UE4 单机） | 完全可用 |
| IoStore | 游戏带 `.utoc` / `.ucas`，mod 也必须带容器才加载（多数 UE5 游戏） | 标「注意」 |
| 插件式 mod | mod 是引擎插件，放在 `<项目>/Plugins/Mods`，根本不看 `~mods`（Squad 就是） | 标「不建议」 |
| 反作弊在线游戏 | 带 EAC / BattlEye，联机时拒绝加载未签名 pak（Squad） | 标「有条件」 |
| 官方 mod 平台 | 游戏内置 mod.io / 创意工坊，官方渠道安装（Ready or Not 也有 mod.io 目录） | 只提示，不干预 |
| 脚本 mod | 需要 UE4SS 注入 DLL，不是 pak 能解决的 | 检测到 UE4SS 会提示 |

选游戏后，路径区会显示一行**兼容性判断**，把命中的情况列出来。判断依据全是目录里的实际文件，不是游戏名单。

## mod 可用性判定

每个 mod 会被标成三种之一：

| 标记 | 含义 | 依据 |
|---|---|---|
| 可用 | UE 能直接加载 | `.pak` 尾部有合法的 `FPakInfo` 魔数 |
| 注意 | 游戏用 IoStore，可能不生效 | 游戏 `Paks` 里有 `.utoc`，但 mod 只给了 `.pak` |
| 无效 | 根本不是 UE mod | 没有 `.pak`，或 pak 校验失败 |

校验只读文件末尾 4 KB，所以哪怕 pak 有几十 GB 也是瞬间完成。

## 支持的形态

只要求游戏满足 UE 的标准目录结构：

```
<游戏根>/
├── Engine/                      ← UE 引擎目录（识别依据）
└── <项目名>/
    ├── Content/Paks/            ← 资源包
    │   └── ~mods/               ← mod 放这里
    └── Binaries/Win64/*.exe     ← 用于判断游戏是否在运行
```

已验证：**Ready or Not**、**Squad**。理论上覆盖所有标准打包的 UE4/UE5 游戏，但不同游戏的 mod 规范不同（有些要求特定前缀，有些走 mod.io），遇到不兼容的欢迎提 issue。

## 这是什么形态的东西

一个**本地运行的工具，界面在浏览器里**。不是网站，也不需要域名。

```
双击启动  →  后台起一个只监听 127.0.0.1 的服务  →  浏览器打开 http://127.0.0.1:8780
```

为什么不做成传统桌面窗口程序：

- 界面用 HTML 写，改样式不用重新编译，改完刷新就生效
- 不依赖任何 GUI 框架，整个程序只有 Python 标准库
- 同一套代码在 Windows / Linux / macOS 上表现一致

这是很常见的做法：qBittorrent、Jellyfin、Syncthing、Stable Diffusion WebUI 都是这个结构。区别只是它们打包好了，用户不用装 Python。

## 给不想装 Python 的人

Release 里提供打包好的 `UEMM.exe`（PyInstaller 单文件），双击即用，不需要装任何东西。

## 三步上手（不用命令行）

1. 打开 `UEMM.exe`，浏览器自动弹出界面
2. 把 mod 的 zip **拖进窗口**，松手就装好
3. 不想要了，把右边的开关拨掉

如果 Windows 第一次拦你一下（提示"未知发布者"）：点**更多信息 → 仍要运行**。这是没有代码签名的小工具都会遇到的提示，不是报错。

游戏没被自动认出来？点「选择游戏文件夹」，选中游戏安装目录（里面有 `Engine` 那一层），不用手打路径。

## 快速开始

需要 Python 3.9+，无第三方依赖。

```bash
git clone <this-repo>
cd ue-mod-manager
python -m uemm --open
```

Windows 也可以直接双击 `run.bat`；Linux/macOS 用 `./run.sh`。

首次启动会自动扫描 Steam 库并列出所有 UE 游戏。扫不到的游戏可以点「添加游戏目录」，选中包含 `Engine` 的那一层目录。

## 用法

1. 顶部选游戏（启动时扫出来的都在下拉框里；装了新游戏点「重新扫描」）。
2. 如果页面提示「检测到 Vortex 的模组目录」，点「直接接入」，你以前用 Vortex 下的 mod 立刻全部出现。
3. 把 mod 的 zip **拖进页面**，或者点「添加 mod」选文件。装好会立刻启用。
4. 不想要了就拨开关，立刻从游戏里移除。

暂存目录默认自动创建在游戏同盘的 `UEMM/<项目名>/`，也可以直接指向 Vortex 的目录共用。**必须和游戏同一块硬盘**，否则硬链接会失败（此时会退回复制，但会占双倍空间）。

## 原理

```
暂存  D:\UEMM\ReadyOrNot\MyMod\pakchunk99-MyMod_P.pak
          │  os.link()  硬链接：两个路径指向同一份数据
          ▼
游戏  D:\steam\...\ReadyOrNot\Content\Paks\~mods\MyMod\pakchunk99-MyMod_P.pak
```

- 不复制数据，不占额外空间
- 删链接不影响源文件，反之亦然
- 不需要管理员权限，不会弹 UAC

配置文件在 `~/.uemm/`（`config.json` 存游戏列表与路径，`state.json` 存哪些 mod 开着）。

## 关于加载顺序

UE 会挂载 `~mods` 下所有 pak，**文件名排序越靠后优先级越高**，所以社区惯例是用 `pakchunk99-`、`ZZZZ_` 这类前缀把 mod 排到本体后面。

本工具不会改你的文件名，只做两件事：按真实顺序列出来，以及标出互相抢同一个 chunk 号的 mod。想调整优先级，请改 pak 文件名前缀。

## 已知限制

- 只处理 `.pak` / `.utoc` / `.ucas` / `.sig`，不解析 pak 内部资源，因此**不会检测"两个 mod 改了同一个贴图"这种资源级冲突**
- 和 Vortex 共用暂存目录时，**不要同时让两边都执行部署**，否则会互相覆盖 `~mods` 里的内容
- `.7z` / `.rar` 不支持（需要先解压成 zip）
- 不提供下载功能，mod 自己去 Nexus / mod.io / Discord 取
- 不处理 FOMOD、脚本扩展器、`.ini` 合并

## 它往游戏目录写了什么

只有两样，都可以一眼看完：

```
<项目>/Content/Paks/~mods/
├── <mod 名>/          ← 硬链接指向暂存目录里的真实文件
└── .uemm.json         ← 本工具的清单（记录了谁放了哪些文件，用于「全部撤下」）
```

不修改任何原始 `.pak`，不覆盖 `.exe`，不写注册表。

## 自己打包 exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name UEMM ^
  --icon docs/icon.ico launcher.py
```

Windows 上直接双击 `build.bat` 也行。产物在 `dist\UEMM.exe`，约 9 MB，单文件，不需要目标机器装 Python。

## 测试

```bash
python -m unittest discover -s tests -v
```

26 个用例，全部在临时目录里跑（自带假游戏、假 pak、假 Epic 清单），**不碰你真实的游戏目录**。覆盖：游戏识别、支持等级、Vortex 目录误判、pak 校验、硬链接部署、开关、残留清理、zip 路径穿越、同名 pak、配置读写。

## 开发

```
uemm/
├── detect.py   Steam / Epic 库解析 + UE 游戏识别 + 兼容性判断
├── mods.py     扫描、部署、安装、冲突检测、进程检测
├── store.py    配置与状态
├── server.py   HTTP 接口
├── web.py      单页界面
└── tests/      隔离环境的单元测试
```

调试扫描：

```bash
python -m uemm --scan
```

## License

MIT
