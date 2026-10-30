"""Read-only, bounded installation inventory. Never decrypts resource blocks."""
from __future__ import annotations

from collections import Counter
import configparser
import json
import os
from pathlib import Path


def locate(root: Path, max_depth: int = 6) -> list[Path]:
    found = []
    if not root.is_dir(): return found
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        depth = len(base.relative_to(root).parts)
        if "StarRail.exe" in files:
            found.append(base); dirs[:] = []; continue
        dirs[:] = [d for d in dirs if any(s in d.casefold() for s in ("mihoyo", "hoyo", "star", "rail", "games", "game")) and not (base / d).is_symlink()]
        if depth >= max_depth: dirs[:] = []
    return found


def registry_locations() -> list[Path]:
    if os.name != "nt": return []
    import winreg
    found = []
    for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        for suffix in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]:
            try:
                with winreg.OpenKey(hive, suffix) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as item:
                                name = winreg.QueryValueEx(item, "DisplayName")[0]
                                if "星穹" in name or "star rail" in name.casefold():
                                    path = winreg.QueryValueEx(item, "InstallLocation")[0]
                                    if path: found.append(Path(path))
                        except OSError: continue
            except OSError: continue
    return list(dict.fromkeys(found))


def inspect_install(game: Path, samples: int = 16) -> dict:
    if not (game / "StarRail.exe").is_file(): raise ValueError("需要包含 StarRail.exe 的游戏目录")
    cfg = configparser.ConfigParser(); cfg.read(game / "config.ini", encoding="utf-8-sig")
    version = next((cfg.get(s, "game_version") for s in cfg.sections() if cfg.has_option(s, "game_version")), "unknown")
    result = {"path": str(game.resolve()), "game_version": version, "read_only": True,
              "parser": "hsr-install-inventory-v1", "categories": {}, "limitations": [], "manifest": {}}
    manifest = game / "pkg_version"
    if manifest.is_file():
        count, suffixes, relevant = 0, Counter(), []
        with manifest.open(encoding="utf-8-sig") as f:
            for line in f:
                try: row = json.loads(line)
                except ValueError: continue
                name = row.get("remoteName", "")
                count += 1; suffixes[Path(name).suffix] += 1
                if any(x in name for x in ["DesignData", "RawRes", "Timeline"]): relevant.append(name)
        result["manifest"] = {"file": "pkg_version", "entries": count, "suffixes": dict(suffixes), "relevant_paths": relevant}
    for suffix in ["StreamingAssets/Asb/Windows", "Persistent/Asb/Windows", "StreamingAssets/DesignData/Windows", "Persistent/DesignData/Windows", "StreamingAssets/RawRes/Windows", "Persistent/RawRes/Windows"]:
        root = game / "StarRail_Data" / suffix
        if not root.is_dir(): continue
        files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
        headers = []
        candidates = [p for p in files if p.suffix in {".block", ".dat", ".bytes"}][:samples]
        for p in candidates:
            with p.open("rb") as f: header = f.read(16)
            magic = next((s for s in ["ENCR", "UnityFS", "SRMI", "SRAR", "SRAM", "DBDC"] if header.startswith(s.encode())), "unknown")
            headers.append({"path": p.relative_to(game).as_posix(), "size": p.stat().st_size, "header_hex": header.hex(), "format": magic})
        result["categories"][suffix] = {"files": len(files), "sampled_headers": headers}
    result["limitations"] = ["ENCR blocks are not opened beyond their header and are not decrypted.",
                             "SRAR/SRAM/DBDC binary records have no audited semantic parser here.",
                             "An installation inventory is not evidence of resolved Timeline dialogue or control flow."]
    return result


def investigate(root: Path) -> dict:
    candidates = [root]
    games = locate(root)
    if not games:
        candidates += registry_locations()
        for p in candidates[1:]: games.extend(locate(p))
    return {"searched_roots": [str(p) for p in candidates], "installations": [inspect_install(p) for p in dict.fromkeys(games)],
            "status": "FOUND" if games else "NOT_FOUND"}
