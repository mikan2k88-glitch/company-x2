"""Private customer workflow core. Not exposed until HTTP/UI integration passes.

Shares public intake quotas. Stores only metadata; single-process deployment.
"""
import copy
import hashlib
import re
from datetime import datetime, timezone

from . import public_intake, template_session
from .template_work import safe_request

SOURCE = 'customer_template_work'


def public_record(record):
    allowed = ('status', 'approval_sha256', 'artifact_sha256', 'input_rows',
               'issue_count', 'updated_at', 'plan', 'reserved')
    return {key: record[key] for key in allowed if key in record}


def preview(store, data, owner):
    """Bound plan previews by the same daily counter as existing public quotes."""
    public_intake.owner_hash(owner)
    proposal = safe_request(data)
    reserve_preview(store)
    return proposal


def suggestion(store, data, owner):
    public_intake.owner_hash(owner)
    from .template_work import suggest
    result = suggest(data)
    reserve_preview(store)
    return result


def reserve_preview(store):
    with public_intake.LOCK:
        from .free_trial import require_open
        require_open(store)
        state = public_intake.load(store)
        if state['quotes'] >= public_intake.QUOTES_PER_DAY:
            raise public_intake.LimitReached('Daily public plan limit reached')
        state['quotes'] += 1
        public_intake.save(store, state)


class OwnedStore:
    def __init__(self, store, owner, replay_received=False):
        self.store = store
        self.digest = public_intake.owner_hash(owner)
        self.replay_received = replay_received

    def opportunities(self):
        # Experiments and other customers cannot enter the session namespace.
        return [{**copy.deepcopy(r), 'source': template_session.SOURCE, 'external_id': r['client_key'], 'experimental': False,
                 'status': 'ready' if self.replay_received and r['status'] == 'received' else r['status']}
                for r in self.store.opportunities()
                if r.get('source') == SOURCE and r.get('owner_hash') == self.digest]

    def save_opportunity(self, record, decision, reason):
        record.setdefault('created_at', datetime.now(timezone.utc).isoformat())
        identifier = hashlib.sha256((self.digest + ':' + record['external_id']).encode()).hexdigest()
        self.store.save_opportunity({**record, 'source': SOURCE, 'owner_hash': self.digest,
                                     'external_id': identifier, 'client_key': record['external_id'],
                                     'experimental': False}, 'blocked',
                                    'Private customer workflow metadata; not a hiring opportunity')


def request(store, data, owner):
    # Validate before reserving; unresolved mappings may be revised with a new key.
    if not isinstance(data.get('request_key'), str) or not re.fullmatch('[A-Za-z0-9_-]{16,64}', data['request_key']):
        raise ValueError('Request key required')
    proposal = safe_request(data)
    scoped = OwnedStore(store, owner)
    with public_intake.LOCK, template_session.LOCK:
        previous = next((r for r in scoped.opportunities()
                         if r['external_id'] == data.get('request_key')), None)
        if previous:
            return public_record(template_session.request(scoped, data))
        if proposal['plan']['questions']:
            # Questions are previews, not orders. Resolving them must not use
            # another order slot or persist customer material.
            from .free_trial import require_open
            require_open(store)
            return {'status': 'needs_information', 'experimental': False,
                    'approval_sha256': proposal['approval_sha256'],
                    'plan': proposal['plan'], 'reserved': False}
        if len(store.opportunities()) >= 80:
            raise public_intake.LimitReached('Customer workflow storage capacity reached')
        from .free_trial import policy, require_open
        require_open(store)
        state = public_intake.load(store)
        key = hashlib.sha256(('template:' + scoped.digest + ':' + str(data.get('request_key'))).encode()).hexdigest()
        ticket = state['tickets'].get(key)
        if not ticket:
            limit = policy()['orders_per_day']
            if len(state['tickets']) >= limit or sum(t['owner'] == scoped.digest for t in state['tickets'].values()) >= public_intake.ORDERS_PER_OWNER:
                raise public_intake.LimitReached('Daily public order limit reached')
            state['tickets'][key] = {'owner': scoped.digest, 'request': proposal['approval_sha256'],
                                     'id': None, 'delivered': False, 'workflow': 'template'}
            public_intake.save(store, state)  # Failed writes block work; ambiguous reservations consume a slot.
        elif ticket['request'] != proposal['approval_sha256']:
            raise ValueError('Request key conflict')
        result = template_session.request(scoped, data)
        return public_record(result)


def process(store, data, owner, *, handoff_check=None):
    # A received artifact may be reproduced from resubmitted input only when
    # its stored consent and artifact hashes match. The saved status stays received.
    scoped = OwnedStore(store, owner, replay_received=True)
    with public_intake.LOCK, template_session.LOCK:
        from .free_trial import require_open
        existing = next((r for r in scoped.opportunities()
                         if r['external_id'] == data.get('request_key')), None)
        if existing and existing.get('handoff'):
            if handoff_check is None:
                raise ValueError('Verified source handoff required')
            evidence = handoff_check()
            if any(evidence.get(key) != value for key, value in existing['handoff'].items()):
                raise ValueError('Source handoff changed')
        if not existing or existing['status'] != 'ready':
            require_open(store)  # Existing verified artifact retrieval stays available.
        return template_session.process(scoped, data)


def receive(store, data, owner):
    # Receipt remains available after trial closure.
    return {**template_session.receive(OwnedStore(store, owner), data), 'experimental': False}


def status(store, owner):
    """Only the current customer's minimal state, without internal identifiers."""
    with public_intake.LOCK, template_session.LOCK:
        allowed = ('status', 'approval_sha256', 'artifact_sha256', 'input_rows', 'issue_count', 'updated_at')
        return {'items': [{'request_key': r['external_id'],
                           **{key: r[key] for key in allowed if key in r}}
                          for r in OwnedStore(store, owner).opportunities()]}


def metrics(store, since='1970-01-01T00:00:00Z'):
    """Aggregate this workflow separately from company transaction RPC IDs."""
    counts = dict(accepted=0, ready=0, received=0, held=0, unfinished=0)
    try:
        start = datetime.fromisoformat(since.replace('Z', '+00:00'))
        if start.tzinfo is None:raise ValueError('Timezone required')
    except (ValueError, TypeError, AttributeError):
        return {'counts': counts, 'hold_rate': None, 'new_intake_paused': True,
                'configuration_error': 'Invalid reporting start time'}
    for row in store.opportunities():
        if row.get('source') != SOURCE or row.get('experimental') is not False:
            continue
        try:
            created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            if created < start:continue
        except (KeyError, ValueError, TypeError):
            continue  # Unknown provenance is not a verified customer count.
        counts['accepted'] += 1
        state = row.get('status')
        counts[state if state in ('ready', 'received', 'held') else 'unfinished'] += 1
    completed = counts['ready'] + counts['received'] + counts['held']
    return {'counts': counts, 'hold_rate': counts['held']/completed if completed else None,
            'new_intake_paused': completed >= 3 and counts['held']/completed >= 0.3}
