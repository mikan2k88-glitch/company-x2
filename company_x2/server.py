"""Password-protected sandbox with optional AI and Stripe test reconciliation."""
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
from .github_source import GitHubUnavailable
from .intake_access import valid as valid_intake, permits as intake_permits
from .worker import process_one
from .public_scout import scan_once, snapshot
from .data_services import SERVICES, require_service
from .planner import REQUESTS, plan_request
from .ai_planner import AIPlanner
from .payments import Payments
from .company import process_transaction
from .company_http import get_route as company_get, post_route as company_post

WEB = Path(__file__).parent / 'web.html'


def handler_for(store, admin_token, *, allowed_hosts=(), access_password=None, scout_enabled=True, ai=None, payments=None, agent_token=None):
    ai, payments = ai or AIPlanner(), payments or Payments()
    class Handler(BaseHTTPRequestHandler):
        intake_signing_key=access_password or admin_token
        def log_message(self, fmt, *args):
            # Do not log URLs, authorization or customer data.
            logging.info('HTTP %s', args[1] if len(args) > 1 else '')

        def respond(self, status, content, content_type='application/json; charset=utf-8', filename=None):
            data = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
            elif content_type.startswith('text/csv'):
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
            path=urlparse(self.path).path
            if intake_permits(self.command,path) and valid_intake(self.headers.get('X-Intake-Access',''),access_password or admin_token):
                return True
            if intake_permits(self.command,path) and self.headers.get('X-Intake-Access'):
                self.respond(401,{'error':'受付リンクの期限切れ、または無効なリンクです。新しいリンクが必要です'})
                return False
            if urlparse(self.path).path == '/api/company/agent-scout' and agent_token and len(agent_token)>=32:
                auth=self.headers.get('Authorization','')
                if auth.startswith('Bearer ') and secrets.compare_digest(auth[7:].encode(),agent_token.encode()):
                    return True
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
                return self.respond(200, {'status': 'ok', 'endpoint': 'E16', 'mode': 'sandbox',
                    'storage': 'supabase' if hasattr(store, 'rpc') else 'sqlite',
                    'payments_enabled': False, 'outreach_enabled': False, 'ai_connected': False})
            if path == '/intake':
                return self.respond(200, (WEB.parent / 'intake.html').read_bytes(), 'text/html; charset=utf-8')
            if not self.access_allowed():
                return
            if path == '/':
                return self.respond(200, WEB.read_bytes(), 'text/html; charset=utf-8')
            if path == '/company':
                return self.respond(200, (WEB.parent / 'company.html').read_bytes(), 'text/html; charset=utf-8')
            if company_get(self,path,store,ai,payments,scout_enabled):
                return
            if path == '/api/scout':
                return self.respond(200, snapshot(store, enabled=scout_enabled))
            if path == '/api/plans':
                return self.respond(200, {'examples': [{'service_key': key, 'request': values[0]}
                    for key, values in REQUESTS.items()], 'planner': 'deterministic', 'ai_connected': False})
            if path == '/api/services':
                try:
                    ready = store.services_ready()
                except (StorageUnavailable, ValueError):
                    ready = False
                return self.respond(200, {'items': [{'key': key, **service,
                    'available': ready or key == 'csv_exact_dedup'} for key, service in SERVICES.items()],
                    'error': None if ready else '追加サービス用SQL（004_data_services.sql）の適用と接続設定を確認してください。'})
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
                    service_key = order.get('service_key', 'csv_exact_dedup')
                    if 'artifact' in order['result']:
                        artifact = order['result']['artifact']
                        # Metadata comes from a fixed service catalog, never raw HTTP inputs.
                        from .data_services import make_artifact
                        trusted = make_artifact(artifact['content'], service_key)
                        encoding = 'utf-8-sig' if SERVICES[service_key]['format'] == 'csv' else 'utf-8'
                        return self.respond(200, trusted['content'].encode(encoding), trusted['content_type'],
                                            filename='company-x2-result.csv' if service_key == 'csv_exact_dedup' else trusted['filename'])
                    return self.respond(200, order['result']['csv'].encode('utf-8-sig'), 'text/csv; charset=utf-8')
                if order['result']:
                    order['result'] = {k: v for k, v in order['result'].items() if k != 'csv'}
                    if 'artifact' in order['result']:
                        order['result']['artifact'] = {k: v for k, v in order['result']['artifact'].items() if k != 'content'}
                return self.respond(200, order)
            return self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            self.connection.settimeout(10)
            if not self.allowed_host():
                return self.respond(403, {'error': 'Host or origin rejected'})
            path = urlparse(self.path).path
            if path == '/api/payments/webhook':
                try:
                    size = int(self.headers.get('Content-Length','0'))
                    if not 0 < size <= 200_000:
                        return self.respond(413,{'error':'Webhook size rejected'})
                    raw = self.rfile.read(size)
                    event = payments.signed_event(raw,self.headers.get('Stripe-Signature',''))
                    return self.respond(200,payments.apply_event(store,event))
                except StorageUnavailable:
                    return self.respond(503,{'error':'Storage unavailable; retry event'})
                except (ValueError,TypeError,TimeoutError):
                    return self.respond(400,{'error':'Webhook evidence rejected'})
                except Exception:
                    logging.error('Webhook processing unavailable')
                    return self.respond(500,{'error':'Webhook processing unavailable; retry event'})
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
                if company_post(self,path,data,store,ai,payments):
                    return
                if path in ('/api/plans', '/api/plans/run'):
                    plan = plan_request(data.get('request'), data.get('csv'))
                    if plan['service_key'] != 'csv_exact_dedup' and not store.services_ready():
                        raise ValueError('004_data_services.sqlの適用と接続設定を確認してください')
                    if path == '/api/plans':
                        return self.respond(200, {'plan': plan, 'submitted': False})
                    if data.get('terms_accepted') is not True:
                        raise ValueError('作業計画と無料検証条件への同意が必要です')
                    digest = data.get('plan_sha256')
                    if (not isinstance(digest, str) or len(digest) != 64
                            or any(c not in '0123456789abcdef' for c in digest)
                            or not secrets.compare_digest(digest, plan['plan_sha256'])):
                        raise ValueError('依頼か入力が変更されました。作業計画を作り直してください')
                    key = data.get('request_key')
                    if not isinstance(key, str):
                        raise ValueError('Request key required')
                    order_id = store.submit(data['csv'], key, self.token(), plan['service_key'])
                    return self.respond(202, {'id': order_id, 'service_key': plan['service_key'],
                        'plan_sha256': plan['plan_sha256'], 'mode': 'sandbox', 'revenue_jpy': 0})
                if path == '/api/orders':
                    if data.get('terms_accepted') is not True:
                        raise ValueError('Sandbox service terms must be accepted')
                    text, key, token = data.get('csv'), data.get('request_key'), self.token()
                    if not isinstance(text, str) or not isinstance(key, str) or len(text.encode()) > MAX_BYTES:
                        raise ValueError('CSV input limit exceeded or invalid request')
                    service_key = require_service(data.get('service_key', 'csv_exact_dedup'))
                    order_id = store.submit(text, key, token, service_key)
                    return self.respond(202, {'id': order_id, 'mode': 'sandbox', 'revenue_jpy': 0})
                if path == '/api/opportunities':
                    if not secrets.compare_digest(self.headers.get('X-Admin-Token', self.token()), admin_token):
                        return self.respond(401, {'error': 'Admin token required'})
                    decision, reason = qualify(data)
                    store.save_opportunity(data, decision, reason)
                    return self.respond(200, {'decision': decision, 'reason': reason, 'proposal_sent': False})
                return self.respond(404, {'error': 'Not found'})
            except GitHubUnavailable as exc:
                logging.warning('Scout source unavailable: stage=%s reason=%s status=%s',exc.stage,exc.reason,exc.status)
                return self.respond(503, {'error':'Public source unavailable; checkpoint unchanged',
                                          'diagnostic':exc.diagnostic()})
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
    scout_enabled = os.environ.get('SCOUT_ENABLED', 'true').lower() == 'true'
    if not store.ping():
        raise ValueError('Storage schema check failed')
    stop = threading.Event()
    # Bind before recovery, so a second instance cannot reset an active worker on this port.
    ai, payments = AIPlanner(), Payments()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(store, admin_token,
        allowed_hosts=hosts, access_password=password if public else None, scout_enabled=scout_enabled,ai=ai,payments=payments,agent_token=os.environ.get('AGENT_SCOUT_TOKEN')))
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
    def company_worker():
        while not stop.is_set():
            try:
                if not process_transaction(store):
                    stop.wait(2)
            except Exception:
                logging.warning('Company queue unavailable; legacy orders continue')
                stop.wait(60)
    company_thread = threading.Thread(target=company_worker,daemon=True)
    company_thread.start()
    def payment_worker():
        while not stop.is_set():
            if payments.status()['ready']:
                try:
                    for order in store.company_rpc('pending_payments'):
                        if stop.is_set():
                            break
                        try:
                            payments.reconcile(store,order)
                        except Exception:
                            logging.warning('Test payment reconciliation deferred')
                except Exception:
                    logging.warning('Test payment queue unavailable')
            stop.wait(30)
    payment_thread = threading.Thread(target=payment_worker,daemon=True)
    payment_thread.start()
    def scout_worker():
        while not stop.is_set():
            try:
                scan_once(store)
            except Exception:
                logging.warning('Public scout unavailable; order processing continues')
                stop.wait(300)
                continue
            stop.wait(30)
    scout_thread = threading.Thread(target=scout_worker, daemon=True) if scout_enabled else None
    if scout_thread:
        scout_thread.start()
    print(f'Company X2 E16 sandbox listening on {args.host}:{server.server_port}', flush=True)
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
        company_thread.join(timeout=5)
        payment_thread.join(timeout=5)


if __name__ == '__main__':
    main()
