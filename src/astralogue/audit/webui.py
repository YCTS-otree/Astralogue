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

        def send(self, status, body):
            raw = body.encode('utf8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
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
                body = detail_page(store, pid, token, store.setting('webui_reviewer') or '') if pid else list_page(store, query)
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
                    self.send(403, 'Invalid CSRF token')
                    return
                pid, action, reviewer = data['id'][0], data['action'][0], data['reviewer'][0]
                suggestion = json.loads(data['suggestion'][0]) if action == 'edit' else None
                with AuditStore(path) as store:
                    current = next((r for r in ordered(store) if r['row']['id'] == pid), None)
                    if not current:
                        raise ValueError('未找到这份提案')
                    if action == 'approve' and not current['ready']:
                        raise ValueError('这项尚未绑定完整的具体修改位置，请暂缓或记为已阅。')
                    review(store, pid, action, reviewer, suggestion)
                    store.setting('webui_reviewer', reviewer)
                self.send_response(303)
                self.send_header('Location', '/?id=' + urllib.parse.quote(pid, safe=''))
                self.end_headers()
            except (ValueError, KeyError) as error:
                self.send(400, page('<h1>未保存这次操作</h1><p>' + esc(error) + '</p><a href="/">返回列表</a>'))

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(path, port=8340):
    server = make_server(path, port)
    print(f'剧情审核管理器：http://127.0.0.1:{server.server_address[1]}', flush=True)
    server.serve_forever()
