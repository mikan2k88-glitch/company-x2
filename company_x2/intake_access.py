"""Expiring, stateless customer access; never grants company administration."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

LIFETIME=7*24*3600
def encode(raw):return base64.urlsafe_b64encode(raw).decode().rstrip('=')

def issue(key,now=None,scope="intake_test",contact_id=None):
    if scope not in ("intake_test","intake_live"):raise ValueError("Invalid intake scope")
    expires=int(time.time() if now is None else now)+LIFETIME
    claims={'scope':scope,'exp':expires,'nonce':secrets.token_hex(16)}
    if contact_id is not None:
        if scope!='intake_test' or not re.fullmatch(r'ot_[a-f0-9]{32}',contact_id):raise ValueError('Invalid contact grant')
        claims['contact_id']=contact_id
    body=encode(json.dumps(claims,separators=(',',':')).encode())
    signature=encode(hmac.new(key.encode(),body.encode(),hashlib.sha256).digest())
    return body+'.'+signature,expires

def valid(token,key,now=None):
    if not isinstance(token,str) or len(token)>512:return False
    try:
        body,signature=token.split('.')
        expected=encode(hmac.new(key.encode(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(signature.encode(),expected.encode()):return False
        data=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        current=int(time.time() if now is None else now)
        return (data.get('scope') in ('intake_test','intake_live') and type(data.get('exp')) is int
                and current<data['exp']<=current+LIFETIME)
    except (ValueError,UnicodeError,TypeError):return False

def permits(method,path):
    if method=='GET':
        return path=='/api/intake/config' or bool(re.fullmatch(r'/api/company/transactions/[A-Za-z0-9_-]+(?:/download)?',path))
    return method=='POST' and path in ('/api/company/quote','/api/company/transactions',
        '/api/company/checkout','/api/company/reconcile','/api/company/receipt')

def public_issue(key,owner,now=None):
    from .public_intake import owner_hash
    expires=int(time.time() if now is None else now)+3600
    body=encode(json.dumps({'scope':'public_free','exp':expires,'owner':owner_hash(owner),
        'nonce':secrets.token_hex(16)},separators=(',',':')).encode())
    return body+'.'+encode(hmac.new(key.encode(),body.encode(),hashlib.sha256).digest()),expires

def public_valid(token,key,owner,now=None):
    from .public_intake import owner_hash
    if not isinstance(token,str) or len(token)>512:return False
    try:
        body,signature=token.split('.')
        expected=encode(hmac.new(key.encode(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(signature.encode(),expected.encode()):return False
        data=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        current=int(time.time() if now is None else now)
        return (data.get('scope')=='public_free' and type(data.get('exp')) is int
            and current<data['exp']<=current+3600 and data.get('owner')==owner_hash(owner))
    except (ValueError,UnicodeError,TypeError):return False

def public_permits(method,path):
    if method=='GET' and path=='/api/intake/template/status':return True
    if method=='POST' and path in ('/api/intake/template/bind','/api/intake/template/suggest','/api/intake/template/plan','/api/intake/template/request',
                                  '/api/intake/template/process','/api/intake/template/receive'):return True
    return (method=='GET' and permits(method,path)) or (method=='POST' and path in
        ('/api/company/quote','/api/company/transactions','/api/company/receipt'))


def live_valid(token,key):
    if not valid(token,key):return False
    body=token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(body+"="*(-len(body)%4))).get("scope")=="intake_live"


def contact_claim(token,key):
    if not valid(token,key):return None
    body=token.split('.')[0]
    claim=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4))).get('contact_id')
    return claim if isinstance(claim,str) and re.fullmatch(r'ot_[a-f0-9]{32}',claim) else None
