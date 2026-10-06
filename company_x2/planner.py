"""Conservative request intake. No model, network or arbitrary code execution."""
import hashlib
import csv
import json
import unicodedata

from .data_services import SERVICES, produce, verify

# Whole-request matching prevents silently ignoring unsupported clauses or negation.
REQUESTS = {
    'csv_exact_dedup': ('CSVの重複を除去', 'CSVの重複行を除去してください', 'remove duplicate CSV rows', 'deduplicate CSV'),
    'csv_trim': ('CSVの前後の空白を除去', 'CSVの前後の空白を除去してください', 'trim CSV whitespace'),
    'csv_to_json': ('CSVをJSONに変換', 'CSVをJSONに変換してください', 'convert CSV to JSON'),
    'csv_audit': ('CSVを検査', 'CSVの空欄と重複を検査してください', 'audit CSV', 'check CSV data quality'),
}


def normalize_request(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1000:
        raise ValueError('依頼文は1〜1,000文字で入力してください')
    return ' '.join(unicodedata.normalize('NFKC', value).strip().rstrip('。.!！').casefold().split())


def plan_request(request, text):
    if not isinstance(text, str):
        raise ValueError('CSVを文字列で指定してください')
    normalized = normalize_request(request)
    service = next((key for key, examples in REQUESTS.items()
                    if normalized in {normalize_request(example) for example in examples}), None)
    if service is None:
        raise ValueError('依頼内容を確定できません。対応する依頼例を選んでください。複数処理・独自条件は未対応です。')
    try:
        result = produce(text, service)
        verify(text, service, result)
    except csv.Error:
        raise ValueError('CSVの形式を確認してください') from None
    # Include only the scope and counts. Never expose customer cells in the plan.
    plan = {'schema_version': 1, 'mode': 'sandbox', 'planner': 'deterministic',
            'service_key': service, 'service_name': SERVICES[service]['name'],
            'scope': SERVICES[service]['description'],
            'input_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'input_rows': result['input_rows'], 'expected_output_rows': result['output_rows'],
            'output_format': SERVICES[service]['format'],
            'steps': ['依頼・入力検査', '注文を永続保存', '成果物を制作', '入力と成果物を照合', '所有者用ダウンロードを提供'],
            'price_jpy': 0, 'revenue_jpy': 0, 'ai_connected': False,
            'outreach_enabled': False, 'payments_enabled': False}
    plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True,
                                                   separators=(',', ':')).encode()).hexdigest()
    return plan
