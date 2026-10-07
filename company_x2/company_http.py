"""Authenticated company routes; signature-authenticated webhook handled separately."""
from .ai_planner import AIPlanner
from .company import company_status, quote, rank_candidates, validate_creation
from .data_services import make_artifact, SERVICES
from .payments import Payments
from .public_scout import snapshot
from .acquisition import organize, draft


def get_route(handler, path, store, ai, payments, scout_enabled):
    if path == '/api/company/status':
        handler.respond(200, company_status(store,ai,payments))
    elif path == '/api/company/candidates':
        data = snapshot(store,enabled=scout_enabled)
        data.update(organize(data.get('items',[])))
        handler.respond(200,data)
    elif path == '/api/intake/config':
        ready = company_status(store,ai,payments)
        handler.respond(200,{'database_ready':ready['database_ready'],
            'database_error':ready['database_error'], 'payments_ready':ready['payments']['ready']})
    elif path.startswith('/api/company/transactions/'):
        parts = path.strip('/').split('/')
        if len(parts) not in (4,5) or (len(parts)==5 and parts[4]!='download'):
            handler.respond(404,{'error':'Not found'})
            return True
        order = store.company_rpc('get',{'id':parts[3],'token_hash':store.digest(handler.token())})
        if not order:
            handler.respond(404,{'error':'Transaction not found'})
        elif len(parts)==5:
            if order['status'] not in ('ready','delivered'):
                handler.respond(409,{'error':'Artifact unavailable'})
            else:
                service = order['plan']['service_key']
                artifact = make_artifact(order['result']['artifact']['content'],service)
                encoding = 'utf-8-sig' if SERVICES[service]['format']=='csv' else 'utf-8'
                handler.respond(200,artifact['content'].encode(encoding),artifact['content_type'],artifact['filename'])
        else:
            if order['result']:
                order['result'].pop('csv',None)
                order['result']['artifact'].pop('content',None)
            handler.respond(200,order)
    else:
        return False
    return True


def post_route(handler, path, data, store, ai, payments):
    if path == '/api/company/lead-draft':
        handler.respond(200,draft(snapshot(store).get('items',[]),data.get('source_url')))
    elif path == '/api/company/ai':
        if data.get('ai_terms_accepted') is not True:
            raise ValueError('依頼文を設定済みのAI提供元へ送信することへの同意が必要です')
        handler.respond(200,ai.analyze(store,data.get('request'),handler.token()))
    elif path == '/api/company/quote':
        handler.respond(200,{'plan':quote(data.get('service_key'),data.get('csv'),data.get('payment_mode','sandbox'))})
    elif path == '/api/company/transactions':
        payload = validate_creation(data,handler.token())
        if payload['plan']['payment_mode']=='stripe_test' and not payments.status()['ready']:
            raise ValueError('Stripeテスト決済が未設定です')
        order = store.company_rpc('create',payload)
        handler.respond(202,{'id':order,'mode':payload['plan']['payment_mode'],'revenue_jpy':0})
    elif path in ('/api/company/checkout','/api/company/reconcile','/api/company/receipt'):
        token_hash = store.digest(handler.token())
        order = store.company_rpc('get',{'id':data.get('id'),'token_hash':token_hash})
        if not order:
            handler.respond(404,{'error':'Transaction not found'})
        elif path.endswith('/checkout'):
            handler.respond(200,payments.checkout(store,order,token_hash,data.get('return_path','/company')))
        elif path.endswith('/reconcile'):
            handler.respond(200,payments.reconcile(store,order))
        else:
            store.company_rpc('receipt',{'id':order['id'],'token_hash':token_hash,
                                       'download_sha256':data.get('download_sha256')})
            handler.respond(200,{'received':True})
    else:
        return False
    return True
