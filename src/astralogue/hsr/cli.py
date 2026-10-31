"""M5 build and investigation commands; network/resource imports stay lazy."""
from pathlib import Path
from typing import Annotated
import json
import typer

app = typer.Typer(no_args_is_help=True, help="崩铁主线任务清单、资源调查、编译与覆盖率")
PACK = Path("data/packs/hsr-mainline.storypack")
IR = Path("data/staging/hsr-mainline.ir.json")


@app.command("reconstruct")
def reconstruct_cmd(directory: Annotated[Path, typer.Option(exists=True)], source: Annotated[Path, typer.Option(exists=True)],
                    control: Annotated[Path, typer.Option(exists=True)],
                    output_ir: Annotated[Path, typer.Option()] = Path("data/staging/hsr-reader.ir.json"),
                    output: Annotated[Path, typer.Option()] = Path("data/packs/hsr-reader.storypack"),
                    report: Annotated[Path, typer.Option()] = Path("data/m6-reconstruction.json"),
                    force: Annotated[bool, typer.Option()] = False):
    """从现有无损导出重建阅读投影；不扫描游戏、不改变 Strict。"""
    from astralogue.cli import console, errors
    from astralogue.compiler import compile_story
    from .reconstruction import reconstruct
    with errors():
        if output_ir.exists() and not force: raise ValueError("输出 IR 已存在；使用 --force")
        result, bundle = reconstruct(directory, source, control)
        compiled = compile_story(bundle, output, force=force)
        bundle.write(output_ir); result["pack_id"] = compiled["pack_id"]
        write(report, result)
        console.print(json.dumps({k: v for k, v in result.items() if k != "original_option_routes"}, ensure_ascii=False), markup=False)


@app.command("scan-native")
def scan_native(executable: Annotated[Path, typer.Option(exists=True)],
                game: Annotated[Path, typer.Option(exists=True)],
                staging: Annotated[Path, typer.Option()] = Path("data/staging/animestudio"),
                database: Annotated[Path, typer.Option()] = Path("data/staging/native-index.sqlite"),
                max_batches: Annotated[int, typer.Option(min=0, max=512)] = 4,
                batch_mib: Annotated[int, typer.Option(min=1, max=4096)] = 512,
                inventory_only: Annotated[bool, typer.Option()] = False,
                retry_failed: Annotated[bool, typer.Option()] = False):
    """Inventory first, then resume content-verified scans of base and patch blocks."""
    from astralogue.cli import console, errors
    from .native_index import NativeIndex
    from .native_scan import inventory, scan
    from .local import inspect_install
    with errors():
        index = NativeIndex(database)
        try: initial = inventory(game, index)
        finally: index.close()
        write(staging / "m59-inventory.json", initial); console.print(json.dumps(initial))
        if not inventory_only:
            version = inspect_install(game, samples=0)["game_version"]
            result = scan(game, executable, staging, database, version, max_batches, batch_mib, retry_failed)
            console.print(json.dumps(result))


@app.command("native-targets")
def native_targets(game: Annotated[Path, typer.Option(exists=True)],
                   baseline_ir: Annotated[Path, typer.Option(exists=True)] = IR,
                   database: Annotated[Path, typer.Option()] = Path("data/staging/native-index.sqlite"),
                   cutscene_config: Annotated[Path | None, typer.Option(exists=True)] = None,
                   output: Annotated[Path, typer.Option()] = Path("data/m59-targets.json")):
    """Exact, version-checked original-reference lookup; named candidates stay separate."""
    from astralogue.cli import console, errors
    from .native_scan import target_report
    with errors():
        report = target_report(database, baseline_ir, cutscene_config, game=game); write(output, report)
        console.print(json.dumps({k:v for k,v in report.items() if isinstance(v,(int,bool))}))


@app.command("schedule-native")
def schedule_native(directory: Annotated[Path, typer.Option(exists=True)],
                    source: Annotated[Path, typer.Option(exists=True)],
                    control: Annotated[Path, typer.Option(exists=True)],
                    output: Annotated[Path, typer.Option()] = Path("data/staging/m59-discussion.ir.json"),
                    report: Annotated[Path, typer.Option()] = Path("data/m59-discussion-coverage.json")):
    """Compile native call-boundary scheduling attempts; unverified behavior blocks."""
    from astralogue.cli import console, errors
    from .native_scheduler import build
    with errors():
        evidence, bundle = build(directory, source, control)
        bundle.write(output); write(report, evidence)
        console.print(json.dumps({k:v for k,v in evidence.items() if k in {"timelines", "full_runtime_complete", "structural_parse_errors"}}))


@app.command("recover-native")
def recover_native(manifest: Annotated[Path, typer.Option(exists=True)],
                   source: Annotated[Path, typer.Option(exists=True)],
                   control: Annotated[Path, typer.Option(exists=True)],
                   output: Annotated[Path, typer.Option()] = Path("data/staging/native-recovered.ir.json"),
                   report: Annotated[Path, typer.Option()] = Path("data/m58-native-recovery.json")):
    """Verify lossless export and trace native dialogue clips; unknown continuation blocks."""
    from astralogue.cli import console, errors
    from .native_story import recover, recover_many
    with errors():
        evidence, bundle = (recover_many(manifest, source, control) if manifest.is_dir()
                            else recover(manifest, source, control))
        bundle.write(output); write(report, evidence)
        if "reports" in evidence:
            console.print(f"Verified objects {evidence['objects_verified']}; dialogue clip routes {evidence['verified_dialogue_clips']}; full Timelines complete: 0")
        else:
            console.print(f"Verified objects {evidence['validation']['objects_verified']}; dialogue clip routes {len(evidence['dialogue_routes'])}; unknown structures {len(evidence['errors'])}")


@app.command("index-native")
def index_native(staging: Annotated[Path, typer.Option()] = Path("data/staging/animestudio"),
                 database: Annotated[Path, typer.Option()] = Path("data/staging/native-index.sqlite")):
    """Persist completed maps once, retaining input content identities."""
    from astralogue.cli import console, errors
    from .native_index import NativeIndex
    with errors():
        index = NativeIndex(database)
        try: console.print(json.dumps(index.ingest(staging), ensure_ascii=False))
        finally: index.close()


@app.command("native-coverage")
def native_asset_coverage(staging: Annotated[Path, typer.Option(exists=True)] = Path("data/staging/animestudio"),
                          baseline_ir: Annotated[Path, typer.Option(exists=True)] = IR,
                          output: Annotated[Path, typer.Option()] = Path("data/m57-native-coverage.json")):
    """Report native recovery stages separately from M5 story execution coverage."""
    from astralogue.cli import console, errors
    from .animestudio import native_coverage
    with errors():
        report = native_coverage(staging, baseline_ir); write(output, report)
        console.print(json.dumps({k: v for k, v in report.items() if isinstance(v, (int, str))}, ensure_ascii=False))


@app.command("native-assets")
def native_assets(executable: Annotated[Path, typer.Option(exists=True)],
                  game: Annotated[Path, typer.Option(exists=True)],
                  name: Annotated[str, typer.Option()],
                  staging: Annotated[Path, typer.Option()] = Path("data/staging/animestudio"),
                  limit: Annotated[int, typer.Option(min=1, max=512)] = 16,
                  max_mib: Annotated[int, typer.Option(min=1, max=4096)] = 128,
                  export: Annotated[str | None, typer.Option(help="Raw, Dump or Convert; default builds map")] = None,
                  container: Annotated[list[str] | None, typer.Option()] = None,
                  block: Annotated[list[str] | None, typer.Option(help="Exact block basenames from map")] = None,
                  index_database: Annotated[Path | None, typer.Option(help="Reuse identical indexed blocks for map scans")] = None,
                  lossless: Annotated[bool, typer.Option(help="Requires the independently built lossless CLI extension")] = False):
    """Bounded native asset recovery. Copies blocks before invoking AnimeStudio."""
    from astralogue.cli import console, errors
    from .animestudio import AnimeStudio
    from .local import inspect_install
    with errors():
        version = inspect_install(game, samples=0)["game_version"]
        if version == "unknown": raise ValueError("Game build version unknown")
        root = game / "StarRail_Data/StreamingAssets/Asb/Windows"
        candidates = sorted(root.glob("*.block"))
        if index_database is not None and export is None:
            from .native_index import NativeIndex
            idx = NativeIndex(index_database)
            try:
                idx.ingest(staging); candidates = idx.remaining(candidates)
            finally: idx.close()
        if block:
            wanted = set(block)
            candidates = [p for p in candidates if p.name in wanted]
            if len(candidates) != len(wanted): raise ValueError("Requested block missing")
        selected, size = [], 0
        for path in candidates:
            if len(selected) >= limit: break
            if size + path.stat().st_size > max_mib * 1024**2: continue
            selected.append(path); size += path.stat().st_size
        if not selected:
            console.print("No unprocessed blocks within the requested limits")
            return
        result = AnimeStudio(executable, game, staging, version).run(
            selected, name, export=export, containers=container, lossless=lossless)
        console.print(json.dumps({k: result[k] for k in ("game_version", "asset_count", "types", "returncode", "timed_out") if k in result}, ensure_ascii=False))


@app.command("inspect-native")
def inspect_native_asset(asset: Annotated[Path, typer.Argument(exists=True)],
                         output: Annotated[Path, typer.Option()] = Path("data/native-inspection.json")):
    """Inventory native JSON objects and PPtr references; unknown controls stay blocked."""
    from astralogue.cli import console, errors
    from .animestudio import inspect_native
    with errors():
        result = inspect_native(asset); write(output, result)
        console.print(result["diagnostic"])


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@app.command("inspect-install")
def inspect_install(root: Annotated[Path, typer.Option()] = Path("G:/Program Files"),
                    report: Annotated[Path, typer.Option()] = Path("data/m5-local-resources.json")):
    """受限、只读定位游戏，并检查版本、清单与文件头；不解密。"""
    from astralogue.cli import console, errors
    from .local import investigate
    with errors():
        result = investigate(root)
        for game in result["installations"]:
            if report.resolve().is_relative_to(Path(game["path"]).resolve()): raise ValueError("报告不能写入游戏安装目录")
        if report.resolve().is_relative_to(root.resolve()): raise ValueError("报告不能写入调查目录")
        write(report, result)
        console.print(f"{result['status']}；安装数 {len(result['installations'])}；报告 {report}", markup=False)


@app.command("fetch-mainline")
def fetch_mainline(output: Annotated[Path, typer.Option()] = Path("data/raw/hsr-mainline"),
                   proxy: Annotated[str | None, typer.Option()] = None,
                   metadata_only: Annotated[bool, typer.Option()] = False):
    """显式获取固定公开版本的主线定义及代表性控制资源闭包。"""
    from astralogue.cli import console, errors
    from .download import PublicSnapshot
    with errors():
        result = PublicSnapshot(output, proxy).run(metadata_only)
        console.print(json.dumps(result, ensure_ascii=False), markup=False)
        if result["failures"]: raise typer.Exit(1)


@app.command()
def manifest(source: Annotated[Path, typer.Option(exists=True)], output: Annotated[Path, typer.Option()] = Path("data/mission-manifest.json")):
    """按真实 Type/任务定义分类，不根据 ID 或文件名建立时间线。"""
    from astralogue.cli import console, errors
    from .manifest import create_manifest
    with errors():
        result = create_manifest(source); write(output, result)
        console.print(json.dumps(result["categories"], ensure_ascii=False), markup=False)


@app.command("import-mainline")
def import_mainline(source: Annotated[Path, typer.Option(exists=True)], output: Annotated[Path, typer.Option()] = IR,
                    lang: Annotated[str, typer.Option()] = "CHS",
                    supplement: Annotated[list[Path] | None, typer.Option(help="额外明文资源根目录，冲突时阻塞")] = None,
                    overlay: Annotated[list[Path] | None, typer.Option(help="第三方导入后的 IR，仅作为有来源的补充证据")] = None,
                    native_ir: Annotated[list[Path] | None, typer.Option(help="版本匹配的预编译原生 Timeline IR，未知行为仍阻塞")] = None):
    """链接主线入口、子任务和 Performance 调用；未知 Timeline 不静默跳过。"""
    from astralogue.cli import console, errors
    from astralogue.compiler.hsr_mainline import MainlineCompiler
    from astralogue.model import Bundle, load_json
    from .fusion import supplement_texts
    with errors():
        if any(path.resolve().suffix.lower() != ".json" for path in native_ir or []): raise ValueError("Native IR 必须为 JSON 文件")
        native = [Bundle.from_dict(load_json(path)) for path in native_ir or []]
        compiler = MainlineCompiler(source, lang.upper(), supplement, native); bundle = compiler.compile()
        bundle.metadata["source"] = compiler.manifest["source"]
        for path in overlay or []: supplement_texts(bundle, Bundle.from_dict(load_json(path)), path.name)
        bundle.write(output)
        console.print(f"已导入 {len(bundle.missions)} 个任务/片段、{len(bundle.nodes)} 个节点 → {output}", markup=False)


@app.command("list")
def list_missions(pack: Annotated[Path, typer.Option(exists=True)] = PACK,
                  category: Annotated[str, typer.Option()] = "TRAILBLAZE",
                  search: Annotated[str, typer.Option()] = "",
                  status: Annotated[str | None, typer.Option()] = None,
                  json_output: Annotated[bool, typer.Option()] = False):
    """主线任务和演出片段分开列出；片段不计入任务完成率。"""
    from astralogue.cli import console, errors
    from astralogue.storypack import StoryPack
    from rich.table import Table
    with errors(), StoryPack(pack) as sp:
        items = sp.missions(search=search, status=status, category=None if category == "ALL" else category)
        if json_output: typer.echo(json.dumps(items, ensure_ascii=False, indent=2)); return
        table = Table("ID", "名称", "分类", "静态完整性")
        for item in items: table.add_row(item["id"], item["name"], item["category"], item["status"])
        console.print(table)


@app.command()
def play(pack: Annotated[Path, typer.Option(exists=True)] = PACK,
         mission: Annotated[str | None, typer.Option()] = None,
         category: Annotated[str, typer.Option()] = "TRAILBLAZE",
         search: Annotated[str, typer.Option()] = ""):
    """复用现有播放器；默认主线列表，可明确选择演出片段。"""
    from astralogue.cli import play as player
    while True:
        result = player(mission=mission, pack=pack, lang="CHS", search=search, status="ALL", category=category,
                        save_file=Path("saves/mainline/latest.save.json"), autosave=Path("saves/mainline/autosave.save.json"))
        if result != "ended": return
        mission = None; search = ""


@app.command()
def resume(pack: Annotated[Path, typer.Option(exists=True)] = PACK,
           save_file: Annotated[Path, typer.Option(exists=True)] = Path("saves/mainline/autosave.save.json")):
    """恢复主线存档；不会覆盖列车访客阶段的存档。"""
    from astralogue.cli import resume as resume_player
    if resume_player(save_file=save_file, pack=pack, autosave=Path("saves/mainline/autosave.save.json")) == "ended":
        play(pack=pack)


@app.command()
def coverage(pack: Annotated[Path, typer.Option(exists=True)] = PACK,
             report: Annotated[Path, typer.Option()] = Path("data/mainline-coverage.json"),
             max_states: Annotated[int, typer.Option(min=1)] = 1000,
             max_steps: Annotated[int, typer.Option(min=1)] = 10000):
    """分别报告资源、文本、控制图和实际 Runtime 验证的分母。"""
    from astralogue.cli import console, errors
    from astralogue.storypack import StoryPack
    from .report import coverage as analyze
    with errors(), StoryPack(pack) as sp:
        result = analyze(sp, max_states, max_steps); write(report, result)
        console.print(json.dumps(result["summary"], ensure_ascii=False), markup=False)
        console.print(f"完整主线覆盖率报告：{report}", markup=False)
