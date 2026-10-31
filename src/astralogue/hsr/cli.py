"""M5 build and investigation commands; network/resource imports stay lazy."""
from pathlib import Path
from typing import Annotated
import json
import typer

app = typer.Typer(no_args_is_help=True, help="崩铁主线任务清单、资源调查、编译与覆盖率")
PACK = Path("data/packs/hsr-mainline.storypack")
IR = Path("data/staging/hsr-mainline.ir.json")


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
                  block: Annotated[list[str] | None, typer.Option(help="Exact block basenames from map")] = None):
    """Bounded native asset recovery. Copies blocks before invoking AnimeStudio."""
    from astralogue.cli import console, errors
    from .animestudio import AnimeStudio
    from .local import inspect_install
    with errors():
        version = inspect_install(game, samples=0)["game_version"]
        if version == "unknown": raise ValueError("Game build version unknown")
        root = game / "StarRail_Data/StreamingAssets/Asb/Windows"
        candidates = sorted(root.glob("*.block"))
        if block:
            wanted = set(block)
            candidates = [p for p in candidates if p.name in wanted]
            if len(candidates) != len(wanted): raise ValueError("Requested block missing")
        selected, size = [], 0
        for path in candidates:
            if len(selected) >= limit: break
            if size + path.stat().st_size > max_mib * 1024**2: continue
            selected.append(path); size += path.stat().st_size
        result = AnimeStudio(executable, game, staging, version).run(
            selected, name, export=export, containers=container)
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
                    overlay: Annotated[list[Path] | None, typer.Option(help="第三方导入后的 IR，仅作为有来源的补充证据")] = None):
    """链接主线入口、子任务和 Performance 调用；未知 Timeline 不静默跳过。"""
    from astralogue.cli import console, errors
    from astralogue.compiler.hsr_mainline import MainlineCompiler
    from astralogue.model import Bundle, load_json
    from .fusion import supplement_texts
    with errors():
        compiler = MainlineCompiler(source, lang.upper(), supplement); bundle = compiler.compile()
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
