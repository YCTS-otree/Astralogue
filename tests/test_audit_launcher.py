import importlib.util
from pathlib import Path


def launcher():
    spec=importlib.util.spec_from_file_location('audit_launcher',Path(__file__).parents[1]/'tools/audit_review_launcher.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_reuses_existing_service_without_launching(monkeypatch):
    m=launcher();monkeypatch.setattr(m,'available',lambda:True)
    monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('duplicate service')))
    monkeypatch.setattr(m.sys,'argv',['launcher','--no-browser'])
    monkeypatch.setattr(m.webbrowser,'open',lambda *a: (_ for _ in ()).throw(AssertionError('browser')))
    assert m.main()==0


def test_detached_service_survives_invoking_terminal_contract(tmp_path,monkeypatch):
    m=launcher();state=iter([False,True]);monkeypatch.setattr(m,'available',lambda:next(state))
    monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m.sys,'argv',['launcher','--no-browser'])
    calls=[];monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**k:calls.append((a,k)))
    assert m.main()==0 and len(calls)==1
    kwargs=calls[0][1]
    if m.os.name=='nt':
        assert kwargs['creationflags'] & m.subprocess.CREATE_BREAKAWAY_FROM_JOB
        assert kwargs['creationflags'] & m.subprocess.DETACHED_PROCESS
    else:assert kwargs['start_new_session']


def test_launcher_failure_is_visible_and_does_not_open_browser(tmp_path,monkeypatch):
    m=launcher();monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'available',lambda:False)
    def denied(*a,**k):raise OSError('denied')
    monkeypatch.setattr(m.subprocess,'Popen',denied)
    monkeypatch.setattr(m.webbrowser,'open',lambda *a: (_ for _ in ()).throw(AssertionError('browser')))
    assert m.main()==1
