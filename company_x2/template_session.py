"""Admin experiment state; metadata only, single-process deployment.

No customer CSV, purpose text or result body is stored in scouting records.
An interrupted processing claim is held for review rather than retried.
"""
import hashlib
import re
import threading
from datetime import datetime, timezone

from .template_work import safe_request

SOURCE = 'template_work_experiment'
LOCK = threading.RLock()


def records(store):
    return [x for x in store.opportunities() if x.get('source') == SOURCE]


def record_for(store,key):
    lookup=getattr(store,'get_work_record',None)
    if lookup is not None:return lookup(key)
    return next((r for r in records(store) if r['external_id']==key),None)


def save(store, record):
    record['updated_at'] = datetime.now(timezone.utc).isoformat()
    store.save_opportunity(record, 'blocked', 'Internal template experiment; not a hiring opportunity')


def request(store, data):
    key = data.get('request_key')
    if not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{16,64}', key):
        raise ValueError('Request key required')
    proposal = safe_request(data)
    with LOCK:
        previous = record_for(store,key)
        if previous:
            if previous['approval_sha256'] != proposal['approval_sha256']:
                raise ValueError('Request key already belongs to a different plan')
            return previous
        if len(store.opportunities()) >= 80:
            raise ValueError('Experiment record capacity reached')
        record = {'source': SOURCE, 'external_id': key,
                  'approval_sha256': proposal['approval_sha256'],
                  'status': 'needs_information' if proposal['plan']['questions'] else 'awaiting_consent',
                  'input_rows': proposal['plan']['input_rows'], 'experimental': True}
        save(store, record)
        return record


def process(store, data):
    proposal = safe_request(data)
    if data.get('accepted') is not True or data.get('approval_sha256') != proposal['approval_sha256']:
        raise ValueError('Current plan consent required')
    if proposal['plan']['questions']:
        raise ValueError('Questions must be resolved first')
    with LOCK:
        record = record_for(store,data.get('request_key'))
        if not record or record['approval_sha256'] != proposal['approval_sha256']:
            raise ValueError('Stored request does not match')
        if record['status'] not in ('awaiting_consent', 'ready'):
            raise ValueError('Request held or already received; do not retry automatically')
        if record['status'] == 'ready':
            result = safe_request(data, True)
            if hashlib.sha256(result['csv'].encode()).hexdigest() != record['artifact_sha256']:
                raise ValueError('Artifact differs from saved evidence')
            result['artifact_sha256'] = record['artifact_sha256']
            return result
        record['status'] = 'processing'
        save(store, record)  # Ambiguous write blocks execution.
        try:
            result = safe_request(data, True)
            record.update(status='ready', artifact_sha256=hashlib.sha256(result['csv'].encode()).hexdigest(),
                          issue_count=len(result['report']['issues']))
            save(store, record)
            result['artifact_sha256'] = record['artifact_sha256']
            return result
        except Exception:
            # Never store customer content or raw exception text.
            record['status'] = 'held'
            save(store, record)
            raise


def receive(store, data):
    with LOCK:
        record = record_for(store,data.get('request_key'))
        if not record or record['status'] not in ('ready', 'received'):
            raise ValueError('Verified artifact required')
        if data.get('artifact_sha256') != record.get('artifact_sha256'):
            raise ValueError('Receipt digest differs')
        if data.get('accepted') is not True:
            raise ValueError('Explicit receipt confirmation required')
        record['status'] = 'received'
        save(store, record)
        return {'status': 'received', 'experimental': True}


def summary(store):
    items = records(store)
    return {'experimental': True, 'real_customer_evidence': False,
            'counts': {state: sum(r['status'] == state for r in items)
                       for state in ('needs_information', 'awaiting_consent', 'processing', 'ready', 'held', 'received')},
            'notice': 'Admin experiments are excluded from customer trial success metrics.'}
