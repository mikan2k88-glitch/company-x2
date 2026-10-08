"""Bounded public GitHub reads with safe, actionable source diagnostics."""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from .supabase_store import NoRedirect, StorageUnavailable

MAX_RESPONSE = 2_000_000


class GitHubUnavailable(StorageUnavailable):
    def __init__(self, stage, reason, *, status=None, retry_after=300):
        self.stage, self.reason, self.status = stage, reason, status
        self.retry_after = max(60, min(7200, retry_after))
        super().__init__('GitHub ' + stage + ': ' + reason + (f' (HTTP {status})' if status else ''))

    def diagnostic(self):
        return {'source':'github', 'stage':self.stage, 'reason':self.reason,
                'http_status':self.status, 'retry_after_seconds':self.retry_after}


def read_json(url, stage, *, opener=None, timeout=20):
    # URLs are built by callers from fixed API routes and validated public IDs.
    if not url.startswith('https://api.github.com/'):
        raise ValueError('Only the GitHub API is supported')
    headers={'Accept':'application/vnd.github+json', 'User-Agent':'Company-X2-scout',
             'X-GitHub-Api-Version':'2022-11-28'}
    token=os.environ.get('GITHUB_SCOUT_TOKEN','').strip()
    if token:
        if '\r' in token or '\n' in token:
            raise GitHubUnavailable(stage,'invalid_source_configuration')
        headers['Authorization']='Bearer '+token
    request=urllib.request.Request(url,headers=headers)
    try:
        with (opener or urllib.request.build_opener(NoRedirect()).open)(request,timeout=timeout) as response:
            raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:
            raise GitHubUnavailable(stage,'response_too_large')
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        response_headers=exc.headers or {}
        delay=300
        for header in ('Retry-After','X-RateLimit-Reset'):
            try:
                value=int(response_headers.get(header,'0'))
                if header=='X-RateLimit-Reset':
                    value-=int(datetime.now(timezone.utc).timestamp())
                delay=max(delay,value)
            except (ValueError,TypeError,AttributeError):
                pass
        limited=exc.code==429 or (exc.code==403 and (
            response_headers.get('X-RateLimit-Remaining')=='0' or response_headers.get('Retry-After')))
        reason='rate_limited' if limited else 'access_denied' if exc.code in (401,403) else 'not_found' if exc.code in (404,410) else 'http_error'
        raise GitHubUnavailable(stage,reason,status=exc.code,retry_after=delay) from None
    except (OSError,ValueError,UnicodeError):
        raise GitHubUnavailable(stage,'connection_or_invalid_response') from None
