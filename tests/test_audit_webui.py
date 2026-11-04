"""Human-readable audit context and source-backed review ordering."""
import copy
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest
from astralogue.audit.store import AuditStore
from astralogue.audit.pages import ordered, list_page, detail_page
from astralogue.audit.presentation import windows
from astralogue.audit.webui import make_server


def seed(path):
    with AuditStore(path) as s:
        transcript = [{'node': 'before', 'speaker': '银狼', 'text': '上文内容'},
                      {'node': 'z-first', 'speaker': '卡芙卡', 'text': '调查画像'},
                      {'node': 'after', 'speaker': '银狼', 'text': '后续共同台词'},
                      {'node': 'a-last', 'speaker': '卡芙卡', 'text': '后面的小节'}]
        s.setting('first_task_findings', {'path': transcript})
        s.setting('audit_plan', [{'task': '混乱行至深处'}])
        for pid, index, title, start in [('later', 3, '取出星核', 100), ('earlier', 1, '进入空间站', 0)]:
            node = transcript[index]
            context = {'task': {'title': '混乱行至深处'}, 'chapter': '今天是昨天的明天',
                       'instances': {}, 'reference_instances': {'N1': node},
                       'scenes': {'p': {'id': 'phase', 'title': title, 'start': start, 'end': start+50}},
                       'evidence': {'wiki': {'source': {'start': start+1}, 'label': '调查画像'}}}
            suggestion = {'operation': 'move_to_optional_interaction', 'instances': ['N1'],
                          'targets': ['p'], 'before': {}, 'after': {'candidate_phases': ['p']},
                          'evidence': ['wiki'], 'rationale': 'technical English', 'unknowns': [], 'conflicts': []}
            payload = {'context': context, 'suggestion': suggestion, 'origin': 'LLM'}
            s.db.execute('INSERT INTO proposals(id,payload) VALUES(?,?)', (pid, json.dumps(payload, ensure_ascii=False)))
        p = copy.deepcopy(payload)
        p['suggestion']['instances'] = ['task']
        p['context']['reference_instances'] = {}
        p['context']['instances'] = {'task': {'title': '混乱行至深处'}}
        s.db.execute('INSERT INTO proposals(id,payload) VALUES(?,?)', ('research', json.dumps(p)))
        s.db.commit()


def test_sections_follow_recorded_plot_not_node_or_insertion_order(tmp_path):
    path = tmp_path/'audit.sqlite'; seed(path)
    with AuditStore(path) as s:
        assert [r['row']['id'] for r in ordered(s) if r['ready']] == ['earlier', 'later']
        body = list_page(s, {})
        assert body.index('进入空间站') < body.index('取出星核')
        assert '今天是昨天的明天' in body and '混乱行至深处' in body
        assert '当前阅读路径第 2 条' in body
        assert '人工已驳回' in body and 'review-feedback' in body
        assert 'move_to_optional_interaction' not in body
        assert '>pending<' not in body


def test_details_show_previous_branch_body_and_shared_continuation(tmp_path):
    path = tmp_path/'audit.sqlite'; seed(path)
    with AuditStore(path) as s:
        body = detail_page(s, 'earlier', 'token', '审核人')
        visible = body.split('<details><summary>技术详情')[0]
        assert visible.index('上文内容') < visible.index('调查画像</p>') < visible.index('后续共同台词')
        assert '进入空间站' in visible and '分支内容（原文保留）' in visible
        assert 'technical English' not in visible
        assert 'value="approve"' in visible
        research = detail_page(s, 'research', 'token', '')
        assert 'value="approve"' not in research
        assert 'value="research_approve"' in research


def test_partial_node_binding_never_presented_as_complete_span():
    payload = {'context': {'instances': {'a': {'node': 'known'}, 'b': {'node': 'absent'}}},
               'suggestion': {'instances': ['a', 'b']}}
    assert not windows(payload, [{'node': 'known'}])[2]


def test_html_in_dialogue_is_escaped(tmp_path):
    path = tmp_path/'audit.sqlite'; seed(path)
    with AuditStore(path) as s:
        row = s.db.execute("SELECT payload FROM proposals WHERE id='earlier'").fetchone()
        payload = json.loads(row[0])
        payload['context']['reference_instances']['N1']['text'] = '<script>alert(1)</script>'
        s.db.execute("UPDATE proposals SET payload=? WHERE id='earlier'", (json.dumps(payload),)); s.db.commit()
        body = detail_page(s, 'earlier', 'token', '')
        assert '<script>alert(1)</script>' not in body and '&lt;script&gt;' in body


def test_http_review_preserves_decisions_and_rejects_unbound_approval(tmp_path):
    path = tmp_path/'audit.sqlite'; seed(path)
    server = make_server(path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = 'http://127.0.0.1:'+str(server.server_address[1])
    try:
        assert '进入空间站' in urllib.request.urlopen(base).read().decode()
        with AuditStore(path) as s: token = s.setting('webui_csrf')
        def post(action, csrf=token):
            request = urllib.request.Request(base, data=urllib.parse.urlencode({'id': 'research', 'csrf': csrf, 'action': action, 'reviewer': '测试审核人'}).encode())
            return urllib.request.urlopen(request)
        with pytest.raises(urllib.error.HTTPError) as error: post('approve')
        assert error.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as error: post('acknowledge', 'wrong')
        assert error.value.code == 403
        post('acknowledge').close()
        with AuditStore(path) as s:
            assert s.db.execute("SELECT status FROM proposals WHERE id='research'").fetchone()[0] == 'acknowledged'
            assert s.db.execute('SELECT COUNT(*) FROM review_log').fetchone()[0] == 1
        def bulk(ids, action):
            values=[('csrf',token),('reviewer','批量测试'),('action',action)]+[('ids',pid) for pid in ids]
            return urllib.request.urlopen(urllib.request.Request(base,data=urllib.parse.urlencode(values).encode(),headers={'Accept':'application/json'}))
        with pytest.raises(urllib.error.HTTPError) as error:bulk(['earlier','research'],'approve')
        assert error.value.code==400
        with AuditStore(path) as s:
            assert s.db.execute("SELECT status FROM proposals WHERE id='earlier'").fetchone()[0]=='pending'
        with bulk(['earlier','later'],'approve') as response:
            result=json.load(response)
            assert result['count']==2 and '提交成功' in result['message']
        with AuditStore(path) as s:
            assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0]==2
        bulk(['earlier','later'],'reject').close()
        with AuditStore(path) as s:
            assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='rejected'").fetchone()[0]==2
            assert s.db.execute('SELECT COUNT(*) FROM review_log').fetchone()[0]==5
    finally:
        server.shutdown(); server.server_close(); thread.join()

def test_proposed_option_and_explanation_are_visible_separately(tmp_path):
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        p=json.loads(s.db.execute("SELECT payload FROM proposals WHERE id='earlier'").fetchone()[0])
        p['suggestion']['after']['interaction']='调查画像'
        p['suggestion']['explanation']='把此处改成主动调查；<script>不能执行</script>'
        s.db.execute("UPDATE proposals SET payload=? WHERE id='earlier'",(json.dumps(p),));s.db.commit()
        html=detail_page(s,'earlier','token','human')
        assert '建议选项文字' in html and '选择「调查画像」' in html
        assert '申请说明（不是剧情正文）' in html and '把此处改成主动调查' in html
        assert '<script>不能执行</script>' not in html and '&lt;script&gt;不能执行' in html

def test_current_pack_options_do_not_replace_proposal_review_state(tmp_path):
    from test_audit_cleanup import fixture
    from astralogue.audit.cleanup import compile_cleanup
    from astralogue.compiler import compile_story
    b,patch=fixture();pack=tmp_path/'p.storypack';compile_story(compile_cleanup(b,[patch]),pack)
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        s.setting('publication_pack',str(pack))
        p=json.loads(s.db.execute("SELECT payload FROM proposals WHERE id='earlier'").fetchone()[0])
        p['context']['scenes']['p']['id']='phase'
        s.db.execute("UPDATE proposals SET payload=? WHERE id='earlier'",(json.dumps(p),));s.db.commit()
        html=detail_page(s,'earlier','token','human')
        assert '当前已有选项' in html and '额外聊天' in html and '推进主线' in html
        assert 'value="approve"' in html

def test_overview_does_not_count_finished_input_as_pending_research(tmp_path):
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        payload=json.loads(s.db.execute("SELECT payload FROM proposals WHERE id='research'").fetchone()[0]);payload['context']['review_round']='round'
        s.db.execute("INSERT INTO proposals(id,payload,status) VALUES(?,?,'revision_submitted')",('input',json.dumps(payload)))
        s.db.execute("UPDATE proposals SET status='approved' WHERE id='earlier'");s.db.commit()
        body=list_page(s,{'status':['awaiting_revision']})
        assert '<strong>1</strong>待审核 · 研究/待补全' in body
        assert '<strong>1</strong>待审核 · 具体修改' in body
        assert '当前筛选：等待修改，匹配 0 项' in body and '查看待审核申请' in body

def test_input_url_resolves_to_real_application_with_history_escape(tmp_path):
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        p=json.loads(s.db.execute("SELECT payload FROM proposals WHERE id='earlier'").fetchone()[0]);p['context']['review_round']='round'
        s.db.execute("UPDATE proposals SET payload=?,status='revision_submitted' WHERE id='earlier'",(json.dumps(p),))
        ctx=p['context'].copy();ctx['parent_proposal']='earlier';job=s.job(2,'human_feedback:test',ctx)
        child=json.loads(json.dumps(p));child['context']=ctx
        s.db.execute('INSERT INTO proposals(id,job,payload) VALUES(?,?,?)',('actual',job,json.dumps(child)))
        s.db.execute("UPDATE jobs SET status='done' WHERE id=?",(job,))
        s.db.execute("INSERT INTO review_comments(proposal,reviewer,comment,action,job,at) VALUES('earlier','test','input','rerun',?,1)",(job,));s.db.commit()
    server=make_server(path,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base='http://127.0.0.1:'+str(server.server_address[1])
        response=urllib.request.urlopen(base+'/?id=earlier');assert response.geturl()==base+'/?id=actual'
        history=urllib.request.urlopen(base+'/?id=earlier&history=1').read().decode()
        assert '解析器输入历史，不是另一份待审申请' in history
    finally:server.shutdown();server.server_close();thread.join()

def test_detail_navigation_stays_in_current_scope_after_approval(tmp_path):
    import re,html
    from urllib.parse import parse_qs,urlparse
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        query={'tab':['changes'],'status':['pending'],'chapter':['100001'],'mission':['混乱行至深处'],'q':['画像']}
        # Both concrete fixtures share this label. The research fixture must
        # never appear among previous/next links, even after current approval.
        listing=list_page(s,query)
        assert 'select name="status"' not in listing and 'select name="view"' not in listing
        links=re.findall(r'href="([^"]+)"',listing)
        concrete=next(html.unescape(link) for link in links if 'id=earlier' in link)
        assert parse_qs(urlparse(concrete).query)['tab']==['changes']
        s.db.execute("UPDATE proposals SET status='approved' WHERE id='earlier'");s.db.commit()
        detail=detail_page(s,'earlier','token','human',filter_query=query)
        nav=detail.rsplit('<nav class="nav">',1)[1]
        assert 'id=later' in nav and 'id=research' not in nav
        target=html.unescape(re.search(r'href="([^"]+)"',nav)[1]);params=parse_qs(urlparse(target).query)
        for key,value in query.items():assert params[key]==value
        scoped=detail_page(s,'earlier','token','human',filter_query={**query,'section':['进入空间站']})
        assert '下一片段' not in scoped.rsplit('<nav class="nav">',1)[1]

def test_default_and_all_status_navigation_skip_approved(tmp_path):
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        s.db.execute("UPDATE proposals SET status='approved' WHERE id='later'");s.db.commit()
        for query in [None,{'tab':['changes'],'status':['all']}]:
            body=detail_page(s,'earlier','token','human',filter_query=query)
            nav=body.rsplit('<nav class="nav">',1)[1]
            assert 'id=later' not in nav and 'id=research' not in nav


def test_stale_next_link_rechecks_state_and_does_not_open_processed(tmp_path):
    from urllib.parse import parse_qs,urlparse
    path=tmp_path/'audit.sqlite';seed(path)
    with AuditStore(path) as s:
        s.db.execute("UPDATE proposals SET status='approved' WHERE id='earlier'");s.db.commit()
    server=make_server(path,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base='http://127.0.0.1:'+str(server.server_address[1])
        stale=base+'/?id=earlier&tab=changes&status=pending&nav=next'
        response=urllib.request.urlopen(stale)
        assert parse_qs(urlparse(response.geturl()).query)['id']==['later']
        with AuditStore(path) as s:s.db.execute("UPDATE proposals SET status='approved' WHERE id='later'");s.db.commit()
        response=urllib.request.urlopen(stale)
        assert 'id' not in parse_qs(urlparse(response.geturl()).query)
        assert '匹配 0 项' in response.read().decode()
    finally:server.shutdown();server.server_close();thread.join()
