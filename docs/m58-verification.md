# M5.8 实测报告（2026-10-31，Astralogue 1.3.0）

本轮实际恢复了自定义字段和原生引用链，不再只有四个基础字段。
但结果属于 15 条额外 Discussion 的原生台词片段，原有 148 个缺失引用仍然单独统计。
完整命名主线任务和完整原生 Timeline 的 Runtime 完成数仍为零。

## 1. 无损导出

在独立 `.research/AnimeStudio-lossless` 源码副本加入 `LosslessWriter`。
固定上游提交 `68700c7d885a68a444886bd4b7f7827e77789e12`，复用用户提供的相同版本核心/原生 DLL。
全局安装微软官方 .NET SDK 10.0.403（安装包通过官方发布元数据 SHA512 校验，安装返回 0）。
使用 SDK 10 Roslyn 成功构建；普通 MSBuild 的 Windows SDK 目录访问限制没有妨碍这条离线编译路线。
上游工具版本独立于本项目，扩展格式标识 `astralogue-lossless-v1`；没有修改原始发行包或游戏客户端。

游戏为 O 盘安装的 4.6.0。资源块只读取并复制到项目 staging；工具只看到复制品。
仅导出过滤器命中的 SerializedFile 内全部对象，没有导出无关的模型、音频和贴图全集。

| 核验项目 | 实际结果 |
|---|---:|
| 第一个容器对象 | 76/76（旧 Raw 导出仅 42 个文件） |
| 样本 SerializedFile | 15 |
| 这些文件全部对象 | 1,010/1,010 |
| 原始 SerializedFile SHA256、对象 SHA256、逐对象字节区间及数量 | 全部通过 |
| 基础头的非空对象引用 | 657 个，全部定位 |
| AssetBundle 容器/预加载引用 | 1,025 个，全部定位 |
| TypeTree 实际可用 | 0 |

每个对象以 PathID 命名，并与完整 SerializedFile SHA256 共同组成身份。
相同显示名的两个 PlaySimpleTalkClip 均保留，独立字节及哈希可核验。
清单还包含 SerializedFile 名称、来源路径、块偏移、对象类型、字节范围、外部引用表及 MonoScript 元数据。
Python 另从 AssetBundle 原始字节独立读取容器和预加载引用，与导出清单逐项比对，并检查预加载范围。
适配器 run.json 记录原始块哈希、游戏清单哈希、CLI/core DLL 哈希。

**引用完整性边界：**已解析引用均检查目标存在，但未知载荷中潜在的 PPtr 尚未全部枚举。
整个原始文件和所有对象字节保留，不能把“已知引用无缺失”解释成“所有字段已理解”。

## 2. 恢复字段与真实语义证据

已找到的 MonoScript 明确指向：
`RPGTools.Timeline.PlaySimpleTalkClip` / `Assembly-CSharp.dll`。
所有样本的 Unity 标识为 `2019.4.34f1`，附带游戏自定义后缀；解析器按已验证版本限制输入。
本机 global-metadata.dat 文件头为 MHY，未将其误当成普通明文 IL2CPP 元数据。

- **26 个 PlaySimpleTalkClip：**载荷相对偏移 +8（本例文件绝对偏移 60）恢复 TalkSentenceID，
  26 个不同 ID 均在固定公开快照的 TalkSentenceConfig 中存在，原文与角色名通过其文本 Hash 读取。
  未验证的前缀、浮点参数、绑定字符串等不赋予猜测含义，保留原始字节。
- **15 个 TimelineAsset：**恢复绑定对象、根轨道数组、固定时长字段及 MarkerTrack 引用；
  一个可能的编辑器浮点字段只标记 candidate，不用于执行。
- **93 个 Track 对象：**按观察到的版本 3 布局恢复父/子引用及可解析的 TimelineClip；
  Clip 的版本 1 布局恢复 start、clipIn、duration、timeScale、asset、parent、混合与外推等字段。
  不支持的布局停止解析；前缀、尾部不明字段继续保留。
- 已解析字段的 PPtr 共 730 个，目标均存在；与上述 657 个基础引用有重叠，不将两者相加当作唯一引用数。

Clip 字段顺序参照公开 Unity Timeline 序列化定义，并通过真实对象的 parent 回指、asset 类型、
数组边界和多样本交叉验证。没有用 PathID 或文件顺序代替执行时间。
参考源码：<https://github.com/needle-mirror/com.unity.timeline/blob/master/Runtime/TimelineClip.cs>。
本项目不复制该实现，二进制读取器为独立实现。

## 3. 一条可追溯样本链

公开控制脚本：`Story/Discussion/Mission/1040601/DS104060102.json`，
快照 `74a7b96fba32f00cf495a5c00b0311bd02207aaf`。
其中明确的 PlayTimeline 引用：`Story/Discussion/Mission/1040601/DS10406010201.playable`。

本机容器位于 `015e049ff7fed15690692f2d77bbd997.block`，精确匹配 assets/asbres 前缀下的相同逻辑路径。
AssetBundle 容器项的实际 asset PPtr 明确指向下述 TimelineAsset，未以“文件中唯一根对象”代替引用。
恢复的实际引用路径：

```text
TimelineAsset 401379373029653754
  → GroupTrack Common -8567812491034083042
    → GroupTrack SimpleTalk 5226496953748120167
      → PlaySimpleTalkTrack -3135415360637932350
        → Clip asset 8431424154225044298 → TalkSentenceID 146010202（start 5s，duration 10s）
        → Clip asset 3625185516905268760 → TalkSentenceID 146010203（start 16s，duration 10s）
```

该 Track 的实际数组时间顺序是 `[5,15,16,26,0]`。
15s、26s 的 Clip 是 PauseMarkerClip；0s 是 SimpleTalkMarkerClip。
因此数组索引不能当作剧情顺序。暂停标记、启动标记和其他并行轨道的语义尚未证明，未跳过后宣称成功。

所有 15 条样本共建立 **26 条 控制脚本→Timeline→Track→Clip→台词→IR 的路径**。
IR 的可执行入口是明确标注的单个台词 Clip 片段，后接 unknown 控制节点；
不是从游戏任务入口执行完整 Timeline，也没有编造片段之间的连接。

## 4. StoryPack 与 Runtime

- `data/packs/hsr-native-fragments.storypack`：26 个 PARTIAL 片段、52 个节点、26 条边。
- 原文、角色名、已恢复时间、来源链以及去重后的原始 SerializedFile/清单证据随包保存。
- 实际遍历全部 26 个片段：26 次 DialogueEvent，随后均为 BlockedEvent。
- CLI 实际播放返回 0，并显示 NativeTimelineContinuation 阻塞，没有显示完整剧情结束。
- 测试将自身复制的原始资源和公开数据删除，再关闭/重开数据库、保存/恢复并离线启动新 CLI 进程。
- 片段无选项，现有回溯接口只回溯选择；不伪造可回溯历史。既有六分支测试继续通过。
- Runtime 未增加游戏专用指令，不依赖 AnimeStudio、.NET 或本机游戏资源。
- 原主线 StoryPack 未覆盖，Schema 和存档版本保持 1；新包身份变化仍触发旧存档兼容性检查。

## 5. 覆盖率分母

| 阶段 | 原有 148 引用 | 额外 15 条 Discussion 样本 |
|---|---:|---:|
| 定位 | 0 | 15 |
| 无损导出 SerializedFile | 0 | 15 |
| 根对象/台词轨引用链 | 0 | 15 |
| 台词 Clip 字段及 IR 路径 | 0 | 26 个 Clip |
| Runtime 播放台词 Clip | 0 | 26 个 Clip |
| 整条 Timeline 完整执行 | 0 | 0 |
| 完整命名主线任务完成 | 0 | 0 |

持久化 SQLite 索引从 811 增至 **890 个块、450,246 个 Asset Map 条目**。
新增扫描仅处理 79 个未索引块。旧块按当前 SHA256 验证后复用，不再次解密和构建 Map。
重复 index-native 实测 new_runs=0；变更内容重新进入待处理集合有测试覆盖。
本地资源索引仍未穷尽，未找到不代表不存在。

## 6. TLS 与自动测试

- 公共源码下载和 PublicSnapshot 使用默认 CERT_REQUIRED、check_hostname=True。
- Windows 上补充读取公共 ROOT/CA 证书库，直连和本机代理均实际成功，不关闭证书验证。
- 新增 TLS 验证保持开启、原生布局拒绝、哈希/数量破坏检测、持久索引、真实字段/引用和独立 CLI 测试。
- 原有 121 项基线重新运行通过；增加 9 项后完整测试实测 **130 passed**，没有 skip。
- 首次新增测试错误地要求无选项片段支持“回溯选择”，按现有接口修正测试预期，没有改变 Runtime 语义。

## 7. 尚未恢复

347 个 Track/Group 对象未完整通过当前布局解析（按对象计）：GroupTrack 60、AnimatorControlTrack 45、
EmoDiscussionTimelineTrack 45、EmoDiscussionMouthTrack 45、CharacterLookAtTrack 45、CharacterStorySteerTrack 45、
CameraCompositionTrack 15、SwitchCharacterAnchorTrack 15、StoryPropTriggerAnimStateTrack 15、
StoryPropAnimatorParamTrack 15、ActorArrangementTrack 2。
其原始数据完整保留，不能当作纯视觉动作静默删除。

暂停/启动标记、角色/物件状态、条件选择、并发同步仍缺少可信语义；未恢复真实选项，未打通完整命名主线。
SRAR/SRAM/DBDC/DesignData 的普适解析不在本轮已验证结果中。
