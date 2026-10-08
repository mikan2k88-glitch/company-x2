"""Separate test/live Checkout channels with verified payment evidence."""
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
        self.live_key=env.get('STRIPE_LIVE_SECRET_KEY','') or (self.key if self.key.startswith('sk_live_') else '')
        self.live_secret=env.get('STRIPE_LIVE_WEBHOOK_SECRET','')
        self.live_enabled=env.get('LIVE_PAYMENTS_ENABLED','false').lower()=='true'
        self.sales_confirmed=env.get('LIVE_SALES_TERMS_CONFIRMED','false').lower()=='true'
        self.terms_url=env.get('SALES_TERMS_URL','')
        price=str(env.get('LIVE_PRICE_JPY',''))
        self.live_price=int(price) if price.isdigit() and 50<=int(price)<=10000 else None
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def status(self):
        parsed = urlparse(self.base)
        valid_url = (parsed.scheme == 'https' and bool(parsed.hostname) and parsed.path in ('','/')
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
        ready = bool(self.key.startswith('sk_test_') and self.webhook_secret.startswith('whsec_') and valid_url)
        return {'ready':ready,'mode':'stripe_test','live_enabled':False,
                'reason':None if ready else 'Stripeテストキー、テストWebhook署名キー、APP_PUBLIC_URLが必要です。本番設定は別チャンネルで確認します。'}

    def connection(self,mode):
        if mode not in ('stripe_test','stripe_live'):raise ValueError('Unsupported payment mode')
        live=mode=='stripe_live'
        key=self.live_key if live else self.key
        secret=self.live_secret if live else self.webhook_secret
        parsed=urlparse(self.base)
        valid=(parsed.scheme=='https' and bool(parsed.hostname) and parsed.path in ('','/')
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
        if not key.startswith('sk_live_' if live else 'sk_test_') or not secret.startswith('whsec_') or not valid:
            raise ValueError('Stripe channel is not configured')
        return key,secret,live

    def live_status(self,store=None):
        reasons=[]
        try:self.connection('stripe_live')
        except ValueError:reasons.append('本番キー・本番Webhook署名キー・APP_PUBLIC_URLが必要です')
        if not self.live_enabled:reasons.append('LIVE_PAYMENTS_ENABLED=true が必要です')
        if self.live_price is None:reasons.append('LIVE_PRICE_JPY（50〜10000円）が必要です')
        parsed=urlparse(self.terms_url)
        if not self.sales_confirmed or not self.terms_url or parsed.scheme!='https' or parsed.netloc!=urlparse(self.base).netloc or parsed.username or parsed.password or parsed.fragment:
            reasons.append('同じサイトの販売条件URLと LIVE_SALES_TERMS_CONFIRMED=true が必要です')
        schema=False
        if store is not None:
            try:schema=store.company_rpc('live_ping')=={'live_schema_version':19}
            except Exception:pass
        if not schema:reasons.append('019_live_payments.sqlの適用が必要です')
        from .refunds import ready as refunds_ready
        if not refunds_ready(store):reasons.append('020_refunds.sqlの適用が必要です')
        return {'ready':not reasons,'mode':'stripe_live','price_jpy':self.live_price,'terms_url':self.terms_url,
            'schema_ready':schema,'reasons':reasons}

    def api(self, path, data=None, idempotency_key=None, payment_mode="stripe_test"):
        key,secret,live=self.connection(payment_mode)
        headers = {'Authorization':'Bearer '+key}
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
            refund_list = re.fullmatch(r'refunds\?payment_intent=pi_[A-Za-z0-9]+&limit=100',path)
            list_valid = (refund_list and isinstance(result,dict) and result.get('object')=='list'
                and isinstance(result.get('data'),list) and type(result.get('has_more')) is bool
                and all(isinstance(x,dict) and x.get('object')=='refund' and ('livemode' not in x or x['livemode'] is live) for x in result['data']))
            refund_valid = (re.fullmatch(r'refunds(?:/re_[A-Za-z0-9]+)?',path)
                and isinstance(result,dict) and result.get('object')=='refund'
                and ('livemode' not in result or result['livemode'] is live))
            if not isinstance(result,dict) or (not list_valid and not refund_valid and result.get('livemode') is not live):
                raise ValueError('Test provider evidence required')
            return result
        except Exception:
            raise ValueError('Stripeの応答を確認できませんでした。同じ注文で再確認してください') from None

    def checkout(self, store, order, token_hash, return_path='/company', locale='auto'):
        if locale not in ('auto','ja','en'):
            raise ValueError('Unsupported checkout language')
        if return_path not in ('/company','/intake'):
            raise ValueError('決済の戻り先を確認してください')
        mode=order['plan']['payment_mode']
        if mode=='stripe_live' and not self.live_status(store)['ready']:raise ValueError('Live payments are not ready')
        if mode not in ('stripe_test','stripe_live'):
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
            'line_items[0][price_data][product_data][name]':('Company X2 ' if mode=='stripe_live' else 'Company X2 TEST ')+({'csv_exact_dedup':'CSV exact deduplication','csv_trim':'CSV whitespace trimming','csv_to_json':'CSV to JSON','csv_audit':'CSV data audit'}[order['plan']['service_key']] if locale=='en' else order['plan']['service_name'])
        },idempotency_key='cx2-checkout-'+order['id'],**({'payment_mode':mode} if mode=='stripe_live' else {}))
        parsed = urlparse(result.get('url',''))
        if (not re.fullmatch(r'cs_live_[A-Za-z0-9]+' if mode=='stripe_live' else r'cs_test_[A-Za-z0-9]+',result.get('id','')) or parsed.scheme != 'https'
                or parsed.netloc != 'checkout.stripe.com' or parsed.username or parsed.password):
            raise ValueError('Checkout response rejected')
        store.company_rpc('session', {'id':order['id'],'token_hash':token_hash,
                                     'session_id':result['id'],'session_url':result['url']})
        return {'url':result['url'],'id':result['id']}

    def signed_event(self, raw, header, now=None, payment_mode="stripe_test"):
        key,secret,live=self.connection(payment_mode)
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
            digest = hmac.new(secret.encode(),str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
            if not any(re.fullmatch('[a-f0-9]{64}',value) and hmac.compare_digest(digest,value) for value in parts.get('v1',[])):
                raise ValueError('signature')
            event = json.loads(raw)
            if not isinstance(event,dict) or event.get('livemode') is not live or not re.fullmatch(r'evt_[A-Za-z0-9]+',event.get('id','')):
                raise ValueError('event')
            return event
        except (ValueError,TypeError,UnicodeError):
            raise ValueError('Webhook署名またはイベントを確認できません') from None

    def apply_event(self, store, event):
        if event.get('type') in ('refund.created','refund.updated','refund.failed'):
            from .refunds import webhook
            return webhook(self, store, event)
        if event.get('type') not in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
            return {'received':True,'ignored':True}
        data=event.get('data',{})
        if not isinstance(data,dict) or not isinstance(data.get('object'),dict):
            raise ValueError('Invalid checkout event')
        session = data['object']
        if type(event.get('livemode')) is not bool or session.get('livemode') is not event['livemode']:raise ValueError('Webhook channel mismatch')
        if session.get('payment_status') != 'paid':
            return {'received':True,'ignored':True}
        return self.reconcile_session(store,session,event['id'])

    def reconcile_session(self, store, session, event_id):
        live=session.get('livemode') is True
        if type(session.get('livemode')) is not bool:raise ValueError('Payment mode evidence required')
        if (session.get('livemode') is not live or session.get('mode') != 'payment'
                or session.get('status') != 'complete' or session.get('payment_status') != 'paid'
                or not re.fullmatch(r'cs_live_[A-Za-z0-9]+' if live else r'cs_test_[A-Za-z0-9]+', session.get('id',''))
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
            'livemode':live,'payment_status':'paid'}
        evidence['fingerprint'] = hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
        store.company_rpc('payment', evidence)
        if session.get('payment_intent'):
            from .refunds import ready
            if ready(store):
                store.company_rpc('refund_bind', {'id':order,'session_id':session['id'],
                    'payment_intent':session['payment_intent'],'livemode':live})
        return {'received':True,'verified':True}

    def reconcile(self, store, order):
        if not order.get('session_id'):
            raise ValueError('Checkoutがまだ作成されていません')
        mode='stripe_live' if order['session_id'].startswith('cs_live_') else 'stripe_test'
        session = self.api('checkout/sessions/'+order['session_id'],**({'payment_mode':mode} if mode=='stripe_live' else {}))
        if session.get('payment_status') != 'paid':
            return {'payment_status':'unpaid'}
        self.reconcile_session(store,session,'reconcile_'+session['id'])
        return {'payment_status':'paid'}
