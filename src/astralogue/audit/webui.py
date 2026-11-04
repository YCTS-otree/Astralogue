"""Loopback transport for the passage-oriented human review manager."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import urllib.parse
from .store import AuditStore
from .review import review
from .pages import page, list_page, detail_page, ordered
from .presentation import esc


def make_server(path, port=8340):
    with AuditStore(path) as store:
        token = store.setting('webui_csrf') or secrets.token_urlsafe(32)
        store.setting('webui_csrf', token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, content_type="text/html; charset=utf-8"):
            raw = body.encode('utf8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            actual_port = self.server.server_address[1]
            return self.headers.get('Host') in {f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'}

        def do_GET(self):
            if not self.valid_host():
                self.send(403, 'Invalid host')
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            pid = query.get('id', [None])[0]
            with AuditStore(path) as store:
                body = detail_page(store, pid, token, store.setting('webui_reviewer') or '', min(100,max(3,int(query.get('context',['3'])[0]))) if query.get('context',['3'])[0].isdigit() else 3) if pid else list_page(store, query)
            self.send(200 if body else 404, body or page('<h1>未找到这份提案</h1>'))

        def do_POST(self):
            if not self.valid_host():
                self.send(403, 'Invalid host')
                return
            actual_port = self.server.server_address[1]
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{actual_port}', f'http://localhost:{actual_port}'}:
                self.send(403, 'Invalid origin')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length < 1024 * 1024:
                    raise ValueError('Invalid request size')
                data = urllib.parse.parse_qs(self.rfile.read(length).decode('utf8'))
                if not secrets.compare_digest(data.get('csrf', [''])[0], token):
                    self.send(403, json.dumps({'message':'页面验证已失效，请刷新后重试。'},ensure_ascii=False), 'application/json; charset=utf-8')
                    return
                ids = list(dict.fromkeys(data.get('ids', data.get('id', []))))
                if not ids or len(ids)>40:raise ValueError('请选择 1–40 项')
                pid, action, reviewer = ids[0], data['action'][0], data['reviewer'][0]
                if len(ids)>1 and action not in {'approve','reject'}:raise ValueError('不支持的批量操作')
                if len(data.get('comment',[''])[0])>12000:raise ValueError('评论超过长度限制')
                suggestion = json.loads(data['suggestion'][0]) if action == 'edit' else None
                with AuditStore(path) as store:
                    rows={r['row']['id']:r for r in ordered(store)}
                    for selected_id in ids:
                        current=rows.get(selected_id)
                        if not current:raise ValueError('未找到提案')
                        if action=='approve' and not current['ready']:raise ValueError('所选项包含尚无具体修改位置的提案；本批次未保存。')
                    if action in {'request_changes','research_approve'}:
                        if len(ids)!=1:raise ValueError('评论修订请逐项提交')
                        from .feedback import submit_feedback
                        submit_feedback(store,pid,action,reviewer,data.get('comment',[''])[0],data.get('provider',['local'])[0])
                    else:
                        with store.db:
                            for selected_id in ids:
                                review(store, selected_id, action, reviewer, suggestion)
                                comment=data.get('comment',[''])[0].strip()
                                if comment:
                                    if len(comment)>12000:raise ValueError('评论超过长度限制')
                                    import time
                                    store.db.execute('INSERT INTO review_comments(proposal,reviewer,comment,action,job,at) VALUES(?,?,?,?,NULL,?)',(selected_id,reviewer,comment,action,time.time()))
                    store.setting('webui_reviewer', reviewer)
                if 'application/json' in self.headers.get('Accept',''):
                    label={'approve':'通过','reject':'驳回','defer':'暂缓','acknowledge':'记为已阅','edit':'保存修改','request_changes':'提交修改意见，等待模型修订','research_approve':'提交研究方向，等待模型生成具体修改'}[action]
                    self.send(200,json.dumps({'message':f'提交成功：已{label} {len(ids)} 项，审核记录已保存。','count':len(ids)},ensure_ascii=False),'application/json; charset=utf-8')
                    return
                self.send_response(303)
                self.send_header('Location', ('/' if 'ids' in data else '/?id=' + urllib.parse.quote(pid, safe='')))
                self.end_headers()
            except (ValueError, KeyError) as error:
                if 'application/json' in self.headers.get('Accept',''):
                    self.send(400,json.dumps({'message':'提交失败：'+str(error)},ensure_ascii=False),'application/json; charset=utf-8')
                    return
                self.send(400, page('<h1>未保存这次操作</h1><p>' + esc(error) + '</p><a href="/">返回列表</a>'))

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(path, port=8340):
    server = make_server(path, port)
    print(f'剧情审核管理器：http://127.0.0.1:{server.server_address[1]}', flush=True)
    import threading
    from .feedback import worker
    stop=threading.Event()
    threading.Thread(target=worker,args=(path,stop),daemon=True).start()
    try:server.serve_forever()
    finally:stop.set();server.server_close()
