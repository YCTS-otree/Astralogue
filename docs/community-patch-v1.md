# Community Patch Protocol v1

补丁是构建阶段的 JSON 叠加层，不改游戏文件、公共快照或 Strict 图。适用于 Schema 1 StoryPack，
应用后必须重编译成新的包；包身份变化，旧存档会拒绝加载。

## 文档结构

```json
{
  "patch_version": 1,
  "id": "my-reader-link",
  "status": "pending",
  "game": "HSR",
  "game_version": "4.6.0",
  "source_hashes": {"control": "从基础 IR 精确复制全部 source_hashes"},
  "evidence": [{"id": "e1", "uri": "https://example.org/evidence", "note": "证据说明"}],
  "operations": [{
    "op": "connect",
    "mission": "Reader 任务 ID",
    "source": "已知源节点 ID",
    "target": "同任务内已知目标节点 ID",
    "evidence": ["e1"],
    "description": "待复核的人工引导关系"
  }]
}
```

这是结构示例；真实文件请用 `patch create` 从基础 IR 生成，不能使用示例哈希。
补丁只需要节点身份、关系和证据，通常不应复制游戏原文。

- `status`: `pending` 或 `reviewed`。后者还需 `review` 对象，包含非空 `reviewer`、
  `reviewed_at` 与有效 `evidence` ID 列表。此状态是提交者的审核声明，程序不认证审核者身份，
  不会访问证据网址，也不将它升级为官方事实。
- `game`、`game_version` 和完整 `source_hashes` 必须与基础 IR 的 `metadata.narrative` 相等。
  哈希绑定控制脚本、文本表、语言映射、每个 SerializedFile 和导出清单。
  即使游戏版本字符串不变，输入改变也会使旧补丁失效。
- `operations` 支持 `connect`、`order`、`condition`、`event`。每项必须指定任务、已有源/目标和证据 ID。
  `order` 表达明确的先后修订，采用与连接相同的显式有向边；不存在基于 ID 排序的行为。
- `condition` 必须有通用条件 AST，例如 `{"eq":[{"var":"reader_flag"},true]}`。
  不执行 Python；检查语法和变量是否在该包/任务中定义。条件不满足时暂停，不强行继续。
- `event` 必须有非空 `event` 字符串。用户接受补丁后才触发，随后进入目标；建议使用
  `reader:` 命名空间，避免把阅读记录解释为游戏任务状态。
- 修改已有顺序时，`replace_edge` 必须精确指出唯一的未验证策略边。
  已验证的原始控制/原生结构关系不可覆盖，分支集合不可整体替换，Strict 节点不可修改。
- 检查不存在的节点、任务归属、无效引用、重复源操作、关系冲突与补丁新引入的循环。
  v1 不允许补丁建立跨任务关系，也不允许凭补丁删除已验证的选择。

应用始终复制基础 IR。补丁原文、哈希、被修改的 Reader 节点、边、策略原值、审核状态、边的来源分类及确认策略
随包保存。删除补丁并从基础 IR 重建即可撤销。相同基础与补丁产生相同包身份；重复应用同 ID 会拒绝。
多个补丁可依次使用上一步输出 IR，但发生源节点/关系冲突时必须人工处理，不能靠输入文件顺序静默覆盖。

## PowerShell 使用

```powershell
.\.venv\Scripts\astralogue.exe patch create --source data/staging/m6-discussion.ir.json `
  --output data/patches/my-link.json --patch-id my-link --mission 'Reader任务ID' `
  --from-node '源节点ID' --to-node '目标节点ID' --evidence-uri '证据URI'
# 按上面的字段规范编辑 JSON；若源已有策略边，还需填写 replace_edge
.\.venv\Scripts\astralogue.exe patch validate --source data/staging/m6-discussion.ir.json --patch data/patches/my-link.json
.\.venv\Scripts\astralogue.exe patch import --source data/staging/m6-discussion.ir.json `
  --patch data/patches/my-link.json --output data/patches/imported-link.json
.\.venv\Scripts\astralogue.exe patch apply --source data/staging/m6-discussion.ir.json `
  --patch data/patches/imported-link.json --output-ir data/staging/patched.ir.json `
  --output data/packs/hsr-reader-patched.storypack --include-pending
```

默认拒绝应用待审核补丁；`--include-pending` 是使用者的显式选择。已审核补丁仍会在 Reader 内
显示非官方修订与再次确认，不会静默进入。普通 `build --source patched.ir.json` 可再次独立构建。
运行时不读取补丁文件，只执行包内通用 choice/emit/condition 节点。

## 证据与策略隔离

`metadata.narrative.relations[edge_id]` 记录 `origin`（`original_control`、`native_structure`、
`inferred`、`community_reviewed`、`unknown`）、`evidence`、`evidence_verified`、`verified` 和 `policy`。
`evidence_verified` 仅表示原始字段/结构已核验，`verified` 才表示该执行关系无需 Reader 假设。
例如原生 Clip.start 可核验，但依赖静态时间阅读策略的边 `verified=false`。
社区审核和推断均不自动得到 `verified=true`。

文字体验策略另存 `policies`，原生完整字节及来源仍留在 `native_evidence`，控制脚本留在 `raw_control`。
用户确认、人工引导、同刻人工排序、补丁接受与真实对话选择均沿用存档选择历史；
`reader audit` 将选择历史与包内证据相连。该审计是可复现的本地记录，不是防篡改证明。
