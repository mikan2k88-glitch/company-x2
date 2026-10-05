"""Password-protected sandbox HTTP application. No payments or outreach."""
import argparse
import base64
import json
import logging
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .csv_service import MAX_BYTES
from .discovery import qualify
from .settings import build_store
from .supabase_store import StorageUnavailable
from .worker import process_one

WEB = Path(__file__).parent / 'web.html'


def handler_for(store, admin_token, *, allowed_hosts=(), access_password=None):
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
            expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}', *allowed_hosts}
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            return host in expected and (not origin or origin in {f'{scheme}://{h}' for h in expected for scheme in ('http','https')})

        def access_allowed(self):
            if not access_password:
                return True
            auth = self.headers.get('Authorization', '')
            try:
                decoded = base64.b64decode(auth[6:], validate=True).decode() if auth.startswith('Basic ') else ''
                password = decoded.split(':', 1)[1] if ':' in decoded else ''
            except (ValueError, UnicodeError):
                password = ''
            if secrets.compare_digest(password.encode(), access_password.encode()):
                return True
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Company X2 Trial"')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False

        def token(self):
            if self.headers.get('X-Order-Token'):
                return self.headers['X-Order-Token']
            auth = self.headers.get('Authorization', '')
            return auth[7:] if auth.startswith('Bearer ') else ''

        def do_GET(self):
            try:
                self.get_response()
            except StorageUnavailable:
                self.respond(503, {'error': 'Storage unavailable; retry later'})
            except Exception:
                logging.exception('GET failed')
                self.respond(500, {'error': 'Internal error'})

        def get_response(self):
            if not self.allowed_host():
                return self.respond(403, {'error': 'Host or origin rejected'})
            path = urlparse(self.path).path
            if path == '/api/health':
                if not store.ping():
                    return self.respond(503, {'status': 'storage_unavailable'})
                return self.respond(200, {'status': 'ok', 'endpoint': 'E02', 'mode': 'sandbox',
                    'storage': 'supabase' if hasattr(store, 'rpc') else 'sqlite',
                    'payments_enabled': False, 'outreach_enabled': False, 'ai_connected': False})
            if not self.access_allowed():
                return
            if path == '/':
                return self.respond(200, WEB.read_bytes(), 'text/html; charset=utf-8')
            if path == '/api/opportunities':
                if not secrets.compare_digest(self.headers.get('X-Admin-Token', self.token()), admin_token):
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
            if not self.access_allowed():
                return
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
                    if not secrets.compare_digest(self.headers.get('X-Admin-Token', self.token()), admin_token):
                        return self.respond(401, {'error': 'Admin token required'})
                    decision, reason = qualify(data)
                    store.save_opportunity(data, decision, reason)
                    return self.respond(200, {'decision': decision, 'reason': reason, 'proposal_sent': False})
                return self.respond(404, {'error': 'Not found'})
            except StorageUnavailable:
                return self.respond(503, {'error': 'Storage unavailable; retry with the same request key'})
            except (ValueError, UnicodeError, TimeoutError) as exc:
                return self.respond(400, {'error': str(exc)[:200]})
            except Exception:
                logging.exception('Request failed')
                return self.respond(500, {'error': 'Internal error'})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8080')))
    parser.add_argument('--host', default='0.0.0.0' if os.environ.get('RENDER') else '127.0.0.1')
    parser.add_argument('--db', default='work/company-x2.db')
    args = parser.parse_args()
    public = args.host not in ('127.0.0.1', 'localhost')
    password = os.environ.get('APP_ACCESS_TOKEN')
    admin_token = os.environ.get('ADMIN_TOKEN') or secrets.token_urlsafe(32)
    hosts = [v.strip() for v in os.environ.get('ALLOWED_HOSTS', '').split(',') if v.strip()]
    if os.environ.get('RENDER_EXTERNAL_HOSTNAME'):
        hosts.append(os.environ['RENDER_EXTERNAL_HOSTNAME'])
    if public and (not password or len(password) < 32 or not hosts):
        raise ValueError('Public trial requires APP_ACCESS_TOKEN (32+ chars) and ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME')
    store = build_store(local_path=args.db)
    if not store.ping():
        raise ValueError('Storage schema check failed')
    stop = threading.Event()
    # Bind before recovery, so a second instance cannot reset an active worker on this port.
    server = ThreadingHTTPServer((args.host, args.port), handler_for(store, admin_token,
        allowed_hosts=hosts, access_password=password if public else None))
    server.daemon_threads = True
    store.recover()
    def worker():
        while not stop.is_set():
            try:
                if not process_one(store):
                    stop.wait(2 if hasattr(store, 'rpc') else 0.25)
            except Exception:
                logging.error('Worker unavailable; retrying without logging request data')
                stop.wait(5)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    print(f'Company X2 E02 sandbox listening on {args.host}:{server.server_port}', flush=True)
    if not public:
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
