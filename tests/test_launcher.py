import os
from pathlib import Path
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]


def test_launcher_outside_project(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'tools/launch.py'),'--help'],cwd=tmp_path,
                          capture_output=True,text=True,encoding='utf8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    assert result.returncode==0 and 'Astralogue' in result.stdout
    assert not (tmp_path/'saves').exists()


def test_copied_cmd_uses_configured_root(tmp_path):
    if os.name!='nt':
        import pytest
        pytest.skip('Windows CMD launcher')
    path=tmp_path/'folder with spaces';path.mkdir()
    copied=path/'Astralogue.cmd';copied.write_bytes((ROOT/'Astralogue.cmd').read_bytes())
    result=subprocess.run(['cmd.exe','/d','/c',str(copied),'--help'],cwd=tmp_path,
                          capture_output=True,text=True,encoding='utf8',
                          env={**os.environ,'ASTRALOGUE_HOME':str(ROOT),'PYTHONIOENCODING':'utf-8'})
    assert result.returncode==0 and 'Astralogue' in result.stdout


def test_invalid_root_explains_error(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'tools/launch.py')],cwd=tmp_path,
                          capture_output=True,text=True,env={**os.environ,'ASTRALOGUE_HOME':str(tmp_path)})
    assert result.returncode!=0 and 'ASTRALOGUE_HOME' in result.stderr


def test_double_click_equivalent_no_arguments(tmp_path):
    if os.name!='nt':
        import pytest
        pytest.skip('Windows launcher')
    path=tmp_path/'Astralogue.cmd';path.write_bytes((ROOT/'Astralogue.cmd').read_bytes())
    result=subprocess.run(['cmd.exe','/d','/c',str(path)],input='0\n',cwd=tmp_path,
                          capture_output=True,text=True,encoding='utf8',
                          env={**os.environ,'ASTRALOGUE_HOME':str(ROOT)})
    assert result.returncode==0 and '登录' in result.stdout and '注册' in result.stdout
    assert not (tmp_path/'saves').exists()
