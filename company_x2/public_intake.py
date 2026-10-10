"""Bounded free public intake for the single-process deployment.

Daily reservations are saved before work. Failed/ambiguous saves fail closed.
This lock serializes threads, not multiple replicas; do not scale this service
without moving these counters to an atomic database RPC.
"""
import copy
import hashlib
import threading
import time
from collections import deque
from datetime import datetime, timezone
from .company import validate_creation
from .data_services import read_csv

SOURCE='public_free_intake'
MAX_BYTES=50_000
MAX_ROWS=1000
ORDERS_PER_DAY=10
ORDERS_PER_OWNER=2
STARTS_PER_DAY=30
QUOTES_PER_DAY=60
LOCK=threading.RLock()
REQUESTS=deque()

def check_rate():
    with LOCK:
        now=time.monotonic()
        while REQUESTS and REQUESTS[0]<now-60:REQUESTS.popleft()
        if len(REQUESTS)>=120:raise LimitReached('Public rate limit reached; retry in one minute')
        REQUESTS.append(now)

class LimitReached(ValueError):
    pass

def day():return datetime.now(timezone.utc).strftime('%Y-%m-%d')

def records(store):
    return [x for x in store.opportunities() if x.get('source')==SOURCE]

def load(store):
    all_items=store.opportunities()
    current=next((x for x in all_items if x.get('source')==SOURCE and x.get('external_id')==day()),None)
    if current is None and len(all_items)>=100:
        raise LimitReached('Public intake temporarily unavailable; contact the operator')
    return copy.deepcopy(current or {'source':SOURCE,'external_id':day(),
        'starts':0,'quotes':0,'visits':[],'tickets':{}})

def save(store,state):
    store.save_opportunity(state,'blocked','Public free test usage; not a job listing')

def owner_hash(owner):
    if not isinstance(owner,str) or not 32<=len(owner)<=128:
        raise ValueError('An order owner token is required')
    return hashlib.sha256(owner.encode()).hexdigest()

def start(store,owner):
    digest=owner_hash(owner)
    with LOCK:
        from .free_trial import policy,require_open
        if policy()['enabled']:
            # Renewal is allowed for an existing customer after closure. New
            # quotes/orders remain gated separately; receipt/download stay open.
            existing=any(t['owner']==digest and t.get('id') for x in records(store) for t in x['tickets'].values())
            if not existing:require_open(store)
            elif not policy()['open']:return
        state=load(store)
        if state['starts']>=STARTS_PER_DAY:raise LimitReached('Daily public start limit reached; retry after 00:00 UTC')
        state['starts']+=1;save(store,state)

def visit(store,key):
    digest=owner_hash(key)
    with LOCK:
        state=load(store)
        if digest not in state['visits'] and len(state['visits'])<200:
            state['visits'].append(digest);save(store,state)

def check_input(data):
    if data.get('payment_mode','sandbox')!='sandbox':raise ValueError('Public intake supports free verification only')
    text=data.get('csv')
    if not isinstance(text,str) or len(text.encode())>MAX_BYTES:raise ValueError('Public CSV limit: 50 KB and 1,000 rows')
    _,rows=read_csv(text)
    if len(rows)>MAX_ROWS:raise ValueError('Public CSV limit: 50 KB and 1,000 rows')

def reserve_quote(store,data):
    check_input(data)
    with LOCK:
        from .free_trial import require_open
        require_open(store)
        state=load(store)
        if state['quotes']>=QUOTES_PER_DAY:raise LimitReached('Daily public plan limit reached; retry after 00:00 UTC')
        state['quotes']+=1;save(store,state)

def create(store,data,owner):
    check_input(data)
    payload=validate_creation(data,owner)
    if payload['source_url']:raise ValueError('Public requests cannot reference job listings')
    key=hashlib.sha256(payload['request_key'].encode()).hexdigest()
    with LOCK:
        state=copy.deepcopy(next((x for x in records(store) if key in x['tickets']),None)) or load(store)
        existing=state['tickets'].get(key)
        identity={'owner':payload['token_hash'],'request':payload['request_hash']}
        if existing:
            if any(existing[k]!=v for k,v in identity.items()):raise ValueError('Request key conflict')
        else:
            from .free_trial import policy,require_open
            require_open(store)
            limit=policy()['orders_per_day'] if policy()['enabled'] else ORDERS_PER_DAY
            if len(state['tickets'])>=limit or sum(x['owner']==payload['token_hash'] for x in state['tickets'].values())>=ORDERS_PER_OWNER:
                raise LimitReached('Daily public order limit reached; retry after 00:00 UTC')
            state['tickets'][key]={**identity,'id':None,'delivered':False}
            save(store,state)  # A crash may consume a slot, never silently refund it.
        order=store.company_rpc('create',payload)
        state['tickets'][key]['id']=order;save(store,state)
        return order

def delivered(store,order,owner):
    digest=owner_hash(owner)
    with LOCK:
        for state in records(store):
            state=copy.deepcopy(state)
            for ticket in state['tickets'].values():
                if ticket['id']==order and ticket['owner']==digest and not ticket['delivered']:
                    ticket['delivered']=True;save(store,state);return

def summary(store):
    with LOCK:
        recent=sorted(records(store),key=lambda x:x['external_id'],reverse=True)[:30]
        days=[{'day_utc':x['external_id'],'visits':len(x['visits']),'starts':x['starts'],'plans':x['quotes'],
            'reserved':len(x['tickets']),'accepted':sum(bool(t['id']) for t in x['tickets'].values()),
            'delivered':sum(bool(t['delivered']) for t in x['tickets'].values())} for x in recent]
    return {'days':days,'totals':{k:sum(x[k] for x in days) for k in ('visits','starts','plans','reserved','accepted','delivered')},
        'limits':{'bytes':MAX_BYTES,'rows':MAX_ROWS,'orders_per_day':ORDERS_PER_DAY,'orders_per_owner':ORDERS_PER_OWNER},
        'notice':'保存済み最大30日。表示数はタブからの申告・重複あり。上限はUTC日（日本時間9時）に更新。単一プロセス運用です。'}
