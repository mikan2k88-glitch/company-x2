"""Server-only Supabase RPC adapter. Never falls back to local storage."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse
from .store import Store
from .data_services import require_service


class StorageUnavailable(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward server secrets to a redirect target.
        raise urllib.error.URLError('Supabase redirect rejected')


class SupabaseStore:
    digest = staticmethod(Store.digest)

    def __init__(self, url, key, *, opener=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('SUPABASE_URL must be an HTTPS project root')
        if not key or key.startswith('sb_publishable_'):
            raise ValueError('Server secret or legacy service-role key required')
        self.url = url.rstrip('/') + '/rest/v1/rpc/cx2_store'
        self.key = key
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def rpc(self, action, payload=None, *, endpoint='cx2_store'):
        if endpoint not in ('cx2_store', 'cx2_scout', 'cx2_services', 'cx2_company', 'cx2_support','cx2_case','cx2_support_auto','cx2_outreach'):
            raise ValueError('Unknown RPC endpoint')
        headers = {'Content-Type': 'application/json', 'apikey': self.key}
        if not self.key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + self.key
        url = self.url.rsplit('/', 1)[0] + '/' + endpoint
        req = urllib.request.Request(url, data=json.dumps({'p_action': action, 'p_payload': payload or {}}).encode(),
                                     headers=headers, method='POST')
        try:
            with self.opener(req, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            # Never log bodies: they may include inputs or credential details.
            if exc.code == 400:
                raise ValueError('Storage rejected request; check input or idempotency key') from None
            hints = {
                401: 'Authentication rejected: verify server key and project URL match',
                403: 'Permission denied: use a server secret/service-role key and verify RPC grant',
                404: 'RPC unavailable: apply ' + {'cx2_store':'002_sandbox_rpc.sql', 'cx2_scout':'003_public_scout.sql',
                    'cx2_services':'004_data_services.sql', 'cx2_company':'009_company.sql', 'cx2_support':'support_inbox migration','cx2_case':'order_support_cases migration','cx2_support_auto':'support_automation migration','cx2_outreach':'external_outbox migration'}[endpoint] + ' in this project and reload the API schema',
                429: 'Supabase rate limit reached; retry later',
            }
            hint = hints.get(exc.code, 'Supabase service failed; verify project availability')
            raise StorageUnavailable(f'Supabase HTTP {exc.code}: {hint}') from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise StorageUnavailable('Supabase unavailable') from None

    def ping(self):
        return self.rpc('ping') == {'schema_version': 2}

    def company_rpc(self, action, payload=None):
        return self.rpc(action, payload, endpoint='cx2_company')

    def support_rpc(self, action, payload=None):
        return self.rpc(action, payload, endpoint='cx2_support')

    def case_rpc(self, action, payload=None):
        return self.rpc(action, payload, endpoint='cx2_case')

    def automation_rpc(self, action, payload=None):
        return self.rpc(action,payload,endpoint='cx2_support_auto')

    def outreach_rpc(self, action, payload=None):
        return self.rpc(action,payload,endpoint='cx2_outreach')

    def services_ready(self):
        return self.rpc('ping', endpoint='cx2_services') == {'schema_version': 4}

    def submit(self, text, request_key, token, service_key='csv_exact_dedup'):
        require_service(service_key)
        if not 16 <= len(request_key) <= 128 or not 32 <= len(token) <= 128:
            raise ValueError('Invalid request key or access token')
        endpoint = 'cx2_store' if service_key == 'csv_exact_dedup' else 'cx2_services'
        return self.rpc('submit', {'input': text, 'request_key': request_key, 'service_key': service_key,
                                  'request_hash': Store.request_digest(text, service_key), 'token_hash': self.digest(token)}, endpoint=endpoint)

    def claim(self):
        legacy = self.rpc('claim')
        if legacy:
            return {**legacy, 'service_key': 'csv_exact_dedup'}
        try:
            return self.rpc('claim', endpoint='cx2_services')
        except StorageUnavailable as exc:
            # 004 may not yet be applied during a rolling upgrade. Keep old orders working.
            if 'HTTP 404:' in str(exc):
                return None
            raise

    def finish(self, order_id, *, result=None, error=None, lease=None):
        self.rpc('finish', {'id': order_id, 'result': result, 'error': error, 'lease': lease},
                 endpoint='cx2_services' if order_id.startswith('svc_') else 'cx2_store')

    def recover(self):
        # Cloud claims have expiring leases. Do not reset another deployment's active work.
        pass

    def get(self, order_id, token):
        result = self.rpc('get', {'id': order_id, 'token_hash': self.digest(token)},
                          endpoint='cx2_services' if order_id.startswith('svc_') else 'cx2_store')
        if result and 'service_key' not in result:
            result['service_key'] = 'csv_exact_dedup'
        return result

    def save_opportunity(self, candidate, decision, reason):
        self.rpc('opportunity', {'candidate': candidate, 'decision': decision, 'reason': reason})

    def opportunities(self):
        return self.rpc('opportunities')

    def claim_scan(self):
        return self.rpc('claim', endpoint='cx2_scout')

    def finish_scan(self, lease, *, items=None, report=None, error=None, delay=3600):
        return self.rpc('finish', {'lease': lease, 'items': items, 'report': report,
                                  'error': error, 'delay': delay}, endpoint='cx2_scout')

    def scan_snapshot(self):
        return self.rpc('snapshot', endpoint='cx2_scout')
