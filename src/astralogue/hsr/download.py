"""Explicit, resumable download of a public pinned mainline research corpus."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import urllib.request

from astralogue.fetch import REPOSITORY, REVISION
from astralogue.hsr.manifest import create_manifest
from astralogue.model import canonical, file_hash, load_json

TABLES = ["MainMission", "MainMissionType", "MissionChapterConfig", "SubMission", "MissionSubType",
          "PerformanceA", "PerformanceC", "PerformanceD", "PerformanceDS", "PerformanceE", "PerformanceVideo", "PerformanceSubMissionLink"]


class PublicSnapshot:
    def __init__(self, root: Path, proxy: str | None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.opener = urllib.request.build_opener(*([urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []))
        self.index = {}
        self.failures = []

    def request(self, url):
        error = None
        for _ in range(3):
            try:
                with self.opener.open(urllib.request.Request(url, headers={"User-Agent": "Astralogue/1.1"}), timeout=40) as response:
                    return response.read()
            except OSError as ex: error = ex
        raise OSError(f"公开数据获取失败: {url}: {error}")

    def api(self, path):
        return json.loads(self.request("https://api.github.com/repos/DimbreathBot/TurnBasedGameData/" + path))

    def catalog(self):
        target = self.root / "resource-index.json"
        if target.is_file():
            old = load_json(target)
            if old.get("revision") != REVISION: raise ValueError("资源索引版本不一致")
            if old.get("complete") and old.get("includes_tables"):
                self.index = old["files"]; return
        roots = {x["name"]: x for x in self.api("contents/?ref=" + REVISION)}
        levels = {x["name"]: x for x in self.api("contents/Config/Level?ref=" + REVISION)}
        for prefix, sha in [("Config/Level/Mission", levels["Mission"]["sha"]), ("Story", roots["Story"]["sha"]),
                            ("ExcelOutput", roots["ExcelOutput"]["sha"]), ("TextMap", roots["TextMap"]["sha"])]:
            tree = self.api("git/trees/" + sha + "?recursive=1")
            if tree.get("truncated"): raise ValueError(f"上游目录被截断，拒绝宣称完整索引: {prefix}")
            for x in tree["tree"]:
                if x["type"] == "blob": self.index[prefix + "/" + x["path"]] = {"sha": x["sha"], "size": x.get("size")}
        target.write_text(canonical({"revision": REVISION, "complete": True, "includes_tables": True,
            "scopes": ["Config/Level/Mission", "Story", "ExcelOutput", "TextMap"], "files": self.index}), encoding="utf-8")

    def fetch(self, logical):
        from astralogue.hsr.sources import Sources
        path = Sources([self.root]).path(self.root.resolve(), logical)
        expected = self.index.get(logical)
        if expected is None: return logical, "not in pinned catalog"
        if path.exists(): data = path.read_bytes()
        else: data = self.request(f"https://raw.githubusercontent.com/DimbreathBot/TurnBasedGameData/{REVISION}/{logical}")
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != expected["sha"]: return logical, "Git blob hash mismatch; not overwritten"
        json.loads(data)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".downloading"); temp.write_bytes(data); temp.replace(path)
        return logical, None

    def batch(self, paths):
        with ThreadPoolExecutor(max_workers=12) as pool:
            for future in as_completed([pool.submit(self.fetch, p) for p in sorted(set(paths))]):
                try:
                    logical, error = future.result()
                    if error: self.failures.append({"path": logical, "reason": error})
                except (OSError, ValueError) as ex: self.failures.append({"reason": str(ex)})

    def run(self, metadata_only=False):
        self.catalog()
        source_path = self.root / "source.json"
        if source_path.exists():
            source = load_json(source_path)
            if source.get("revision") != REVISION: raise ValueError("目录来源版本冲突")
        source_path.write_text(canonical({"repository": REPOSITORY, "revision": REVISION, "game_version": "4.6.0",
                                         "scope": "mainline metadata plus explicitly selected control closure"}), encoding="utf-8")
        self.batch(["ExcelOutput/" + x + ".json" for x in TABLES] + ["TextMap/TextMapCHS.json", "TextMap/TextMapMainCHS.json"])
        missions = load_json(self.root / "ExcelOutput/MainMission.json")
        if isinstance(missions, dict): missions = list(missions.values())
        main = [m for m in missions if m.get("Type") == "Main"]
        paths = []
        for row in main:
            for ext in [".json", ".partial.json"]:
                rel = f"Config/Level/Mission/{row['MainMissionID']}/MissionInfo_{row['MainMissionID']}" + ext
                if rel in self.index: paths.append(rel)
        self.batch(paths)
        manifest = create_manifest(self.root)
        if not metadata_only:
            chapters = load_json(self.root / "ExcelOutput/MissionChapterConfig.json")
            chapters = chapters.values() if isinstance(chapters, dict) else chapters
            main_chapters = {m.get("ChapterID") for m in main}
            ranked = [c for c in chapters if c.get("ID") in main_chapters and "ChapterDisplayPriority" in c]
            first = min(ranked, key=lambda c: c["ChapterDisplayPriority"])["ID"] if ranked else None
            selected = [m for m in manifest["missions"] if m["category"] == "TRAILBLAZE" and m["submissions"] and
                        ((len(m["submissions"]) <= 10 and all(s["finish_type"] == "Talk" for s in m["submissions"])) or m["chapter"] == first)]
            # Display rank is only an acquisition sampling strategy, never an execution edge.
            chosen = [s["resource"] for m in selected for s in m["submissions"] if s["resource"]]
            self.batch(chosen)
            from astralogue.hsr.sources import Sources, performance_index
            from astralogue.compiler.hsr_mainline import walk
            performance = performance_index(Sources([self.root]))
            seen = set(chosen)
            for _ in range(8):
                fresh = set()
                for logical in seen:
                    path = self.root / logical
                    if not path.is_file(): continue
                    for task in walk(load_json(path)):
                        if task.get("$type") == "RPG.GameCore.TriggerPerformance":
                            fresh.update(performance.get((task.get("PerformanceType"), str(task.get("PerformanceID"))), set()))
                fresh -= seen
                if not fresh: break
                self.batch(fresh); seen.update(fresh)
            (self.root / "acquisition.json").write_text(canonical({"strategy": "Talk-only missions <=10 goals plus first displayed chapter; reference closure <=8",
                "missions": [m["id"] for m in selected], "requested_control_resources": sorted(seen)}), encoding="utf-8")
        result = {"revision": REVISION, "identified_trailblaze": len(main), "failures": self.failures, "metadata_only": metadata_only}
        (self.root / "acquisition-report.json").write_text(canonical(result), encoding="utf-8")
        return result
