# Architecture / 架构

版本 1.13.1，Python 3.11+。运行时与任何游戏格式、提取工具和网络模块解耦。

默认 CLI 与 arcs play 进入本地账号入口。accounts 模块通过现有 Runtime/ArcSession 的存档格式序列化，
把每个账号的唯一进度事务性写入独立 SQLite，而非写入 StoryPack。账号模式禁用回退/另存，检查已确认身份和选择前缀，
使用每账号 OS 文件锁及数据库修订号避免并发覆盖；旧文件存档工具仍独立保留。账号数据库 Schema 1 与剧情包 Schema 分开。

PlayerProfile 存于现有 State.variables，ArcSession 提供 ProfileEvent、显示时变量解析和逐边审计。
初始化在编译出的真实剧情锚点发生；原 Runtime 未重写。持久变量由显式 set_story_variable/continue_to API 延续，
只有到达当前章节出口并验证载体定义后才能开启下一阅读会话，不据此制造原生跨章节控制边。
StoryPack/Save Schema 均保留 1；增强包声明 reader-player-v1 能力，旧引擎拒绝误读，旧包仍可直接打开。
BWIKI 适配器使用带参数嵌套边界的 Wikitext 模板解析，仅在 HF 区间、原始选项组与汇合锚点可核实时增补 Reader。
来源与原文保留；普通 CLI 的来源隐藏仅属显示策略，--debug 恢复证据说明。

```mermaid
flowchart LR
    raw[本地游戏 JSON] --> adapter[游戏 Adapter]
    exported[第三方 JSONL / SQLite] --> lossy[有损 Adapter]
    adapter --> ir[规范 IR JSON]
    lossy --> ir
    ir --> compiler[Compiler + Validator]
    compiler --> pack[只读 StoryPack SQLite]
    pack --> runtime[Runtime 状态机]
    runtime --> events[统一事件]
    events --> cli[CLI]
    cli --> runtime
    runtime <--> save[独立 JSON 存档与历史快照]
```

## 模块边界

| 模块 | 职责 | 不能依赖 |
| --- | --- | --- |
| adapters | 原始结构 → 规范图，来源及文件哈希 | CLI、运行时状态 |
| compiler | 验证、确定性排序、原子构建 | 游戏专有字段 |
| storypack | SQLite 写入与只读访问、Schema 检查 | 上游资源、网络 |
| runtime | 图执行、条件/状态、选择、存档及回溯 | Adapter、终端、游戏 JSON |
| cli | 事件呈现、选项输入、命令编排 | 游戏流程推断 |
| validation | 静态诊断及使用 Runtime 的有界探索 | 第三方提取程序 |

中间表示直接采用可序列化 dataclass；不引入运行时插件发现框架或复杂 ORM。
新增 Adapter 只需要输出 `Bundle`，节点类型与边语义须保持统一。

## 原有 HSR 会话适配路径（兼容 1.0）

`OnStartSequece` 不是剧情数组。各 `TaskList` 是并发序列，其内部任务和
`SimpleTalkList` 是有顺序的指令流。当前仅降低已观察到的串行叙事子集：

1. 一个可识别的非等待入口；额外纯表现序列仅保留来源与信息诊断。
2. 序列末尾的选项/触发器，且事件在当前文件只有一个等待者。
3. 明确的 `EndPerformance` 结束会话。

也支持实际观察到的 PlaySimpleTalk 紧邻 WaitSimpleTalkFinish 指令对；
仅在有显式等待且中间没有其他任务时将其按串行台词执行。独立异步播放仍然阻塞。

遇到并发控制、额外初始化、非末尾 handoff、动态条件或未知控制字段即阻塞。
不按台词编号生成连接，不把等待事件名中的编号当作播放台词的证据。
`PlayTimeline` 可能携带缺失台词，保持 unknown，不当作可忽略动画。
完整任务与 Act 之间的世界状态调度尚未实现，每个 Act/Discussion 单独成为会话。
任务原 ID 与章节信息用于归属和浏览，不用于推断执行顺序。

## 执行和一致性

Runtime 沿显式边执行，不维护“台词列表索引”。对话事件发出后，指针移动到下一句未读节点；
选择事件直到 `choose()` 成功前保持不变。两个选项可有相同目标，但保留不同边和选择值。
分支节点必须恰好命中一个条件。未定义变量、歧义、缺失目标或未知指令均返回 BlockedEvent。
自动步骤有上限，重复状态也会暂停。状态包含当前任务、节点、变量、事件、选择历史和任务上下文。

`back()` 恢复最近一次选择之前的完整状态快照，同时撤销此后的选择。
快照不嵌套历史，避免递归存档；选择较多时历史仍会增长，尚无自动压缩。
`enter`/`exit` 使用显式跨任务边与上下文栈，不根据任务名或 ID 自动跳转。
通用 IR 可表达条件、变量和事件；并不表示已翻译原游戏所有谓词。

包通过规范 IR、源文件哈希、Schema、编译器版本和验证语言计算 SHA-256 标识。
相同输入、工具链下可得到字节一致的 SQLite 文件；不承诺跨 SQLite 版本的物理字节一致。
内容变化导致存档兼容性检查失败，格式升级须显式迁移。当前没有已有旧版 Schema，
故未实现空壳迁移器，读取器会拒绝未知版本。

## 验证边界

静态检查包括重复 ID、文本和目标引用、入口、节点/边类型、条件语法、无法到达的节点、
无法到达结束的路径、可能的环和明显的歧义。不能证明的条件覆盖、外部等待会被标记受限。
RESOLVED 仅表示这个会话静态检查没有已知问题；并非完整原游戏任务的兼容性认证。

有界探索合并相同执行状态，报告执行过的选项边、结束状态、阻塞与截断情况。
不同选择汇合到相同状态后可能只记录一个结束状态，不把结束状态数解释为完整路径数。
任意初始变量、外部游戏世界事件及巨大状态空间不在自动穷举承诺范围。

## M5 主线编译路径

`hsr/manifest.py` 按 MainMission.Type 和 MainMissionType 的实际标签分类；
`MissionInfo` 提供开始与完成子任务，`.partial.json` 提供声明的依赖、控制文件与完成条件。
显示优先级只用于下载抽样和菜单，不产生执行边。

`compiler/hsr_mainline.py` 链接任务、控制脚本和 Performance 表中的明确路径，
把 TriggerPerformance 转为通用 call/return。每个调用点分别存储 callee 入口和 continuation；
return 边列出合法返回地址，运行时只允许返回当前调用帧的地址。
候选边的静态遍历会过近似调用上下文，因此 M5 单独使用实际 Runtime 验证，不把静态可达当作完整可玩。

子任务调度使用显式依赖和完成状态；多个同时满足的路径会报告歧义，未模拟游戏世界。
Talk 完成需要脚本产生与定义 ParamStr1 对应的事件，并检查 Equal / Progress=1。
未理解的 FinishActionList、世界条件、并发或异步控制仍然阻塞。

引用收集与执行解耦：即使父指令不支持，仍收集其中明确声明的资源和台词作为静态证据，
但不给未知父节点编造跳转。任务、子任务片段和演出片段分别标记，覆盖率仅按任务层计算。
角色移动等可跳过的演出不被转成世界状态成功事件。

`hsr/sources.py` 管理明确的来源优先级、来源版本、内容哈希和冲突。
未知版本的补充控制资源不会自动执行；有损导出只作有来源的候选证据。
完整原始控制对象以 SHA-256 去重存入 metadata.resource_blobs，source_refs 保存逻辑路径及指针。
原生 Timeline 和二进制容器的限制见 M5 报告。
# M5.9 构建时调度

`compiler.schedule` 将有明确契约的动作、逻辑时间、依赖和事件等待转换为既有 set/wait/emit/dialogue/return 节点。
每条调度使用独立时钟变量，等待期间不推进；同刻动作没有明确依赖时阻塞，结束策略未证明时不生成成功返回。
这不增加 Runtime 的 Unity 或 HSR 依赖。

`hsr.native_scheduler` 读取已核验的原生对象并构建 Track 层级与 Clip 调度事实。
原生激活条件、Marker 恢复契约和退出策略未证明时生成受阻调用图；静态结构可解析不代表调度可执行。
其版本匹配的 IR 可以通过主线编译器的 `native_bundles` / CLI `--native-ir` 链接，未知语义继续传递至调用点。
原生库记录使用独立 NATIVE_LIBRARY 范围，不计作完整任务或已完成片段。

`hsr.native_scan` 为构建阶段提供持久化扫描状态与精确资源查询。
索引使用 WAL 和独立只读快照支持与解析并行；内容变化保留旧版本并重新扫描。
当前安装的查询绑定包清单、路径、大小和修改时间快照；内容 SHA256 在扫描阶段验证，查询报告明确注明这个边界。
# M6：证据图与阅读策略

`narrative.Reconstruction` 只依赖通用 Bundle，不依赖 HSR、Unity 或 UI。
HSR 构建适配器先复用原生调度审计与无损证据，再附加单独命名的 Reader 任务；
原 Strict 节点、边、字节与诊断保持原值。Reader 不改变任何原始资源。

Reader 的用户确认、轨道选择、未知后继人工引导、同刻人工排序、补丁接受都编译为既有通用
choice/set/branch/emit 节点。无需扩展 Runtime，也无需修改 SQLite 或存档 Schema。
原始控制脚本的字面事件监听和 TaskList 内显式顺序可以作为证据边，多个监听序列不能靠数组顺序连接。
原生 Clip 的静态时间只用于经过主动选择的文字投影，不能当作游戏暂停/并发恢复契约。
同刻无依赖时由用户选择阅读顺序并记录 visited 状态，不用 PathID 破平局。

`metadata.narrative.relations` 保存证据分类，`policies` 保存非官方阅读策略，`patches` 保存补丁原文和修改前值。
Strict 与 Reader 分别有入口和范围；Reader 保持 PARTIAL 诊断，阅读结束节点不发出游戏完成事件。
`Runtime` 的原选择快照支持确认步骤的回溯/保存；UI 可通过 `reader audit` 导出选择到证据的关联。
社区审核不是官方执行证据，不能覆盖已验证原始关系。协议详见 community-patch-v1.md。


## HF 中文转录输入

HF 下载器固定提交并保存逐文件哈希，下载阶段与离线对齐/运行分离。
JSON Adapter 保留原数组位置和原始类型；共享 M8 中文候选索引负责原文/规范化/模糊检索。
独立 GameEvidence 从既有控制包取得可观测路径与显式局部边，未知、条件、调用边界不会被静态投影跨越。
重复候选保留；模糊只有在同一原生节点实例有双侧锚点时才接纳。

HF 没有完整分支结构，编译时将缺口与非文本边界拆为独立 Reader 范围。仅外部顺序的关系增加确认节点；
原控制节点/边/任务/原文逐条保持不变。Wiki 编译器增加可选 Strict 输入及 namespace，默认接口不变。
新的包只使用原有通用 IR，Runtime 不加载 HF 文件或访问网络。
Archive 可选导入对齐证据，外部关系不升级为原生已验证关系。


## Story Arc Reader

arcs inventory 从正式 Auto/跨章前置和 NextTrackMainMission 建立边界与任务链，不以文件号排序。
编译层将完整转录、旁白、舞台说明和原生局部分支投影为既有 Dialogue/Choice IR，保留 Strict 原图。
Source Transcript Policy 一次接受，逐边证据随包保存。ArcSession 只负责 UI 会话审计、快照导航和持久化；
Runtime 与 SQLite Schema 不变。原生游戏完成、来源转录覆盖和已知局部分支覆盖分别报告。
