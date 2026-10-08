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

def issue(key,now=None):
    expires=int(time.time() if now is None else now)+LIFETIME
    body=encode(json.dumps({'scope':'intake_test','exp':expires,'nonce':secrets.token_hex(16)},separators=(',',':')).encode())
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
        return (data.get('scope')=='intake_test' and type(data.get('exp')) is int
                and current<data['exp']<=current+LIFETIME)
    except (ValueError,UnicodeError,TypeError):return False

def permits(method,path):
    if method=='GET':
        return path=='/api/intake/config' or bool(re.fullmatch(r'/api/company/transactions/[A-Za-z0-9_-]+(?:/download)?',path))
    return method=='POST' and path in ('/api/company/quote','/api/company/transactions',
        '/api/company/checkout','/api/company/reconcile','/api/company/receipt')
