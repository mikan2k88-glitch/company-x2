"""Server-only Supabase RPC adapter. Never falls back to local storage."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse
from .store import Store


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

    def rpc(self, action, payload=None):
        headers = {'Content-Type': 'application/json', 'apikey': self.key}
        if not self.key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + self.key
        req = urllib.request.Request(self.url, data=json.dumps({'p_action': action, 'p_payload': payload or {}}).encode(),
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
                403: 'Permission denied: use a server secret/service-role key and verify cx2_store grant',
                404: 'RPC unavailable: apply 002_sandbox_rpc.sql in this project and reload the API schema',
                429: 'Supabase rate limit reached; retry later',
            }
            hint = hints.get(exc.code, 'Supabase service failed; verify project availability')
            raise StorageUnavailable(f'Supabase HTTP {exc.code}: {hint}') from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise StorageUnavailable('Supabase unavailable') from None

    def ping(self):
        return self.rpc('ping') == {'schema_version': 2}

    def submit(self, text, request_key, token):
        if not 16 <= len(request_key) <= 128 or not 32 <= len(token) <= 128:
            raise ValueError('Invalid request key or access token')
        return self.rpc('submit', {'input': text, 'request_key': request_key,
                                  'request_hash': self.digest(text), 'token_hash': self.digest(token)})

    def claim(self):
        return self.rpc('claim')

    def finish(self, order_id, *, result=None, error=None, lease=None):
        self.rpc('finish', {'id': order_id, 'result': result, 'error': error, 'lease': lease})

    def recover(self):
        # Cloud claims have expiring leases. Do not reset another deployment's active work.
        pass

    def get(self, order_id, token):
        return self.rpc('get', {'id': order_id, 'token_hash': self.digest(token)})

    def save_opportunity(self, candidate, decision, reason):
        self.rpc('opportunity', {'candidate': candidate, 'decision': decision, 'reason': reason})

    def opportunities(self):
        return self.rpc('opportunities')

