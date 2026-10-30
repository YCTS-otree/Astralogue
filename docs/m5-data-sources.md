# M5 数据源与本机资源调查 — 2026-10-31

M5 当前是部分交付。任务清单、任务控制链接、真实主线子任务片段与覆盖率工具已实现；
完整命名主线任务尚未验证成功。不能把明文控制图补充协议写成原生 Unity Timeline 解包支持。

## 公开数据与任务系统

固定版本为 [74a7b96fba32f00cf495a5c00b0311bd02207aaf](https://github.com/DimbreathBot/TurnBasedGameData/tree/74a7b96fba32f00cf495a5c00b0311bd02207aaf)，
提交标记为 OSPRODWin4.6.0_D16854589_A16781679_L16781679。

实际 MainMissionType.TextMap 标签确认：

| 原始 Type | 标签 | 规范类别 |
| --- | --- | --- |
| Main | 开拓任务 | TRAILBLAZE |
| Gap | 开拓续闻 | CONTINUANCE |
| Companion | 同行任务 | COMPANION |
| Branch | 冒险任务 | ADVENTURE |
| Daily | 日常任务 | DAILY |

所有 2,184 条 MainMission 记录均进入清单，分别为 365 / 106 / 67 / 1,551 / 95。
分类依据 Type，不依据文件名或 ID 大小。Type=Main 中另保留无标题、明确隐藏及 System 记录；
有标题且未明确隐藏/System 的菜单候选为 336 条，其他记录没有从清单或包中删除。

旧 Adapter 只读 Act/Story 的 OnStartSequece，忽略了主线所需的这些结构：

- MissionInfo.MainMissionID、StartSubMissionList、FinishSubMissionList；
- MissionInfo.partial.json 中 SubMissionList 的明确所有者、MissionJsonPath、TakeType / TakeParamIntList；
- FinishType、ParamType、ParamStr1、Progress、FinishActionList；
- PerformanceA/C/D/DS/E/Video 表中的 PerformanceID → PerformancePath；
- 调用后返回脚本，再产生 FinishPerformanceMission 事件的关系。

实际数据证明，子任务 ID、控制文件父目录和所属主任务不能简单相互替代。
例如子任务 100020113 的声明所有者是 1000202，控制文件却位于 1000201 目录。
它明确调用 D 类型演出，再产生 Mission_100020113 完成事件。
MainMission.TakeParam、NextMainMissionList 和 NextTrackMainMission 原样保留；
未将跟踪提示或数字顺序伪装成合法执行时间线。

下载器先取得完整分类和任务定义，再按数据选择代表性资源：
首个显示章节，以及不超过十个且均为 Talk 目标的任务，然后追踪明确 Performance 引用闭包。
显示优先级只决定获取样本，不决定执行关系。获取目录包含 334 个请求过的控制资源路径，
完整规则与任务清单保存在 acquisition.json，下载失败报告单独记录。
资源索引的 complete 仅指 Mission / Story / ExcelOutput / TextMap 四个列明范围。

## 为什么 Timeline 不能直接跳过

Story/Discussion 文件实际出现 PlayTimeline、TimelineName、Type 和 Parameters。
这些调用可能处于选项后的独占分支，也可能先于汇合事件或任务结束。
公开仓库有调用 JSON，但本次相关 .playable / Cutscene 资源本体不可用。
等待事件名中的 TalkSentence_ID 不是该句在此被播放的证据。

M5 支持由明确索引提供的、可读取的 JSON 控制图：

    timeline-index.json: {"逻辑 TimelineName": "相对资源路径"}

对应资源必须是已经核实过的 OnStartSequece / TaskList 控制图结构，
其中台词、事件、选择和调用会进入同一编译器，而不是变成空的占位节点。
此接口用于经审查、与来源版本匹配的明文补充资源。
它不是原生 Unity .playable 二进制序列化规范，也没有从 clips 名称或台词 ID 猜测时间顺序。
本次真实 Timeline 引用解析为 0/148；明文补充图的执行能力通过单元测试验证，
尚无真实原生 Timeline 内容成功解析的结论。

## 本机安装资源

最初指定的 G:\Program Files 存在，其 miHoYo Launcher/games 为空。
卸载注册表给出明确的 O 盘安装位置，随后在
O:\Program Files\miHoYo Launcher\games\Star Rail\Game 找到 StarRail.exe，config.ini 报告版本 4.6.0。
没有扫描整个 G/O 盘，没有启动客户端或第三方解包器。

实际调查结果：

- pkg_version 有 11,077 条记录；其中 9,450 条 .block 资源、1,183 条 .usm 等。
- StreamingAssets/Asb/Windows 下有 9,458 个文件；所抽查 block 头为 ENCR。
- 资源索引还出现 SRMI、SRAM、SRAR，RawConfig 容器出现 DBDC。
- DesignData 存在明文资源名/字段标记，但其二进制对象结构尚未实现可靠解码。
- 只做清单、文件头和有限静态字段标记分析，没有将字符串出现位置当作台词顺序。

详细结构化结果在本机 data/m5-local-resources.json。
本地与公开版本都标记 4.6.0，尚不能证明二者补丁构建完全相同。
本次没有将本机二进制资源导入执行图；它们没有成为运行时依赖。
没有修改游戏文件、读取进程内存、注入、接触反作弊逻辑、绕过保护或上传本机资源。

## 其他来源与融合

继续保留已有 StarrailDialog JSON/JSONL、Dialogue Browser SQLite 导入器。
此前固定源码版本和许可调查见 data-sources.md，未复制第三方实现。
这些导出缺少完整入口、Timeline 和部分条件控制，因此不能单独修复主线执行关系。
额外检查的 hoyo_public_wiki_parser 将 HSR 中文 Wiki 支持标作进行中，
没有采用未验证的文本转录替代游戏控制图。

多来源以明确顺序处理：主原始数据在前，额外明文源在后。
同一逻辑资源内容不同、版本不一致、Timeline 索引冲突均报告并阻塞。
相同内容按 SHA-256 去重，原始控制对象保留在包中，路径与指针单独保留。
SQLite 原始文本哈希及 JSONL 显式句子 ID 可产生规范文本候选，
只有原始文本键可核对、来源修订一致时才填补缺失值。
未知版本、冲突值及上游丢失的控制连接不会被静默接受。

## 已知版本限制

365 条 Main 记录中，九条没有找到公开 MissionInfo 定义：
1054600、1054601、1054602、1054603、1054604、1054605、1054607、1054608、1054609。
已在索引中检查整个 MissionInfo 文件名集合，不能断言这些任务在游戏中不存在或尚未开放。
另有三个显式台词引用在该快照中无法解析：403101004、403101007、403101009。
均保留缺失诊断，没有编写任务 ID 特例或生成替代台词。
