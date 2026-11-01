"""Traditional terminal UI. All execution decisions belong to Runtime."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
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
from astralogue.player import ProfileEvent

app = typer.Typer(no_args_is_help=False, help="Astralogue 星轨叙事引擎：离线剧情编译与播放")
console = Console(highlight=False)
DEFAULT_PACK = Path("data/packs/astralogue.storypack")
DEFAULT_IR = Path("data/staging/story.ir.json")
DEFAULT_SAVE = Path("saves/latest.save.json")
_DEBUG=ContextVar('astralogue_cli_debug',default=False)


@app.callback(invoke_without_command=True)
def configure(ctx: typer.Context, debug: Annotated[bool, typer.Option(help="显示来源、证据等级和 Reader 调试说明")] = False):
    token=_DEBUG.set(debug);ctx.call_on_close(lambda:_DEBUG.reset(token))
    if ctx.invoked_subcommand is None:
        from astralogue.accounts import launch
        launch(debug=debug)


@app.command('start')
def start(pack:Path=Path('data/packs/prologue-player.storypack'),accounts_dir:Path=Path('saves/accounts'),debug:bool=False,import_save:Path|None=None):
    """注册/登录本地账号，自动继续唯一进度。"""
    from astralogue.accounts import launch
    return launch(pack,accounts_dir,debug,import_save)


def debug_enabled(explicit=False):
    return bool(explicit or _DEBUG.get())


def reading_text(value: str, debug: bool) -> str:
    if debug:return value
    if value.startswith('社区转录·'):value=value[len('社区转录·'):]
    if value.startswith('版本/上下文对照附注'):return '附注'
    if value=='Wiki 舞台/资源注释':return '画面提示'
    return value.replace('（Wiki 注释：','（').replace('（Wiki 图标展示：','（画面展示：').replace('（Wiki 图片展示：','（画面展示：')


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


HELP = "回车：下一句；选项输入编号；:back 回溯选择；:previous 返回已读快照；:profile 档案；:progress 进度；:save [路径]；:load [路径]；:event 事件名；:quit 退出。"


def interact(rt: Runtime, save_path: Path, autosave: Path, debug: bool = False, account=None):
    debug=debug_enabled(debug)
    help_text=HELP if account is None else '回车：下一句；选项输入编号；:profile 档案；:progress 进度；:quit 返回账号菜单。'
    def persist():
        if account is None:rt.save(autosave)
        else:account.save(rt)
        if debug:console.print('已自动保存'+(f'：{autosave}' if account is None else '：账号唯一进度'),markup=False)
    if getattr(rt,'profile_notice',None):console.print(rt.profile_notice,markup=False)
    mode = rt.pack.metadata.get("narrative", {}).get("modes", {}).get(rt.state.mission, {}).get("mode", "strict")
    if mode == "reader":
        try: title = rt.pack.text(rt.pack.mission(rt.state.mission)["title"], rt.lang)
        except ValueError: title = rt.state.mission
        console.print(("Reader 范围："+title) if debug else title.split(' · ')[0], markup=False)
        if debug:console.print("Reader 文字投影：确认/人工引导均写入存档；阅读结束不证明原游戏任务或 Strict 完成。", markup=False)
    console.print(help_text, markup=False)
    event = None
    while True:
        if event is None:
            event = rt.next()
            if isinstance(event, DiagnosticEvent): event = None; continue
            if isinstance(event, ProfileEvent):
                if event.migration:console.print('旧存档缺少玩家档案：请显式补全，当前剧情进度保留。', markup=False)
                if event.stage == 'avatar':
                    console.print('【系统 · 启用载体】', markup=False)
                    for i,(aid,a) in enumerate(event.avatars.items(),1):console.print(f"  {i}. {a['name']}"+(f' [{aid}]' if debug else ''), markup=False)
                elif event.stage == 'avatar_confirm':
                    console.print(f"【系统 · 载体确认】\n已选择：{event.profile['avatar_name']}\n认证完成后将无法更换载体。\n1. 确认\n2. 返回重新选择", markup=False)
                elif event.stage == 'name':console.print('【系统 · 设置代号】请输入开拓者代号（Astralogue 限制：1–32 个 Unicode 字符）。', markup=False)
                else:console.print(f"【系统 · 确认代号】\n载体：{event.profile['avatar_name']}\n代号：{event.profile['nickname']}\n1. 确认\n2. 重新输入", markup=False)
            elif isinstance(event, DialogueEvent):
                console.print(f"【{reading_text(event.speaker,debug)}】", style="cyan", markup=False)
                console.print(reading_text(event.text,debug), markup=False, soft_wrap=True)
            elif isinstance(event, ChoiceEvent):
                node=rt.pack.node(event.node);action=node.data.get('reader_action');message=node.data.get('reader_message')
                if debug and message:console.print('[Reader] '+message,markup=False)
                elif not debug:
                    if action=='optional_inquiry':console.print('可逐一询问，也可选择继续。',markup=False)
                    elif action=='optional_idle_dialogue':console.print('等待时的可选对白：查看或继续剧情。',markup=False)
                    elif action in {'manual_guide','user_order','community_patch','track_selection'}:console.print('当前阅读关系尚未确定；请选择采用的阅读方向。',markup=False)
                    elif action in {'confirmation','unknown_marker'}:console.print('暂停条件尚未恢复；确认后继续阅读。',markup=False)
                for i,opt in enumerate(event.options,1):
                    label=opt.text if debug else reading_text(opt.text,False)
                    if not debug:
                        if action in {'source_transcript_policy','hf_consent','reader_consent'}:label='开始阅读'
                        elif action in {'confirmation','unknown_marker','nontext_confirmation'}:label='确认继续'
                        elif action=='community_patch':label='采用此阅读修订'
                        elif action=='reading_end':label='结束本段阅读'
                        elif action=='timeline_return':label='返回当前故事'
                        elif action=='track_selection':label=f'阅读片段 {i}'
                    console.print(f'  {i}. {label}',markup=False)
            elif isinstance(event, EndEvent):
                plain_end='本章阅读结束。' if rt.state.mission in rt.pack.metadata.get('story_arcs',{}) else '本段阅读结束。'
                label = ("Reader 所选文字阅读段结束；未证明原游戏任务完成。" if debug else plain_end) if mode == "reader" else "本会话结束。"
                console.print(label + ('回车返回账号菜单。' if account else '回车返回，也可 :back 或 :save。'), markup=False)
            elif isinstance(event, BlockedEvent): console.print(f"剧情暂停 [{event.code}]：{event.reason}", style="yellow", markup=False)
            persist()
        try:
            answer = console.input("选择/命令 > " if isinstance(event, (ChoiceEvent,ProfileEvent)) else "> ").strip()
        except (EOFError, KeyboardInterrupt):
            persist(); return 'eof'
        try:
            command, _, arg = answer.partition(" ")
            if account is not None:
                if command in {':back',':previous',':load'}:raise ValueError('账号只有一份持续进度，不能读档回退或改选')
                if command==':save':
                    if arg:raise ValueError('账号模式不支持另存文件')
                    persist();continue
            if command == ':profile' and hasattr(rt,'profile'):
                p=rt.profile
                console.print(json.dumps(p.to_dict(),ensure_ascii=False) if debug else f"载体：{p.avatar_name or '尚未选择'}\n代号：{p.nickname or '尚未设置'}",markup=False);continue
            if command == ":previous" and hasattr(rt, "previous"):
                rt.previous(); event = None; continue
            if command == ":progress" and hasattr(rt, "traversal"):
                p=rt.progress()
                console.print(json.dumps(p,ensure_ascii=False) if debug else f"{p['chapter']} · {p['task_title'] or '章节边界'}（{p['task'] or p['total_tasks']}/{p['total_tasks']}）",markup=False);continue
            if command in {":quit", ":q", ":logout"}:
                persist(); return
            if command in {":help", ":h"}: console.print(help_text, markup=False); continue
            if command == ":save":
                dest = Path(arg) if arg else save_path
                rt.save(dest); console.print(f"已保存：{dest}", markup=False); continue
            if command == ":load":
                rt = load_session(rt.pack, Path(arg) if arg else save_path); event = None; continue
            if command == ":back": rt.back(); event = None; continue
            if command == ":event":
                if not isinstance(event, BlockedEvent) or event.code != "waiting_event": raise ValueError("只有等待外部事件时可显式注入事件")
                rt.signal(arg); event = None; continue
            if isinstance(event,ProfileEvent):
                if event.stage=='avatar':
                    keys=list(event.avatars)
                    if not answer.isdecimal() or not 1<=int(answer)<=len(keys):raise ValueError('请选择有效载体编号')
                    value=keys[int(answer)-1]
                elif event.stage=='name':value=answer
                else:
                    if answer not in {'1','2'}:raise ValueError('请输入 1 或 2')
                    value='confirm' if answer=='1' else 'back'
                rt.identity_input(value);event=None
            elif isinstance(event, ChoiceEvent):
                if not answer.isdecimal() or not 1 <= int(answer) <= len(event.options): raise ValueError("请输入有效的选项编号")
                rt.choose(event.options[int(answer) - 1].value); event = None
            elif isinstance(event, DialogueEvent) and answer == "": event = None
            elif isinstance(event, EndEvent) and answer == "":persist();return "ended"
            else: console.print("请输入有效操作，:help 查看命令。", markup=False)
            if account is not None:persist()
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
         autosave: Annotated[Path, typer.Option()] = Path("saves/autosave.save.json"),
         debug: Annotated[bool,typer.Option(help="显示来源及 Reader 调试信息")] = False):
    """逐句阅读真实剧情并执行分支；全程离线。"""
    with errors(), StoryPack(pack) as sp:
        if mission is None:
            if status not in {"RESOLVED", "PARTIAL", "BLOCKED", "ALL"}: raise ValueError("完整性状态无效")
            mission = select_mission(sp, search, lang.upper(), status, category)
            if mission is None: return
        m = sp.mission(mission)
        debug=debug_enabled(debug)
        if debug:console.print(f"完整性：{m['status']}（状态仅针对该会话）", markup=False)
        label = sp.metadata.get("mission_labels", {}).get(mission, {})
        if debug and label.get("scope") == "PERFORMANCE_FRAGMENT":
            console.print("这是主线演出片段入口；未断言原任务的世界前置条件已满足，也不表示完整任务已完成。", markup=False)
        elif debug and label.get("scope") == "SUBMISSION_FRAGMENT":
            console.print("这是主线子任务片段入口；前提为该子任务已激活，不表示完整开拓任务已完成。", markup=False)
        elif debug and label.get("scope") == "MISSION":
            console.print("主线入口按任务已接取初始化；原游戏 TakeParam 前置世界状态没有被伪造。", markup=False)
        return interact(session(sp, mission, lang.upper()), save_file, autosave,debug)


@app.command()
def resume(save_file: Annotated[Path, typer.Option(exists=True)] = Path("saves/autosave.save.json"),
           pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK,
           autosave: Annotated[Path, typer.Option()] = Path("saves/autosave.save.json"),
           debug: Annotated[bool,typer.Option()] = False):
    """检查存档兼容性，恢复下一句未读剧情及选择历史。"""
    with errors(), StoryPack(pack) as sp: return interact(load_session(sp, save_file), save_file, autosave,debug)


@app.command()
def save(output: Annotated[Path, typer.Option()] = DEFAULT_SAVE,
         from_save: Annotated[Path, typer.Option(exists=True)] = Path("saves/autosave.save.json"),
         pack: Annotated[Path, typer.Option(exists=True)] = DEFAULT_PACK):
    """把已验证的自动存档另存；播放时用 :save 保存当前进度。"""
    with errors(), StoryPack(pack) as sp:
        load_session(sp, from_save).save(output)
        console.print(f"已另存：{output}", markup=False)


from astralogue.hsr.cli import app as hsr_app
app.add_typer(hsr_app, name="hsr")
from astralogue.narrative.cli import reader_app, patch_app
app.add_typer(reader_app, name="reader")
app.add_typer(patch_app, name="patch")

from astralogue.archive.cli import app as archive_app, browse
app.add_typer(archive_app, name='archive')
app.command('browse')(browse)

from astralogue.adapters.wiki.cli import app as wiki_app
app.add_typer(wiki_app, name='wiki')

from astralogue.hsr.hf_cli import app as hf_app
app.add_typer(hf_app, name='hf')

from astralogue.arcs.session import session, load_session
from astralogue.arcs.cli import app as arcs_app
app.add_typer(arcs_app, name="arcs")
