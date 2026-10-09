"""Authenticated company routes; signature-authenticated webhook handled separately."""
from .ai_planner import AIPlanner
from .company import company_status, quote, rank_candidates, validate_creation
from .data_services import make_artifact, SERVICES
from .payments import Payments
from .public_scout import snapshot
from .acquisition import organize, draft
from .cloud_scout import run as cloud_run
from .agent_scout import state as agent_state, register as agent_register, summary as agent_summary
from .sales import assess as sales_assess, proposal as sales_proposal
from .intake_access import issue as issue_intake
from . import public_intake
from datetime import datetime, timezone
from urllib.parse import urlencode


def get_route(handler, path, store, ai, payments, scout_enabled):
    if path == '/api/company/outreach':
        from .outreach import status
        handler.respond(200,{**status(),'items':store.outreach_rpc('list')})
    elif path == '/api/company/public-intake':
        handler.respond(200,public_intake.summary(store))
    elif path == '/api/company/sales':
        handler.respond(200,sales_assess((agent_state(store).get('items',[])+snapshot(store,enabled=scout_enabled).get('items',[]))[:30]))
    elif path == '/api/company/agent-scout/status':
        handler.respond(200,agent_summary(store))
    elif path == '/api/company/agent-scout':
        saved=agent_state(store)
        handler.respond(200,{**saved,'scout_status':agent_summary(store,saved)})
    elif path == '/api/company/status':
        handler.respond(200, company_status(store,ai,payments))
    elif path == '/api/company/candidates':
        data = snapshot(store,enabled=scout_enabled)
        assessed=sales_assess((agent_state(store).get('items',[])+data.get('items',[]))[:30])
        data.update(items=assessed['items'],summary=assessed['triage_summary'],notice=assessed['notice'])
        handler.respond(200,data)
    elif path == '/api/intake/config':
        ready = company_status(store,ai,payments)
        live=ready['live_payments']
        handler.respond(200,{'database_ready':ready['database_ready'],
            'database_error':ready['database_error'], 'payments_ready':ready['payments']['ready'] and not getattr(handler,'public_customer',False),
            'public_free':getattr(handler,'public_customer',False),
            'live_payments_ready':getattr(handler,'live_customer',False) and live['ready'],
            'live_price_jpy':live['price_jpy'],'sales_terms_url':live['terms_url'],
            'max_bytes':public_intake.MAX_BYTES if getattr(handler,'public_customer',False) else 1000000,
            'max_rows':public_intake.MAX_ROWS if getattr(handler,'public_customer',False) else 10000})
    elif path.startswith('/api/company/transactions/'):
        parts = path.strip('/').split('/')
        if len(parts) not in (4,5) or (len(parts)==5 and parts[4]!='download'):
            handler.respond(404,{'error':'Not found'})
            return True
        order = store.company_rpc('get',{'id':parts[3],'token_hash':store.digest(handler.token())})
        if order:
            order['delivery_allowed'] = False
            if order['status'] in ('ready','delivered'):
                from .delivery_safety import require_delivery
                try:
                    require_delivery(order)
                    if store.case_rpc('state',{'order_id':order['id']})['hold']:
                        order['delivery_error']='問題報告の確認中、または不適合が確認されたため納品を保留しています。問い合わせ窓口で対応状況を確認してください。'
                        raise ValueError('Support case pending')
                    order['delivery_allowed'] = True
                except ValueError:
                    order.setdefault('delivery_error','安全検査が未完了または不一致のため納品を保留しています。新しい計画が必要です。')
        if not order:
            handler.respond(404,{'error':'Transaction not found'})
        elif len(parts)==5:
            if order['status'] not in ('ready','delivered') or order.get('refund',{}).get('state','none') != 'none':
                handler.respond(409,{'error':'Artifact unavailable'})
            elif not order['delivery_allowed']:
                handler.respond(409,{'error':order['delivery_error']})
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
    if path == '/api/company/outreach/prepare':
        from .outreach import collect,status
        handler.respond(200,{'collected':collect(store),**status(),'items':store.outreach_rpc('list')})
    elif path == '/api/company/intake-link':
        from .data_services import require_service
        language=data.get('language','ja')
        if language not in ('ja','en'):raise ValueError('Unsupported customer language')
        service=require_service(data.get('service_key'))
        live=data.get('payment_mode')=='stripe_live'
        if live and not payments.live_status(store)['ready']:raise ValueError('Live payments are not ready')
        token,expires=issue_intake(handler.intake_signing_key,scope='intake_live' if live else 'intake_test')
        host=handler.headers.get('Host')
        scheme='http' if host.split(':')[0] in ('localhost','127.0.0.1') else 'https'
        handler.respond(200,{'url':scheme+'://'+host+'/intake?'+urlencode({'lang':language})+'#'+urlencode({'access':token,'service':service}),
            'expires_at':datetime.fromtimestamp(expires,timezone.utc).isoformat(),'mode':'stripe_live' if live else 'test_only','live_price_jpy':payments.live_price if live else None})
    elif path == '/api/company/sales-proposal':
        handler.respond(200,sales_proposal((agent_state(store).get('items',[])+snapshot(store).get('items',[]))[:30],data.get('source_url'),data.get('language','ja')))
    elif path == '/api/company/agent-scout':
        handler.respond(200,cloud_run(store) if data.get('action')=='cloud_run' else agent_register(store,data))
    elif path == '/api/company/lead-draft':
        items=(agent_state(store).get('items',[])+snapshot(store).get('items',[]))[:30]
        sales_proposal(items,data.get('source_url'))
        handler.respond(200,draft(items,data.get('source_url')))
    elif path == '/api/company/ai':
        if data.get('ai_terms_accepted') is not True:
            raise ValueError('依頼文を設定済みのAI提供元へ送信することへの同意が必要です')
        handler.respond(200,ai.analyze(store,data.get('request'),handler.token()))
    elif path == '/api/company/quote':
        from .intake_risk import require_declared_scope
        require_declared_scope(data.get('risk_context'))
        if getattr(handler,'public_customer',False):public_intake.reserve_quote(store,data)
        mode=data.get('payment_mode','sandbox')
        if mode=='stripe_live' and (not getattr(handler,'live_customer',False) or not payments.live_status(store)['ready']):raise ValueError('Live payments are not ready')
        handler.respond(200,{'plan':quote(data.get('service_key'),data.get('csv'),mode,payments.live_price,payments.terms_url,data.get('risk_context'))})
    elif path == '/api/company/transactions':
        from .intake_risk import require_declared_scope
        require_declared_scope(data.get('risk_context'))
        if getattr(handler,'public_customer',False):
            order=public_intake.create(store,data,handler.token())
            handler.respond(202,{'id':order,'mode':'sandbox','revenue_jpy':0})
            return True
        if data.get('payment_mode')=='stripe_live' and (not getattr(handler,'live_customer',False) or not payments.live_status(store)['ready']):raise ValueError('Live payments are not ready')
        payload = validate_creation(data,handler.token(),payments.live_price,payments.terms_url)
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
            from .delivery_safety import require_plan
            require_plan(order['plan'])
            handler.respond(200,payments.checkout(store,order,token_hash,data.get('return_path','/company'),data.get('locale','auto')))
        elif path.endswith('/reconcile'):
            handler.respond(200,payments.reconcile(store,order))
        else:
            from .delivery_safety import require_delivery
            require_delivery(order)
            if store.case_rpc('state',{'order_id':order['id']})['hold']:
                raise ValueError('問題報告を確認中のため受領を記録できません')
            store.company_rpc('receipt',{'id':order['id'],'token_hash':token_hash,
                                       'download_sha256':data.get('download_sha256')})
            public_intake.delivered(store,order['id'],handler.token())
            handler.respond(200,{'received':True})
    else:
        return False
    return True
