# AnimeStudio 独立无损导出扩展

扩展代码属于 Astralogue（MIT）；上游源码保存在忽略的 `.research` 中，固定提交
`68700c7d885a68a444886bd4b7f7827e77789e12`，其 MIT LICENSE 随独立构建保留。
没有复制上游实现进 Astralogue Runtime，也没有自行实现解密器。

需要全局 .NET 10 SDK（本机已安装 10.0.403）以及该提交对应的原始发行包。
prepare.py 使用证书和主机名验证始终开启的 HTTPS；Windows 环境加载公共 ROOT/CA 信任库。
所有下载仅为公开工具源码，游戏资源不会上传。

```powershell
$studio = 'G:\hoyostudio\AnimeStudio-net10-68700c7d885a68a444886bd4b7f7827e77789e12'
.\.venv\Scripts\python.exe tools/animestudio/prepare.py .research/AnimeStudio-lossless $studio --proxy http://127.0.0.1:10808
.\.venv\Scripts\python.exe tools/animestudio/build.py .research/AnimeStudio-lossless $studio

.\.venv\Scripts\astralogue.exe hsr native-assets `
  --executable .research/AnimeStudio-lossless/build/AnimeStudio.CLI.exe `
  --game 'O:\Program Files\miHoYo Launcher\games\Star Rail\Game' `
  --name my-lossless --limit 1 --max-mib 32 `
  --block 015e049ff7fed15690692f2d77bbd997.block `
  --container 'ds104060102[0-9]+[.]playable$' --export Raw --lossless
```

每次 run name 必须唯一。扩展通过环境变量接入，适配器的 `--lossless` 会显式设置它并检查生成的清单；
普通导出会清除此变量。不能给原始 CLI 加一个标志就声称无损。

构建调用全局 SDK 自带的 Roslyn，引用本机 .NET 10 Runtime 和匹配发行包的核心 DLL，
不经过 NuGet、不重新构建或修改原生解密库；提供的 csproj 为源码参考。
常规 MSBuild 在当前沙箱中遇到 Windows SDK 目录访问限制，直接编译路径已实测成功。
发行包根目录和 bin 布局保持原样，修改的是独立副本的 CLI.dll；原发行包保持不变。

无损范围是**过滤命中的 SerializedFile 内全部对象**，不是整个游戏：

- 文件身份为完整解码 SerializedFile 的 SHA256，保留其名称、原始路径、块偏移、Unity 版本、外部引用表。
- 每个 PathID 独立命名 `.dat`，不依赖对象显示名称，因此同名对象不会互相覆盖或跳过。
- 包含对象元数据表、类型、原始字节区间、SHA256、可用 TypeTree、MonoScript 的类名/命名空间/程序集。
- 同时保留整个 SerializedFile，Python 验证对象数、唯一身份、哈希、区间和不重叠性。
- 没有 TypeTree 的自定义载荷依然保留；不能保证未知字段里的所有 PPtr 已被枚举。

恢复与编译（需要相应版本公开台词表与原始控制脚本）：

```powershell
.\.venv\Scripts\astralogue.exe hsr recover-native `
  --manifest data/staging/animestudio/my-lossless/output/lossless `
  --source data/raw/hsr-mainline `
  --control data/staging/animestudio/reference/DS104060102.json
.\.venv\Scripts\astralogue.exe build --source data/staging/native-recovered.ir.json --output data/packs/hsr-native-fragments.storypack
.\.venv\Scripts\astralogue.exe list --pack data/packs/hsr-native-fragments.storypack --search 146010202
```

不要用 `--force` 无提示替换现有包及其存档。当前产物明确标为台词片段，后续控制未解决，不能当作完整 Timeline。
原始控制脚本来自公开快照的 `Story/Discussion/Mission/1040601/DS104060102.json`，不随代码分发。
`recover-native` 接受单个 manifest.json 或包含多个文件子目录的 lossless 根目录。

增量地图：

```powershell
.\.venv\Scripts\astralogue.exe hsr index-native
.\.venv\Scripts\astralogue.exe hsr native-assets `
  --executable "$studio\AnimeStudio.CLI.exe" `
  --game 'O:\Program Files\miHoYo Launcher\games\Star Rail\Game' `
  --name next-map --limit 128 --max-mib 512 --index-database data/staging/native-index.sqlite
.\.venv\Scripts\astralogue.exe hsr index-native
```

旧块通过当前字节 SHA256 核验后复用索引，不重复解密或建立 Asset Map。
改变内容的块会重新进入待处理集合。有错误、警告、超时或未完成的 map run 不进入成功缓存。
