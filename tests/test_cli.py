import json
from typer.testing import CliRunner

from astralogue.cli import app

runner = CliRunner()


def test_help_version():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and "1.0.0" in result.output


def test_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / "data/staging").is_dir()
    assert "fetch-sample" in result.output


def test_import_build_validate_list(tmp_path, graph):
    ir = tmp_path / "source.json"; graph.write(ir)
    staging = tmp_path / "staging.json"; pack = tmp_path / "cli.storypack"
    assert runner.invoke(app, ["import", "--source", str(ir), "--output", str(staging)]).exit_code == 0
    assert runner.invoke(app, ["build", "--source", str(staging), "--output", str(pack)]).exit_code == 0
    report = tmp_path / "report.json"
    result = runner.invoke(app, ["validate", "--pack", str(pack), "--report", str(report), "--explore", "m"])
    assert result.exit_code == 0, result.output
    assert json.loads(report.read_text(encoding="utf-8"))["missions"] == {"m": "RESOLVED"}
    result = runner.invoke(app, ["list", "--pack", str(pack), "--search", "测试"])
    assert "测试会话" in result.output
    assert runner.invoke(app, ["list", "--pack", str(pack), "--chapters"]).exit_code == 0


def test_play_back_save_resume(pack_path, tmp_path):
    save, auto = tmp_path / "manual.json", tmp_path / "auto.json"
    # a -> choice -> b -> back -> choice -> c -> save next unread d
    result = runner.invoke(app, ["play", "m", "--pack", str(pack_path), "--save-file", str(save), "--autosave", str(auto)],
                           input="\n1\n:back\n2\n:save\n:quit\n")
    assert result.exit_code == 0, repr(result.exception)
    assert "测试 b [literal]" in result.output and "测试 c [literal]" in result.output
    assert save.exists() and auto.exists()
    result = runner.invoke(app, ["resume", "--pack", str(pack_path), "--save-file", str(save), "--autosave", str(auto)], input="\n\n")
    assert result.exit_code == 0 and "测试 d [literal]" in result.output
    assert "本会话结束" in result.output


def test_invalid_choice_and_eof_autosave(pack_path, tmp_path):
    auto = tmp_path / "auto.json"
    result = runner.invoke(app, ["play", "m", "--pack", str(pack_path), "--autosave", str(auto)], input="\n99\n")
    assert result.exit_code == 0
    assert "有效的选项编号" in result.output
    assert json.loads(auto.read_text(encoding="utf-8"))["state"]["node"] == "pick"


def test_save_command(pack_path, tmp_path):
    auto = tmp_path / "auto.json"; output = tmp_path / "copy.json"
    runner.invoke(app, ["play", "m", "--pack", str(pack_path), "--autosave", str(auto)], input=":quit\n")
    result = runner.invoke(app, ["save", "--pack", str(pack_path), "--from-save", str(auto), "--output", str(output)])
    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["state"] == json.loads(auto.read_text(encoding="utf-8"))["state"]


def test_missing_pack_and_bad_ir(tmp_path):
    assert runner.invoke(app, ["play", "--pack", str(tmp_path / "absent.storypack")]).exit_code != 0
    bad = tmp_path / "bad.json"; bad.write_text('{"ir_version":99}', encoding="utf-8")
    result = runner.invoke(app, ["build", "--source", str(bad), "--output", str(tmp_path / "bad.storypack")])
    assert result.exit_code == 2 and "IR" in result.output


def test_invalid_graph_exit_code(tmp_path, graph):
    graph.nodes[0].text = "absent"
    ir = tmp_path / "bad.json"; graph.write(ir)
    pack = tmp_path / "bad.storypack"
    runner.invoke(app, ["build", "--source", str(ir), "--output", str(pack)])
    assert runner.invoke(app, ["validate", "--pack", str(pack)]).exit_code == 1


def test_batch_exploration_and_json_list(pack_path, tmp_path):
    report = tmp_path / "batch.json"
    result = runner.invoke(app, ["validate", "--pack", str(pack_path), "--explore-all", "--report", str(report)])
    assert result.exit_code == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["exploration_summary"] == {"missions": 1, "blocked": 0, "truncated": 0, "option_edges": 2}
    result = runner.invoke(app, ["list", "--pack", str(pack_path), "--status", "RESOLVED", "--json-output"])
    assert json.loads(result.output)[0]["id"] == "m"
    assert runner.invoke(app, ["validate", "--pack", str(pack_path), "--explore-all", "--max-states", "1"]).exit_code == 1


def test_menu_search_and_select(pack_path, tmp_path):
    result = runner.invoke(app, ["play", "--pack", str(pack_path), "--autosave", str(tmp_path / "a.json")],
                           input="s absent\ns 测试\n1\n:quit\n")
    assert result.exit_code == 0 and "共 0 个会话" in result.output and "测试 a [literal]" in result.output
