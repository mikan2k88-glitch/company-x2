"""Evidence-aware acquisition assessment. A listing is not an accepted order."""
import re
from .acquisition import organize
from .data_services import SERVICES
from datetime import datetime, timezone

def evidence(item, now):
    text=str(item.get('title',''))+'\n'+str(item.get('description',''))[:12000]
    lines=[x.strip()[:300] for x in text.splitlines() if x.strip()]
    patterns={'request':r'please|need|request|looking for|seeking|依頼|募集',
        'reward':r'USD|JPY|[$¥€£]|報酬|支払',
        'deadline':r'deadline|due date|締切|納期',
        'ai_terms':r'\bAI\b|automated|自動|人工知能',
        'payment_terms':r'payment|paid|pay upon|支払|入金'}
    quotes={k:next((x for x in lines if re.search(pattern,x,re.I)),None) for k,pattern in patterns.items()}
    deadline=None
    if quotes['deadline']:
        match=re.search(r'(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)',quotes['deadline'])
        if match:
            try:deadline=datetime.strptime(match[1],'%Y-%m-%d').date()
            except ValueError:pass
    return {'source_url':item.get('url'),'checked_at':item.get('source_checked_at'),
        'quotes':quotes,'deadline_date':deadline.isoformat() if deadline else None,
        'deadline_expired':deadline is not None and deadline<now.date(),
        'verified':False,'notice':'原文の記載です。支払者の合意・資金・応募許可の確認とは異なります。'}


def assess(items, now=None):
    now=now or datetime.now(timezone.utc)
    ranked=organize(items,now=now)
    counts={'scope_candidate':0,'excluded':0,'conditions_pending':0}
    for item in ranked['items']:
        title=str(item.get('title','')).lower()
        body=str(item.get('description',''))[:12000].lower()
        text=title+'\n'+body
        seller=bool(re.search(r'seller work offer|i will deliver|available for purchase|not a bounty',text))
        proposal=bool(re.search(r'not a funded offer|requested reward|bounty proposal|bounty suggestion|proposed reward',text))
        other_work=bool(re.search(r'\b(?:docs|quickstart|translation|serbian|monetization|architecture|research|dependency|cli|sdk)\b',title))
        explicit_csv=bool(re.search(r'\bcsv\b',title) or re.search(r'\b(?:please|need|request|looking for|seeking)\b.{0,100}\bcsv\b',body[:1200]))
        facts=evidence(item,now)
        supported=not facts['deadline_expired'] and item['eligible_for_review'] and explicit_csv and not other_work and not seller and not proposal
        if facts['deadline_expired']:reason='記載された期限を過ぎています。募集継続の確認が必要です'
        elif seller:reason='販売者の出品です。Company X2への発注募集ではありません'
        elif proposal:reason='報酬を提案している段階で、発注者の支払い承認は確認できません'
        elif other_work or not explicit_csv:reason='CSV加工の直接依頼ではなく、文書・開発・事業計画などの募集です'
        elif not item['eligible_for_review']:reason=item['review_note']
        else:reason='CSV作業の範囲候補です。報酬・納期・AI利用許可と実データの確認が必要です'
        missing=['発注者の依頼と合意','報酬額・通貨・支払い条件','期限','AIによる作業・応募の許可','実際のCSV入力'] if supported else []
        item.update(sales_candidate=supported,sales_reason=reason,sales_missing=missing,
            sales_status='conditions_pending' if supported else 'excluded',auto_contact_allowed=False,
            sales_evidence=facts)
        if item['review_group']=='review' and not supported:
            ranked['summary']['review']-=1
            ranked['summary']['unsupported']+=1
            item.update(review_group='unsupported',review_note=reason,eligible_for_review=False,score=0)
        counts['scope_candidate']+=int(supported);counts['conditions_pending']+=int(supported)
        counts['excluded']+=int(not supported)
    reasons={}
    for item in ranked['items']:
        reason=item['sales_reason'];reasons[reason]=reasons.get(reason,0)+1
    return {'exclusion_reasons':[{'reason':k,'count':v} for k,v in reasons.items() if any(x['sales_reason']==k and not x['sales_candidate'] for x in ranked['items'])],
        'evaluated_count':len(ranked['items']),'items':ranked['items'],'summary':counts,'triage_summary':ranked['summary'],
        'notice':'金額やCSVの単語だけでは発注募集と判定しません。案内文は下書きです。'}

def proposal(items,url):
    item=next((x for x in assess(items)['items'] if x.get('url')==url and x['sales_candidate']),None)
    if item is None:raise ValueError('営業対象のCSV依頼候補を選んでください')
    names='・'.join(SERVICES[k]['name'] for k in item['service_keys'])
    message=('Company X2は'+names+'に対応しています。UTF-8 CSV、1MB・10,000行以内の入力で処理範囲を確認できます。'
        '\n発注の意思、報酬額・通貨・支払い時期、納期、AIによる作業と応募の可否を確認させてください。'
        '\n現在の受付は無料検証またはStripeテスト100円です。実際の課金・報酬の受領は行いません。'
        '\n条件確認後、検証用の受付リンクをご案内します。機密データを公開Issueに添付しないでください。')
    return {'source_url':url,'title':item['title'],'message':message,'draft_only':True,
            'sent':False,'evidence':item['sales_evidence'],
            'estimate':{'status':'input_required','currency':'JPY','live_amount':None,
                'test_amount':100,'max_bytes':1000000,'max_rows':10000,
                'options':[{'service_key':k,**SERVICES[k]} for k in item['service_keys']],
                'deadline_committed':False,'notice':'実データと合意前の条件付き見積もりです。本番料金・納期は未確定です。'},
            'live_quote_jpy':None,'test_price_jpy':100,'missing_evidence':item['sales_missing']}
