#!/usr/bin/env python3
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

STATIC = Path(__file__).resolve().parent / 'static'


def make_server(workspace, host='0.0.0.0', port=8080):
    workspace = Path(workspace).resolve()

    class Handler(BaseHTTPRequestHandler):
        def send_data(self, content, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            parts = [unquote(p) for p in urlsplit(self.path).path.split('/') if p]
            try:
                if parts in ([], ['app.js'], ['style.css']):
                    name = parts[0] if parts else 'index.html'
                    kind = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
                    return self.send_data((STATIC / name).read_bytes(), kind + '; charset=utf-8')
                if parts == ['api', 'cases']:
                    cases = []
                    for file in sorted(workspace.glob('osint-*/case.json'), reverse=True):
                        if file.resolve().parent.parent != workspace:
                            continue
                        try:
                            case = json.loads(file.read_text(encoding='utf-8'))
                            case['id'] = file.parent.name
                            cases.append(case)
                        except (OSError, ValueError):
                            continue
                    return self.send_data(json.dumps(cases).encode(), 'application/json; charset=utf-8')
                if len(parts) == 5 and parts[:2] == ['api', 'cases'] and parts[3] == 'evidence':
                    name, filename = parts[2], parts[4]
                    if not name.startswith('osint-') or Path(name).name != name or Path(filename).name != filename:
                        raise ValueError('invalid path')
                    case = (workspace / name).resolve()
                    if case.parent != workspace:
                        raise ValueError('invalid case')
                    data = json.loads((case / 'case.json').read_text(encoding='utf-8'))
                    allowed = {s[key] for s in data['scans'] for key in ('output', 'structured_output') if s.get(key)}
                    if filename not in allowed:
                        raise ValueError('unlisted evidence')
                    evidence = (case / filename).resolve()
                    if evidence.parent != case:
                        raise ValueError('invalid evidence')
                    return self.send_data(evidence.read_bytes(), 'text/plain; charset=utf-8')
            except (OSError, ValueError, KeyError, TypeError):
                pass
            self.send_error(404)

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == '__main__':
    make_server(os.environ.get('WORKSPACE', '/workspace'), port=int(os.environ.get('PORT', '8080'))).serve_forever()
