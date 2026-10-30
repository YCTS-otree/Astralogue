# 数据源调查（2026-10-30）

调查读取了三个公开仓库的源码/文件清单及真实游戏 JSON；网络直连失败后通过本地 HTTP 代理完成获取。
研究文件位于被忽略的 `.research/`，游戏数据位于被忽略的 `data/raw/`。
未将第三方实现复制进项目，也未调用第三方代码来构建样本。

## A. TurnBasedGameData

固定版本：[74a7b96fba32f00cf495a5c00b0311bd02207aaf](https://github.com/DimbreathBot/TurnBasedGameData/tree/74a7b96fba32f00cf495a5c00b0311bd02207aaf)。

实际检查到 `Story/`、`Config/Level/Mission/`、`ExcelOutput/`、`TextMap/`。
当前 TalkSentenceConfig 是数组，244,380 条；部分条目没有角色名字段。
MainMission 和 MissionChapterConfig 当前也是数组，分别用 MainMissionID 和 ID 索引。
适配器也支持旧工具处理过的字典型配置，但不假设键格式，读取显式 ID 字段。
台词正文与角色名分别引用 TalkSentenceText.Hash / TextmapTalkSentenceName.Hash，Hash 用字符串查询 TextMap。
当前样本 TextMapCHS、TextMapMainCHS 还可能和分片文件一起出现，冲突值不能静默覆盖。

实际分支验证来自
[Act500100101.json](https://github.com/DimbreathBot/TurnBasedGameData/blob/74a7b96fba32f00cf495a5c00b0311bd02207aaf/Config/Level/Mission/TrainVisitor/Act/Act500100101.json)。
它包含两个初始选项、各自两句台词、事件汇合、一个单选项和明确结束。
等待者和选项通过字符串匹配，并非通过台词 ID 数值排序。
其他检查样本为 Act100010113 和 DS103010102；它们有额外表现/控制或 Timeline 依赖，
当前不会被误标为完整可玩。

## B. StarrailDialog

固定版本：[149dd8e2e7c9a87fbe6a8f3982e4eba73b0bcd18](https://github.com/mrzjy/StarrailDialog/tree/149dd8e2e7c9a87fbe6a8f3982e4eba73b0bcd18)。
检查 get_dialogues.py、get_missions.py、util/common.py、story_util.py、train_visitor_util.py。
JSONL 记录包含 conversations、options、next_TalkSentenceID；任务元数据另外提取。
parse_on_sequence 只识别部分指令，merge_on_sequence_sessions 进一步合并会话。
未知控制、原始来源边界和某些选项会丢失；等待事件附带的 content 也不能自动证明该句确实被播放。
因此复用其数据接口，保留显式目标作补全材料，不把提取结果直接视为可执行图。

## C. StarRail_Dialogue_Browser

固定版本：[99f27a6099d32c30c6380d5e8923fd2ebd74d883](https://github.com/M1k0t0/StarRail_Dialogue_Browser/tree/99f27a6099d32c30c6380d5e8923fd2ebd74d883)。
检查 build_dialogue_db.py、app_config.py、README。
表包含 text_map、talk_sentence、dialogue_group、dialogue_line、group_triggers、file_talk_ref。
sequence_index 和 sort_order 提供组内浏览顺序；wait_custom_string、trigger_custom_string、group_triggers
保留有价值的事件线索。但嵌套条件分支的触发器可被收集到同一组，不能视为无条件动作。
等待事件名中的台词 ID 也可能被补成显示行，不能据此恢复原始执行语义。
我们的 SQLite Adapter 校验实际列，使用只读连接，保留已解析文本与原始记录并明确标记损失。
最终 StoryPack 与该数据库 Schema 无关。

## 许可与集成方式

截至上述固定版本，三个仓库的根目录/文件树没有发现明确许可证文件，GitHub 仓库许可证元数据为空。
公开可读与第三方代码的再分发许可分开处理：当前独立实现，不复制或捆绑提取器代码。
游戏原始数据直接由用户导入；显式 fetch-sample 仅从公开仓库获取固定样本及其必要文本表。
程序本身使用 MIT 许可证，游戏内容归原权利人，面向非商业再创作。

## 验证方法

tests/test_real_data.py 不存放剧情原文。设置 ASTRALOGUE_HSR_SOURCE 后：

- 从真实目录复制所需文件至测试拥有的临时目录，导入并编译，然后删除这个上游副本。
- 两条路径分别核对台词 ID，排除另一分支，并核对共同汇合后缀。
- 关闭并重新打开包，保存、恢复，再回溯改选另一分支。
- 禁止 Python socket 连接后执行运行时；在无上游目录的新进程中运行真实 CLI。

真实初始分支 1 的专属台词 ID 为 500100105/500100106；分支 2 为 500100108/500100109。
两条路径都在 500100110 汇合，后续为 500100112/500100113/500100114。
这验证一个真实会话的分支，不代表全游戏剧情兼容率。

后续验证扩展到了固定版本全部 **374 个列车访客 Act**（排除 `.layout.json`）。
根据实际样本补充了数值型 TextSpeed、明确配对的 PlaySimpleTalk/WaitSimpleTalkFinish，
以及角色朝向的表现省略。最终 372 个 RESOLVED、2 个 PARTIAL；
有界探索覆盖这 372 个会话的 **573 条选项边**，没有阻塞或探索截断。
剩余 Act500170101 涉及对外部事件触发后继续执行；Act500180901 涉及额外表现及控制形态，
仍保留诊断并暂停，不强行补全。原始完整目录可用 `fetch-sample --scope train-visitors` 显式获取。
