"""Small loopback-only service for reproducible TestHub demonstrations."""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/login':
            self.reply(200, {'token': 'demo-session-token', 'user_id': 7})
        else:
            self.reply(404, {'error': 'not_found'})

    def do_GET(self):
        if self.path == '/profile':
            if self.headers.get('Authorization') != 'Bearer demo-session-token':
                self.reply(401, {'error': 'unauthorized'})
            else:
                self.reply(200, {'user': {'id': 7, 'name': 'TestHub Demo'}})
        elif self.path == '/slow':
            time.sleep(6)
            self.reply(200, {'ready': True})
        elif self.path == '/health':
            self.reply(200, {'status': 'ok'})
        else:
            self.reply(404, {'error': 'not_found'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1', help='Bind address; use 0.0.0.0 only inside the isolated verification network')
    parser.add_argument('--port', type=int, default=8089)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), DemoHandler).serve_forever()
