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
