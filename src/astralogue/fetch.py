"""Opt-in build-time public sample download. Never used by the runtime."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import urllib.request

from astralogue.model import canonical, file_hash, load_json

REPOSITORY = "https://github.com/DimbreathBot/TurnBasedGameData"
REVISION = "74a7b96fba32f00cf495a5c00b0311bd02207aaf"
FILES = ("Config/Level/Mission/TrainVisitor/Act/Act500100101.json", "ExcelOutput/TalkSentenceConfig.json",
         "TextMap/TextMapCHS.json", "TextMap/TextMapMainCHS.json")


def fetch_sample(output: Path, proxy: str | None = None, scope: str = "sample") -> dict:
    if scope not in {"sample", "train-visitors"}: raise ValueError("scope 必须为 sample 或 train-visitors")
    # Explicit user-supplied proxy or the OS environment; no insecure TLS bypass.
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    output.mkdir(parents=True, exist_ok=True)
    files = list(FILES)
    if scope == "train-visitors":
        url = f"https://api.github.com/repos/DimbreathBot/TurnBasedGameData/contents/Config/Level/Mission/TrainVisitor/Act?ref={REVISION}"
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "Astralogue/1.0"}), timeout=45) as response:
            listing = json.load(response)
        if not isinstance(listing, list): raise ValueError("上游目录接口返回格式不正确")
        for item in listing:
            name = item.get("name", "")
            if item.get("type") == "file" and name.endswith(".json") and not name.endswith(".layout.json"):
                if Path(name).name != name or "\\" in name or "/" in name: raise ValueError("上游文件名包含非法路径")
                files.append("Config/Level/Mission/TrainVisitor/Act/" + name)
    files = sorted(set(files))
    manifest_path = output / "source.json"
    progress_path = output / ".download-state.json"
    existing = load_json(manifest_path if manifest_path.exists() else progress_path) if manifest_path.exists() or progress_path.exists() else {}
    if existing and (existing.get("revision") != REVISION or existing.get("repository") != REPOSITORY): raise ValueError("目录已有其他来源或版本；请使用新目录")
    hashes = dict(existing.get("files", {}))

    def fetch(rel: str):
        path = output / rel
        if path.exists():
            actual = file_hash(path)
            if hashes.get(rel) == actual: return rel, actual
            raise ValueError(f"拒绝覆盖未登记或已修改的文件: {path}")
        url = f"https://raw.githubusercontent.com/DimbreathBot/TurnBasedGameData/{REVISION}/{rel}"
        error = None
        for _ in range(3):
            try:
                with opener.open(urllib.request.Request(url, headers={"User-Agent": "Astralogue/1.0"}), timeout=45) as response:
                    data = response.read()
                json.loads(data)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                return rel, file_hash(path)
            except (OSError, ValueError) as ex: error = ex
        raise OSError(f"下载失败 {rel}: {error}；可用 --proxy 指定代理")

    failures = []
    manifest = {"repository": REPOSITORY, "revision": REVISION, "files": hashes, "scope": scope}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in as_completed([pool.submit(fetch, rel) for rel in files]):
            try:
                rel, h = future.result(); hashes[rel] = h
                progress_path.write_text(canonical(manifest), encoding="utf-8")
            except (OSError, ValueError) as ex: failures.append(str(ex))
    if failures: raise OSError(f"{len(failures)} 个文件下载失败，可重试同一命令；首个错误: {failures[0]}")
    (output / "source.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    progress_path.unlink(missing_ok=True)
    return manifest
