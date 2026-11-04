# Astralogue — 星轨叙事引擎

离线交互式剧情引擎，Python 3.11+，Windows / Linux，CLI 使用 Typer + Rich。
构建阶段将游戏数据解析为自己的 SQLite `.storypack`；播放器只读该包。
当前版本 **1.15.0**，StoryPack Schema **1**。

直接打开即可注册或登录本地账号：

```powershell
.\.venv\Scripts\astralogue.exe
# 也可显式指定入口或开启调试提示
.\.venv\Scripts\astralogue.exe start
.\.venv\Scripts\astralogue.exe start --debug
```

每个账号只有一份持续推进的进度，登录自动继续。每句、小节边界、选项及身份确认都会自动保存，普通模式不提示保存。
账号内不提供重开、另存、读档回退或回溯改选；载体和代号一经确认即锁定。其他账号独立从头开始。
账号名与剧情代号是两回事。账号和进度只存本地 `saves/accounts/accounts.sqlite`，不需要网络。
退出剧情返回账号菜单，可登录另一个账号；同账号不能在两个窗口同时推进。
现有剧情包可直接使用，本轮无需重新构建；已有账号使用的包请保留，不能覆盖成其他包后自动重置进度。
账号规则、旧档导入和验证记录见 [本地账号文档](docs/accounts.md)。

序章现在支持剧情内选择「星／穹」、二次确认与中文代号；身份、变量、历史和来源审计随原存档保存。
BWIKI 补足卡芙卡的三组选项及《漩涡止于中心》的三组遗漏选项；两处询问对话根据原脚本恢复返回菜单和隐藏已选项。
普通播放只呈现剧情，来源前缀和 Reader 技术说明通过 `--debug` 显示；未确定的剧情关系与真正阻塞仍会提示。
详见 [玩家档案与 BWIKI 实测](docs/player-profile-bwiki-verification.md)。

M9 已完成序章 **「今天是昨天的明天」整章 Reader**：从正式开场到列车出发的章节边界，
7 个任务段自动衔接，941/941 个来源条目保留；已知原生选择的 18 种组合都能读到章节出口。
这是标明来源的转录阅读完成，原生 Strict 完成仍未证明。详见 [M9 验证报告](docs/m9-verification.md)。

```powershell
# 构建工具：仅首次准备数据包时使用；已有账号不要覆盖其绑定的包
.\.venv\Scripts\astralogue.exe arcs build --force
.\.venv\Scripts\astralogue.exe arcs play
# 需要查看来源、证据与调试说明时
.\.venv\Scripts\astralogue.exe arcs play --debug
# 以下为旧文件存档/开发工具入口，不操作账号进度
.\.venv\Scripts\astralogue.exe reader play --pack data/packs/prologue-player.storypack
.\.venv\Scripts\astralogue.exe resume --pack data/packs/prologue-player.storypack --save-file saves/arc/autosave.save.json
.\.venv\Scripts\astralogue.exe arcs audit saves/arc/autosave.save.json --output data/arc-edge-audit.json
```

账号播放中 `:profile` 查看载体与代号，`:progress` 查看任务进度，`:quit` 返回账号菜单；进度静默保存。
来源转录阅读策略和逐边证据继续随包及存档保留；普通界面隐藏重复技术说明。未匹配原始 ID 的文本保留社区来源，
不全局替换字面称谓“开拓者”，也不将 BWIKI 关系升级为 Strict。
下载/对齐方法仍见下文；播放只需要独立 StoryPack，不需要 HF、原始表或游戏安装目录。

```powershell
# 新环境显式获取本轮的小范围缓存；之后重建和播放都不联网
.\.venv\Scripts\python.exe tools/prepare_player_sources.py --proxy http://127.0.0.1:10808
# 新账号第一次使用时，可显式接入旧文件存档；账号有进度后不允许替换
.\.venv\Scripts\astralogue.exe start --import-save saves/old.save.json
# M9 旧包保留不变；跨包加载必须显式迁移到新文件
.\.venv\Scripts\astralogue.exe arcs migrate-save --save saves/old.save.json --old-pack data/packs/prologue-arc.storypack --pack data/packs/prologue-player.storypack --output saves/migrated.save.json
# 原 M9 构建流程仍可用
.\.venv\Scripts\astralogue.exe arcs build --no-player --output data/packs/prologue-arc.storypack --force
```

旧存档仍可用原包继续阅读。显式迁移保留原进度、身份（如已有）、旧选项及逐边审计，另存迁移凭据；
更换过的剧情图不伪造旧导航快照，回溯从迁移点开始。缺档案时先提示补全，不自动设置默认姓名或载体。
节点结构已变化的少数位置会拒绝自动迁移，可先在原包继续到结构稳定的台词处。
应用自身的代号限制为 1–32 个 Unicode 字符，拒绝控制/格式字符；这不是游戏官方长度限制。

HF 中文有序转录已接入 M8：两个样本映射到 193 个不同原始 ID，31 个明确范围的 Reader 节选已实跑，
净新增 105 条 **HF 来源阅读关系**，新增原生控制关系为 0。完整游戏任务仍未证明完成。
详情见 [HF 实测报告](docs/m8-hf-verification.md)。

```powershell
uv sync --locked
# 首次联网：只取两份任务 JSON 与 README；已验证缓存直接复用
.\.venv\Scripts\astralogue.exe hf fetch --proxy http://127.0.0.1:10808
# 两样本确认后可获取同一固定提交下其余 missions（不取繁体、续闻或预训练文件）
.\.venv\Scripts\astralogue.exe hf fetch --all-missions --proxy http://127.0.0.1:10808
# 此后完全离线重建：需保留既有 hsr-mainline 快照与 hsr-mainline-m59.storypack
.\tools\rebuild_hf.ps1 -Batch
.\.venv\Scripts\astralogue.exe reader play --pack data/packs/hf-002.storypack
.\.venv\Scripts\astralogue.exe reader play --pack data/packs/hf-001.storypack
.\.venv\Scripts\astralogue.exe browse --database data/archive-hf.sqlite --search 阿兰
```

数据截至 3.0 且只转录第一选项，不能当完整分支真值。未知上下文需主动确认；未匹配条目断开为独立节选，
不会静默跳过后连成完整任务。两个包均保留原主线控制图，可用原任务 ID 进入已有原生分支。
下载采用固定提交与 SHA256 清单；本机未装 huggingface_hub，使用经 TLS 验证的官方 HTTPS 接口，未新增依赖。
人工下载后可用 `hf import-local <目录> <40位提交SHA>` 导入两个样本，再用 `hf align` 和 `hf build` 离线处理。
数据和剧情包不随程序发布；数据集元数据许可证不代表拥有游戏文本的商业再分发许可。

M6 新增独立的文字叙事重建层、Strict / Reader 双入口和 Community Patch Protocol v1。
Discussion1040601 的 DS104060102 阅读段已验证全部 27 种真实选项组合、26 条正文台词；
主线 1000202 的子任务 100020111 可在 Reader 中连续阅读 17 条原生台词。
Reader 需主动确认未知暂停、轨道选择及返回策略，记录随存档保留；这些结果不计为原生 Timeline
或完整主线任务完成。Strict 完整命名主线仍为 0。详见 [M6 实测报告](docs/m6-verification.md)
和 [补丁协议](docs/community-patch-v1.md)。

```powershell
# 继续使用已有环境；尚未安装本项目时执行
uv sync --locked
# 复用已导出的 15 条资源，不重新扫描游戏，不需要运行 AnimeStudio
.\.venv\Scripts\astralogue.exe hsr reconstruct `
  --directory data/staging/animestudio/m58-lossless-final/output/lossless `
  --source data/raw/hsr-mainline --control data/staging/animestudio/reference/DS104060102.json `
  --output-ir data/staging/m6-discussion.ir.json --output data/packs/hsr-reader.storypack
# 构建完成后，只需 .storypack；其他构建输入可以移走
.\.venv\Scripts\astralogue.exe reader play --pack data/packs/hsr-reader.storypack --mode reader
.\.venv\Scripts\astralogue.exe reader play --pack data/packs/hsr-reader.storypack --mode strict
.\.venv\Scripts\astralogue.exe resume --pack data/packs/hsr-reader.storypack --save-file saves/reader/autosave.save.json
.\.venv\Scripts\astralogue.exe reader audit --pack data/packs/hsr-reader.storypack `
  --save-file saves/reader/autosave.save.json --output data/reader-audit.json
```

已有输出需显式加 `--force` 才会替换；旧版本包和存档保持可用。首次取得上游数据和无损导出的方法见下文及历史报告。
Reader 与普通播放器共用逐句显示、选择、`:save`、`:back` 和恢复；同刻未证明先后的内容由用户明确排序，
多条文字轨道由用户选择，均不会默认全部激活。后继未知时可以由重建层或补丁暴露标注为非官方的手动引导，
没有显式目标的未知行为继续阻塞。当前 Reader 只保证所选文字范围，不模拟其他未理解轨道的世界状态。

M5.9 已完成已知 ASB 目录的 9,457 个块索引，原有 148 条引用精确定位 142 条；
新增逻辑时钟/显式等待/依赖顺序/返回的通用 IR 预编译器，修复 347 个原生 Track 布局解析错误。
真实 Discussion 的 440 条 Track、187 个 Clip 均可结构解析；完整 Timeline 调度仍受阻，未宣称完整主线可玩。
1000202 的原生控制图已通过 `import-mainline --native-ir` 接入原主线编译器，语义未知仍在调用点阻塞。
详见 [M5.9 实测报告](docs/m59-verification.md)。

M5.8 已实现独立 AnimeStudio 源码扩展的无损导出，核验 15 个 SerializedFile、1,010 个对象；
从真实 Discussion 样本恢复 26 个台词 ID、Clip 时间及 Timeline/Track/Clip 引用链。
原生台词片段可编译后离线播放，后续未知控制明确阻塞；完整命名主线仍为 0。
详见 [M5.8 实测报告](docs/m58-verification.md) 与 [外部工具构建说明](tools/animestudio/README.md)。
历史 [M5.7 报告](docs/m57-verification.md) 保留当时的结果。

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
目前**尚未达到完整主线连续播放目标**：公开控制资源缺少 Timeline 本体；本机 ASB 索引和定向无损导出已打通，
但大部分已定位的主线资源尚未结构化接入，轨道激活、暂停/恢复及游戏世界状态仍有语义缺口。

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

## 文件存档开发工具

以下是显式 play/resume 的旧文件模式，供开发验证及旧档兼容，不访问账号进度。普通玩家使用默认账号入口。
账号模式自动保存，不支持这些另存与回退命令；首次导入旧文件见上文 `start --import-save`。

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

## M7 档案浏览初版

独立 Archive Schema 1，不修改 StoryPack 或存档。当前导入范围见 docs/m7-verification.md；
TalkSentence 收录不等于已证明引用，更不等于主线覆盖。未知归属保留，Browse 排序明确不是剧情顺序。

```powershell
.\.venv\Scripts\astralogue.exe archive build data/raw/hsr-mainline --pack data/packs/hsr-reader.storypack --output data/archive.sqlite
.\.venv\Scripts\astralogue.exe browse --search 翁法罗斯
.\.venv\Scripts\astralogue.exe browse --mission 1000202
.\.venv\Scripts\astralogue.exe browse --category TRAILBLAZE --orphans
.\.venv\Scripts\astralogue.exe archive recover --output data/m7-review-tasks.json
.\.venv\Scripts\astralogue.exe archive coverage
```

浏览支持 speaker/chapter/search/mission/category 筛选、n/p 分页、编号查看原始记录/引用/前后边、q 返回。
中文搜索是精确子串，未使用默认 FTS 分词。档案数据库可单独复制，浏览不需要游戏、AnimeStudio 或构建输入。
本版尚未完成全来源自动发现、完整归属闭包、已审查任务转 Patch、Browse 内跳转播放器及全部恢复指标。

## M8 实验性 Wiki 对齐

新增 wiki fetch/parse/align/report/review/build，详见 [M8 实测与限制](docs/m8-verification.md)。
当前 Fandom 经代理访问为 403，直连超时；未完成真实 Wiki 任务验收，未交付 Wiki 对齐剧情包。
离线工具支持显式结构树、有限 Wikitext、唯一英文匹配及 CHS 映射；HTML 与未知模板阻塞。
英文输入需与 source 的固定快照 blob 相符。模糊候选须人工审查，Wiki 来源不进入 Strict。

### BWIKI 后台 Pilot 与自由探索（1.13.0）

详见 [采集、恢复、离线构建与探索指南](docs/bwiki-background-pilot.md)。显式启动低频 Worker，默认仅序章；新探索包使用独立账号目录，原包和旧账号继续可用。未知游戏世界条件保留 unknown，可选内容仅作为 Reader 阅读入口。

### 双击即玩

直接双击根目录 `Astralogue.cmd`，可复制到桌面或任意文件夹，无需参数。沿用项目环境、源码和存档；正常源码更新后仍可启动。LLM 可在持续 PTY 会话内运行同一文件，详见 [启动器说明](docs/launcher.md)。

### 剧情审核管理器

审核页面按章节、任务和小节展示具体前后台词及分支内容，研究结论单独处理。启动与审核规则见 [审核管理器说明](docs/audit-review-manager.md)。

