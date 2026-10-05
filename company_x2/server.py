"""Loopback-only sandbox HTTP application with a durable, single worker."""
import argparse
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .csv_service import MAX_BYTES
from .discovery import qualify
from .store import Store
from .worker import process_one

WEB = Path(__file__).parent / 'web.html'


def handler_for(store, admin_token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log URLs, authorization or customer data.
            logging.info('HTTP %s', args[1] if len(args) > 1 else '')

        def respond(self, status, content, content_type='application/json; charset=utf-8'):
            data = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if content_type.startswith('text/csv'):
                self.send_header('Content-Disposition', 'attachment; filename="company-x2-result.csv"')
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            # Prevent DNS rebinding and cross-origin writes to the local service.
            expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            return host in expected and (not origin or origin in {f'http://{h}' for h in expected})

        def token(self):
            auth = self.headers.get('Authorization', '')
            return auth[7:] if auth.startswith('Bearer ') else ''

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, {'error': 'Host or origin rejected'})
            path = urlparse(self.path).path
            if path == '/':
                return self.respond(200, WEB.read_bytes(), 'text/html; charset=utf-8')
            if path == '/api/health':
                return self.respond(200, {'status': 'ok', 'mode': 'sandbox', 'payments_enabled': False,
                                          'outreach_enabled': False, 'ai_connected': False})
            if path == '/api/opportunities':
                if not secrets.compare_digest(self.token(), admin_token):
                    return self.respond(401, {'error': 'Admin token required'})
                return self.respond(200, {'items': store.opportunities()})
            parts = path.strip('/').split('/')
            if len(parts) in (3, 4) and parts[:2] == ['api', 'orders']:
                order = store.get(parts[2], self.token())
                if not order:
                    return self.respond(404, {'error': 'Order not found'})
                if len(parts) == 4:
                    if parts[3] != 'download' or order['status'] != 'ready':
                        return self.respond(409, {'error': 'Artifact unavailable'})
                    return self.respond(200, order['result']['csv'].encode('utf-8-sig'), 'text/csv; charset=utf-8')
                if order['result']:
                    order['result'] = {k: v for k, v in order['result'].items() if k != 'csv'}
                return self.respond(200, order)
            return self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            self.connection.settimeout(10)
            if not self.allowed_host():
                return self.respond(403, {'error': 'Host or origin rejected'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BYTES * 6 + 4096:
                    return self.respond(413, {'error': 'Request size rejected'})
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.respond(415, {'error': 'JSON required'})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Object required')
                path = urlparse(self.path).path
                if path == '/api/orders':
                    if data.get('terms_accepted') is not True:
                        raise ValueError('Sandbox service terms must be accepted')
                    text, key, token = data.get('csv'), data.get('request_key'), self.token()
                    if not isinstance(text, str) or not isinstance(key, str) or len(text.encode()) > MAX_BYTES:
                        raise ValueError('CSV input limit exceeded or invalid request')
                    order_id = store.submit(text, key, token)
                    return self.respond(202, {'id': order_id, 'mode': 'sandbox', 'revenue_jpy': 0})
                if path == '/api/opportunities':
                    if not secrets.compare_digest(self.token(), admin_token):
                        return self.respond(401, {'error': 'Admin token required'})
                    decision, reason = qualify(data)
                    store.save_opportunity(data, decision, reason)
                    return self.respond(200, {'decision': decision, 'reason': reason, 'proposal_sent': False})
                return self.respond(404, {'error': 'Not found'})
            except (ValueError, UnicodeError, TimeoutError) as exc:
                return self.respond(400, {'error': str(exc)[:200]})
            except Exception:
                logging.exception('Request failed')
                return self.respond(500, {'error': 'Internal error'})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--db', default='work/company-x2.db')
    args = parser.parse_args()
    store = Store(args.db)
    admin_token = secrets.token_urlsafe(32)
    stop = threading.Event()
    # Bind before recovery, so a second instance cannot reset an active worker on this port.
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(store, admin_token))
    server.daemon_threads = True
    store.recover()
    def worker():
        while not stop.is_set():
            try:
                if not process_one(store):
                    stop.wait(0.25)
            except Exception:
                logging.exception('Worker error')
                stop.wait(1)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    print(f'Company X2 sandbox: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Local discovery admin token: {admin_token}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
