# M6 实测报告 — 2026-10-31 / 1.5.0

本轮交付了独立叙事重建层、Reader 策略、Community Patch Protocol v1 和可离线播放的两个阅读段。
**DS104060102 的 27 种已知选项组合均读到 Reader 出口；100020111 的 17 条正文可连续阅读。
完整命名主线、完整原生 Timeline 的 Strict 完成数仍为 0。**

## 环境与基线

- 在已有 1.4.0 项目和 `.venv` 上开发；先读 M5.9 报告、原生解析器、IR、存档和 CLI。
- 基线实际运行 **144 passed in 54.01s**，最终全量 **171 passed，无 skip**。
- 原 Runtime 文件和 SQLite Schema 未修改，存档版本仍为 1；版本升级为 1.5.0。
- 没有扫描游戏目录、重新导出游戏块或修改游戏文件；复用已有 15 + 1 个无损 SerializedFile。
  没有运行 AnimeStudio、启动游戏、访问进程内存或上传游戏资源。
- 使用已有工具，无新 SDK/运行环境安装。uv 默认缓存写入受限，改为工作区 data/staging/uv-cache。
  发布依赖通过代理及系统证书验证获取，没有关闭 TLS 验证。

## 已实现的分层

- `narrative.Reconstruction`：不依赖 HSR/Unity/UI 的证据与文字策略层，复制 Strict 后附加 Reader 任务。
  支持原始控制、原生结构、推断、社区审核、未知五类来源，原字段证据与执行关系是否已验证分开存储。
- `hsr.reconstruction`：复用 binding-v2 解码和原始容器精确匹配，用 TaskList 明确顺序、字面事件监听、
  原生 Track/Clip 字段生成阅读投影。没有按任务/台词 ID 排序拼接控制流。
- Reader 用既有 choice/set/branch/emit/wait/end 节点实现，不向 Runtime 引入游戏专用结构。
  保留全部原生字节、清单、原控制脚本与来源。Clip 实例身份与它引用的对象身份区分，避免复用同一对象时丢失 Clip。
- 用户必须确认阅读策略、初始化抽象、文字轨道选择、未知 Marker、未知返回契约和阅读段结束。
  不默认激活其他轨道，不将其他轨道判为纯视觉；这些轨道明确处于所选阅读范围之外。
- 同刻无已知先后时生成用户排序菜单，记录每项 visited 状态；未知后继可由非官方人工引导菜单提供显式目标。
  缺少明确目标、未知自定义 Clip、不能唯一定位的事件监听仍阻塞。
- `reader audit` 将包绑定存档中的真实选择、确认、人工引导/排序、社区补丁与证据关联；确认步骤可回溯。
  阅读结束不发出游戏完成状态，不等于原生 Timeline 正常退出。

## 真实 Discussion 验证

来源：公开快照 `74a7b96fba32f00cf495a5c00b0311bd02207aaf` / 4.6.0，
本地同版本原生导出，控制脚本 `DS104060102.json`。范围为 Discussion1040601 的这段控制脚本，
不是整个任务。原有 15 个 SerializedFile、1,010 个对象的无损证据仍随包保存。

| 阶段 | 实际结果 |
|---|---:|
| 精确关联的 Discussion Timeline | 15 |
| 已恢复正文 Clip / 唯一台词 ID | 26 / 26 |
| 原脚本选项 / 选择层数 | 9 / 3 |
| Reader 已验证选项组合 | 27 / 27 |
| 原生完整 Timeline Strict 执行成功 | 0 / 15 |
| Reader 完整原生调度证明 | 0 |
| 完整命名任务完成 | 0 |

独立校验器逐一检查 27 种路径，而不是只采用合并状态探索。每次最多 300 个事件；单测使用 250 上限。
脚本中的选项 146010227 实际触发 `Wait_Option_104060102_82`，保留字面值，没有根据台词 ID 生成事件名。

首条实播路径选择 146010204 → 146010217 → 146010227，正文顺序为：

```text
146010202, 146010203, 146010205, 146010206,
146010215, 146010216, 146010218,
146010224, 146010225, 146010226, 146010228,
146010235, 146010236
```

其他选项分别进入原脚本证明的 02/03/04、06/07/08、10 或 11→12 或 13→14，
再经字面事件汇合到 05、09、15。所有正文逐条校验，真实文本直接查原 TextMap，不改写原文。
Marker 中匹配到选项 ID 的字段保留为未知语义，不重复当成正文播放。

完整原文播放记录保存在本地 `data/staging/m6-playback/discussion-cli.txt`，不提交游戏原文到 Git。
同目录 discussion-audit.json、27 个存档及 `data/m6-runtime-verification.json` 保存逐路径 ID、原始选择与确认依据。
27 次运行合计显式记录 27 次 Reader 同意、54 次非文本确认、207 次轨道选择、603 次未知 Marker 确认、
207 次阅读返回及 27 次阅读结束确认；这些是重复路径累计操作数，不是独立资源数。

## 主线与资源覆盖率分开计算

主线依据既有 MissionInfo_1000202.partial.json 和 PerformanceC 控制引用，验证 1000202 所属子任务
100020111 的 Story100020111 控制脚本与原生 Timeline；不按目录名推断任务归属。
一条文字轨道中实际读到：

```text
100020314 … 100020327, 100020360, 100020361, 100020362
```

共 17 条正文。19 个未知 Marker 需要用户确认；文字轨道读毕后确认返回脚本并结束阅读段。
这只覆盖一个子任务的文字投影，没有伪造其他子任务、移动、战斗、任务完成或后续任务连接。
原有 100020113 六种真实分支回归测试保留通过。

| 范围 | Strict 完成 | Reader 阅读结果 |
|---|---:|---|
| Discussion DS104060102 控制段 | 0 条完整原生 Timeline | 27/27 已知选择路径，26 条正文 |
| Main1000202/Sub100020111 控制段 | 0 条完整原生 Timeline | 1 条所选文字路径，17 条正文 |
| 已知主线 MainMission 全集 | 0 个完整命名任务 | 本轮未声称完整任务，0 |
| 社区审核修订 | 本轮未引入 | 真实 community-reviewed 补丁 0 |

使用当前引擎重新对旧主线包执行有界覆盖率：365 条记录，336 条命名候选、356 条定义可用，
338 BLOCKED、27 PARTIAL；唯一能结束的记录是既有隐藏技术记录，完整命名任务仍为 0。
报告 `data/m6-mainline-strict-coverage.json`；该包保持 M5.9 原内容，没有用 Reader 包替换它。

9,457 个 ASB 块的既有完整索引没有重新扫描。原 148 条主线引用仍为 **142 精确定位、1 结构解析并链接、0 Strict 完整执行**。
本轮只处理已有依赖闭包：15 条 Discussion 单列，主线 1 条单列；没有新增其他 141 条的解码覆盖。
六条无后缀引用对应的 12 个性别候选保持未决，不选择默认性别，也不计入精确匹配。

## Patch Protocol v1 实测

支持 create/import/validate/apply，JSON 绑定 game/version、控制脚本/文本表/语言表及所有原生 SerializedFile/manifest 哈希。
检查失效节点、任务归属、条件语法与变量、证据引用、循环、重复操作、关系冲突、审核状态和版本/哈希变化。
源关系已验证时拒绝覆盖；只允许显式替换唯一未验证 Reader 策略边。补丁不能修改 Strict。

真实样本另用项目自建的 `m6-local-policy-demonstration` **pending** 补丁验证导入与重编译：
对初始化确认添加 `reader:setup_acknowledged` 记录，依据原 TaskList 的明确后继，
既不声称恢复游戏世界状态，也没有伪造社群审核。使用者通过 `--include-pending` 显式接受，播放时仍需确认非官方修订。
补丁后的 27 种路径、26 条正文及分支与基础 Reader 一致；Strict 原生调用仍全部阻塞。
补丁原文、被修改 Reader 节点/边/策略原值和关系证据随包保存，活动关系不会保留失效边引用。
输出路径禁止覆盖基础 IR、补丁原文或彼此重叠。待审核默认拒绝，重复应用同 ID 拒绝。
`reviewed` 的结构验证和事件执行已由单测覆盖；它只是外部审核声明，不是程序对证据真实性的认证。

本地证据：`data/patches/m6-local-policy.patch.json`、`data/m6-patched-runtime-verification.json`、
`data/staging/m6-patched-playback/discussion-cli.txt` 及审计记录。
测试还检查相同基础 IR + 补丁重新应用得到相同 pack_id，原基础 IR 不变。

## 实际命令

```powershell
$env:ASTRALOGUE_HSR_SOURCE = (Resolve-Path data/raw/hsr-sample).Path
$env:ASTRALOGUE_HSR_BATCH_SOURCE = (Resolve-Path data/raw/hsr-cli-sample).Path
$env:ASTRALOGUE_HSR_MAINLINE_SOURCE = (Resolve-Path data/raw/hsr-mainline).Path
$env:ASTRALOGUE_HSR_NATIVE_SOURCE = (Resolve-Path data/staging/animestudio).Path
.\.venv\Scripts\python.exe -m pytest -q

.\.venv\Scripts\astralogue.exe hsr reconstruct `
  --directory data/staging/animestudio/m58-lossless-final/output/lossless `
  --source data/raw/hsr-mainline --control data/staging/animestudio/reference/DS104060102.json `
  --output-ir data/staging/m6-discussion.ir.json --output data/packs/hsr-reader.storypack `
  --report data/m6-discussion-reconstruction.json --force
.\.venv\Scripts\astralogue.exe hsr reconstruct `
  --directory data/staging/animestudio/m59-main-1000202/output/lossless `
  --source data/raw/hsr-mainline --control data/raw/hsr-mainline/Story/Mission/1000201/Story100020111.json `
  --output-ir data/staging/m6-mainline.ir.json --output data/packs/hsr-mainline-reader.storypack `
  --report data/m6-mainline-reconstruction.json --force
.\.venv\Scripts\python.exe tools/verify_m6.py
.\.venv\Scripts\astralogue.exe hsr coverage --pack data/packs/hsr-mainline-m59.storypack `
  --report data/m6-mainline-strict-coverage.json --max-states 1000 --max-steps 10000

.\.venv\Scripts\astralogue.exe patch validate --source data/staging/m6-discussion.ir.json --patch data/staging/m6-local-policy.patch.json
.\.venv\Scripts\astralogue.exe patch import --source data/staging/m6-discussion.ir.json `
  --patch data/staging/m6-local-policy.patch.json --output data/patches/m6-local-policy.patch.json
.\.venv\Scripts\astralogue.exe patch apply --source data/staging/m6-discussion.ir.json `
  --patch data/patches/m6-local-policy.patch.json --output-ir data/staging/m6-discussion-patched.ir.json `
  --output data/packs/hsr-reader-patched.storypack --include-pending --force
.\.venv\Scripts\python.exe tools/verify_m6.py --discussion-pack data/packs/hsr-reader-patched.storypack `
  --records data/staging/m6-patched-playback --output data/m6-patched-runtime-verification.json
```

新增 27 个测试用例，含全部 27 条真实路线、原文查表、真实选项存档/恢复/回溯、同刻人工排序、未知阻塞、
待审核选择、已审核声明、补充事件、条件不满足、补丁循环/冲突/失效、重复重建及离线 CLI。
CLI 子进程在无上游数据的临时工作目录运行，移除全部上游环境变量并禁用可用网络代理；只接收包路径。
两段实际播放及补丁播放返回码均为 0，且明确出现 Reader 范围的结束提示；不是仅检查进程成功退出。
另外直接从发布 wheel 导入代码，在临时目录实际完成第一条 Discussion 路径；记录
`data/staging/m6-playback/wheel-cli.txt`。已检查 wheel/sdist 不含上游 data、研究缓存或存档，
包版本为 1.5.0，锁文件离线检查通过。

## 交付与剩余边界

- 本地包：data/packs/hsr-reader.storypack、hsr-mainline-reader.storypack、hsr-reader-patched.storypack。
  全部为 Schema 1，Reader 静态状态为 PARTIAL；可单独复制到其他目录播放。
- 原始游戏内容、导出、存档、完整原文播放日志、数据包和研究缓存均未提交 Git。
- Release/v1.5.0 提供 wheel/sdist，程序、协议、测试和验证工具开源；用户自行持有数据。
- 仍未知：轨道激活标志、PauseMarker 的恢复条件、SimpleTalkMarker 的真实动作、原生结束契约、
  多数非文字轨道的控制/状态影响及游戏世界前置状态。本轮没有新增这些字段的原生语义证明。
- Reader 静态时间投影不保证与游戏并行调度完全一致。非所选轨道不在阅读范围内，不被标成纯视觉。
  复杂的并行事件监听和不能唯一确定的调用仍需阻塞/明确人工引导。
- 继续优先定向处理已定位资源和实际任务依赖闭包；通过可复核证据补充非文本任务转换，再扩大阅读段，
  保持社群修订、Reader 路径完成和 Strict 原生执行三套独立指标。
