# 多次调查与已批准申请的后续意见（1.24.0）

## 行为

经人工审核的 `after.segments` 表示按访问次数执行的 Reader 调查阶段。首次进入第一个阶段，第二次进入第二个阶段，依此类推；最后一个阶段持续重复。菜单入口不消失。使用普通 branch、set 和 condition IR，Runtime 无需读取 BWIKI 或运行模型。

阶段文本按原节点原文顺序校验，并检查是否遗漏原文；不会根据台词ID或文件顺序拆分。原始节点、原文、来源结构及补丁仍保留。普通没有重复触发计划的可选互动维持原有一次性策略。

已批准页面增加“提交后续修改建议”。提交后保留已批准状态、审核人、批准时间和已发布版本；新任务继承实际来源、关联申请与人工意见，模型输出继续是待人工审核的新申请。提交建议不会直接插入句子或更改当前剧情包。新增句子的实际发布仍需具备来源和插入位置编译支持，现有发布校验不会静默跳过这些要求。

## 实测

- 已批准申请：`ce27cc510e63e12ee9aaacf26368174c38aa17ab83682d6176ea8843fcbcde27`。
- 仅重试该申请的发布，成功增量发布到当前游玩包，修订13；未撤销其他已发布内容。
- 从实际菜单运行“调查星核”四次，首次为长段，后三次为再次调查短段；每次均返回菜单且调查选项仍可选。
- 每次返回菜单后保存并重新加载；另验证选择回溯。未修改用户账号或实际存档。
- 实际事件记录（本机生成，不提交）：`data/audit/repeat-inspection-validation.json`。
- WebUI真实HTTP检查通过：阶段说明、已发布修订13、已批准后续意见按钮存在，旧“不支持”提示已移除。未进行浏览器像素检查。

## 测试

- 完整回归命令：`.\.venv\Scripts\python.exe -m pytest -q`，配置已有真实资源环境变量，324 passed，109.12秒。日志：`data/repeat-inspection-tests.log`。
- 补充HTTP发布后意见提交测试；专项命令：`python -m pytest -q tests/test_audit_cleanup.py tests/test_audit_feedback.py tests/test_audit_webui.py tests/test_live_publication.py tests/test_audit.py tests/test_audit_reference_recovery.py`，50 passed，5.58秒。
- 新增覆盖：2/3/4个访问阶段、末阶段重复、菜单保留、纯主线跳过、保存恢复、拒绝伪造或遗漏原文、已批准父申请保留、模型子申请仍为待审、已发布HTTP提交不撤销发布。

## 范围

上述执行关系是经人工审核的Reader访问策略，不是GAME_VERIFIED的Unity触发契约。本轮未调用付费模型，未自动批准模型结果，未重抓BWIKI、未打包EXE。


## 调查楼梯申请恢复

- 原申请 `f51f120e0b1e27cf13d41e4e0bad94426cc283b0e17512f20dcc095a3b73bc29` 未被自动批准。
- 两个根因：BWIKI与HF在“再次调查”后的换行不同，原精确匹配漏绑；模型在 `before.default_path_nodes` 使用了已有对象名称而非ID。
- 新增限定当前任务的格式空白归一化唯一文本绑定；若多个实例同文则仍不选择。结构差异中的名称仅在唯一已绑定节点对应时转为别名，不接受不存在对象。
- 恢复并复用已保存的失败响应，按已有关联复核流程生成具体待审申请 `55ea6ac63163844ae32fe7e6f32e0c12c9323fa1dbb406eec4daea79173e86ab`，实际绑定任务0的row74，与当前“推进主线、调查终端、额外对话（空间站的标志）、调查电子屏”菜单对应同一小节。
- 原失败记录保留，新申请为pending且可直接人工批准；本轮未替用户批准该申请。


## 1.24.1：电梯拆分申请发布修复

申请 `73c07d714f149cbb930b85a50ee3a2b34876b5b2697c94a18ea1b3fcfb458a3a` 已由人工批准，具有明确的调查电梯菜单名称、所属场景和首次/再次原文分段，但操作枚举是 `split_dialogue_sequence`。编译器此前只放行 `move_to_optional_interaction`，导致流程明确的申请仍被报告无执行计划。

新增共享能力判断：仅当拆分操作同时具备明确互动名称及至少两个访问阶段时，进入已有调查编译路径，继续校验唯一场景、原文覆盖及原始执行边。任意拆分操作不因枚举放宽而被自动执行。UI与编译器使用同一能力判断。

实际重试该已批准申请，发布到当前游玩包为修订15。四次访问顺序为首次、再次、再次、再次，菜单选项持续保留；每次回菜单后保存恢复，再验证回溯。记录位于 `data/audit/elevator-validation.json`（本机生成，不提交）。HTTP详情显示已发布修订15，无过期的不支持提示。未更改人工决定或调用模型。

专项命令：`.\.venv\Scripts\python.exe -m pytest -q tests/test_audit_cleanup.py tests/test_live_publication.py tests/test_audit_webui.py tests/test_audit_feedback.py`，41 passed，5.13秒。新增覆盖拆分操作的2/3/4阶段、末阶段重复与存档，以及缺少明确计划的普通拆分不自动执行。本轮未重新运行完整回归，上一轮完整回归324项通过。
