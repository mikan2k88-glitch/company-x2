"""Evidence-based support: no external AI, no automatic hold releases."""
from .delivery_safety import require_plan, VERSION
from .data_services import make_artifact, SERVICES
import hashlib
import json
import re

VERSION_AUTOMATION='support-auto-v1'
FAQ={
 '対応サービスは？':'CSVの完全一致重複除去、空白整形、JSON変換、データ検査に対応します。実行前の作業計画で範囲を確認してください。',
 'What services are supported?':'We support exact CSV deduplication, whitespace trimming, CSV to JSON, and data inspection. Check the work plan before ordering.',
 '個人情報は送れますか？':'個人情報・認証情報を含むCSVは受付できません。匿名化したデータをご利用ください。',
 '本番販売はしていますか？':'現在、本番販売は停止しています。無料検証とStripeテスト決済で検証中です。',
}

def inspect(order):
    """Absent provenance is uncertainty; matched provenance permits hash comparison."""
    try:require_plan(order['plan'])
    except (ValueError,KeyError,TypeError,AttributeError):return 'manual','計画の安全検査記録が不足しているため自動判断できません。納品保留を継続します。'
    result=order.get('result');plan=order['plan']
    if order['status'] not in ('ready','delivered') or not isinstance(result,dict):
        return 'manual','成果物の検査記録を確認できません。納品保留を継続します。'
    if plan.get('service_key') not in SERVICES or not isinstance(result.get('artifact'),dict):
        return 'manual','処理範囲または成果物の検査記録を確認できません。納品保留を継続します。'
    proof=result.get('delivery_safety') or {};content=result['artifact'].get('content')
    if not isinstance(proof,dict):return 'manual','検査記録の形式を確認できません。納品保留を継続します。'
    expected=proof.get('artifact_sha256');download=result.get('download_sha256')
    if proof.get('version')!=VERSION or proof.get('input_sha256')!=plan.get('input_sha256') or not isinstance(content,str) or not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected) or not isinstance(download,str) or not re.fullmatch('[a-f0-9]{64}',download):
        return 'manual','検査記録が不足または旧版です。不備を確定せず、納品保留を継続します。'
    service=plan['service_key'];encoding='utf-8-sig' if service in ('csv_exact_dedup','csv_trim') else 'utf-8'
    if hashlib.sha256(content.encode('utf-8')).hexdigest()!=expected or hashlib.sha256(content.encode(encoding)).hexdigest()!=download:
        return 'confirmed_defect','自動再検査で保存済み成果物と納品時のハッシュ記録の不一致を確認しました。納品を停止し、支払い確認済みの有料注文は全額返金処理に進めます。'
    try:
        if service not in SERVICES or result.get('service_key')!=service or result['artifact']!=make_artifact(content,service):raise ValueError('metadata mismatch')
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return 'confirmed_defect','自動再検査で成果物の形式・サービス情報と合意した処理範囲の不一致を確認しました。納品を停止し、支払い確認済みの有料注文は全額返金処理に進めます。'
    return 'manual','保存済みファイルと検査記録は一致しています。ただし元CSVは処理後に消去するため、内容への異議を自動的に否定できません。納品保留を継続して個別確認します。'

def run_once(store):
    count=0
    for item in store.automation_rpc('pending'):
        if item.get('order'):
            outcome,reason=inspect(item['order'])
        else:
            reason=FAQ.get(item['ticket']['message'].strip()) if item['ticket']['kind']=='question' else None
            outcome='answered' if reason else 'manual'
            reason=reason or '個別確認が必要なため自動回答を保留しています。販売者情報の開示、取引書類、返金の確約は自動回答しません。'
        if store.automation_rpc('commit',{'id':item['ticket']['id'],'outcome':outcome,'reason':reason,
            'version':VERSION_AUTOMATION,'expected':item['order'],'expected_reply':item['ticket']['reply']}):count+=1
    return count
