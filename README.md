# Astralogue — 星轨叙事引擎

离线交互式剧情引擎，Python 3.11+，Windows / Linux，CLI 使用 Typer + Rich。
构建阶段将游戏数据解析为自己的 SQLite `.storypack`；播放器只读该包。
当前版本 **1.0.0**，StoryPack Schema **1**。

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
```

架构、规范与调查记录见 [docs/architecture.md](docs/architecture.md)、
[docs/storypack-schema.md](docs/storypack-schema.md)、[docs/data-sources.md](docs/data-sources.md)。
源代码采用 MIT 许可证；游戏内容归原权利人。本仓库不附带游戏资源，用户自行导入用于非商业再创作。
真实资源、生成包、存档和第三方研究文件默认均不进入 Git。
