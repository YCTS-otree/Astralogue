# M8 验证报告 — 1.7.0 / 2026-10-31

**M8 未达到真实 Wiki 任务端到端验收。** 已实现实验性离线对齐基础，不将目录往返测试当作 Wiki 任务成功。

## 实际访问证据

依次经本机 HTTP 代理 http://127.0.0.1:10808，以正常验证 TLS 的 urllib 访问：
- https://honkai-star-rail.fandom.com/robots.txt ：403
- api.php 的 query/revisions/rvslots=main 请求：403
- /wiki/To_Rot_or_to_Burn ：403
- /wiki/A_New_Venture_on_the_Eighth_Dawn_(Trailblaze_Mission) ：403
- /wiki/Honkai_Star_Rail_Wiki:Dialogue_Guide ：403

另作一次不使用代理的 API 对照，20 秒超时。未绕过挑战、关闭 TLS 或换镜像规避访问限制。
网页工具对部分地址返回 402；仅能获取 Eighth Dawn 的缓存展平文本，无法用它证明原始模板/HTML 分支结构，未用于构建。
用户确认没有本地 Wiki 导出。本轮没有可供真实页面回归的原始快照。

## 实际实现

- adapters/wiki：缓存快照结构、原文哈希、页面身份和修订证据；有限 Wikitext 行型解析，未知模板/HTML 均保留为 Unknown。
- wiki-tree-v1：显式的人工/适配器结构协议，保留嵌套 Choice 的独立 body，共享后续由父序列表示；不是已验证 Fandom 模板解析器。
- 英文对齐：规范化 Unicode、空格、引号和少量游戏格式标签；唯一精确匹配且角色一致才自动选 ID，重复匹配全部保留。
- 模糊检索仅给审查候选，不自动通过。0.8 仅为候选检索筛选，未校准为正确性或真实性概率。
- 审核文件绑定完整 alignment_hash（含页面修订与输入哈希），允许选择候选/拒绝；修改返回副本，不改上游。
- StoryPack 生成：只显示本地 CHS 原文，未匹配台词/选项与未知结构阻塞。Wiki 来源边保持 inferred/verified=false，标签 WIKI_ALIGNED。
- Reader 明确同意 Wiki 外部顺序，不提供 Strict 入口，不发出游戏任务完成事件。Wiki 选择另标 wiki_choice，避免审计误记为原始游戏选项。
- CLI：wiki fetch/parse/align/report/review/build。fetch 先检查 robots，拒绝访问时停止，不覆盖已有缓存。

## 英文数据与测试

公开游戏快照 revision 74a7b96fba32f00cf495a5c00b0311bd02207aaf。
本机原目录没有 TextMapEN；通过代理从该 revision 的 raw.githubusercontent.com 获取 58,586,809 字节。
Git blob SHA 校验为 fe9d68edaafaa1361fbcdd8454fef0151b235837，与既有 resource-index.json 一致。
保存在 data/staging/wiki/TextMapEN.json；align 每次检查该 blob 与指定 source 一致，构建另外检查 CHS/台词表哈希。

基线实际运行 175 passed in 74.74s。新增用例验证保守规范化、未知模板阻塞、嵌套树保留、HTML 不冒充支持、空选项拒绝、审核失效与候选检查。
真实目录测试使用 TalkSentenceID 146010202：原英文 → 候选 ID → 本地中文 → StoryPack → Runtime 对话与范围结束。
**该测试没有 Wiki 输入，不证明真实 Wiki 排列、真实 Wiki 分支或任务完成。**
最终完整运行 **183 passed in 80.58s，无 skip**，结果见 data/m8-tests.log。所有测试均不依赖在线 Wiki；真实英文目录测试缺资源时明确 skip。

## 覆盖率与未交付项

| 指标 | 本轮 |
|---|---:|
| 获取到可解析原始快照的 Wiki 任务页 | 0 |
| 真实 Wiki 页面解析回归 | 0 |
| 真实 Wiki 台词对齐/多层分支恢复 | 未验证 |
| 经校准且验证的模糊匹配 | 0 |
| Wiki 范围完整阅读成功任务 | 0 |
| 完整游戏任务证明 | 0 |

未实现真实 Fandom HTML/模板语法完整解析、分支感知动态规划、条件/可选对话的可执行语义、游戏控制冲突核对、
Community Patch v1 转换、真实页面抽样正确率和真实 Wiki CLI 播放记录。审核 JSON 是 alignment 决策协议，尚非 Community Patch v1。
未批量抓取或重新解包；Runtime、StoryPack Schema 1 和存档保持不变，M6/M7 回归继续运行。

## 命令

```powershell
.\.venv\Scripts\astralogue.exe wiki fetch To_Rot_or_to_Burn --output data/staging/wiki/rot.json --proxy http://127.0.0.1:10808
# 当前该命令会在 robots 403 时停止；以下需先有合法取得的真实快照
.\.venv\Scripts\astralogue.exe wiki parse snapshot.json --output parsed.json
.\.venv\Scripts\astralogue.exe wiki align parsed.json data/raw/hsr-mainline data/staging/wiki/TextMapEN.json --output alignment.json
.\.venv\Scripts\astralogue.exe wiki report alignment.json
.\.venv\Scripts\astralogue.exe wiki build alignment.json data/raw/hsr-mainline --output data/packs/wiki.storypack
.\.venv\Scripts\astralogue.exe reader play --pack data/packs/wiki.storypack
```

当前没有交付真实 Wiki 对齐 StoryPack。取得可审查原始页面后，应先核实实际模板并建立真实回归，再推进第一个任务；不能靠手工编造树补齐本轮验收。
