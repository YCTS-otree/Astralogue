// Astralogue extension for AnimeStudio CLI. MIT; upstream sources remain separate.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using AnimeStudio;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AnimeStudio.CLI
{
    internal static class LosslessWriter
    {
        static string Hash(byte[] data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();
        static void Json(string path, object value) => File.WriteAllText(path, JsonConvert.SerializeObject(value, Formatting.Indented));
        public static void Export(string output, List<AssetItem> selected)
        {
            var root = Path.Combine(output, "lossless"); Directory.CreateDirectory(root);
            foreach (var file in selected.Select(x => x.SourceFile).Distinct())
            {
                var previous = file.reader.Position;
                file.reader.Position = 0;
                var bytes = file.reader.ReadBytes(checked((int)file.header.m_FileSize));
                file.reader.Position = previous;
                if (bytes.LongLength != file.header.m_FileSize) throw new IOException("Truncated SerializedFile");
                var id = Hash(bytes); var dir = Path.Combine(root, id);
                Directory.CreateDirectory(dir);
                File.WriteAllBytes(Path.Combine(dir, "serialized-file.dat"), bytes);
                var objects = new List<object>();
                foreach (var info in file.m_Objects)
                {
                    var reader = new ObjectReader(file.reader, file, info, Studio.Game);
                    previous = file.reader.Position; reader.Reset();
                    var raw = reader.ReadBytes(checked((int)info.byteSize));
                    file.reader.Position = previous;
                    if (raw.Length != info.byteSize) throw new IOException("Truncated object");
                    var filename = info.m_PathID.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".dat";
                    File.WriteAllBytes(Path.Combine(dir, filename), raw);
                    var obj = file.Objects.FirstOrDefault(x => x.m_PathID == info.m_PathID);
                    object structured = null; string error = null;
                    try { if (obj != null) structured = obj.ToType(); }
                    catch (Exception ex) { error = ex.GetType().Name + ": " + ex.Message; }
                    if (structured != null) Json(Path.Combine(dir, info.m_PathID + ".json"), structured);
                    object script = null;
                    if (obj is MonoScript ms)
                        script = new { ms.m_ClassName, ms.m_Namespace, ms.m_AssemblyName };
                    object bundle = null;
                    if (obj is AssetBundle ab)
                        bundle = new {
                            preload = ab.m_PreloadTable.Select(p => new { p.m_FileID, p.m_PathID }).ToArray(),
                            containers = ab.m_Container.Select(p => new {
                                name = p.Key, p.Value.preloadIndex, p.Value.preloadSize,
                                asset = new { p.Value.asset.m_FileID, p.Value.asset.m_PathID }
                            }).ToArray()
                        };
                    objects.Add(new {
                        path_id = info.m_PathID, type_id = info.classID,
                        type = ((ClassIDType)info.classID).ToString(), name = obj?.Name,
                        byte_start = info.byteStart, byte_size = info.byteSize,
                        raw = filename, sha256 = Hash(raw), structured_error = error,
                        script, asset_bundle = bundle, type_tree = info.serializedType?.m_Type,
                        structured = structured,
                        containers = selected.Where(x => x.SourceFile == file && x.m_PathID == info.m_PathID).Select(x => x.Container).Distinct().ToArray()
                    });
                }
                Json(Path.Combine(dir, "manifest.json"), new {
                    format = "astralogue-lossless-v1", serialized_file_id = id,
                    file_name = file.fileName, full_name = file.fullName,
                    original_path = file.originalPath, bundle_offset = file.offset,
                    unity_version = file.unityVersion, serialized_version = file.header.m_Version.ToString(),
                    serialized_file_bytes = bytes.Length, object_count = file.m_Objects.Count,
                    scope = "all objects in serialized files selected by container filter",
                    externals = file.m_Externals, objects
                });
                Console.WriteLine($"[Astralogue] Lossless {file.fileName}: {objects.Count} objects, identity {id}");
            }
        }
    }
}
