# M5.9 实测报告 — 2026-10-31 / 1.4.0

本轮完成了原生结构解析修复、全量已知 ASB 块索引、精确资源映射、通用调度 IR 预编译及主线编译器链接。
**没有完成真实 Timeline 的执行闭环。Discussion 15 条和主线 1 条调用尝试均明确阻塞，完整命名主线完成数仍为 0。**
本报告将静态布局、资源可用、IR 链接和 Runtime 返回分别计数。

## 环境、基线与安全边界

- 延续现有分支与代码，不重写 Runtime，保留原主线包和 M5.8 台词片段包。
- 使用现有 `.venv`、现有 AnimeStudio 独立无损扩展和已安装的全局 .NET 10 SDK，本轮没有安装新工具链。
- 首先完整运行基线：**130 passed**。最终完整运行：**144 passed，无 skip**。
- 游戏安装目录只读；所有新复制块、资产导出、索引和日志写入项目 data/staging 或 data 下的构建报告。
- 没有启动游戏、注入、读取游戏进程内存、修改客户端或上传游戏资源。公开 CutSceneConfig 通过开启证书验证的 HTTPS 获取，并校验固定快照 Git blob SHA。
- 游戏与公开快照均标记 4.6.0，公开源码快照为 `74a7b96fba32f00cf495a5c00b0311bd02207aaf`。
  相同版本号不等于证明所有游戏构建完全一致；原生对象、工具 DLL 和输入块均保留哈希。

## 资源索引与原 148 条引用

初始统计限定 StreamingAssets/Asb/Windows：9,450 个块，890 已索引、8,560 待扫描。
之后补查已知 Persistent/Asb/Windows，增加 7 个块，最终已知安装范围如下：

| 项目 | 实测 |
|---|---:|
| StreamingAssets ASB 块 | 9,450 |
| Persistent ASB 块 | 7 |
| 合计 | **9,457** |
| 已完成哈希核验和 Asset Map 的块 | **9,457** |
| 待处理 / 失败 | **0 / 0** |
| 输入块总字节 | 60,410,843,049 |
| 索引条目 | **6,821,208** |

分母为上述两个 ASB 目录的块；资产类型过滤面向叙事资源，不是全游戏所有类型对象的全集。
扫描复用已有索引，小批次复制后调用 AnimeStudio，不批量转换贴图、模型和音频。
断点表记录 PENDING/RUNNING/MAPPED/FAILED、来源 SHA、run 和诊断；同名同大小且保留修改时间的内容变化也有重新扫描测试。
旧内容版本不被覆盖。WAL 和独立读取快照修复了扫描与查询并行时的锁升级问题。
扫描结束后再次核验缓存输入哈希并写入当前安装快照。

| 原有引用阶段 | 数量 / 分母 |
|---|---:|
| 精确容器路径或显式配置关系定位 | **142 / 148** |
| 定向导出、结构解析并接入主线编译器 | **1 / 148** |
| 原生控制图链接 | **1 / 148** |
| 完整 Timeline Runtime 返回 | **0 / 148** |

路径匹配处理大小写、斜线和已验证的 assets/asbres 前缀，不删除性别后缀、不将 prefab 当作 playable。
CutSceneConfig 明确区分 CutSceneName 与 CutScenePath；命名引用通过真实表关系定位，不由文件名猜路径。

未精确定位的六条为 `CS_Chap00_Act240/245/250/260/280/290`。
每条有 `_f`、`_m` 后缀资源候选，共 12 条；配置中的原始无后缀路径没有精确容器。
这些候选保留 `resolved=false`，未自动选择性别，也未计入 142。
资源与安装快照结果：`data/m59-targets.json`、`data/m59-final-inventory.json`、
`data/staging/animestudio/m59-scan-progress.json`。

## 字段修复及分类

M5.8 的 347 个布局错误不是 347 套需要逐个实现的指令。
通用前缀实际包含两个变长字符串：绑定对象名称和骨骼/Transform 路径。
原解析器将其当作固定 8 字节，只有空串情形正确，非空字符串使后面的 Clip 数组错位。

另有 17 个 Track 的辅助外推字段包含非有限浮点位模式；它们现在按原 IEEE754 字节保留，
不转成默认 0、不直接赋予“无限保持”等执行含义。开始、持续、速度等调度核心数值仍要求有限且合法。

| 额外 Discussion 样本结构 | M5.8 | M5.9 |
|---|---:|---:|
| Timeline 根对象 | 15 | 15 |
| 可完整读取 Track 布局 | 93 | **440** |
| Track 布局错误 | 347 | **0** |
| 读取 Clip 调度字段 | 部分 | **187** |
| 已核对台词 ID 的 Clip | 26 | 26 |

新配置 `binding-v2` 经过全部 15 条样本验证，包含父/子 PPtr、绑定字符串、Clip 数组及时间参数。
旧 `m58` 解析配置保留以复现实测历史。绑定字段名称是 Astralogue 对观察值的标签，不宣称已取得游戏的原始字段名或方法语义。

分类表包含直接文本载体、已证明控制、任务状态、角色/物件状态、已证明纯视觉、语义未知六类。
目前只证明 26 个直接文本载体，未证明其完整激活条件；187 个 Clip 中其余 161 个保持语义未知。
Actor 绑定名称、骨骼路径及依赖关系单独记录，不因名字包含 Camera/Emotion/Animator 就判定可以忽略。
已证明可安全排除的纯视觉行为数为 **0**；这不表示资源中没有视觉效果。

## Marker 与调度证据

- 26 个 PauseMarkerClip 的额外载荷均为 **0 字节**。
- 26/26 个 PauseMarker 都位于同轨一个台词 Clip 的结束时间，已记录对应台词候选。
  这种时间关联没有给出恢复事件或恢复条件，不能据此自动继续。
- SimpleTalkMarkerClip 有 28 字节载荷、多种首部整数状态；5 个末尾参数匹配控制脚本的选项文本 ID。
  字段按原始 word 保留，语义未猜测。状态 `[0,1]` 与 `[1,0]` 没有被强行合并为统一 no-op。
- 选项文字 146010204 真正触发的原文事件是 `TalkSentence_146010205`，不是由选项 ID 拼接的事件。
  控制脚本共 **9 条选项 → 字面信号 → 唯一监听序列** 的关系已恢复，包含不同分支的后续 Timeline 调用。
  这些是外部控制脚本关系，不能冒充原生 PauseMarker 的恢复契约。
- 第一条台词 Track 的 Clip 数组为 `[5,15,16,26,0]`；5s/16s 的台词 ID 为 146010202/146010203，
  两者 duration 都为 10s，15s/26s 为 PauseMarker，0s 为 SimpleTalkMarker。
  数组顺序显然不能当作执行顺序。

## 通用调度器与真实阻塞

`compiler.schedule` 将显式契约转换成既有 IR：独立逻辑时钟变量、dialogue、wait、emit、依赖关系及 return。
等待期间冻结逻辑时钟；相同时刻没有明确依赖时阻塞；没有恢复事件时不生成猜测事件；结束策略未证明时不返回。
已验证“等待 → 保存 → 关闭数据库 → 读取 → 显式信号恢复 → 后续台词 → 返回调用者”。
这些是**通用 IR 结构测试**，不计作真实游戏 Timeline 成功。

真实资源有以下尚未证明的执行契约：

1. Track 前缀与激活/继承控制的对应关系未知，不能把所有轨道设为默认激活后全局按 start 排序。
2. PauseMarker 空载荷没有恢复绑定；MonoScript 只有类名、命名空间和程序集身份，不包含 CreatePlayable/ProcessFrame 方法体。
   通用 Unity Timeline 的公开实现不能直接证明游戏自定义 Marker 的行为。
3. SimpleTalkMarker 的参数与选项文本存在关联，但展示、等待、复用当前选择等动作未证实。
4. 原生结束策略未证明。最大 Clip end 仅记录为时间下界，不能代替退出/循环/保持策略。
5. 对控制脚本明确引用的 DS104060102.prefab 已定向无损导出：46 个对象，其中没有 PlayableDirector 类型对象。
   当前资源没有提供可据以解释宿主 Director 初始化/退出策略的序列化配置；这不是断言游戏不会运行时创建 Director。

因此 15 个真实 Timeline 调用均从实际根对象的层级生成调度事实，再于 preflight 明确阻塞。
实际 Runtime 尝试 **15 次、返回 0、阻塞 15**，调用栈仍保留，未执行伪造的成功 continuation。
数据和所有未理解行为随包保留，完整根调用没有退化成“每个 Clip 单独运行”的成功计数。

## 1000202 主线资源与编译器接入

实际关联链来自字段：MainMission 1000202 的 SubMissionList → SubMission 100020111 →
Mission_100020111.json 的 TriggerPerformance(C,100020111) → PerformanceC 的 PerformancePath →
`Story/Mission/1000201/Story100020111.json` → 明确 PlayTimeline →
`Story/Mission/1000201/Story10002011101.playable`。

该原生文件已无损导出 **742 个对象**，解析 **59 条 Track、272 个 Clip**，没有布局错误。
版本匹配的预编译 IR 通过 `import-mainline --native-ir` 注册到现有主线编译器：
真实 PlayTimeline 调用边连接原生 IR 入口，未知语义诊断传回调用点，未编造 return。
不匹配来源版本或注册冲突会报错。调用边界测试不宣称已经满足原任务的物件触发等世界前置条件。

重新生成主线包 **622 条任务/片段/库记录、5,284 节点、5,234 边**，其中一条为独立原生库记录，
不将其计作新增完整任务。旧主线包保持原样。
原任务分母仍为已知 365 条 Main 记录、336 个命名候选、356 份定义；实际重新执行有界覆盖检查，
完整命名主线仍为 0。唯一结束的隐藏技术记录仍单独统计。
100020113 六种原有分支组合、存档与回溯回归保持通过。

特别纠正：CS_Chap00_Act250 属于已知 1000101 控制资源，Act260 属于 1000203，不能因目录名相近把它们认成 1000202。

## 实际命令

本轮初始全量扫描使用 scan()（512 MiB/批、最多 128 块/批、每次进程超时 300 秒），其实现现已暴露为 CLI。
原始执行记录在 data/m59-scan.log、data/m59-persistent-scan.log 和 data/m59-final-hash-check.log。
以下为同一工作流的可复现接口；有缓存时复用，name 参数须使用新值。

```powershell
$game = 'O:\Program Files\miHoYo Launcher\games\Star Rail\Game'
$studio = 'G:\hoyostudio\AnimeStudio-net10-68700c7d885a68a444886bd4b7f7827e77789e12\AnimeStudio.CLI.exe'
.\.venv\Scripts\astralogue.exe hsr scan-native --game $game --executable $studio --inventory-only
.\.venv\Scripts\astralogue.exe hsr scan-native --game $game --executable $studio --max-batches 256
.\.venv\Scripts\astralogue.exe hsr native-targets --game $game --cutscene-config data/staging/m59-public/ExcelOutput/CutSceneConfig.json

.\.venv\Scripts\astralogue.exe hsr schedule-native --directory data/staging/animestudio/m58-lossless-final/output/lossless --source data/raw/hsr-mainline --control data/staging/animestudio/reference/DS104060102.json
.\.venv\Scripts\astralogue.exe build --source data/staging/m59-discussion.ir.json --output data/packs/hsr-native-scheduled.storypack --force

.\.venv\Scripts\astralogue.exe hsr schedule-native --directory data/staging/animestudio/m59-main-1000202/output/lossless --source data/raw/hsr-mainline --control data/raw/hsr-mainline/Story/Mission/1000201/Story100020111.json --output data/staging/m59-mainline-native.ir.json --report data/m59-mainline-native-call.json
.\.venv\Scripts\astralogue.exe hsr import-mainline --source data/raw/hsr-mainline --native-ir data/staging/m59-mainline-native.ir.json --output data/staging/m59-mainline-linked.ir.json
.\.venv\Scripts\astralogue.exe build --source data/staging/m59-mainline-linked.ir.json --output data/packs/hsr-mainline-m59.storypack --force
.\.venv\Scripts\astralogue.exe hsr coverage --pack data/packs/hsr-mainline-m59.storypack --report data/m59-mainline-linked-runtime.json

$env:ASTRALOGUE_HSR_SOURCE = (Resolve-Path data/raw/hsr-sample).Path
$env:ASTRALOGUE_HSR_BATCH_SOURCE = (Resolve-Path data/raw/hsr-cli-sample).Path
$env:ASTRALOGUE_HSR_MAINLINE_SOURCE = (Resolve-Path data/raw/hsr-mainline).Path
$env:ASTRALOGUE_HSR_NATIVE_SOURCE = (Resolve-Path data/staging/animestudio).Path
.\.venv\Scripts\python.exe -m pytest -q
```

测试结果 **144 passed**，含 14 项新增测试，全部原有 130 项保留通过。
新测试覆盖时间冻结与恢复、同刻依赖/歧义、已执行前缀保留、未知结束不返回、版本冲突、
性别候选不冒充精确匹配、内容变化重扫、真实结构/选项关系、完整根调用阻塞、主线链接和新进程离线 CLI。
CLI 实际记录：data/m59-discussion-cli.txt、data/m59-mainline_linked-cli.txt；两次返回码均为 0，
显示阻塞且没有剧情成功结束；退出码 0 不被当作 Timeline 成功。

## 交付与限制

- `data/m59-discussion-coverage.json`：15 条 Discussion 的完整结构、分类、依赖、Marker 证据和实际 Runtime 结果。
- `data/m59-mainline-coverage.json`：已知主线全集的有界验证、资源定位及 1000202 的原生调用证据。
- `data/m59-targets.json`：原 148 引用与 12 条未验证性别后缀候选，分别计数。
- `data/packs/hsr-native-scheduled.storypack`、`data/packs/hsr-mainline-m59.storypack`：受阻调度和主线链接结果。
- `data/m59-runtime-verification.json`：Discussion 15 次、主线库 1 次真实调用尝试，均未返回。

Schema 和存档版本保持 1；Runtime 没有 Unity、AnimeStudio 或原始资源依赖。
本轮没有恢复暂停/恢复、激活及退出的完整游戏契约，没有证明全部分支完成；不会将全块索引、结构解析或通用调度单测标记为完整剧情成功。
