"""Stripe test Checkout and raw-body webhook verification. Live keys rejected."""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.request
from urllib.parse import urlencode, urlparse

from .supabase_store import NoRedirect


class Payments:
    def __init__(self, env=None, opener=None):
        env = os.environ if env is None else env
        self.key = env.get('STRIPE_SECRET_KEY','')
        self.webhook_secret = env.get('STRIPE_WEBHOOK_SECRET','')
        self.base = env.get('APP_PUBLIC_URL','').rstrip('/')
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def status(self):
        parsed = urlparse(self.base)
        valid_url = (parsed.scheme == 'https' and bool(parsed.hostname) and parsed.path in ('','/')
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
        ready = bool(self.key.startswith('sk_test_') and self.webhook_secret.startswith('whsec_') and valid_url)
        return {'ready':ready,'mode':'stripe_test','live_enabled':False,
                'reason':None if ready else 'Stripeテストキー、Webhook署名キー、APP_PUBLIC_URLが必要です。実決済キーは受付しません。'}

    def api(self, path, data=None, idempotency_key=None):
        if not self.status()['ready']:
            raise ValueError('Stripeテスト決済が未設定です')
        headers = {'Authorization':'Bearer '+self.key}
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        req = urllib.request.Request('https://api.stripe.com/v1/'+path,
            data=urlencode(data).encode() if data is not None else None,headers=headers)
        try:
            with self.opener(req,timeout=20) as response:
                raw = response.read(200_001)
            if len(raw) > 200_000:
                raise ValueError('Provider response too large')
            result = json.loads(raw)
            if not isinstance(result,dict) or result.get('livemode') is not False:
                raise ValueError('Test provider evidence required')
            return result
        except Exception:
            raise ValueError('Stripeの応答を確認できませんでした。同じ注文で再確認してください') from None

    def checkout(self, store, order, token_hash, return_path='/company', locale='auto'):
        if locale not in ('auto','ja','en'):
            raise ValueError('Unsupported checkout language')
        if return_path not in ('/company','/intake'):
            raise ValueError('決済の戻り先を確認してください')
        if order['plan']['payment_mode'] != 'stripe_test':
            raise ValueError('無料注文に決済は不要です')
        if order.get('session_id'):
            return {'url':order['session_url'],'id':order['session_id']}
        if order['status'] != 'awaiting_payment':
            raise ValueError('この注文は決済受付できません')
        result = self.api('checkout/sessions',{
            'mode':'payment','locale':locale,'payment_method_types[0]':'card',
            'success_url':self.base+return_path+'?checkout=returned', 'cancel_url':self.base+return_path+'?checkout=cancelled',
            'client_reference_id':order['id'],'metadata[cx2_order_id]':order['id'],
            'line_items[0][quantity]':1,'line_items[0][price_data][currency]':'jpy',
            'line_items[0][price_data][unit_amount]':order['plan']['price_jpy'],
            'line_items[0][price_data][product_data][name]':'Company X2 TEST '+({'csv_exact_dedup':'CSV exact deduplication','csv_trim':'CSV whitespace trimming','csv_to_json':'CSV to JSON','csv_audit':'CSV data audit'}[order['plan']['service_key']] if locale=='en' else order['plan']['service_name'])
        },idempotency_key='cx2-checkout-'+order['id'])
        parsed = urlparse(result.get('url',''))
        if (not re.fullmatch(r'cs_test_[A-Za-z0-9]+',result.get('id','')) or parsed.scheme != 'https'
                or parsed.netloc != 'checkout.stripe.com' or parsed.username or parsed.password):
            raise ValueError('Checkout response rejected')
        store.company_rpc('session', {'id':order['id'],'token_hash':token_hash,
                                     'session_id':result['id'],'session_url':result['url']})
        return {'url':result['url'],'id':result['id']}

    def signed_event(self, raw, header, now=None):
        if not self.status()['ready']:
            raise ValueError('Webhookが未設定です')
        parts = {}
        for piece in header.split(','):
            key, separator, value = piece.partition('=')
            if separator:
                parts.setdefault(key,[]).append(value)
        try:
            if len(parts.get('t',[])) != 1:
                raise ValueError('timestamp')
            timestamp = int(parts['t'][0])
            if abs((time.time() if now is None else now)-timestamp) > 300:
                raise ValueError('expired')
            digest = hmac.new(self.webhook_secret.encode(),str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
            if not any(re.fullmatch('[a-f0-9]{64}',value) and hmac.compare_digest(digest,value) for value in parts.get('v1',[])):
                raise ValueError('signature')
            event = json.loads(raw)
            if not isinstance(event,dict) or event.get('livemode') is not False or not re.fullmatch(r'evt_[A-Za-z0-9]+',event.get('id','')):
                raise ValueError('event')
            return event
        except (ValueError,TypeError,UnicodeError):
            raise ValueError('Webhook署名またはイベントを確認できません') from None

    def apply_event(self, store, event):
        if event.get('type') not in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
            return {'received':True,'ignored':True}
        data=event.get('data',{})
        if not isinstance(data,dict) or not isinstance(data.get('object'),dict):
            raise ValueError('Invalid checkout event')
        session = data['object']
        if session.get('payment_status') != 'paid':
            return {'received':True,'ignored':True}
        return self.reconcile_session(store,session,event['id'])

    def reconcile_session(self, store, session, event_id):
        if (session.get('livemode') is not False or session.get('mode') != 'payment'
                or session.get('status') != 'complete' or session.get('payment_status') != 'paid'
                or not re.fullmatch(r'cs_test_[A-Za-z0-9]+', session.get('id',''))
                or type(session.get('amount_total')) is not int):
            raise ValueError('決済完了の証拠が不足しています')
        metadata=session.get('metadata')
        if not isinstance(metadata,dict):
            raise ValueError('Invalid checkout metadata')
        order = metadata.get('cx2_order_id')
        if not isinstance(order,str) or not order.startswith('cx_') or session.get('client_reference_id') != order:
            return {'received':True,'ignored':True}
        evidence = {'id':order,'session_id':session['id'],'event_id':event_id,
            'amount':session['amount_total'],'currency':session.get('currency'),
            'livemode':False,'payment_status':'paid'}
        evidence['fingerprint'] = hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
        store.company_rpc('payment', evidence)
        return {'received':True,'verified':True}

    def reconcile(self, store, order):
        if not order.get('session_id'):
            raise ValueError('Checkoutがまだ作成されていません')
        session = self.api('checkout/sessions/'+order['session_id'])
        if session.get('payment_status') != 'paid':
            return {'payment_status':'unpaid'}
        self.reconcile_session(store,session,'reconcile_'+session['id'])
        return {'payment_status':'paid'}
