# StoryPack Schema 1 / IR 1

StoryPack 是普通 SQLite 文件，扩展名 `.storypack`。`PRAGMA user_version=1`，
`metadata.schema_version=1`，二者必须一致。数据库始终由运行时以 `mode=ro` 打开。
原始资源、临时路径和第三方数据库均不参与运行。存档不写入包。

| 表 | 主键 | 内容 |
| --- | --- | --- |
| metadata | key | JSON 值：pack_id、pack_version、engine_version、schema_version、validation_language、languages、inputs、source 等 |
| chapters | id | title 文本键 |
| missions | id | title、entry、chapter、original_id、status |
| nodes | id | mission、kind、text、speaker、data JSON 扩展字段 |
| edges | id | source、target、kind、text、condition JSON、value |
| texts | id, lang | 原始文本，不对内容规范化或去标签 |
| source_refs | id | node、file、pointer、record JSON（含 raw、original_id 等） |
| diagnostics | id | origin（source / validation）、code、message、severity、mission、node |

边和节点分别存储；多语言只改变 texts，复用同一剧情图。
为容纳部分解析与未解决引用，跳转目标没有 SQL 外键约束；由验证器显式报告，
运行时还会再次检查，禁止静默跳过。重复主键不能进入包。

## 规范 IR

`Bundle.to_dict()` 是完整 IR 协议：`ir_version`、`metadata`、`chapters`、`missions`、
`nodes`、`edges`、`texts`、`source_refs`、`diagnostics`。`texts` 为
`{"文本键": {"CHS": "原文", "EN": "English"}}`；节点与选项只引用文本键。

Node：`id`、`mission`、`kind`、可空 `text`/`speaker`、`data` 对象。
Edge：`id`、`source`、`target`、`kind`、可空 `text`、`condition`、`value`。
Mission：`id`、`title`、可空 `entry`、`chapter`、可空 `original_id`。
所有字段、默认值和类型的可执行定义见 `src/astralogue/model.py`。

| 节点 kind | data / 行为 | 出边 |
| --- | --- | --- |
| dialogue | text、speaker 引用 | 唯一 next |
| choice | 可选 option_events：选择值 → 事件名 | option 边携带 text 和唯一 value，可携带条件 |
| branch | 条件判断 | condition 边，每次必须唯一命中 |
| set | var、value、op（set 默认，或 add 数值加法） | 唯一 next |
| emit | event | 设置事件后 next |
| wait | event、consume（默认 false）、internal（构建期证明标志） | 事件存在后 next |
| enter / exit | 跨任务上下文压栈/弹栈 | 唯一显式 next |
| call | 保存 caller、continuation，跳入 callee | 唯一 call 边 + 唯一 next 返回地址边 |
| return | 校验当前调用帧并返回 | 显式 return 候选边；实际目标由栈帧决定 |
| noop | 可选 reason，表现省略信息 | 唯一 next |
| end | 当前叙事会话结束 | 无出边 |
| unknown | operation、原始指令通过 source_refs 保留 | 运行时始终阻塞 |

条件 DSL 不执行 Python：bool，或单键对象。支持 `all`/`any` 数组、`not` 条件、
`event` 事件名，以及 `eq/ne/gt/ge/lt/le` 双操作数数组。
操作数为 JSON 标量或 `{"var":"变量名"}`。未知操作符、未赋值变量、类型不兼容均暂停。
初始变量可放入 `metadata.initial_variables`。

稳定 ID：HSR 使用来源相对路径 + sequence/task/line 索引。同一来源位置重复构建稳定，
不把重复的 TalkSentenceID 误认为同一执行节点。原游戏调整任务数组位置可能改变节点 ID；
源哈希和包身份同时改变，旧存档会被拒绝，不能假设新版一定兼容。

## 存档协议 1

JSON 包含 `save_schema`、`pack_id`、`pack_version`、`pack_schema`、`language`、`state`、`history`。
state 包含 `mission`、`node`、`variables`、`events`、`choices`、`context`。
history 是选择前的 state 快照数组，不包含自身。加载时检查包身份、任务、节点和选择记录。
写入同目录临时文件并原子替换。不能将存档目标设为正在使用的 StoryPack。

1.1.0 在 state 中添加可选 frames 数组，每帧为 call / mission / return。
旧 Save Schema 1 中缺少 frames 时视为空栈，因此旧包的旧存档仍可读取。
新包的内容标识不同，旧存档不能无提示用于重建后的包。

StoryPack Schema 保持 1；包含新节点的包声明 required_capabilities=["call-return-v1"]。
使用 1.1.0+ 执行此类包，当前读取器拒绝未知能力。无需迁移数据库表，但重建包后需新存档。
metadata.mission_initial_variables 允许通用的按任务初始化状态。
imported_at_utc 保留为溯源信息，不改变内容标识；同一 IR 重复构建仍可复现，
两次重新导入的时间元数据可以不同，不承诺其物理文件逐字节相同。

## 扩展与升级

data / metadata / source_refs.record 为扩展保留空间，例如未来场景描述、媒体引用或记忆标签；
首期不解释这些字段。增加改变执行语义的节点、边、条件或表结构必须更新兼容性规则。
不认识的执行节点始终阻塞，未知 Schema 始终拒绝打开。
输入哈希目前用于来源核对与全量构建；尚未实现增量依赖调度。
