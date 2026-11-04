import json
from pathlib import Path
import pytest
from astralogue.audit.store import AuditStore
from astralogue.audit.pages import ordered,list_page
from astralogue.audit import navigation as nav
from test_audit_webui import seed


def units():
    return [{'id':'source','chapter':'100001','chapter_label':nav.chapter_label('100001'),'task':'混乱行至深处','section':'取出星核','section_id':'phase',
             'path':'unused','sha256':'hash','revision':1,'page_id':2,'start':0,'end':100,
             'text':'星核放进容器，银狼协助。','part':{'id':'part','kind':'active_investigation','label':'调查星核','raw':'星核放进容器，银狼协助。','source':{'start':5,'raw':'星核放进容器，银狼协助。'},'segments':[]}}]


def test_chinese_multi_keyword_search_and_scope():
    query={'chapter':['100001'],'mission':['混乱行至深处'],'section':['取出星核'],'q':['星核 容器 银狼']}
    assert len(nav.filter_sources(units(),query))==1
    assert not nav.filter_sources(units(),{**query,'q':['星核 未出现']})
    assert len(nav.filter_sources(units(),{**query,'q':['星核 未出现'],'match':['any']}))==1
    assert not nav.filter_sources(units(),{**query,'mission':['其他任务']})


def test_proposal_filters_preserve_navigation_and_no_request_source_entry(tmp_path,monkeypatch):
    path=tmp_path/'a.sqlite';seed(path);monkeypatch.setattr(nav,'catalog',units)
    with AuditStore(path) as s:
        query={'chapter':['100001'],'mission':['混乱行至深处'],'section':['进入空间站'],'q':['调查画像'],'status':['pending']}
        rows=nav.filter_proposals(ordered(s),query)
        assert {r['row']['id'] for r in rows}=={'earlier','research'}
        html=list_page(s,query)
        assert 'name="chapter"' in html and 'name="q"' in html
        assert 'mission=' in html and 'section=' in html and 'q=' in html
        html=list_page(s,{'view':['source'],'q':['星核 容器 银狼']})
        assert '暂无已关联申请' in html and 'source_parse' in html and 'source_model' in html
        assert '星核放进容器' in html


def test_source_parser_is_idempotent_and_model_submission_is_not_approval(tmp_path,monkeypatch):
    from test_audit_cleanup import fixture
    from astralogue.compiler import compile_story
    b,_=fixture();b.metadata['story_arcs']={'reader':{'plan':{'tasks':[{'title':'混乱行至深处'}]}}}
    pack=tmp_path/'p.storypack';compile_story(b,pack)
    monkeypatch.setattr(nav,'catalog',units)
    with AuditStore(tmp_path/'a.sqlite') as s:
        s.setting('publication_pack',str(pack))
        first=nav.request_source(s,'source','source_parse','human')
        assert first['proposal']==nav.request_source(s,'source','source_parse','human')['proposal']
        assert s.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1
        with pytest.raises(ValueError):nav.request_source(s,'source','source_model','human','')
        result=nav.request_source(s,'source','source_model','human','主动调查，首次与再次分开。')
        assert s.db.execute('SELECT status FROM jobs WHERE id=?',(result['job'],)).fetchone()[0]=='pending'
        assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0]==0
        with pytest.raises(ValueError):nav.request_source(s,'invalid','source_parse','human')

def test_http_source_request_does_not_require_existing_proposal(tmp_path,monkeypatch):
    import threading,urllib.request,urllib.parse
    from astralogue.audit.webui import make_server
    from test_audit_cleanup import fixture
    from astralogue.compiler import compile_story
    b,_=fixture();pack=tmp_path/'p.storypack';compile_story(b,pack)
    path=tmp_path/'audit.sqlite';monkeypatch.setattr(nav,'catalog',units)
    with AuditStore(path) as s:s.setting('publication_pack',str(pack))
    server=make_server(path,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base='http://127.0.0.1:'+str(server.server_address[1])
        query=urllib.parse.urlencode({'view':'source','q':'星核 容器 银狼'})
        html=urllib.request.urlopen(base+'/?'+query).read().decode()
        assert 'source_parse' in html and '暂无已关联申请' in html
        with AuditStore(path) as s:token=s.setting('webui_csrf')
        values={'csrf':token,'source_id':'source','action':'source_parse','reviewer':'human'}
        request=urllib.request.Request(base,data=urllib.parse.urlencode(values).encode(),headers={'Accept':'application/json'})
        result=json.load(urllib.request.urlopen(request));assert result['proposal'] and result['count']==1
        values.update(action='source_model',comment='主动调查需要分开。',provider='local')
        request=urllib.request.Request(base,data=urllib.parse.urlencode(values).encode(),headers={'Accept':'application/json'})
        result=json.load(urllib.request.urlopen(request));assert result['job']
        with AuditStore(path) as s:assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0]==0
    finally:server.shutdown();server.server_close();thread.join()
