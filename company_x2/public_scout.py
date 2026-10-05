"""Read-only public GitHub discovery. Listings are evidence, never instructions."""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse

from .supabase_store import NoRedirect, StorageUnavailable

QUERY = 'is:issue is:open csv label:bounty in:title,body'
SOURCE = 'github_public_bounty'
LIMIT = 30
MAX_RESPONSE = 2_000_000
INTERVAL = 3600


class SourceUnavailable(RuntimeError):
    pass


def fetch_issues(opener=None):
    url = 'https://api.github.com/search/issues?' + urlencode(
        {'q': QUERY, 'per_page': LIMIT, 'sort': 'updated', 'order': 'desc'})
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'Company-X2-public-scout',
        'X-GitHub-Api-Version': '2022-11-28'}, method='GET')
    try:
        with (opener or urllib.request.build_opener(NoRedirect()).open)(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise SourceUnavailable('募集データが取得上限を超えました')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
            raise ValueError('Invalid search response')
        if payload.get('incomplete_results') is not False:
            raise SourceUnavailable('検索結果が不完全です。時間を置いて再試行します')
        return payload
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise SourceUnavailable('GitHubの取得制限に達しました。時間を置いて再試行します') from None
        raise SourceUnavailable(f'GitHub APIが取得できませんでした（HTTP {exc.code}）') from None
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError):
        raise SourceUnavailable('GitHub APIの接続または応答を確認できませんでした') from None


def normalize(issue, checked_at):
    if not isinstance(issue, dict) or 'pull_request' in issue or issue.get('state') != 'open':
        return None
    url = issue.get('html_url', '')
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*', parsed.path)):
        return None
    if type(issue.get('id')) is not int or not isinstance(issue.get('title'), str):
        return None
    title = issue['title'][:500]
    body = issue.get('body') or ''
    if not isinstance(body, str):
        return None
    # Retain only a bounded excerpt; never follow links or download attachments.
    body = body[:12000]
    labels = [label['name'][:100] for label in issue.get('labels', [])
              if isinstance(label, dict) and isinstance(label.get('name'), str)][:30]
    text = (title + '\n' + body).lower()
    # A currency token is a quoted reward mention, not verified funding or revenue.
    reward = re.search(r'(?:USD\s*|\$|JPY\s*|¥|€|£)\d[\d,]*(?:\.\d{1,2})?(?:\s*[kK]\b)?', title + '\n' + body)
    csv_match = bool(re.search(r'\bcsv\b', text))
    dedup_match = bool(re.search(r'\b(?:deduplicat\w*|dedup|duplicates?|duplicate\s+rows)\b|重複', text))
    trim_match = bool(re.search(r'\b(?:trim|whitespace|leading spaces|trailing spaces)\b|空白', text))
    json_match = bool(re.search(r'csv\s*(?:to|→|から)\s*json|convert.{0,60}csv.{0,60}json', text))
    audit_match = bool(re.search(r'\b(?:audit|data quality|missing values|empty cells|validate csv)\b|データ検査|空欄', text))
    service_keys = [key for key, match in [('csv_exact_dedup',dedup_match),('csv_trim',trim_match),
                    ('csv_to_json',json_match),('csv_audit',audit_match)] if csv_match and match]
    software = bool(re.search(r'\b(?:implement|feature|bug|pull request|codebase|sdk|pipeline|refactor)\b', title.lower()))
    checks = ['報酬の支払い条件と支払者を確認', 'AIによる作業・応募の可否を確認',
              '入力ファイル、期限、サイズと選択サービスの処理条件を確認']
    if issue.get('locked') or issue.get('assignees'):
        decision, reason = 'blocked', '担当者がいる、または募集への参加が制限されています'
    elif not csv_match:
        decision, reason = 'rejected', 'CSV作業の記載がありません'
    elif software:
        decision, reason = 'rejected', 'ソフトウェア改修を要求しており、現在のCSV加工サービスの範囲を超えます'
    elif not reward:
        decision, reason = 'blocked', '報酬額・通貨の記載を確認できません。bountyラベルだけでは有料案件と判断しません'
    elif not service_keys:
        decision, reason = 'rejected', 'CSV関連ですが、重複除去・空白整形・JSON変換・データ検査との適合を確認できません'
    else:
        decision, reason = 'needs_review', 'CSV処理サービスに関連する記載があります。作業範囲・報酬・応募条件は未確認です'
    return {'source': SOURCE, 'external_id': str(issue['id']), 'url': url, 'title': title,
            'description': body, 'labels': labels, 'service_key': service_keys[0] if service_keys else None,
            'service_keys': service_keys,
            'reward_mention': reward.group(0) if reward else None,
            'reward_verified': False, 'automated_proposals_allowed': False,
            'proposal_sent': False, 'source_checked_at': checked_at,
            'source_updated_at': issue.get('updated_at'), 'decision': decision,
            'reason': reason, 'required_checks': checks}


def scan_once(store, *, fetcher=fetch_issues, interval=INTERVAL):
    """A durable lease prevents overlapping deploys from scanning simultaneously."""
    lease = store.claim_scan()
    if not lease:
        return False
    try:
        payload = fetcher()
        checked = datetime.now(timezone.utc).isoformat()
        items = [item for raw in payload['items'][:LIMIT]
                 if (item := normalize(raw, checked)) is not None]
        report = {'query': QUERY, 'total_count': payload.get('total_count'),
                  'collected': len(items), 'needs_review': sum(i['decision'] == 'needs_review' for i in items),
                  'blocked': sum(i['decision'] == 'blocked' for i in items),
                  'rejected': sum(i['decision'] == 'rejected' for i in items),
                  'scope': '最新の最大30件。全募集の網羅検索ではありません', 'checked_at': checked}
    except SourceUnavailable as exc:
        store.finish_scan(lease, error=str(exc), delay=300)
        return True
    except Exception:
        store.finish_scan(lease, error='募集データの検証に失敗しました。次回再試行します', delay=300)
        return True
    # Storage failure must not turn a failed/partial save into a successful scan.
    store.finish_scan(lease, items=items, report=report, delay=interval)
    return True


def snapshot(store, *, enabled=True):
    if not enabled:
        return {'status': 'disabled', 'items': [], 'error': None, 'report': None}
    try:
        return store.scan_snapshot()
    except StorageUnavailable:
        return {'status': 'setup_required', 'items': [], 'report': None,
                'error': '探索用DBに接続できません。003_public_scout.sqlの適用と接続設定を確認してください'}
