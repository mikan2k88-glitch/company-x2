"""Bounded content screening and fail-closed delivery evidence, not legal clearance."""
import hashlib
import json
import re
import unicodedata

from .data_services import read_csv, require_service
from .intake_risk import VERSION as RISK_VERSION, require_declared_scope

VERSION = 'delivery-safety-v1'
SENSITIVE_HEADERS = {'email','emailaddress','phone','telephone','address','password','secret',
                     'apikey','accesstoken','creditcard','ssn','dateofbirth','fullname',
                     'メール','メールアドレス','電話','電話番号','住所','氏名','生年月日','パスワード','マイナンバー'}
PATTERNS = (
    re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I),
    re.compile(r'(?:sk_(?:live|test|proj)_|whsec_|AIza)[A-Za-z0-9_-]{8,}'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'(?<!\d)0\d{1,4}[- ]\d{1,4}[- ]\d{3,4}(?!\d)'),
)


def check_string(value, header=False):
    normalized = unicodedata.normalize('NFKC', value)
    if header and re.sub(r'[\s_-]', '', normalized).casefold() in SENSITIVE_HEADERS:
        raise ValueError('安全検査: 個人情報・秘密情報を示す列があるため受付・納品できません')
    if normalized.lstrip().startswith(('=', '+', '-', '@')) or any(ord(c)<32 and c not in '\t\r\n' for c in normalized):
        raise ValueError('安全検査: 数式・制御文字のような値があるため受付・納品できません')
    if any(pattern.search(normalized) for pattern in PATTERNS):
        raise ValueError('安全検査: 連絡先・認証情報のような値があるため受付・納品できません')


def inspect_input(text):
    header, rows = read_csv(text)
    for key in header:
        check_string(key, header=True)
    for row in rows:
        for value in row:
            check_string(value)
    return {'version': VERSION, 'input_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def inspect_artifact(content, service):
    require_service(service)
    if service in ('csv_exact_dedup', 'csv_trim'):
        inspect_input(content)
    else:
        value = json.loads(content)
        def walk(item):
            if isinstance(item, str):
                check_string(item)
            elif isinstance(item, dict):
                for key, child in item.items():
                    check_string(key, header=True)
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)
        walk(value)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def require_plan(plan):
    risk = plan.get('intake_risk') or {}
    if risk.get('version') != RISK_VERSION:
        raise ValueError('安全確認の版が未確認です。新しい計画が必要です')
    require_declared_scope(risk.get('declarations'))
    proof = plan.get('input_safety') or {}
    if proof.get('version') != VERSION or proof.get('input_sha256') != plan.get('input_sha256'):
        raise ValueError('入力の安全確認が未完了です。新しい計画が必要です')


def require_delivery(order):
    require_plan(order['plan'])
    result = order.get('result') or {}
    proof = result.get('delivery_safety') or {}
    if proof.get('version') != VERSION or proof.get('input_sha256') != order['plan']['input_sha256']:
        raise ValueError('納品前の安全検査が未完了です')
    content = result.get('artifact', {}).get('content')
    if not isinstance(content, str) or inspect_artifact(content, order['plan']['service_key']) != proof.get('artifact_sha256'):
        raise ValueError('成果物の安全検査が一致しません')
    encoding = 'utf-8-sig' if order['plan']['service_key'] in ('csv_exact_dedup','csv_trim') else 'utf-8'
    if hashlib.sha256(content.encode(encoding)).hexdigest() != result.get('download_sha256'):
        raise ValueError('納品ファイルの検査記録が一致しません')
