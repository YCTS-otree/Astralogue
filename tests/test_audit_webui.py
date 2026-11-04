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
        assert 'value="acknowledge"' in research


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
        assert '<script>' not in body and '&lt;script&gt;' in body


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
            return urllib.request.urlopen(urllib.request.Request(base,data=urllib.parse.urlencode(values).encode()))
        with pytest.raises(urllib.error.HTTPError) as error:bulk(['earlier','research'],'approve')
        assert error.value.code==400
        with AuditStore(path) as s:
            assert s.db.execute("SELECT status FROM proposals WHERE id='earlier'").fetchone()[0]=='pending'
        bulk(['earlier','later'],'approve').close()
        with AuditStore(path) as s:
            assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='approved'").fetchone()[0]==2
        bulk(['earlier','later'],'reject').close()
        with AuditStore(path) as s:
            assert s.db.execute("SELECT COUNT(*) FROM proposals WHERE status='rejected'").fetchone()[0]==2
            assert s.db.execute('SELECT COUNT(*) FROM review_log').fetchone()[0]==5
    finally:
        server.shutdown(); server.server_close(); thread.join()
