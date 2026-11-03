# BWIKI 后台采集与自由探索

网络采集仅在显式 `start` / `resume` 时启动，不注册开机自启。Worker 是独立隐藏窗口子进程；退出 Reader 不影响它。限制为 Chapter 100001 的七篇任务页面及章节索引。标题先由章节索引的真实链接确认，不使用文件编号安排任务顺序。模拟宇宙页面真实标题含 `•`，本地任务标题含 `·`。

```powershell
.\.venv\Scripts\python.exe -m astralogue bwiki pilot start --chapter 100001
# 网络需要本地代理时，加 --proxy http://127.0.0.1:10808
.\.venv\Scripts\python.exe -m astralogue bwiki pilot status
.\.venv\Scripts\python.exe -m astralogue bwiki pilot pause
.\.venv\Scripts\python.exe -m astralogue bwiki pilot resume
.\.venv\Scripts\python.exe -m astralogue bwiki pilot stop
```

默认目录 `data/staging/bwiki-pilot`。所有子命令可传 `--root`。最少间隔 120 秒，从响应完成算起；每日 UTC 请求预算 12，包含 robots 请求；网络异常最多三次，指数退避。403/429/5xx 保守暂停，429 同时遵循 Retry-After。robots 无法取得或不允许 API 时暂停。使用正常 User-Agent，不发送登录 Cookie，不关闭 TLS 校验。完成目标后自动退出，不遍历其他章节。

## 缓存与恢复

SQLite WAL 事务记录每页状态、原始身份、修订号、哈希、重试及下次请求时间。完整 API 响应包含 Wikitext 与 HTML，一次取得后全部本地解析。临时文件 fsync、哈希核验后原子替换；OS 文件锁保证同目录单 Worker。意外退出后锁由操作系统释放；下次显式恢复时，FETCHING 若已有完整缓存则补登记，否则重排队。数据库已登记缓存被篡改时失败，不静默联网覆盖。

```powershell
# 手动导入完整 MediaWiki action=parse JSON（包含 title/pageid/revid/wikitext）
.\.venv\Scripts\python.exe -m astralogue bwiki pilot import .\page.json
# 以下全部离线；单页重建可附加 --title 页面标题
.\.venv\Scripts\python.exe -m astralogue bwiki pilot parse
.\.venv\Scripts\python.exe -m astralogue bwiki pilot report
.\.venv\Scripts\python.exe -m astralogue bwiki pilot build --output data/packs/prologue-exploration-v112.storypack
.\.venv\Scripts\python.exe -m astralogue start --pack data/packs/prologue-exploration-v112.storypack --accounts-dir saves/exploration-accounts
```

构建保留原 `prologue-player.storypack` 和 M9 包，不覆盖已有账号绑定。新图的 pack_id 不同，旧账号不会静默迁移；原账号仍使用原包继续。文件存档可用已有 `arcs migrate-save` 显式迁移；旧历史保留，迁移后不跨图回溯。账号绑定图的自动升级尚未实现。

## Reader 策略及证据边界

第一批两个场景为监控室额外银狼对话、试图前往相反方向的阿兰回应。菜单只在同一 Wiki 任务步骤有唯一后续台词锚点时插入；多义锚点、不支持的模板、原生已验证控制边冲突不自动接入。可选内容播放后经过 set 节点记录已读并返回菜单；直接推进走已有主线后继。原来串在线性转录中的错误方向回应从默认路径移出，原节点及来源保留为档案，新互动复用其游戏文本、ID、变量标注。

**这两处为有证据的可选内容阅读入口，不是复现空间站行走与任务世界状态。** Wiki 证明“额外”分类、章节位置、错误方向条件；无法证明当前游戏世界所有触发条件或重复次数。后两项仍为 unknown，不能提升为 GAME_VERIFIED。菜单选择表示主动阅读此额外内容；once 是 Reader 防重复策略。没有把未知游戏条件放进表达式然后当 true。已知 IR 条件仍由原 evaluator 执行，缺变量会阻塞。

监控画面与存储设备仍属于任务调查步骤，不默认归类为可选。折叠模板不自动代表可选；只有显式“额外对话”分类才能成为候选，还必须通过唯一锚点、纯对白和控制冲突检查。其他内容输出未连接清单并保留原行为。

场景及已读标记保存在原 State.variables（`current_scene_id`、`current_exploration_node`、稳定互动 ID 的 `:read`）。历史选择与逐边来源审计沿用 ArcSession；不增加第二套存档。已确认身份、账号单进度约束不变，普通输出不显示证据及自动保存通知，`--debug` 可查看。

## Local Narrative Auditor Roadmap（本轮无推理实现）

未来审核输入协议 `narrative-review-input-v1`：资源哈希和版本、稳定节点 ID、原始游戏文本引用、BWIKI 结构位置、HF 数组位置、已验证边、任务变量与冲突诊断。适配器可选择 MNN 或其他本地模型后端，完全离线运行。

输出 `ReviewProposal`：`proposal_id`、`task_type`（missing_text / speaker / optionality / order / branch / placeholder / stage_direction）、`source_node`、`candidate_targets`、`evidence_refs`、`source_hashes`、`rationale`、`status=needs_review`。所有引用必须经程序校验，原资源变化使建议失效。人工确认后才能转换为 Community Patch；不修改原始文本、不自动采纳、不自行升级 GAME_VERIFIED。本轮没有下载、安装或调用模型。

## 1.13.0：持续采集到 4.5（覆盖前述本轮仅序章限制）

用户显式扩展范围后，可用 `bwiki pilot start --target-version 4.5` 启用。通过开拓任务总目录真实 mission-line-child-kt 行发现任务，排除均衡突破；不按任意页面链接遍历。任务所属版本从原始任务模板读取，缺失版本不算已证明 4.5。完成已知队列后，若尚无 4.5 声明，每天重新读取目录，保持后台等待；发现 4.5 且已知队列全部缓存验证后停止。默认每日 12 次；本轮按持续采集要求显式设为 240 次（--daily-budget 240），请求仍至少间隔 120 秒；403/429/5xx 等仍安全暂停。意外进程终止后需显式 resume，不注册系统自启。

此目标是已知目录范围的采集，不代表全部版本剧情已经解析或可玩。新版页面即使语义不支持也保留完整缓存，并输出 not_executable 和 unparsed_structure。现有七任务 Reader 不自动扩展为其他章节。

### 用户指定的持久调度

本机队列已启用北京时间（Asia/Shanghai，UTC+8）08:00–12:00、14:00–22:00 工作窗口。每轮随机工作 600–900 秒，随机休息 600–1200 秒，随机获取 4–5 个完整任务页面；达到配额后本轮不再请求。时间、配额、已取页数保存在 work_cycle 设置中，退出重启不重新分配本轮额度。午休和夜间不发起新请求，已在途响应可正常落盘。每日 240 次是额外上限，不是必须用完的指标。
