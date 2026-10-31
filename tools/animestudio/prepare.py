"""Prepare an independent, pinned CLI source copy against the installed core DLLs.

Run with Astralogue's Python; no game files are read. HTTPS verification is mandatory.
"""
from pathlib import Path
import argparse
import json
import struct
from xml.sax.saxutils import escape

from astralogue.http import verified_opener

REVISION = "68700c7d885a68a444886bd4b7f7827e77789e12"


def prepare(destination: Path, distribution: Path, proxy: str | None):
    opener = verified_opener(proxy)
    tree = json.load(opener.open(f"https://api.github.com/repos/Escartem/AnimeStudio/git/trees/{REVISION}?recursive=1", timeout=30))
    if tree.get("truncated"): raise ValueError("Truncated source tree")
    for entry in tree["tree"]:
        name = entry["path"]
        if entry["type"] != "blob" or not (name.startswith("AnimeStudio.CLI/") or name == "LICENSE"): continue
        if not name.endswith((".cs", ".csproj", ".config", ".ico")) and name != "LICENSE": continue
        path = destination / name
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(opener.open(f"https://raw.githubusercontent.com/Escartem/AnimeStudio/{REVISION}/{name}", timeout=30).read())
    program = destination / "AnimeStudio.CLI/Program.cs"
    text = program.read_text(encoding="utf-8-sig")
    old = "ExportAssets(o.Output.FullName, exportableAssets, o.GroupAssetsType, o.AssetExportType);"
    new = 'if (Environment.GetEnvironmentVariable("ASTRALOGUE_LOSSLESS") == "1") LosslessWriter.Export(o.Output.FullName, exportableAssets); else ' + old
    if new not in text:
        if text.count(old) != 1: raise ValueError("Upstream export hook changed")
        program.write_text(text.replace(old, new), encoding="utf-8")
    (program.parent / "LosslessWriter.cs").write_bytes(Path(__file__).with_name("LosslessWriter.cs").read_bytes())
    refs = []
    for dll in sorted((distribution / "bin").glob("*.dll")):
        if dll.stem in {"AnimeStudio.CLI", "AnimeStudio.GUI"}: continue
        data = dll.read_bytes()
        pe = struct.unpack_from("<I", data, 0x3c)[0]
        optional = pe + 24
        directory = optional + (112 if struct.unpack_from("<H", data, optional)[0] == 0x20b else 96)
        cli_rva = struct.unpack_from("<I", data, directory + 14 * 8)[0]
        if cli_rva:
            refs.append(f'<Reference Include="{escape(dll.stem)}"><HintPath>{escape(str(dll.resolve()))}</HintPath></Reference>')
    project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><AssemblyName>AnimeStudio.CLI</AssemblyName><Version>1.1.0</Version><GenerateAssemblyInfo>false</GenerateAssemblyInfo></PropertyGroup><ItemGroup>' + ''.join(refs) + '</ItemGroup></Project>'
    (program.parent / "Astralogue.Lossless.csproj").write_text(project, encoding="utf-8")
    (destination / "astralogue-extension.json").write_text(json.dumps({"revision": REVISION, "core_distribution": str(distribution.resolve()), "extension": "astralogue-lossless-v1"}), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--proxy")
    args = parser.parse_args()
    prepare(args.destination, args.distribution, args.proxy)
