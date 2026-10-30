# MVP 验证记录 — 2026-10-30

引擎 1.0.0 / StoryPack Schema 1 / Save Schema 1。
在 Windows PowerShell、现有 Python 3.12.14、uv 0.13.6 上实际执行。
沿用已有解释器，使用 uv 的项目 `.venv`，没有额外安装 Python SDK。

| 阶段 | 交付与主要文件 | 实际验证 |
| --- | --- | --- |
| M0 | pyproject.toml、uv.lock、docs/data-sources.md | 三个上游源码与真实 JSON 调查；uv sync --locked、CLI help/version |
| M1 | model.py、adapters/、compiler/、storypack/、validation/ | 374 个真实崩铁会话导入、构建、引用检查、可复现构建、只读与重开 |
| M2 | runtime/、conditions.py | 顺序、单/多选、同目标选项、汇合、变量/条件/事件、未知阻塞、执行上限 |
| M3 | cli/ | 实际命令和 CliRunner：搜索、分页菜单、中文台词、选择、存档、恢复与回溯 |
| M4 | tests/test_real_data.py、test_hsr_batch.py | 删除测试上游副本后离线执行；新进程 CLI；真实分支逐句 ID 断言；批量探索 |

最终完整测试：**77 passed**，无跳过。已设置真实样本与完整列车访客目录两个环境变量。
不设置环境变量时相应集成测试明确 skip，不计为通过。

## 真实崩铁集合

固定来源版本：74a7b96fba32f00cf495a5c00b0311bd02207aaf。
完整列车访客 Act 集合排除 `.layout.json`，共 **374 个会话**。
最终默认包包含 **5,503 个节点、5,401 条边**。

- 372 个 RESOLVED、2 个 PARTIAL。
- 对 372 个 RESOLVED 会话使用实际 Runtime 有界探索，覆盖 573 条选项边。
- 没有运行时阻塞、没有探索截断。
- 部分路径合并为相同状态，因此选项边覆盖数不等于端到端路径数。
- Act500170101、Act500180901 保持 PARTIAL；未绕过其未知控制。
- 额外调查的主线/Discussion 样本存在 Timeline 等未支持行为，不能据此声称主线完整可玩。

精确分支断言使用 Act500100101：分支一执行 500100105/500100106，
分支二执行 500100108/500100109，共同到达 500100110 并继续至明确结束。
另实测保存后关闭/重开包、恢复下一句、回溯并改选另一条分支。

## 本机复现命令

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD ".cache\uv"
uv sync --locked
$env:ASTRALOGUE_HSR_SOURCE = (Resolve-Path .\data\raw\hsr-cli-sample).Path
$env:ASTRALOGUE_HSR_BATCH_SOURCE = $env:ASTRALOGUE_HSR_SOURCE
uv run --no-sync pytest -q

.\.venv\Scripts\astralogue.exe import --source .\data\raw\hsr-cli-sample
.\.venv\Scripts\astralogue.exe build --force
.\.venv\Scripts\astralogue.exe validate --explore-all --report .\data\validation.json
.\.venv\Scripts\astralogue.exe play --search Act500100101
```

完整包包含两个受限会话，因此 validate 按设计返回 **1**；JSON 报告中的
exploration_summary 为 missions=372、blocked=0、truncated=0、option_edges=573。
这是对受限数据的如实失败报告，不是全部会话都已通过。

完整报告在本机 `data/validation.json`；原始资源、报告、包与存档均未提交 Git。
`saves/latest.save.json` / `saves/autosave.save.json` 已通过实际 CLI 保存到 Act500100101 的首次选择处，
可直接运行 resume 继续体验。

## 已知限制与下一步

当前专注崩铁。完整主线任务的跨 Act 世界调度、Timeline 隐含台词与复杂并发仍需逐类调查。
应继续补充原始控制结构及对应真实断言，不能用台词 ID 或文件顺序补线。
Linux 尚未在本机实测；代码使用跨平台 pathlib/SQLite，但不能将其标记为 Linux 验证通过。
当前不提供旧格式迁移、增量构建、GUI、音视频或 AI 功能。
