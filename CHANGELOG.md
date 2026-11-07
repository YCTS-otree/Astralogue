## v1.0.0 - 2026-10-30

### Notes
- 完成开发前环境检查：工作目录为空 Git 仓库，无既有提交或远程地址。
- 经用户授权，在现有共享 Python 环境安装 uv 0.13.6；默认 Python 为 3.10.11，另有应用内置 Python 3.12.14 可用。
- 已初步检查三个上游仓库；完整源码、数据接口与许可调查尚未完成。
- 当前仅完成初始化检查，尚未实现引擎、创建发行版本或执行项目测试；1.0.0 为计划的初始版本。

## v1.0.0 - 2026-10-30

### Added
- 交付首个崩铁 CLI MVP：真实数据导入、规范 IR、独立 SQLite StoryPack、验证器和离线运行时。
- 支持真实台词、选项、事件触发/等待、分支汇合；通用状态执行支持变量、条件和显式任务进入/退出。
- 提供章节与任务搜索、分页菜单、逐句阅读、选择、独立存档、恢复和基于完整状态快照的选择回溯。
- 增加公开固定版本数据下载、代理、失败重试及下载进度哈希校验；支持小样本或完整列车访客集合。
- 保留来源版本、输入 SHA-256、原始 ID、JSON 指针及未知指令；增加 JSON/JSONL、第三方 SQLite 的有损导入与诊断。
- 增加 Schema/存档版本检查、确定性全量构建、静态完整性报告与有界分支探索。
- 增加 77 项自动化测试、架构和格式文档、三个上游的源码调查记录及实际验证报告。

### Fixed
- 关闭 SQLite 写连接后再原子替换构建文件，解决 Windows 下文件占用导致的构建失败。
- 对并发入口、未知控制字段、嵌套动作、不确定跳转、条件歧义和变量未可靠初始化明确阻塞或报告受限。

### Notes
- 真实崩铁列车访客集合共 374 个会话：372 个 RESOLVED、2 个 PARTIAL；已实际探索前者的 573 条选项边，无阻塞或截断。
- 完整测试实测 77 passed；包含删除测试上游副本后的独立运行、真实分支逐句 ID、存档恢复和新进程 CLI 验证。
- 当前聚焦崩铁；未声称完整主线或全游戏兼容。Timeline、复杂并发和跨 Act 世界调度仍保留明确诊断。
- Linux 尚未实测；不捆绑原始游戏内容或第三方提取器代码。

## v1.1.0 - 2026-10-31

### Added
- 增加 M5 主线任务清单，按原始 Type 和实际文本标签区分开拓、续闻、同行、冒险及日常任务，保留入口、依赖、完成条件、来源和解析状态。
- 增加主线控制脚本与 Performance 表链接、通用 call/return 节点、可保存调用栈及明确的返回关系。
- 增加子任务条件、完成事件检查、部分状态修改和独立的子任务/演出片段播放；结束后可返回任务菜单。
- 增加固定公开版本的主线资源获取、Git blob 校验、本机只读资源调查和明文控制图补充入口。
- 增加多来源版本/文本/索引冲突检测、候选证据保留、原始控制对象内容哈希去重及独立主线覆盖率报告。
- 增加 32 项测试；完整测试实测 109 passed，含真实开拓子任务六种分支组合、调用返回、完成事件、存档恢复和移除上游后的离线播放。

### Changed
- Schema 和存档版本保持 1；调用栈为可选字段，旧包及其旧存档继续可读，新执行能力通过 required_capabilities 声明。
- 主线包、菜单和存档与既有列车访客路径分开，主线完成度不使用访客或片段数量计算。
- 即使父控制指令受限，仍保留其明确引用的资源和台词，避免以未知控制为由丢弃静态证据。

### Notes
- M5 为部分交付，完整命名主线任务验证数仍为 0；不能把静态提取或片段播放宣称为完整主线支持。
- 已识别 365 条 Main 记录、取得 356 份定义；本次有 43 条记录导入了控制资源。实际分母和限制见 M5 报告。
- 已解析 421/424 个显式台词引用、68/133 个选项目标；真实 Timeline 为 0/148，保持缺失诊断。
- 本机游戏在 O 盘找到，版本 4.6.0；仅只读调查，ENCR 和未理解的二进制容器未解包，未修改或上传本机资源。

## v1.2.0 - 2026-10-31

### Added
- 增加构建阶段 AnimeStudio CLI 适配器：SR Asset Map、定向 Raw/Dump/Convert 导出、输入复制隔离、大小/数量/超时限制及来源哈希。
- 增加原生 MonoBehaviour 基础头和不透明载荷保留、按文件作用域的 Unity 引用图、基础字段缺失诊断及独立资源恢复覆盖报告。
- 增加 12 项测试，含本机真实导出一致性检查；全套实际运行 121 passed。

### Notes
- 实际读取本机 4.6.0 ENCR，受限索引 811 个块；独立剧情脚本的 15 个 Timeline 引用可精确定位，定向导出一个容器。
- 现有 148 个缺失引用在本轮部分索引中仍未匹配；原生控制语义到 IR 尚未完成，新增可执行主线任务为零。
- 外部工具的基础字段 JSON 与同名跳过行为不能作为完整剧情结构证据。既有 StoryPack、Runtime、Schema 和存档格式保持兼容。

## v1.3.0 - 2026-10-31

### Added
- 增加独立 AnimeStudio CLI 源码扩展及可复现构建脚本，保留完整 SerializedFile、全部对象身份/原始字节/哈希、MonoScript、外部表与容器引用，解决同名跳过。
- 增加无损核验器，逐对象对照原始文件区间，并独立解析 AssetBundle 引用和预加载范围；真实样本 15 个文件、1,010 个对象通过核验。
- 增加受版本限制的原生 Timeline/Track/Clip 解析，恢复 26 个可核对的台词 ID、显式 Clip 时间和真实对象引用链。
- 增加 recover-native 和持久化增量资源索引；原生台词片段可编译到独立 StoryPack，未知后续控制明确阻塞。

### Fixed
- 公共源码及主线下载保持 TLS 证书和主机名验证，Windows 使用公共系统信任库，无默认关闭验证的回退。
- 资源扫描复用内容哈希一致的已索引块，避免反复解密；工具来源记录补充 CLI/core DLL 指纹。

### Notes
- 全局安装并使用微软官方 .NET 10 SDK 10.0.403；Runtime 不依赖该 SDK、AnimeStudio 或游戏目录。
- 原有 121 项测试保留，新增 9 项后实际完整运行 130 passed，含真实原生对象、引用篡改检测、存档及移除测试上游后的 CLI 验证。
- 额外 Discussion 样本恢复 26 条可播放台词片段；与原有 148 个缺失引用分开统计。完整原生 Timeline 和完整命名主线完成数仍为零。
- 旧主线包未替换，StoryPack Schema 和存档版本保持 1；未知原生载荷完整保留，不将静态引用链等同于完整剧情执行。

## v1.4.0 - 2026-10-31

### Added
- 增加显式逻辑时钟、事件等待/恢复、同刻依赖检查和调用返回的构建时通用调度预编译器，不增加 Runtime 的游戏依赖。
- 增加原生 Timeline 根层级、Marker 证据、依赖分类及受阻调用核验；主线编译器可通过 --native-ir 链接来源版本匹配的原生控制图。
- 增加可恢复的原生扫描队列、当前安装快照和精确引用查询，支持 StreamingAssets 与 Persistent 的 ASB 块。

### Fixed
- 修复 Track 前缀中两个变长绑定字符串的错位解析，额外 Discussion 样本的 347 个布局错误全部消除；辅助非有限浮点位模式保留为原始数据。
- 索引使用 WAL 和独立读取快照解决并行查询的锁升级；同名同大小内容变化可重扫，历史版本不静默覆盖。
- 区分 CutSceneName 和真实 CutScenePath，严格保留未验证的性别后缀候选；缓存覆盖报告分批处理 Map，避免累积全量对象到内存。

### Notes
- 当前安装已知两个 ASB 目录的 9,457 个块全部建立索引，共 6,821,208 条叙事类型资产条目；原 148 条引用精确定位 142 条。
- 1000202 的原生控制图实际链接 1/148，解析 742 个对象、59 条 Track、272 个 Clip；原有主线包保留，新主线包独立生成。
- 额外 Discussion 的 15 个根、440 条 Track、187 个 Clip 可结构解析；15 次 Discussion 和 1 次主线原生调用均受阻，完整 Timeline 和完整命名主线完成数仍为零。
- 原有 130 项测试保留通过，新增 14 项后实际完整运行 144 passed；100020113 六分支回归继续通过。
- Schema 与存档版本保持 1；未编造 Marker 恢复事件、轨道激活状态、结束策略或跨任务连接。

## v1.5.0 - 2026-10-31

### Added
- Independent narrative reconstruction with separate Strict/Reader entry points, evidence categories and explicit text-reading policies.
- Audited confirmation, track selection, manual guidance and ambiguous-time user ordering using existing generic IR and save history.
- Community Patch Protocol v1 JSON create/import/validate/apply commands, source/version binding, conflict/cycle checks and reproducible rebuilds.
- Real DS104060102 verification of all 27 option combinations and 26 body lines; Main1000202/Sub100020111 Reader projection with 17 body lines.
- Offline playback transcripts, separate Strict/Reader/community coverage and M6 verification tooling; 27 new tests (171 passed total).

### Changed
- Reader completion is explicitly scoped to selected text segments; original game control evidence, raw assets and Strict behavior remain separate.

### Notes
- StoryPack Schema 1 and save Schema 1 retained. Full named mainline missions and fully verified native Timeline execution remain zero.
- Reused existing native exports/index without new full scans. Pending demo patch is project-authored and is not presented as community-reviewed evidence.

## v1.6.0 - 2026-10-31

### Added
- Independent SQLite story archive and offline paginated Browse CLI with Chinese substring search, source records and graph adjacency.
- Source-bound unresolved transition exports and separate archive coverage statistics.
- Four archive tests, including real source browsing and duplicate import checks; 175 tests passed.

### Notes
- M7 is partial: complete attribution closure, reviewed-task conversion to Patch and verified Amphoreus sequence recovery remain unfinished.
- StoryPack and saves retain Schema 1; no changes to Runtime or new game resource scans.

## v1.7.0 - 2026-10-31

### Added
- Experimental offline Wiki snapshot/tree adapter, conservative normalized English alignment and source-bound review decisions.
- Reader graph compilation with local CHS text and explicit Wiki evidence; unmatched content blocks.
- Wiki CLI fetch/parse/align/report/review/build and eight tests, including pinned EN-to-ID-to-CHS catalog roundtrip.

### Notes
- 183 tests passed. Fandom robots/API/page requests through the local proxy returned 403; direct API timed out.
- No real Wiki task completion or native Fandom template support is claimed; M8 acceptance remains unfinished.
- English snapshot verified against the existing pinned Git blob. Runtime, StoryPack and save schemas unchanged.

## v1.8.0 - 2026-10-31

### Added
- Fixed-revision Hugging Face JSON download/cache verification and local import, with no repository script execution or new dependencies.
- Shared CHS dialogue index, original-control cross-checks and source-bound HF alignment checkpoints with review-only fuzzy candidates.
- Two real task integrations: 193 distinct aligned IDs, 31 exercised Reader excerpts and 105 net-new HF reading relations; no new GAME_VERIFIED relations.
- Offline alignment of 100 mission files (87 distinct contents), separate batch reports, Archive evidence import and reproducible PowerShell rebuild tools.
- Sixteen tests for integrity, ambiguous IDs, conservative order, independent anchors, real data, offline CLI and Archive boundaries; 199 passed.

### Changed
- M8 graph compilation accepts optional namespaces and an existing Strict bundle while preserving the original graph and text.
- Dataset-only transitions require explicit audited Reader confirmation; missing transcript context remains separated.

### Fixed
- Preserved raw text while normalizing explicitly supported typographic differences for lookup.
- Excluded pre-existing local control and Reader relations from novelty counts and retained duplicate-file aliases in reports.

### Notes
- StoryPack and saves remain Schema 1; Runtime unchanged. The dataset captures first options and is not complete branch truth.
- Two complete HF transcript ranges and complete native game missions remain unproven; no ASB rescans or Wiki-origin requests.
- Raw game text, datasets, generated databases, logs, packs and saves are excluded from source distributions and Git.

## v1.9.0 - 2026-11-01

### Added
- Full prologue Story Arc Reader using declared mission transitions: seven task groups, 16 internal records and all 941 transcript items.
- One-time source transcript policy, labelled community dialogue/narration/stage directions and explicit version-comparison handling.
- Native local branch projection preserving three-way and six-path scenes; all 18 full-chapter combinations verified.
- Arc CLI, per-edge audit, snapshot-based previous/back navigation and resumable chapter sessions without Runtime or StoryPack schema rewrites.
- Full-chapter verification tool and four regression tests; 203 passed including all previous 199 tests.

### Fixed
- Distinct choices sharing a target retain the selected edge identity in the chapter audit.
- Current original-control continuation takes precedence over an obsolete beta wording; original transcript retained as labelled notes.

### Notes
- Story Arc Reader completion succeeds; native game execution remains unproven. Missing branches outside projected scenes remain disclosed.
- Full HF source coverage is not a claim of full game text coverage. Raw sources, full logs, saves and StoryPacks remain excluded from Git.

## v1.10.0 - 2026-11-01

### Added
- In-story Star/Caelus identity selection, confirmation, Unicode nickname and versioned PlayerProfile in existing saves, with explicit legacy-save migration.
- Presentation-only nickname/gender variables, 29 source-bound community nickname annotations, and explicit persistent variable continuation between chapters.
- Cached BWIKI template adapter, nine additional prologue options across six menus, and two original-script-backed optional inquiry loops with HideSelected behavior.
- Reviewed, hash-bound Community Patch text-parameter operations and structured anonymous speaker metadata.
- Inline media metadata and a separate, source-backed baseball-bat editorial stage note without invented actions.
- Two-profile real CLI save/quit/resume verification, 17 menu paths, 18 preserved native combinations and 217 passing regression tests.

### Changed
- Ordinary playback hides provenance prefixes and repeated Reader diagnostics; global or command-level --debug restores them without altering evidence or audits.
- Player-enabled prologue builds use prologue-player.storypack; the prior M9 pack and its rebuild mode remain available.

### Fixed
- Default community nicknames no longer remain literal where complete original variable layouts prove the replacement; ambiguous IDs remain unassigned.
- Waiting-time identity-selection extras are explicitly optional instead of mandatory sequential dialogue.
- Arc autosaves atomically write complete state and audit once, with bounded Windows replacement retries.

### Notes
- StoryPack and Save Schema remain 1. Enhanced packs declare reader-player-v1; incompatible old engines reject them rather than silently omitting identity.
- Strict nodes, edges and texts are preserved. Full prologue Reader succeeds; complete native game execution and remaining branch coverage are still unproven.

## v1.11.0 - 2026-11-01

### Added
- Local registration/login on default startup and arcs play, with one canonical SQLite progress record per account and automatic continuation.
- Per-account session locks, revision checks, confirmed-identity protection and rejection of rewritten choice history.
- One-time legacy file-save import for accounts without progress, preserving original files and pack compatibility checks.
- Account regression tests and a real offline CLI registration/quit/login/full-prologue verification; 223 tests pass.

### Changed
- Account mode disables alternate save slots, load/rewind and restarting completed progress; low-level file-save tools remain separate.
- Automatic checkpoints after visible content and account choices/identity steps are silent unless --debug is enabled.
- Normal avatar menus omit internal resource IDs.

### Notes
- Existing StoryPack and Save Schema stay unchanged. Account database Schema 1 is separate, stores salted password hashes, and requires no online service.
- Existing account progress is not reset when a different or incompatible pack is supplied; cross-pack account upgrades require a future explicit migration.

## v1.11.1 - 2026-11-01

### Fixed
- Normal reading skips the explicitly optional carrier-selection waiting dialogue via its existing skip edge. Debug retains access to the source archive; no timer semantics are invented.
- Existing StoryPacks and account bindings remain unchanged.

## v1.12.0 - 2026-11-03

### Added
- 序章 BWIKI 后台 Worker、SQLite 持久队列、robots 检查、120 秒限速、缓存校验及中断恢复。
- 离线场景分类与独立探索包编译，两个来源明确的可选互动可返回菜单并保存已读状态。
- 七任务离线结构报告与 Local Narrative Auditor 接口路线图（无模型执行）。

### Fixed
- 阿兰错误方向额外回应不再默认串入新探索包主线。
- 玩家回归验证明确排除载体选择的九句等待彩蛋，不把它们计入普通阅读路径。

### Notes
- Runtime、StoryPack Schema 1 及旧包不变；新图需独立账号或显式文件存档迁移，未知世界条件不提升为原生事实。

## v1.13.0 - 2026-11-03

### Added
- 默认本地 0 号账号及其显式章节/小节导航，选择记录独立审计；普通账号仍保持唯一进度。
- BWIKI 4.5 目标持续采集，基于总目录任务行扩展持久队列，目标未出现时每日检查目录。

### Changed
- 按用户授权清零当前正式账号目录中的剧情进度，保留账号。
- 采集缓存的未知结构显式保留并标记不可执行，任务声明版本独立记录。

### Maintenance
- 后台调度持久化：北京时间工作窗口、随机工作/休息周期、每轮 4–5 页配额；继续遵循服务端限流与缓存复用。
- 本轮完整回归 238 项通过；加入调度后相关测试 21 项通过。

## v1.13.1 - 2026-11-03

### Fixed
- 已有同名 0 号账号首次升级时同步默认密码校验信息，避免初始化 INSERT OR IGNORE 保留旧密码而无法登录；保留账号身份、剧情进度和其他账号。


## v1.13.1 - 2026-11-03

### Notes
- 工作区占用审计：主要空间来自 AnimeStudio staging 保留的游戏资源块副本与原生资产索引；本轮仅检查，未删除数据或缓存，未更改程序版本。

## v1.13.1 - 2026-11-04

### Removed
- 按用户授权永久删除 AnimeStudio staging 下 117 个 input 目录中的 9,466 个游戏资源块副本，共 60,453,069,834 字节（56.30 GiB）；保留资产映射、原生索引、导出结果、剧情包及存档。

## v1.14.0 - 2026-11-04

### Added
- 可复制到任意目录的 Astralogue.cmd，使用现有虚拟环境和当前源码，支持终端/持久 PTY 交互。
- 启动器固定数据包选择和项目工作目录，更新应用不会自动切换账号数据包；支持 ASTRALOGUE_HOME / ASTRALOGUE_PACK。

### Notes
- 未生成独立 EXE；启动器依赖项目目录与既有 Python 环境。

### Verification
- 项目外真实 PTY 持续交互通过；启动器与账号相关测试 13 项通过。

## v1.15.0 - 2026-11-04

### Changed
- 普通账号仅开放今天是昨天的明天·混乱行至深处，到任务出口停止；超出范围的已有进度保留并拒绝继续。0 号账号仍可自由导航。

### Fixed
- 注册输入用户名后立即检查重复，统一规范化用户名；保留数据库唯一约束，不覆盖已有凭据与存档。

### Notes
- 16 项相关测试通过；真实 CLI 普通账号从入口运行到首任务出口后停止验证通过。

## v1.16.0 - 2026-11-04

### Added
- 持久化剧情审计索引、分块队列、本地与 DeepSeek Provider、人工审核和 Reader 修订重编译工具；模型建议与原始游戏事实分离。

### Changed
- 审核管理器改为中文剧情片段视图，展示章节、任务、小节、前后台词和分支正文，按已记录阅读路径及来源小节定位排列。
- 未绑定具体节点或修改位置的研究结论单独展示，只能记为已阅、暂缓或驳回；原始 JSON 收入技术详情。

### Notes
- 审核记录保留；只有人工批准的具体修改可用于后续重编译。本轮 UI 更新没有自动批准提案或修改已发布剧情包。
- 完整自动化回归 264 项通过，无跳过；新版审核列表和详情通过真实 HTTP 检查。

## v1.16.1 - 2026-11-04

### Added
- 从已缓存 BWIKI 调查折叠与“再次调查”模板自动生成待审核结构提案，保留首次/重复调查、原文及来源偏移；不因折叠标题判定全部内容可选。
- AuditReview.cmd 独立审核后台启动入口，重复启动复用已有服务，不依赖当前终端会话。

### Fixed
- 调查类无说话者文本进入审计交叉检查；电梯等被 HF 合并的重复访问文本在提案预览中分别显示。

### Notes
- 真实首任务自动检测新增 5 个调查块提案；全部仍待人工审核，未修改已发布剧情包或存档。
- 完整回归 270 项通过、无跳过；嵌套调查边界和启动器等定向测试 15 项通过，真实缓存匹配及 HTTP 分段预览验证通过。

## v1.17.0 - 2026-11-04

### Added
- 审核列表支持多选、全选本页及批量通过/驳回；逐项保留审核记录，批量通过前统一检查修改位置，存在不可批准项则整批拒绝。

## v1.17.1 - 2026-11-04

### Added
- 审核提交显示非阻断式成功/失败提示，批量结果包含处理条数，失败保留当前表单；列表新增人工已驳回计数。

### Fixed
- 重新部署实际监听的旧审核后台，使多选控件及新提示生效。

## v1.18.0 - 2026-11-04

### Added
- 评论驱动的具体修改/研究审核流程，支持本地模型或预算内 DeepSeek 低推理，持久化人工方向、任务和新待审提案；模型输出不自动批准。
- 审核按钮显示已批准、已驳回及等待修改状态；右侧说明栏跟随滚动，允许扩展前后文。

### Notes
- 结构化调查解析已用于提案生成，尚未自动改写正式剧情包；本地服务已按授权重新启动。
- 完整回归 275 项通过，无跳过；独立测试库完成一次真实本地模型判别，未自动批准或改写生产剧情。

## v1.19.0 - 2026-11-04

### Added
- 最终人工批准的具体提案自动校验并增量发布到当前启动器 StoryPack；事务写入、压缩字段差异历史、重复发布防护、历史查看及最新修订回滚，不生成整包副本。
- 保留原包基础身份及稳定节点，用独立修订号和能力标记管理兼容更新；运行中 Reader 刷新关系和新增状态默认值，既有账号身份与选择保留。

### Fixed
- 评论返修必须生成新待审提案，拒绝空结果及原样退回；补充相邻真实节点、原始小节及父提案上下文，恢复后台重启遗留的推理任务。
- 新增模型返修申请入口和完成提示；模型输出仍须人工再次批准，不能直接发布。

### Notes
- 已实际增量发布 6 项既有人工批准内容，历史压缩后 615,103 字节，无新增整包副本；真实 CLI 纯主线/充分探索分别验证 137/159 条对话事件，未覆盖内容仍保留。
- 评论返修支持一次提交1–3份独立待审申请，前后端校验数量；拆分申请分别审批，历史不删除。
- 全量回归 282 项通过，无跳过；新增发布、返修对象分组等定向测试 27 项通过。首次/再次调查混合节点禁止整体发布，避免批准后继续错误串播。

## v1.20.0 - 2026-11-04

### Added
- 审核页面支持章、任务、小节筛选及中文多关键词搜索，全部/任一关键词模式，分页与分类切换保留筛选条件。
- 原文定位视图覆盖尚无申请的缓存来源块，可重新结构解析或带评论向所选模型发起修改请求；生成待审提案，不自动批准。

### Notes
- 真实星核样本通过章节定位、三关键词搜索、首次/再次调查分段及节点关联验证；未发起新增 Wiki 采集。
- 完整回归 287 项通过，无跳过；导航、搜索、无既有提案的 HTTP 审查入口等定向测试 18 项通过。

## v1.21.0 - 2026-11-04

### Added
- 分支审核直接显示当前游玩包选项和建议的玩家入口文字，与分支回应正文分离。
- 申请支持独立中文 explanation；允许提出有来源的 additions 补句，验证原文引用并独立显示。

### Notes
- additions 仅为待审建议，新增句子节点尚未接入发布器，界面和发布校验均明确阻止静默应用。模型说明不进入剧情原文。
- 完整回归290项通过；分支展示、当前包选项对照、申请说明和来源补句等定向22项通过，真实HTTP详情验证通过。

## v1.21.1 - 2026-11-04

### Changed
- 每份申请右侧“你需要判断”卡片固定展示章、节/任务、小节，随侧栏滚动保留位置提示；未确定归属如实标注。

## v1.22.0 - 2026-11-04

### Added
- 已驳回申请支持恢复待审核；研究批准支持撤销并连带撤回多轮后续申请，取消任务并丢弃迟到模型结果，保留审核历史。
- 研究后续内容已发布时仅回滚该研究拥有的最新连续修订；存在其他研究修订则整次拒绝，避免误撤。
- 模型草案与已有申请（包括已批准/发布内容）存在节点、来源、小节或长句关联时，正式提交前额外复核一轮；沿用所选模型和预算，不自动覆盖已有决定。

### Changed
- 新模型调用的审核说明、理由、未知和冲突描述要求中文，机器ID及原始文本保持不变。

### Notes
- 新申请自动记录提交时间，模型任务单独记录排队时间；列表及详情按北京时间显示，旧记录保留“未记录”，不伪造精确时间。
- 按用户指定的2026-11-04 21:20（含）截止清理66条旧研究/待定位：从默认列表删除并保留审计历史，根据已有快照确认旧记录时间上界；后续新申请和已发布内容保留。
- 完整回归302项通过、无跳过；撤销、关联复核、中文说明、提交时间及清理边界等定向27项通过。

## v1.22.1 - 2026-11-04

### Fixed
- 旧申请按最新返修任务同步显示排队/推理、修改失败或已提交返修，避免模型结束后仍堆积为“等待修改”；已批准或驳回的人工决定保持不变。

## v1.23.0 - 2026-11-04

### Added
- 按来源块开启全新复审轮次：保留通过及发布内容，清理未通过旧记录和任务，重新运行解析器及本地模型。
- 来源块作用域和通过内容只读约束；相同对象与相同修改复用已有申请并建立引用，不再因说明不同重复提交。

### Fixed
- 新人工更正取消旧的未完成轮次；优先完成单个来源的关联复核，让审核结果逐项出现。

### Notes
- 按用户授权移出75条未通过旧记录，保留8条已通过记录和全部已发布修订；重建16个来源块复审，跳过8个已通过来源块。
- 完整回归306项通过，无跳过；复审、重复抑制、关联复核与生命周期定向28项通过。
- 本轮16个来源块解析及32次本地判别/关联复核已完成，形成16份待审申请，精确重复组0；8条通过记录与已发布修订保持不变。

## v1.23.1 - 2026-11-04

### Fixed
- 审核概览按真正待审核结果计数，排除已完成自动输入任务及已批准内容；卡片可跳转对应状态，空筛选明确显示当前条件和待审核入口。

## v1.23.2 - 2026-11-04

### Fixed
- 解析输入与正式模型申请分离：单结果输入链接跳转到实际申请，输入只保留历史说明；普通前后导航和关联申请不再把自动输入当作重复申请。

## v1.23.3 - 2026-11-04

### Fixed
- 修复真实节点/场景ID被误当作未知别名的问题，仅规范化能够精确对应已给定资源的引用，保留原始响应。
- 区分批准研究转具体申请与要求修改旧方案；人工确认的Reader政策不再被Unity验证缺口阻断。
- 方案未改动不再作为ValueError或复制新申请，独立显示理由供人工处理；作用域/拆分等判断问题改为明确提示，发布安全校验保留。

### Notes
- 恢复原有三条人工意见；已支付但被错误校验拒绝的DeepSeek响应可直接复用，不重复生成收费。
- 明确BWIKI主动交互结构优先于HF线性顺序及模型猜测；直接形成Reader交互申请，主动触发与是否必经分开，不将缺少Unity验证作为重复退回理由。
- 实测原三条评论恢复后已生成具体申请；完整回归312项通过，未知引用格式、研究转申请及付费响应复用等定向测试通过。

## v1.23.4 - 2026-11-04

### Changed
- 移除重复的查看/审核状态下拉框，保留快捷入口和章节搜索条件。

### Fixed
- 列表进入详情、上下文扩展、返回及前后申请导航保留当前筛选；批准后当前项离开待审集合仍能前往同筛选的相邻项，不跨入研究类别。

## v1.23.5 - 2026-11-04

### Fixed
- 无筛选直达详情不再默认按全部状态连续导航；审核模式及“包含已处理”视图的前后导航只取待审核项。
- 导航链接打开时重新校验状态，跳过已被处理的目标；无后续待审时返回原筛选列表，保留显式已批准/驳回历史浏览。


## v1.24.0 - 2026-11-04

### Added
- 将经审核的多次调查分段编译为通用访问计数分支，支持任意多个明确阶段；入口持续可选，最终阶段重复，计数随存档与回溯保存。
- 已批准及已发布申请可提交后续模型修改建议；保留原批准与发布，模型新申请仍需人工审核。

### Fixed
- 修复已明确提供首次/再次分段的调查申请仍被发布器整体拒绝；原文未覆盖或无明确分段时继续提示核实。
- 审核详情按访问阶段显示内容，移除已支持的多次调查结构的过期警告。
- 修复BWIKI格式换行导致来源未绑定现有剧情节点、已绑定对象名称在结构差异中被误判为伪造引用的问题；保留多候选歧义，不猜测绑定。

### Notes
- 已批准“调查星核”申请已增量发布为修订13；实际验证四次调查、保存恢复和回溯。未变更Strict关系或StoryPack/存档格式。


## v1.24.1 - 2026-11-04

### Fixed
- 修复有明确菜单、场景及多次访问分段的split_dialogue_sequence申请被发布器误判为无执行计划；与主动调查计划共用编译能力判断和访问调度。
- 审核页同步显示拆分调查的各次内容及发布支持情况，普通没有明确计划的拆分仍不自动编译。

### Notes
- 已批准“调查电梯”申请成功增量发布为修订15；实际四次调查、保存恢复、回溯及HTTP详情验证通过，专项回归41项通过。

## v1.24.1 - 2026-11-07

### Notes
- 工作区垃圾检查：发现约 6.24 GiB 未完成模型下载分片、旧工具安装包和缓存；上次清理的游戏资源块副本未重新生成。本轮仅检查，未删除文件或更改程序版本。

## v1.24.1 - 2026-11-07

### Removed
- 按用户授权永久删除 Qwen3.5-9B 的两个未完成 .part 模型下载分片，共 6,698,303,488 字节（6.24 GiB）；保留完整 GGUF 模型。

## v1.24.1 - 2026-11-07

### Notes
- 首次将项目及既有 Git 历史同步至公开仓库 YCTS-otree/Astralogue，使用现有 MIT 许可证；程序版本保持 1.24.1。
- 同步前测试：282 项通过、45 项跳过、1 项失败；失败项为 test_repeat_preview_separates_visits 的重复调查预览标题断言，本次未修改功能代码。

## v1.24.1 - 2026-11-07

### Changed
- README 开头注明剧情文本来自《崩坏：星穹铁道》和 BWIKI、CC BY-NC-SA 4.0 协议及仅供玩家回顾、禁止商业化的用途说明，并区分引擎代码的 MIT 许可证。
- 修正 README 中的当前版本为 1.24.1，并补充公开仓库简介。
