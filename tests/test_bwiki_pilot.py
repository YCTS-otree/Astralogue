import json
import time
import urllib.error
import pytest
from astralogue.adapters.wiki.pilot import Pilot, single_instance, TITLES
from astralogue.model import file_hash


def snapshot(path, title=TITLES[0], text='==剧情内容==\n===目标===\n*甲：你好。'):
    path.write_text(json.dumps({'parse':{'title':title,'pageid':11,'revid':12,'wikitext':{'*':text}}}),encoding='utf8')
    return path


def test_dedupe_hash_and_offline_parse(tmp_path,monkeypatch):
    p=Pilot(tmp_path/'pilot');src=snapshot(tmp_path/'a.json')
    monkeypatch.setattr('astralogue.adapters.wiki.pilot.verified_opener',lambda *_:pytest.fail('Network'))
    p.import_page(src);p.import_page(src);p.parse_cached()
    rows=p.status()['pages'];assert len(rows)==2 and rows[1]['status']=='VALIDATED'
    cached=p.root/rows[1]['cache'];cached.write_text('corrupt')
    p.recover();assert p.status()['pages'][1]['status']=='FAILED'
    p.close()


def test_rate_budget_and_single_lock(tmp_path):
    p=Pilot(tmp_path)
    with pytest.raises(ValueError):Pilot(tmp_path,119)
    with single_instance(tmp_path/'worker.lock'):
        with pytest.raises(ValueError):
            with single_instance(tmp_path/'worker.lock'):pass
    assert p.due(1000)
    with p.db:p.db.execute('INSERT INTO requests VALUES(?,?,?)',(1000,'test','ok'))
    assert not p.due(1119) and p.due(1120)
    p.budget=1;assert not p.due(1120)
    p.close()


def test_crash_after_atomic_cache_before_db_commit(tmp_path):
    p=Pilot(tmp_path/'pilot');src=snapshot(tmp_path/'a.json');title=TITLES[0]
    with p.db:p.db.execute('INSERT INTO pages(title,chapter,status) VALUES(?,?,?)',(title,'100001','FETCHING'))
    dest=p.cache_path(title);dest.parent.mkdir();dest.write_bytes(src.read_bytes())
    p.close();p=Pilot(tmp_path/'pilot')
    with single_instance(p.root/'worker.lock'):p.recover();p.parse_cached()
    assert p.status()['pages'][1]['status']=='VALIDATED'
    assert file_hash(dest)==file_hash(src)
    p.state('paused');assert not p.tick()
    p.close()


def test_retry_after_pauses(tmp_path,monkeypatch):
    p=Pilot(tmp_path);(tmp_path/'robots.txt').write_text('User-agent: *\nDisallow:\n')
    p.state('running')
    class Opener:
        def open(self,*a,**kw):raise urllib.error.HTTPError('x',429,'slow',{'Retry-After':'600'},None)
    monkeypatch.setattr('astralogue.adapters.wiki.pilot.verified_opener',lambda *_:Opener())
    now=time.time();assert not p.tick(now=now)
    r=p.status()['pages'][0];assert r['next_at']>=now+600 and r['attempts']==1 and p.state()=='paused'
    assert not p.tick(now=now+1000) and p.status()['pages'][0]['attempts']==1
    p.close()


def test_robots_denial_never_fetches(tmp_path,monkeypatch):
    p=Pilot(tmp_path);(tmp_path/'robots.txt').write_text('User-agent: *\nDisallow: /sr/\n')
    p.state('running');monkeypatch.setattr('astralogue.adapters.wiki.pilot.verified_opener',lambda *_:pytest.fail('Forbidden network'))
    assert not p.tick() and p.state()=='paused' and p.status()['requests']==0
    p.close()


def test_optional_classification_does_not_guess_investigation(tmp_path):
    from astralogue.adapters.wiki.bwiki import parse_page
    from astralogue.adapters.wiki.scenes import classify_page
    src=snapshot(tmp_path/'a.json',text='==剧情内容==\n===检查终端===\n{{折叠|标题=调查桌面|内容=纸张}}\n{{折叠|标题=额外对话（甲）|内容=*甲：你好。}}')
    a,b=classify_page(parse_page(src))['sections'][0]['interactions']
    assert a['kind']=='unknown' and b['kind']=='optional_dialogue'
    assert b['availability']==b['repeat_policy']=='unknown'


def test_scope_rejects_unrelated_page(tmp_path):
    p=Pilot(tmp_path/'pilot')
    with pytest.raises(ValueError):p.import_page(snapshot(tmp_path/'bad.json','other'))
    p.close()


def test_multiline_nested_structure_retained_as_unknown():
    from astralogue.adapters.wiki.bwiki import dialogue_body
    rows,unknown=dialogue_body('*甲：{{剧情选项\n|选项1=你好\n}}')
    assert rows==[] and unknown[0]=='*甲：{{剧情选项'


def test_section_heading_inside_fold_does_not_break_document(tmp_path):
    from astralogue.adapters.wiki.bwiki import parse_page
    from astralogue.adapters.wiki.scenes import classify_page
    path=snapshot(tmp_path/'nested.json',text='==剧情内容==\n===前往终端===\n{{折叠|标题=额外对话（甲）|内容=\n*甲：你好。\n===嵌入标题===\n*甲：再会。\n}}')
    r=classify_page(parse_page(path))
    assert len(r['sections'])==2
    assert r['sections'][0]['interactions'][0]['unknown']==['===嵌入标题===']
