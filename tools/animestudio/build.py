"""Compile the pinned CLI extension with the installed .NET 10 SDK compiler.

Direct Roslyn compilation avoids NuGet restore and Windows SDK discovery. Core
libraries/native dependencies are reused from the matching, user-supplied build.
"""
from pathlib import Path
import argparse
import json
import shutil
import struct
import subprocess


def managed(path: Path) -> bool:
    data = path.read_bytes()
    try:
        if data[:2] != b"MZ": return False
        pe = struct.unpack_from("<I", data, 0x3c)[0]
        if data[pe:pe+4] != b"PE\x00\x00": return False
        optional = pe + 24
        directory = optional + (112 if struct.unpack_from("<H", data, optional)[0] == 0x20b else 96)
        return bool(struct.unpack_from("<I", data, directory + 14 * 8)[0])
    except struct.error: return False


def build(root: Path, distribution: Path):
    sdks = subprocess.check_output(["dotnet", "--list-sdks"], text=True)
    sdk = next(line for line in reversed(sdks.splitlines()) if line.startswith("10."))
    version, location = sdk.split(" [", 1)
    compiler = Path(location.rstrip("]")) / version / "Roslyn/bincore/csc.dll"
    runtimes = subprocess.check_output(["dotnet", "--list-runtimes"], text=True)
    runtime = next(line for line in reversed(runtimes.splitlines()) if line.startswith("Microsoft.NETCore.App 10."))
    _, version, location = runtime.split(" ", 2)
    runtime_path = Path(location.strip("[]")) / version
    output = root / "build"; output.mkdir(exist_ok=True)
    references = [p for base in (runtime_path, distribution / "bin") for p in sorted(base.glob("*.dll"))
                  if p.stem not in {"AnimeStudio.CLI", "AnimeStudio.GUI"} and managed(p)]
    args = ["-nologo", "-target:exe", "-nostdlib+", "-langversion:preview",
            '-out:"' + str((output / "AnimeStudio.CLI.dll").resolve()) + '"']
    args += ['-r:"' + str(p.resolve()) + '"' for p in references]
    args += ['"' + str(p.resolve()) + '"' for p in sorted((root / "AnimeStudio.CLI").rglob("*.cs"))
             if not any(part in {"obj", "bin"} for part in p.parts)]
    rsp = root / "compile.rsp"; rsp.write_text("\n".join(args), encoding="utf-8")
    subprocess.run(["dotnet", str(compiler), "@" + str(rsp.resolve())], check=True)
    binary = output / "bin"; binary.mkdir(exist_ok=True)
    for p in (distribution / "bin").iterdir():
        if p.is_file() and (p.suffix.lower() == ".dll" or p.name.endswith((".runtimeconfig.json", ".deps.json", ".config"))) and p.name != "AnimeStudio.CLI.dll":
            shutil.copyfile(p, binary / p.name)
    shutil.copyfile(output / "AnimeStudio.CLI.dll", binary / "AnimeStudio.CLI.dll")
    shutil.copyfile(distribution / "AnimeStudio.CLI.exe", output / "AnimeStudio.CLI.exe")
    shutil.copyfile(root / "LICENSE", output / "LICENSE")
    (output / "extension-build.json").write_text(json.dumps({"compiler": str(compiler), "runtime": version,
        "extension": "astralogue-lossless-v1"}), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("distribution", type=Path)
    args = parser.parse_args()
    build(args.root, args.distribution)
