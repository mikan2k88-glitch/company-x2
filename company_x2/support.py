"""Private support tickets; deterministic guidance, never external AI or automatic refunds."""
import re
import secrets
import hashlib
import json

KINDS = {'question':'サービスについて', 'refund':'決済・返金について',
         'disclosure':'販売者情報の開示請求', 'receipt':'領収書・取引書類について'}
GUIDANCE = {
 'question':'CSVの重複除去・空白整形・JSON変換・データ検査に対応しています。注文は依頼受付窓口から行ってください。個別の質問は運営者が確認します。',
 'refund':'決済・返金のご相談を受け付けました。この問い合わせだけでは返金を実行しません。注文との関係を運営者が確認します。',
 'disclosure':'販売者情報の開示請求を受け付けました。この受付確認は情報の開示ではありません。現在、本番販売は準備中です。運営者の回答をお待ちください。',
 'receipt':'取引書類についてのご要望を受け付けました。発行要否を含め運営者が確認します。ここでは発行を拒否・確約しません。'}

def token_hash(token):
    if not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{64}',token):
        raise ValueError('秘密の確認キーが必要です')
    return hashlib.sha256(token.encode()).hexdigest()

def create(store,data,token,order_token=''):
    kind=data.get('kind'); message=data.get('message'); key=data.get('request_key')
    if not isinstance(kind,str) or kind not in (*KINDS,'defect') or not isinstance(message,str) or not 1<=len(message.strip())<=2000:
        raise ValueError('問い合わせ種別と2000文字以内の本文を指定してください')
    if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',key):
        raise ValueError('受付キーが必要です')
    message=message.strip()
    order_id=data.get('order_id') if kind=='defect' else None
    if kind=='defect' and (not isinstance(order_id,str) or not re.fullmatch(r'cx_[A-Za-z0-9_-]{20,50}',order_id) or not isinstance(order_token,str) or not 32<=len(order_token)<=128):
        raise ValueError('注文番号と注文の所有者キーが必要です')
    fingerprint=hashlib.sha256(json.dumps([kind,message,order_id],ensure_ascii=False).encode()).hexdigest()
    payload={'id':'sp_'+secrets.token_hex(16),'token_hash':token_hash(token),
        'request_key':key,'kind':'refund' if kind=='defect' else kind,'message':message,'fingerprint':fingerprint,
        'guidance':'問題報告を保存し、この注文の以後の納品を保留しました。返金はまだ実行していません。確認結果をお待ちください。' if kind=='defect' else GUIDANCE[kind]}
    if kind=='defect':
        payload.update(order_id=order_id,order_token_hash=hashlib.sha256(order_token.encode()).hexdigest())
        return store.case_rpc('report',payload)
    return store.support_rpc('create',payload)

def get(store,id,token):
    if not re.fullmatch(r'sp_[a-f0-9]{32}',id):return None
    payload={'id':id,'token_hash':token_hash(token)}
    ticket=store.support_rpc('get',payload)
    if ticket:ticket['case']=store.case_rpc('get',payload)
    return ticket

def reply(store,data):
    text=data.get('reply'); id=data.get('id')
    if not isinstance(id,str) or not re.fullmatch(r'sp_[a-f0-9]{32}',id) or not isinstance(text,str) or not 1<=len(text.strip())<=4000:
        raise ValueError('受付番号と4000文字以内の回答が必要です')
    return store.support_rpc('reply',{'id':id,'reply':text.strip()})

def ready(store):
    try:return store.support_rpc('ping')=={'support_schema_version':21} and store.case_rpc('ping')=={'case_schema_version':23}
    except Exception:return False

def resolve(store,data):
    if not isinstance(data.get('id'),str) or not re.fullmatch(r'sp_[a-f0-9]{32}',data['id']) or data.get('decision') not in ('confirmed_defect','not_confirmed') or not isinstance(data.get('reason'),str) or not 1<=len(data['reason'].strip())<=4000:
        raise ValueError('判断と4000文字以内の確認理由が必要です')
    return store.case_rpc('resolve',{'id':data['id'],'decision':data['decision'],'reason':data['reason'].strip()})
