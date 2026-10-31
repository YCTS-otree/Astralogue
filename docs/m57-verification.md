# M5.7 实测与剩余问题（2026-10-31，程序 1.2.0）

本阶段是部分交付：外部工具接入和原生资产恢复有效；原生 Timeline 到可执行 IR 尚未完成。
没有新增可玩主线，也没有将不完整原生数据注入既有 StoryPack。
旧 1.1.0 包与存档保持原样；Schema、存档版本和 Runtime 均未改变。

## 工具审查与操作边界

- 使用用户已提供的 AnimeStudio 1.1.0，提交 `68700c7d885a68a444886bd4b7f7827e77789e12`。
- 审查对应提交的 README、CLI Program/CommandLine/Exporter、AssetsHelper、
  BundleFile、AssetsManager、MonoBehaviour 和 TypeTreeHelper 的相关实现。
- 官方源码：<https://github.com/Escartem/AnimeStudio/tree/68700c7d885a68a444886bd4b7f7827e77789e12>。
  本地发行包附带 MIT 许可证；外部工具独立运行，本项目没有复制其解析实现。
- 已有 .NET 10.0.11 运行时可执行该发行包。本机只有 .NET 7/8 SDK，本次未构建或修改外部工具。
- CLI 即使遇到失败也可能退出 0；检查实际输出和日志，不能仅依据退出码计数。
- CLI 的普通导出和 Asset Map 路径都调用 MergeSplitAssets，因此**输入始终为项目 staging 中的复制品**。
- 游戏实际目录为 `O:\Program Files\miHoYo Launcher\games\Star Rail\Game`，config.ini 标记 4.6.0。
  不修改游戏、不读取进程内存、不上传游戏资产。公开源码/脚本下载经本机代理完成。
- TLS 信任链存在问题，调查源码的 Python 下载临时关闭证书验证；不是产品自动下载功能，未下载或执行外部二进制。

## 实际恢复结果

初次使用最小三个块证明 SR 加载与 JSON Asset Map 可运行，取得 976 个条目。
随后三次受限扫描，合计 811 个不同内容块，取得 428,363 个 Asset Map 条目。
这只是本地安装的部分块，不能据此认定未匹配资源不存在；本轮没有导出贴图、模型或音频全集。
Map 保留 Name、Container、Source、PathID、Type、Hash、Offset 原始字段。
run.json 另记录输入块 SHA256、原始相对路径、工具启动文件 SHA256、版本、参数、超时/退出状态和导出哈希。
新运行还记录 pkg_version SHA256；同为 4.6.0 不能证明构建完全一致。

### 原有 M5 分母

`data/m57-native-coverage.json` 将原有 IR 中的 148 次 Timeline 引用逐项匹配，恰好为 148 个不同名称。

| 阶段 | 原有 148 个引用 |
|---|---:|
| 在本轮部分 Asset Map 精确定位 | 0 |
| 关联并实际导出 | 0 |
| 控制结构解析 | 0 |
| 转换为可执行 IR | 0 |
| Runtime 验证 | 0 |
| 因原生资产而解除阻塞的任务 | 0 |

未找到的引用继续阻塞，未以效果资源的相似名称替代，也未将轨道或文件排序编造成执行顺序。

### 独立的真实样本链（不计入上述 148）

从相同公开快照 `74a7b96fba32f00cf495a5c00b0311bd02207aaf` 取得：
`Story/Discussion/Mission/1040601/DS104060102.json`。
脚本中明确的 15 个 PlayTimeline 引用，全部精确匹配本机容器路径。
例如 `Story/Discussion/Mission/1040601/DS10406010201.playable` 对应
`assets/asbres/story/discussion/mission/1040601/ds10406010201.playable`，位于
`015e049ff7fed15690692f2d77bbd997.block`。
Map 中保留对象 pathID、块偏移和工具 Hash。注意块偏移不是完整的 Unity 序列化文件身份。

只定向导出这一个容器：Convert 61 个文件（其中 JSON 36 个），Raw 42 个文件，Dump 0 个文件。
这些是文件数，不是已恢复台词/剧情数量。Raw 中验证了 28 个兼容头布局的对象。
具体来源链和 Raw 头位于 `data/staging/animestudio/sample-chain.json`。

关键样本 `PlaySimpleTalkClip`：Raw 140 字节；可验证 Unity 基础头与 Convert JSON 一致，
但 Convert 只有 m_GameObject、m_Enabled、m_Script、m_Name 四个基础字段。
其后的自定义二进制载荷未被 JSON 表达。脚本引用可保留，但无法从这些字段确定台词 ID、时序与条件。
Dump 没有可用类型结构输出。**这证明读取/解密已经成功，剩余失败发生在自定义结构及语义恢复阶段。**

还发现默认同名导出会被跳过：Raw 日志报告 75 个候选，42 个导出，33 个跳过。
因此不能将输出文件名与所有 pathID 一一关联；本轮没有伪造这种映射。

## 新代码与命令

- `hsr/animestudio.py`：外部进程、受限复制、Map 实际格式验证、精确名称匹配、版本检测、分阶段报告。
- `hsr/native_timeline.py`：已验证布局的 MonoBehaviour 基础头解码、原始载荷保留、按文件作用域的 PPtr 图。
- `hsr native-assets`、`hsr inspect-native`、`hsr native-coverage`。
- 原生引用图与执行图明确分离；没有把引用图当作剧情图。
- 尚不支持 Native Timeline 脚本字段、轨道/Clip 调度和条件的 IR 转换；现有 JSON 控制图补充接口不冒充原生解码器。

## 实际验证

- 正确配置三个既有真实数据目录后，基线 **109 passed**。
- 新增适配器/对象解码/来源冲突测试和一个本机实际导出的测试，全套 **121 passed**。
- 真实主线子任务 100020113 的既有六种选项、调用返回、完成事件、存档恢复、回溯和脱离上游测试均重新通过。
  这些执行仍使用原有公开脚本，并未证明替换为本机 Timeline 后等价。
- 实际 CLI 执行：最小 SR Asset Map、受限批量 Map、定向 Convert/Raw/Dump、inspect-native、native-coverage。
- 设置 `ASTRALOGUE_HSR_NATIVE_SOURCE=data/staging/animestudio` 才执行本机导出测试；无资源则明确 skip。

## 下一步的具体阻碍

1. 需要可审计地恢复自定义序列化布局。当前原始对象载荷存在，但 TypeTree/脚本类型不足；
   先验证 PlaySimpleTalkClip、TimelineAsset、TrackAsset 等实际字段，再实现 IR 转换。
2. 外部 CLI 需要保留序列化文件标识、pathID 与每份导出的精确对应，避免默认同名丢失；
   优先在独立工具副本增加无损导出清单，不能靠文件名猜测。
3. 现有 148 引用尚未在部分扫描中定位，需持久化、分批构建完整资源索引，避免重复复制与扫描。
4. SRAR/SRAM/DBDC/DesignData 尚未有可信结构解析；ENCR Bundle 的成功不能被泛化为所有格式已支持。
5. 原生 Timeline 结构恢复后仍需完成世界事件、条件、并发和合法跨任务推进，再验证完整命名任务。

结论：恢复了真实可追溯的剧情资源样本和原始对象载荷；**新增可执行主线剧情为零**。
本报告不宣称 M5.7 的完整命名主线目标已经达成。
