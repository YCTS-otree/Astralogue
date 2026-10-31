"""Traditional terminal UI. All execution decisions belong to Runtime."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from astralogue import __version__
from astralogue.model import Bundle, canonical, load_json
from astralogue.runtime import BlockedEvent, ChoiceEvent, DiagnosticEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack

app = typer.Typer(no_args_is_help=True, help="Astralogue 星轨叙事引擎：离线剧情编译与播放")
console = Console(highlight=False)
DEFAULT_PACK = Path("data/packs/astralogue.storypack")
DEFAULT_IR = Path("data/staging/story.ir.json")
DEFAULT_SAVE = Path("saves/latest.save.json")


@contextmanager
def errors():
    try: yield
    except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as ex:
        console.print(f"错误：{ex}", style="red", markup=False)
        raise typer.Exit(2) from ex


def langs(value: str) -> list[str]:
    result = list(dict.fromkeys(x.strip().upper() for x in value.split(",") if x.strip()))
    if not result or any(not x.isalpha() for x in result): raise ValueError("语言参数示例：CHS 或 CHS,EN")
    return result


@app.command()
def version():
    """显示引擎版本。"""
    console.print(__version__)


@app.command()
def init():
    """创建本地工作目录并显示真实数据导入指引。"""
    with errors():
        for d in ["data/staging", "data/packs", "data/raw", "saves"]: Path(d).mkdir(parents=True, exist_ok=True)
        console.print("工作目录已就绪。以下两种方式任选其一：", markup=False)
        console.print("1. astralogue fetch-sample   # 显式联网下载固定版本的真实分支样本", markup=False)
        console.print("2. astralogue import --source <本地 TurnBasedGameData 目录>", markup=False)
        console.print("随后运行 astralogue build、astralogue validate、astralogue play。", markup=False)


@app.command("fetch-sample")
def fetch_sample(output: Annotated[Path, typer.Option(help="下载目录；不覆盖已有文件")] = Path("data/raw/hsr-sample"),
                 proxy: Annotated[str | None, typer.Option(help="显式 HTTP 代理，例如 http://127.0.0.1:10808")] = None,
                 scope: Annotated[str, typer.Option(help="sample 或 train-visitors（完整列车访客 Act 集合）")] = "sample"):
    """显式下载公开仓库的真实列车访客分支；play/resume 从不联网。"""
    with errors():
        from astralogue.fetch import fetch_sample as fetch
        manifest = fetch(output, proxy, scope)
        console.print(f"真实样本已获取：{manifest['revision']}", markup=False)
        console.print(f'astralogue import --source "{output}"', markup=False)


@app.command("import")
def import_cmd(source: Annotated[Path, typer.Option(exists=True, help="本地原始目录、JSON/JSONL 或第三方 SQLite")],
               output: Annotated[Path, typer.Option()] = DEFAULT_IR,
               lang: Annotated[str, typer.Option(help="逗号分隔的语言代码")] = "CHS",
               adapter: Annotated[str, typer.Option()] = "auto",
               pattern: Annotated[str | None, typer.Option(help="原始数据相对路径 glob；未指定时自动发现")] = None):
    """解析数据源，写出独立的规范 IR（不会启动播放器）。"""
    with errors():
        from astralogue.adapters import import_source
        b = import_source(source, langs(lang), adapter, pattern)
        b.write(output)
        console.print(f"已导入 {len(b.missions)} 个会话、{len(b.nodes)} 个节点 → {output}", markup=False)


@app.command()
def build(source: Annotated[Path, typer.Option(exists=True)] = DEFAULT_IR,
          output: Annotated[Path, typer.Option()] = DEFAULT_PACK,
          lang: Annotated[str, typer.Option()] = "CHS",
          force: Annotated[bool, typer.Option(help="明确允许替换现有开发数据包")] = False):
    """只从规范 IR 构建 StoryPack；所有原始结构和已解析文本随包保存。"""
    with errors():
        from astralogue.compiler import compile_story
        b = Bundle.from_dict(load_json(source))
        report = compile_story(b, output, lang.upper(), force)
        console.print(f"已构建 {output}\npack_id={report['pack_id']}", markup=False)
        console.print(canonical(report["counts"]), markup=False)
        if report["counts"].get("PARTIAL", 0) or report["counts"].get("BLOCKED", 0):
            console.print("包含受限会话；请运行 validate 查看具体原因。", style="yellow")


@app.command()
def validate(pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK,
             lang: Annotated[str, typer.Option()] = "CHS",
             report: Annotated[Path | None, typer.Option(help="完整 JSON 报告输出路径")] = None,
             explore: Annotated[str | None, typer.Option(help="要自动探索的会话 ID")] = None,
             explore_all: Annotated[bool, typer.Option(help="探索所有静态 RESOLVED 会话")] = False,
             max_states: Annotated[int, typer.Option(min=1)] = 1000,
             max_steps: Annotated[int, typer.Option(min=1)] = 10000):
    """检查引用、控制流和完整性；有界探索使用实际运行时。"""
    with errors():
        from astralogue.validation import validate as validate_bundle
        from astralogue.validation.explore import explore as explore_runtime
        if explore and explore_all: raise ValueError("--explore 与 --explore-all 只能选择一种")
        runtime_failure = False
        with StoryPack(pack) as sp:
            result = validate_bundle(sp.bundle(), lang.upper())
            if explore:
                result["exploration"] = explore_runtime(sp, explore, lang.upper(), max_states, max_steps)
                runtime_failure = bool(result["exploration"]["blocked"] or result["exploration"]["truncated"])
            if explore_all:
                all_results = {mid: explore_runtime(sp, mid, lang.upper(), max_states, max_steps) for mid, status in result["missions"].items() if status == "RESOLVED"}
                result["exploration_all"] = all_results
                summary = {"missions": len(all_results), "blocked": sum(bool(r["blocked"]) for r in all_results.values()),
                           "truncated": sum(r["truncated"] for r in all_results.values()), "option_edges": sum(len(r["choices_explored"]) for r in all_results.values())}
                result["exploration_summary"] = summary
                runtime_failure = bool(summary["blocked"] or summary["truncated"])
        if report:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        console.print(canonical(result["counts"]), markup=False)
        for mid, status in result["missions"].items(): console.print(f"{status}  {mid}", markup=False)
        for d in [d for d in result["diagnostics"] if d["severity"] != "info"][:30]:
            console.print(f"{d['severity']} [{d['code']}] {d['node'] or d['mission']}: {d['message']}", markup=False)
        if explore: console.print(canonical(result["exploration"]), markup=False)
        if explore_all: console.print(canonical(result["exploration_summary"]), markup=False)
        console.print(result["scope"], markup=False)
        if report: console.print(f"完整报告：{report}", markup=False)
        if runtime_failure or any(d["severity"] == "error" for d in result["diagnostics"]): raise typer.Exit(1)


@app.command("list")
def list_cmd(pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK,
             lang: Annotated[str, typer.Option()] = "CHS",
             search: Annotated[str, typer.Option(help="任务名或 ID 子串")] = "",
             chapter: Annotated[str | None, typer.Option()] = None,
             status: Annotated[str | None, typer.Option(help="RESOLVED / PARTIAL / BLOCKED")] = None,
             json_output: Annotated[bool, typer.Option(help="输出完整 ID 的 JSON")] = False,
             chapters: Annotated[bool, typer.Option(help="显示章节列表")] = False):
    """浏览章节与会话，或搜索任务名称。"""
    with errors(), StoryPack(pack) as sp:
        if status is not None and status not in {"RESOLVED", "PARTIAL", "BLOCKED"}: raise ValueError("完整性状态无效")
        if json_output:
            typer.echo(json.dumps(sp.missions(search, chapter, lang.upper(), status), ensure_ascii=False, indent=2))
            return
        table = Table("ID", "名称", "完整性")
        if chapters:
            for row in sp.con.execute("SELECT * FROM chapters ORDER BY id"):
                table.add_row(row["id"], sp.text(row["title"], lang.upper()), "")
        else:
            for m in sp.missions(search, chapter, lang.upper(), status): table.add_row(m["id"], m["name"], m["status"])
        console.print(table)


HELP = "回车：下一句；选项输入编号；:back 回溯选择；:save [路径]；:load [路径]；:event 事件名；:quit 退出（自动保存）。"


def interact(rt: Runtime, save_path: Path, autosave: Path):
    mode = rt.pack.metadata.get("narrative", {}).get("modes", {}).get(rt.state.mission, {}).get("mode", "strict")
    if mode == "reader":
        console.print("Reader 文字投影：确认/人工引导均写入存档；阅读结束不证明原游戏任务或 Strict 完成。", markup=False)
    console.print(HELP, markup=False)
    event = None
    while True:
        if event is None:
            event = rt.next()
            if isinstance(event, DiagnosticEvent): event = None; continue
            if isinstance(event, DialogueEvent):
                console.print(f"【{event.speaker}】", style="cyan", markup=False)
                console.print(event.text, markup=False, soft_wrap=True)
            elif isinstance(event, ChoiceEvent):
                message = rt.pack.node(event.node).data.get("reader_message")
                if message: console.print("[Reader] " + message, markup=False)
                for i, opt in enumerate(event.options, 1): console.print(f"  {i}. {opt.text}", markup=False)
            elif isinstance(event, EndEvent):
                label = "Reader 所选文字阅读段结束；未证明原游戏任务完成。" if mode == "reader" else "本会话结束。"
                console.print(label + "回车返回，也可 :back 或 :save。", markup=False)
            elif isinstance(event, BlockedEvent): console.print(f"剧情暂停 [{event.code}]：{event.reason}", style="yellow", markup=False)
            rt.save(autosave)
        try:
            answer = console.input("选择/命令 > " if isinstance(event, ChoiceEvent) else "> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n已自动保存：{autosave}", markup=False); return
        try:
            command, _, arg = answer.partition(" ")
            if command in {":quit", ":q"}:
                rt.save(autosave); console.print(f"已自动保存：{autosave}", markup=False); return
            if command in {":help", ":h"}: console.print(HELP, markup=False); continue
            if command == ":save":
                dest = Path(arg) if arg else save_path
                rt.save(dest); console.print(f"已保存：{dest}", markup=False); continue
            if command == ":load":
                rt = Runtime.load(rt.pack, Path(arg) if arg else save_path); event = None; continue
            if command == ":back": rt.back(); event = None; continue
            if command == ":event":
                if not isinstance(event, BlockedEvent) or event.code != "waiting_event": raise ValueError("只有等待外部事件时可显式注入事件")
                rt.signal(arg); event = None; continue
            if isinstance(event, ChoiceEvent):
                if not answer.isdecimal() or not 1 <= int(answer) <= len(event.options): raise ValueError("请输入有效的选项编号")
                rt.choose(event.options[int(answer) - 1].value); event = None
            elif isinstance(event, DialogueEvent) and answer == "": event = None
            elif isinstance(event, EndEvent) and answer == "": return "ended"
            else: console.print("请输入有效操作，:help 查看命令。", markup=False)
        except ValueError as ex: console.print(str(ex), style="yellow", markup=False)


def select_mission(sp: StoryPack, search: str, lang: str, status: str, category: str | None = None) -> str | None:
    page = 0
    while True:
        missions = sp.missions(search=search, lang=lang, status=None if status == "ALL" else status, category=category)
        pages = max(1, (len(missions) + 19) // 20)
        page = min(page, pages - 1)
        for i in range(page * 20, min((page + 1) * 20, len(missions))):
            m = missions[i]
            console.print(f"{i + 1}. {m['name']} [{m['status']}]", markup=False)
        console.print(f"共 {len(missions)} 个会话，第 {page + 1}/{pages} 页；n/p 翻页，s 关键词 搜索，q 退出。", markup=False)
        try: answer = console.input("选择会话编号 > ").strip()
        except (EOFError, KeyboardInterrupt): return None
        if answer in {"q", ":quit"}: return None
        if answer == "n": page = min(page + 1, pages - 1); continue
        if answer == "p": page = max(0, page - 1); continue
        if answer.startswith("s "):
            search = answer[2:].strip(); page = 0; continue
        if answer.isdecimal() and 1 <= int(answer) <= len(missions): return missions[int(answer) - 1]["id"]
        console.print("会话编号无效，也可输入 s 关键词 搜索。", markup=False)


@app.command()
def play(mission: Annotated[str | None, typer.Argument(help="不指定时从会话菜单选择")] = None,
         pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK,
         lang: Annotated[str, typer.Option()] = "CHS",
         search: Annotated[str, typer.Option(help="菜单会话名或 ID 筛选")] = "",
         status: Annotated[str, typer.Option(help="菜单完整性筛选；显式会话 ID 不受此筛选限制")] = "RESOLVED",
         category: Annotated[str | None, typer.Option(help="菜单任务类别筛选")] = None,
         save_file: Annotated[Path, typer.Option()] = DEFAULT_SAVE,
         autosave: Annotated[Path, typer.Option()] = Path("saves/autosave.save.json")):
    """逐句阅读真实剧情并执行分支；全程离线。"""
    with errors(), StoryPack(pack) as sp:
        if mission is None:
            if status not in {"RESOLVED", "PARTIAL", "BLOCKED", "ALL"}: raise ValueError("完整性状态无效")
            mission = select_mission(sp, search, lang.upper(), status, category)
            if mission is None: return
        m = sp.mission(mission)
        console.print(f"完整性：{m['status']}（状态仅针对该会话）", markup=False)
        label = sp.metadata.get("mission_labels", {}).get(mission, {})
        if label.get("scope") == "PERFORMANCE_FRAGMENT":
            console.print("这是主线演出片段入口；未断言原任务的世界前置条件已满足，也不表示完整任务已完成。", markup=False)
        elif label.get("scope") == "SUBMISSION_FRAGMENT":
            console.print("这是主线子任务片段入口；前提为该子任务已激活，不表示完整开拓任务已完成。", markup=False)
        elif label.get("scope") == "MISSION":
            console.print("主线入口按任务已接取初始化；原游戏 TakeParam 前置世界状态没有被伪造。", markup=False)
        return interact(Runtime(sp, mission, lang.upper()), save_file, autosave)


@app.command()
def resume(save_file: Annotated[Path, typer.Option(exists=True)] = Path("saves/autosave.save.json"),
           pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK,
           autosave: Annotated[Path, typer.Option()] = Path("saves/autosave.save.json")):
    """检查存档兼容性，恢复下一句未读剧情及选择历史。"""
    with errors(), StoryPack(pack) as sp: return interact(Runtime.load(sp, save_file), save_file, autosave)


@app.command()
def save(output: Annotated[Path, typer.Option()] = DEFAULT_SAVE,
         from_save: Annotated[Path, typer.Option(exists=True)] = Path("saves/autosave.save.json"),
         pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK):
    """把已验证的自动存档另存；播放时用 :save 保存当前进度。"""
    with errors(), StoryPack(pack) as sp:
        Runtime.load(sp, from_save).save(output)
        console.print(f"已另存：{output}", markup=False)


from astralogue.hsr.cli import app as hsr_app
app.add_typer(hsr_app, name="hsr")
from astralogue.narrative.cli import reader_app, patch_app
app.add_typer(reader_app, name="reader")
app.add_typer(patch_app, name="patch")

from astralogue.archive.cli import app as archive_app, browse
app.add_typer(archive_app, name='archive')
app.command('browse')(browse)
