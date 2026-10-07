"""E06-E09 orchestration. Provider evidence is separate from listing claims."""
import hashlib
import json
import re
from datetime import datetime, timezone

from .data_services import SERVICES, produce, verify
from .planner import REQUESTS, plan_request
from .supabase_store import StorageUnavailable


def rank_candidates(items):
    ranked = []
    for original in items:
        item = dict(original)
        services = [key for key in item.get('service_keys', []) if key in SERVICES]
        score = (40 if services else 0) + (20 if item.get('reward_mention') else 0)
        score += 10 if item.get('decision') == 'needs_review' else 0
        blocked = item.get('decision') != 'needs_review'
        item.update(score=score, eligible_for_review=not blocked,
                    execution_allowed=False, auto_bid_allowed=False,
                    missing_evidence=['顧客の依頼と合意', '実際の入力データ', '期限と処理条件', '入金確認'],
                    acquisition_status='unverified_listing')
        ranked.append(item)
    return sorted(ranked, key=lambda item: (-item['score'], item.get('external_id', '')))


def quote(service, text, mode='sandbox'):
    if not isinstance(service,str) or service not in SERVICES or mode not in ('sandbox', 'stripe_test'):
        raise ValueError('対応サービスと検証モードを指定してください')
    plan = plan_request(REQUESTS[service][0], text)
    plan.update(payment_mode=mode, price_jpy=100 if mode == 'stripe_test' else 0,
                currency='jpy', terms_version='e09-v1', test_payment=mode == 'stripe_test')
    plan.pop('plan_sha256')
    plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True,
                                                 separators=(',', ':')).encode()).hexdigest()
    return plan


def validate_creation(data, token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise ValueError('所有者トークンが必要です')
    key = data.get('request_key')
    if not isinstance(key, str) or not 16 <= len(key) <= 128:
        raise ValueError('受付キーを確認してください')
    if data.get('terms_accepted') is not True:
        raise ValueError('処理範囲・料金・検証条件への同意が必要です')
    plan = quote(data.get('service_key'), data.get('csv'), data.get('payment_mode', 'sandbox'))
    if data.get('plan_sha256') != plan['plan_sha256']:
        raise ValueError('計画か入力が変わりました。見積もりを作り直してください')
    source = data.get('source_url') or ''
    if not isinstance(source, str) or (source and not re.fullmatch(
            r'https://github\.com/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*', source)):
        raise ValueError('参照募集URLを確認してください')
    return {'request_key': key, 'token_hash': hashlib.sha256(token.encode()).hexdigest(),
            'request_hash': hashlib.sha256((plan['plan_sha256']+'\0'+source).encode()).hexdigest(),
            'input': data['csv'], 'plan': plan, 'source_url': source}


def process_transaction(store):
    job = store.company_rpc('claim')
    if not job:
        return False
    try:
        service = job['plan']['service_key']
        result = produce(job['input'], service)
        verify(job['input'], service, result)
        encoding = 'utf-8-sig' if SERVICES[service]['format'] == 'csv' else 'utf-8'
        result['download_sha256'] = hashlib.sha256(result['artifact']['content'].encode(encoding)).hexdigest()
        store.company_rpc('finish', {'id': job['id'], 'lease': job['lease'], 'result': result})
    except StorageUnavailable:
        raise
    except Exception:
        store.company_rpc('finish', {'id': job['id'], 'lease': job['lease'],
                                    'error': '制作または検品に失敗しました。運用画面で確認してください。'})
    return True


def company_status(store, ai, payments):
    try:
        ready = store.company_rpc('ping') == {'schema_version': 9}
        overview = store.company_rpc('overview') if ready else None
        database_error = None if ready else 'E09用SQLの適用が必要です'
    except (StorageUnavailable, ValueError):
        ready, overview = False, None
        database_error = '009_company.sqlをSupabaseに適用してください'
    return {'endpoint': 'E12', 'database_ready': ready, 'database_error': database_error,
            'ai': ai.status(), 'payments': payments.status(), 'overview': overview,
            'outreach_enabled': False, 'live_payments_enabled': False,
            'autonomy': '検証注文の受付後は制作・検品・納品準備まで自動。営業と実決済は未稼働。'}
