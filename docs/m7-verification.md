# M7 档案初版验证 — 1.6.0 / 2026-10-31

本轮交付可工作的 Archive/Browse 初版，**未完成 M7 的全部验收**。原 Runtime、StoryPack Schema 1 和存档未修改。

## 实际输入与计数

使用既有 hsr-mainline 固定快照，以及 hsr-mainline-m59、hsr-reader、hsr-mainline-reader、hsr-reader-patched 四个包。
没有再次扫描 9,457 个 ASB 块，没有运行 AnimeStudio、联网抓取或修改游戏文件。
只消费上述明确输入，尚未自动发现所有历史第三方结果；不声称全游戏覆盖。

| 指标 | 实际数量 |
|---|---:|
| TalkSentence ID | 243,976 |
| 有 CHS 原文 | 243,960 |
| 在本次控制/图输入中有引用且存在目录记录的 ID | 556 |
| 明确归属任务的目录台词 ID | 59 |
| 其中明确 Main 类型开拓任务 | 59 |
| 尚未明确归属任务 | 243,917 |
| 图内正文实例 | 43 |
| 导入的显式已验证关系（跨阶段去重） | 30 |
| 待审核转换任务 | 43 |
| 翁法罗斯关键词命中 | 1,088 |

243,976 是台词目录分母，不代表每条均被本地剧情脚本引用。TextMap 的 474,193 个字符串没有全部当成对话。
同文本 Hash 不合并不同 TalkSentence ID；图实例按节点、来源数据区分，多个阶段副本不重复计实例。
原始引用不存在目录记录时保留引用，但不计入有效台词数。
局部执行恢复本轮新增为 0，导入的已验证边来自 M6，不将静态 Clip.start 当执行顺序。
43 个图实例来自先前 26+17 条 Reader 正文，不等于新增 43 条剧情。绝大多数目录条目尚无已验证执行连接。

## 翁法罗斯实际样本

原始 TalkSentenceID **104020086**，TalkSentenceText.Hash **11869397784945432870**，
来源 ExcelOutput/TalkSentenceConfig.json 与 TextMap/TextMapCHS.json。原始记录含 VoiceID，未提供角色名称。
该条含翁法罗斯关键词，已实际通过 Browse 阅读并查看详情。
原始记录和 CLI 输出保存在本地 data/m7-amphoreus-sample.json、data/m7-browse-transcript.txt，不提交游戏原文。

这是一条**弱证据候选**：本次输入没有证明该条所属任务、章节或前后执行顺序，恢复关系数为 0。
MainMission/MissionChapterConfig 确实包含翁法罗斯相关章节记录，例如 5000401 等记录的章节文本；
1040601 明确为 Main 类型、WorldID=501，但不能仅凭世界 ID 或关键词把该台词归给它。
本轮没有完成“明确归属的翁法罗斯阅读块”的验收，不把 1,088 个关键词命中当章节覆盖率。

## 命令与测试

```powershell
.\.venv\Scripts\astralogue.exe archive build data/raw/hsr-mainline `
  --pack data/packs/hsr-mainline-m59.storypack --pack data/packs/hsr-reader.storypack `
  --pack data/packs/hsr-mainline-reader.storypack --pack data/packs/hsr-reader-patched.storypack `
  --output data/archive.sqlite --force
.\.venv\Scripts\astralogue.exe browse --search 翁法罗斯
.\.venv\Scripts\astralogue.exe browse --search 104020086
.\.venv\Scripts\astralogue.exe browse --mission 1000202 --category TRAILBLAZE
.\.venv\Scripts\astralogue.exe archive recover --output data/m7-review-tasks.json
.\.venv\Scripts\astralogue.exe archive coverage
```

Browse 支持中文子串、台词 ID、任务、章节名称、角色和孤立条目筛选，n/p 分页、编号详情、q 返回。
所有资料列表显示“非已验证剧情发生顺序”。详情保留原始目录记录、引用、来源版本、图数据及前后关系。
不使用默认 FTS 分词器；中文子串和 ID 查询已实际测试。
独立档案可复制使用，不需要原始数据或游戏。普通 Browse 不运行构建器。

基线：171 passed in 64.54s。新增四项测试后完整运行：**175 passed in 75.76s**。
新增用例覆盖真实中文检索、重建、复制数据库后独立查询、分页、同文本不同 ID、任务分类、
重复包导入去重、强制覆盖保护、未验证关系不升级为 Strict、待审核任务生成。
最后两项计数修正另执行 Archive 用例复验；没有把未跑的测试记为通过。

## 文件及接口

- archive/__init__.py：独立 SQLite Archive Schema 1、构建、检索、详情、恢复任务和覆盖率。
- archive/cli.py：archive build/recover/coverage 与根 browse 命令。
- tests/test_archive.py：结构测试和实际数据验证。
- data/archive.sqlite、data/m7-coverage.json、data/m7-review-tasks.json：本地生成产物，未提交 Git。
- detail/search 返回普通 Python dict；角色陈述标记 character_statement_not_verified_world_fact，
  原始关系和未知关系保留 verified 字段，可作为后续知识导出的基础；未实现 MNN/LLM。

## 尚未交付

- 全来源自动发现、独立 TextMap-only 浏览、多语言归档、完整角色 ID 映射和冲突诊断。
- Performance/Act/Discussion 到 MainMission 的完整归属闭包，多候选归属的完整报告。
- 已归属无位置/局部有序/完整执行五类的完整指标，以及可靠局部块计数。
- 待审核任务到 Community Patch 的转换、上游更新失效验证与审查操作命令。
- Browse 内跳转 Play、按组阅读上下文和返回层级导航。
- 明确任务证据支持的翁法罗斯片段及新增局部阅读链。

M6 的 Strict、Reader 和 Patch 执行保持原有测试覆盖；本轮没有新增完整任务，未将档案收录算作可交互覆盖。
