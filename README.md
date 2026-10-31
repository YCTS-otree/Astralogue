# Astralogue — 星轨叙事引擎

离线交互式剧情引擎，Python 3.11+，Windows / Linux，CLI 使用 Typer + Rich。
构建阶段将游戏数据解析为自己的 SQLite `.storypack`；播放器只读该包。
当前版本 **1.2.0**，StoryPack Schema **1**。

M5.7 增加构建阶段 AnimeStudio CLI 适配器、受限资源复制/导出、原生对象头与引用图解析。
已实际读取本机 ENCR 并导出剧情资产，但自定义 Timeline 控制字段尚未恢复，新增完整可玩主线为 0。
不要把资源导出当作剧情执行成功。详见 [M5.7 实测报告](docs/m57-verification.md)。

```powershell
# 使用现有环境；工具输入自动复制到 staging，游戏目录保持只读
.\.venv\Scripts\astralogue.exe hsr native-assets `
  --executable 'G:\hoyostudio\AnimeStudio-net10-68700c7d885a68a444886bd4b7f7827e77789e12\AnimeStudio.CLI.exe' `
  --game 'O:\Program Files\miHoYo Launcher\games\Star Rail\Game' `
  --name my-map --limit 16 --max-mib 128
# 每次 name 必须唯一；可用 --block 精确指定 Map 中的块，避免重复大范围扫描
# 定向导出时追加 --export Raw --container 'ds10406010201[.]playable$'
.\.venv\Scripts\astralogue.exe hsr native-coverage
# 现有主线片段仍可独立播放（无需游戏安装目录或 AnimeStudio）
.\.venv\Scripts\astralogue.exe hsr play --category TRAILBLAZE_SUBMISSION --search 100020113
```

## M5 主线支持的实际边界

已增加按原始分类字段建立的 Mission Manifest、子任务调度、Performance 调用/返回、
状态和完成事件检查、版本冲突检测及单独的主线覆盖率报告。
目前**尚未达到完整主线连续播放目标**：公开控制资源缺少 Timeline 本体，
本机相关资源含 ENCR 块和未完成解码的二进制容器，不能静默跳过其中的文本和控制。

已实测《漩涡止于中心》的真实子任务 100020113：进入演出、两级选择、
六种组合、共享后续、返回脚本、产生声明的完成事件、存档与回溯。
这些结果属于子任务片段，不计为完整开拓任务完成。

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD ".cache\uv"
uv sync --locked

# 只读调查安装目录；找不到时会查明确的安装注册表位置
uv run astralogue hsr inspect-install
# 显式联网获取固定版本任务清单和代表性控制资源；可重试并校验 Git blob 哈希
uv run astralogue hsr fetch-mainline --proxy http://127.0.0.1:10808
uv run astralogue hsr manifest --source .\data\raw\hsr-mainline
uv run astralogue hsr import-mainline --source .\data\raw\hsr-mainline
uv run astralogue build --source .\data\staging\hsr-mainline.ir.json --output .\data\packs\hsr-mainline.storypack --force
uv run astralogue hsr coverage --report .\data\mainline-coverage.json

# 主线任务和可单独验证的子任务片段分别列出
uv run astralogue hsr list
uv run astralogue hsr list --category TRAILBLAZE_SUBMISSION --search 100020113
uv run astralogue hsr play --category TRAILBLAZE_SUBMISSION --search 100020113
uv run astralogue hsr resume
```

不需要代理时省略 `--proxy`。正常播放不会联网。主线包与列车访客包、存档分别保存：
`data/packs/hsr-mainline.storypack`、`saves/mainline/`；
原有 `data/packs/astralogue.storypack` 和 `saves/` 中的旧存档保持可用。
任务结束回车返回主线菜单；不根据任务编号自动跳到下一任务。

本次已识别 365 条 Type=Main 记录，其中 336 条有标题且未明确隐藏/标为 System；
有 356 份任务定义、43 条记录取得了部分控制资源。当前被证明完整可执行的命名主线任务为 **0**。
统计细分、真实子任务证据和下一步问题见 [M5 验证记录](docs/m5-verification.md)。
不要将已解析台词比例或片段成功数解释为整个主线完成率。

可选补充源：`hsr import-mainline --supplement <明文资源根目录>` 按相同逻辑路径补充资源；
原始数据、文本或版本冲突会阻塞相应路径。已有 JSON/JSONL/SQLite 先用 `import` 转为 IR，
再用 `--overlay <IR>` 保留有来源的文本候选；只有可核对的原始文本键和相同来源版本可填补缺失文本，
不会导入上游丢失控制信息后的猜测连接。
明文 Timeline 控制图及其索引协议见 [M5 数据源报告](docs/m5-data-sources.md)；
原生 Unity Timeline 二进制解包尚未实现。

## 安装与真实剧情体验（PowerShell）

```powershell
# 已安装 Python 3.11+ 和 uv 时
$env:UV_CACHE_DIR = Join-Path $PWD ".cache\uv"
uv sync --locked
uv run astralogue init

# 显式联网下载公开仓库固定版本的列车访客分支样本（约 94 MB）
uv run astralogue fetch-sample
# 扩大到固定版本的全部列车访客会话，支持校验并复用已下载文件
# uv run astralogue fetch-sample --scope train-visitors --proxy http://127.0.0.1:10808
# 网络需要代理时，改用下面这条命令；端口应按自己的配置修改
# uv run astralogue fetch-sample --proxy http://127.0.0.1:10808

uv run astralogue import --source .\data\raw\hsr-sample
uv run astralogue build --lang CHS
uv run astralogue validate --report .\data\validation.json
uv run astralogue list --chapters
uv run astralogue list --search Act500100101
uv run astralogue play
uv run astralogue resume
```

已有本地 TurnBasedGameData 时，可以跳过下载，直接导入：

```powershell
uv run astralogue import --source D:\TurnBasedGameData --lang CHS
# 首次建议只选择已验证的分支会话，避免一次解析全部资源
uv run astralogue import --source D:\TurnBasedGameData --pattern "Config/Level/Mission/TrainVisitor/Act/Act500100101.json"
uv run astralogue build
uv run astralogue validate --explore "hsr:Config/Level/Mission/TrainVisitor/Act/Act500100101" --report .\data\validation.json
```

批量崩铁会话：下载 `--scope train-visitors` 后重新 import/build，使用
`list --status RESOLVED --json-output` 查看可执行会话的完整 ID，
`play --search Act500100101` 筛选菜单，`validate --explore-all --report data/batch-validation.json`
批量探索所有静态 RESOLVED 会话。菜单默认只显示 RESOLVED；可用 `--status PARTIAL` 查看受限会话。
截至固定版本已实测 374 个列车访客会话：372 个 RESOLVED，2 个 PARTIAL；
372 个会话的 573 条选项边均已通过有界运行时探索。这不代表全游戏任务兼容率。
下载自动重试，并记录已完成文件及哈希；失败后可重试相同命令，不覆盖已修改文件。

导入其他语言需提供对应 TextMap，例如 `--lang CHS,EN`。播放用 `--lang EN`。
不会静默切换语言或修改原始台词；模板占位符和游戏标签原样保留。
播放器仅需已安装引擎和 StoryPack，删除原始目录与 staging 后仍可运行。
首次 `uv run` 可能同步环境；需要保证启动无联网时，环境就绪后用
`.\.venv\Scripts\astralogue.exe play`（Linux：`.venv/bin/astralogue play`）。

## 操作与存档

- 回车逐句推进；选项输入显示的编号，单选项也需确认。
- `:back` 恢复上次选择前的完整状态，可重新选择分支。
- `:save [路径]` / `:load [路径]` 保存、读取；路径可包含空格。
- `:quit` 或 Ctrl+C 退出。每个可见事件都会写入独立的自动存档。
- `:event 名称` 仅用于等待事件的节点，显式模拟外部事件；不会绕过未知指令。
- `astralogue save` 将自动存档校验后另存，`resume` 默认恢复自动存档。

台词事件返回后指针已指向下一句未读内容；选项事件保持在选项处，直到选择。
存档含包哈希、包版本、Schema、当前任务/节点、变量、事件、选择记录和回溯快照。
数据包变化时拒绝继续旧存档；当前不提供自动迁移。

## 支持范围

原始 Adapter 支持观察到的 `PlayAndWaitSimpleTalk`、紧邻 `WaitSimpleTalkFinish` 的 `PlaySimpleTalk`、末尾 `PlayOptionTalk`、
唯一监听者的末尾 `TriggerCustomString`、`WaitCustomString`、`EndPerformance`。
只在同一文件内解析确定的事件交接。保留所有原始结构、ID、JSON 指针与输入 SHA-256。
表现指令仅按严格白名单省略，并记录诊断。

**每个 Act/Discussion 是独立会话，不声称已恢复完整任务。** 并发入口、非末尾事件交接、
多监听者、未知谓词、Timeline 中隐含台词等会明确标记 BLOCKED/PARTIAL，执行到未知控制时暂停。
不从 `TalkSentence_数字` 的命名凭空生成台词，不按文件名或台词 ID 拼接剧情。

第三方 StarrailDialog JSON/JSONL 可保留显式 `next_TalkSentenceID` 并导入；
Dialogue Browser SQLite 可导入带来源的会话、文本和触发器原始记录。
这类有损结果需原始数据补全或显式编辑 IR 后才能可靠执行，默认 BLOCKED，
不会把浏览器显示顺序伪装成剧情控制流。通用规范 IR 提供完整条件、变量、事件与跨任务跳转。

`RESOLVED` 表示当前会话静态检查无已知缺陷；`PARTIAL` 表示分支受限或存在警告；
`BLOCKED` 表示入口/关键数据不可用。数据库构建成功并不等于全部任务可游玩。
`validate` 有错误时退出码为 1，参数/文件错误为 2；完整报告含统计和全部诊断。

## 开发与验证

```powershell
uv sync --locked
uv run pytest -q
# 真实样本集成测试：没有资源时明确 skip，不宣称通过
$env:ASTRALOGUE_HSR_SOURCE = (Resolve-Path .\data\raw\hsr-sample).Path
uv run pytest -q tests/test_real_data.py
# 已获取完整列车访客集合时
$env:ASTRALOGUE_HSR_BATCH_SOURCE = $env:ASTRALOGUE_HSR_SOURCE
uv run pytest -q tests/test_hsr_batch.py
# M5 真实主线子任务测试
$env:ASTRALOGUE_HSR_MAINLINE_SOURCE = (Resolve-Path .\data\raw\hsr-mainline).Path
uv run pytest -q tests/test_mainline_real.py
```

架构、规范与调查记录见 [docs/architecture.md](docs/architecture.md)、
[docs/storypack-schema.md](docs/storypack-schema.md)、[docs/data-sources.md](docs/data-sources.md)。
源代码采用 MIT 许可证；游戏内容归原权利人。本仓库不附带游戏资源，用户自行导入用于非商业再创作。
真实资源、生成包、存档和第三方研究文件默认均不进入 Git。
