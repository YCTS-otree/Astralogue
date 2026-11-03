# BWIKI Background Pilot & Free Exploration 验证

日期：2026-11-03；引擎 1.12.0；StoryPack / save schema 仍为 1。没有构建可执行文件或发行包。

## 实际结果

序章 Chapter 100001 的七篇任务页面和章节索引均已缓存。2 篇复用已校验的旧快照，6 篇新增 API 获取；另有一次 robots.txt 调查请求。取得完整 Wikitext + HTML 后只在本地解析，不按小节反复联网。七任务共 47 个三级标题区段；这是缓存结构区段数，不代表 47 个可执行游戏场景。

七页记录 38 个明确“额外对话”折叠，浅层提取到 242 条发言行，其中复杂嵌套结构仍标 unknown，不能将这些数字算成新增可玩台词。31 个其他折叠（包含动画、调查、彩蛋）未擅自分类为可选。

本轮接入 **2 个 Reader 探索菜单、2 条可选正文**：

| 任务 | 互动 | 阅读位置与返回依据 | 触发状态 |
| --- | --- | --- | --- |
| 混乱行至深处 | 额外对话（银狼） | “协助银狼调查监控室内的终端”小节中显式额外折叠，后续调查对话唯一匹配 HF 节点 | Wiki 小节可选内容已确认；游戏世界精确条件、重复次数未知 |
| 漩涡止于中心 | 额外对话（试图前往相反方向） | 同一任务步骤中阿兰额外回应；折叠外下一句作为唯一 HF 汇合锚点 | Wiki 明确为错误方向；未模拟人物移动与坐标判定 |

新增可选 NPC 提示 1 处，错误方向回应 1 处；**物件调查接入 0 处，完整原生触发条件验证 0 处**。两处均是主动阅读入口，once 是 Reader 防重复策略，不声称原游戏只触发一次。没有把未知 availability 当作游戏条件 true。

阿兰的 1 条错误方向回应此前出现在默认 HF 路径，现移到可选互动；银狼的重复提示按 Wiki 额外内容单独呈现。原始节点及文本仍保留。其他 36 个明确可选折叠和 31 个未分类折叠共 **67 项未连接**，原因包括没有唯一续接锚点、复杂分支正文、上下文或条件缺失。未批量移除 HF 中其余内容；240 条可选发言文字与 HF 有重合，但重合并不证明全部原来都被误串进主线。

## 网络与断点恢复

使用公开 API 与真实章节索引链接，无 Cookie、浏览器伪装、TLS 降级或验证绕过。最短相邻 API 请求间隔（上一响应完成至下一开始）为 **120.033 秒**；另有 120.959、120.087、120.073、127.653 秒。6 次 API 请求在预算 12 内。Worker 最终 `completed`，已自动停止。

实际强制终止本轮启动的 Worker PID 49220，随后用相同 `queue.sqlite` 显式恢复。终止前已验证缓存的 SHA256 和请求次数在恢复后保持一致，没有删除进度数据库。缓存完成但事务未更新的边界、锁释放、429/Retry-After、robots 拒绝另由可重复测试覆盖。没有真实制造网站 429、断电或重启系统；这些不能算作真实网络故障实测。

新增页面暴露了折叠内部标题和跨行嵌套模板：修复为完整文档解析后分区，跨行不支持内容保留原始结构和 unknown，不展平分支。旅途页面解析修复在本地完成，没有重新下载。

## 实际命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m astralogue bwiki pilot start --chapter 100001 --proxy http://127.0.0.1:10808
# 本轮实际启动 PID，经确认后仅终止自己的 Worker
Stop-Process -Id 49220 -Force
.\.venv\Scripts\python.exe -m astralogue bwiki pilot resume --proxy http://127.0.0.1:10808
.\.venv\Scripts\python.exe -m astralogue bwiki pilot parse --title 旅途正在继续
.\.venv\Scripts\python.exe -m astralogue bwiki pilot report
.\.venv\Scripts\python.exe -m astralogue bwiki pilot build --output data/packs/prologue-exploration-v112.storypack
.\.venv\Scripts\python.exe tools/verify_exploration.py
.\.venv\Scripts\python.exe tools/verify_accounts.py
```

上面 PID 为验证历史，不是可再次执行的操作指引。构建和播放不启动采集。额外在 socket.connect 禁止的进程中再次编译，两个包逻辑 pack_id 完全一致；原 Strict 节点、边和全部既有文本逐项比较不变。

## CLI 真实播放

新包：`data/packs/prologue-exploration-v112.storypack`。实际子进程在临时工作目录中运行，从入口到出口逐个进入并退出 7 个任务，网络连接和上游资源访问由 Python audit hook 禁止。

| 路径 | 探索菜单数 | 可选正文数 | DialogueEvent 数 | 保存恢复 | 手动任务跳转 |
| --- | ---: | ---: | ---: | --- | ---: |
| 两处都探索后返回 | 2 | 2 | 893 | 可选对白后、结算前保存并退出；恢复后返回菜单且隐藏已读项 | 0 |
| 两处均直接推进 | 2 | 0 | 891 | 本路径一次进程到出口 | 0 |

DialogueEvent 数含任务边界、叙述和过场，不能当成原生台词 ID 数。实际日志中包括自由探索菜单、互动、返回及章节出口；模拟最终 State、选择与逐边审计和 CLI 自动存档完全相同，无重复对白节点。独立测试另验证菜单保存、回溯恢复未读状态和两玩家隔离。

原序章账号 CLI 注册→中途退出→登录→七任务出口、第二账号隔离、已完成账号不重开、静默保存也重新通过。原 M9 / 玩家包保留；新包使用不同 pack_id，原账号不会静默换包。旧包旧存档可照常使用；文件存档须显式迁移，账号绑定自动升级仍未实现。

## 测试与本地产物

- 基线：224 passed（91.51s）。
- 首轮新增功能完整回归：233 passed（105.59s）。随后增加两项真实解析问题回归用例，最终完整回归 **235 passed（115.32s）**，见 `data/pilot-tests-final.log`。
- Pilot / exploration 定向测试：11 passed（4.54s）。
- `uv lock --check --offline` 通过，缓存使用工作区 `data/staging/uv-cache`。
- `git diff --check` 通过。

未提交 Git 的本地产物：`data/bwiki-pilot-report.json`（逐页 ID、revision、哈希及七任务差异）、`data/pilot-recovery-verification.json`、`data/exploration-report.json`、`data/exploration-verification.json`、`data/exploration-pack-verification.json`、`data/staging/exploration-verification/*.txt`、原始 API 缓存与 SQLite 队列。

## 边界与后续

本轮完成两处真实可选内容的探索阅读闭环，不代表恢复了整个序章所有自由活动机制。其他复杂 NPC 问答、物件调查、重复调查、全局条件仍需基于原始脚本或审核补丁继续恢复。Reader 七任务阅读完成仍不等于 Native Strict 完成；本轮没有增加完整命名主线 Strict 完成数。

Local Narrative Auditor 的纯数据接口与离线人工审核路线见 [使用文档](bwiki-background-pilot.md)，本轮未运行 LLM。
