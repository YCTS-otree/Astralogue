"""Offline Reader and rebuildable community overlay commands."""
import json
from pathlib import Path
from typing import Annotated

import typer

from astralogue.model import Bundle, load_json

reader_app = typer.Typer(no_args_is_help=True, help="独立文字阅读策略与选择审计")
patch_app = typer.Typer(no_args_is_help=True, help="Community Patch Protocol v1（仅作用于 Reader）")


def write(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


@reader_app.command()
def play(pack: Annotated[Path, typer.Option(exists=True)], mode: Annotated[str, typer.Option()] = "reader",
         save_file: Annotated[Path, typer.Option()] = Path("saves/reader/latest.save.json"),
         autosave: Annotated[Path, typer.Option()] = Path("saves/reader/autosave.save.json"),
         debug: Annotated[bool,typer.Option()] = False):
    """选择 Strict/Reader；普通 play 和 resume 同样兼容该包。"""
    from astralogue.cli import errors, play as player
    from astralogue.storypack import StoryPack
    with errors(), StoryPack(pack) as sp:
        if mode not in {"strict", "reader"}: raise ValueError("mode 必须为 strict 或 reader")
        mission = sp.metadata.get("narrative", {}).get("entries", {}).get(mode)
        if not mission: raise ValueError("剧情包没有该模式的入口")
        return player(mission=mission, pack=pack, lang="CHS", search="", status="ALL", category=None,
                      save_file=save_file, autosave=autosave,debug=debug)


@reader_app.command("audit")
def audit_cmd(pack: Annotated[Path, typer.Option(exists=True)], save_file: Annotated[Path, typer.Option(exists=True)],
              output: Annotated[Path, typer.Option()] = Path("data/reader-audit.json")):
    """从包与存档导出确认、真实选择、人工排序及补丁来源。"""
    from astralogue.cli import console, errors
    from astralogue.runtime import Runtime
    from astralogue.storypack import StoryPack
    from . import audit
    with errors(), StoryPack(pack) as sp:
        Runtime.load(sp, save_file)  # validate pack version and all save snapshots
        result = audit(sp, load_json(save_file)); write(output, result)
        console.print(f"审计记录：{output}；模式 {result['mode']}；选择/确认 {len(result['records'])}", markup=False)


@patch_app.command("create")
def create(source: Annotated[Path, typer.Option(exists=True)], output: Annotated[Path, typer.Option()],
           patch_id: Annotated[str, typer.Option()], mission: Annotated[str, typer.Option()],
           from_node: Annotated[str, typer.Option()], to_node: Annotated[str, typer.Option()],
           evidence_uri: Annotated[str, typer.Option()]):
    """创建绑定当前资源哈希的待审核补丁，随后手工编辑。"""
    from astralogue.cli import errors
    with errors():
        if output.exists(): raise ValueError("拒绝覆盖已有补丁")
        b = Bundle.from_dict(load_json(source)); info = b.metadata.get("narrative", {})
        value = {"patch_version": 1, "id": patch_id, "status": "pending", "game": info.get("game"), "game_version": info.get("game_version"),
                 "source_hashes": info.get("source_hashes", {}), "evidence": [{"id": "e1", "uri": evidence_uri}],
                 "operations": [{"op": "connect", "mission": mission, "source": from_node, "target": to_node, "evidence": ["e1"]}]}
        write(output, value)


@patch_app.command("validate")
def validate_cmd(source: Annotated[Path, typer.Option(exists=True)], patch: Annotated[Path, typer.Option(exists=True)]):
    from astralogue.cli import console, errors
    from .patch import validate_patch
    with errors():
        result = validate_patch(Bundle.from_dict(load_json(source)), load_json(patch))
        console.print(json.dumps(result, ensure_ascii=False), markup=False)
        if not result["valid"]: raise typer.Exit(1)


@patch_app.command("import")
def import_cmd(source: Annotated[Path, typer.Option(exists=True)], patch: Annotated[Path, typer.Option(exists=True)],
               output: Annotated[Path, typer.Option()]):
    """检查后导入独立 JSON；不会更改原始输入。"""
    from astralogue.cli import errors
    from .patch import validate_patch
    with errors():
        if output.exists(): raise ValueError("拒绝覆盖已有补丁")
        document = load_json(patch)
        result = validate_patch(Bundle.from_dict(load_json(source)), document)
        if not result["valid"]: raise ValueError("; ".join(result["errors"]))
        write(output, document)


@patch_app.command("apply")
def apply_cmd(source: Annotated[Path, typer.Option(exists=True)], patch: Annotated[Path, typer.Option(exists=True)],
              output_ir: Annotated[Path, typer.Option()], output: Annotated[Path, typer.Option()],
              include_pending: Annotated[bool, typer.Option()] = False, force: Annotated[bool, typer.Option()] = False):
    """重新应用到基础 IR，并重编译独立 StoryPack。"""
    from astralogue.cli import console, errors
    from astralogue.compiler import compile_story
    from .patch import apply_patch
    with errors():
        inputs = {source.resolve(), patch.resolve()}
        if output_ir.resolve() in inputs or output.resolve() in inputs or output_ir.resolve() == output.resolve():
            raise ValueError("补丁输出不能覆盖基础 IR、补丁原文，或使用相同输出路径")
        if output_ir.exists() and not force: raise ValueError("输出 IR 已存在；使用 --force")
        b = apply_patch(Bundle.from_dict(load_json(source)), load_json(patch), include_pending)
        report = compile_story(b, output, force=force)
        b.write(output_ir)
        console.print(f"补丁已应用（Strict 未修改）：{output}；pack_id={report['pack_id']}", markup=False)
