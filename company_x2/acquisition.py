"""E10 listing triage and bounded draft contracts; no external submissions."""
import re
import unicodedata
from datetime import datetime, timezone
from .data_services import SERVICES


def organize(items, now=None):
    now = now or datetime.now(timezone.utc)
    seen_urls, seen_titles, ranked = {}, {}, []
    counts = {'review':0, 'stale':0, 'unknown_date':0, 'unsupported':0, 'duplicate':0}
    for original in items[:30]:
        item = dict(original)
        keys = list(dict.fromkeys(k for k in item.get('service_keys', []) if k in SERVICES))
        title = unicodedata.normalize('NFKC', str(item.get('title',''))).casefold()
        title = re.sub(r'^\s*\[(?:bounty[^\]]*|[\w.-]+/[\w.-]+)\]\s*', '', title)
        title = re.sub(r'\s+', ' ', title).strip()
        url = item.get('url')
        valid_url = isinstance(url,str) and re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*',url)
        duplicate = seen_urls.get(url) if valid_url else None
        if not duplicate and len(title) >= 24:
            duplicate = seen_titles.get(title)
        age = None
        try:
            updated = datetime.fromisoformat(item.get('source_updated_at','').replace('Z','+00:00'))
            if updated.tzinfo is not None and updated <= now:
                age = (now-updated).days
        except (ValueError, TypeError, AttributeError):
            pass
        if duplicate:
            group, detail = 'duplicate', '同じURLまたは同じ募集名の候補があります。重複の可能性を確認してください'
        elif not valid_url or item.get('decision') != 'needs_review' or not keys:
            group, detail = 'unsupported', item.get('reason') or '対応範囲・募集条件を確認できません'
        elif age is None:
            group, detail = 'unknown_date', '更新日を確認できないため、募集が継続しているか確認してください'
        elif age > 90:
            group, detail = 'stale', '90日を超えて更新がないため、募集が継続しているか確認してください'
        else:
            group, detail = 'review', '対応範囲の候補です。顧客の合意と実データが必要です'
        counts[group] += 1
        if valid_url and not duplicate:
            seen_urls[url] = url
            if len(title) >= 24:
                seen_titles[title] = url
        item.update(service_keys=keys, review_group=group, review_note=detail,
            age_days=age, duplicate_of=duplicate, eligible_for_review=group=='review',
            execution_allowed=False, auto_bid_allowed=False,
            score=(80 if group=='review' else 0)+(10 if group=='review' and len(keys)==1 else 0),
            missing_evidence=['顧客の依頼と合意','実際の入力データ','期限と処理条件','入金確認'],
            acquisition_status='unverified_listing')
        ranked.append(item)
    order = {'review':0,'unknown_date':1,'stale':2,'unsupported':3,'duplicate':4}
    ranked.sort(key=lambda x:(order[x['review_group']],-x['score'],x.get('external_id','')))
    return {'items':ranked,'summary':counts,'stale_after_days':90,
            'notice':'最新最大30件の整理です。募集や報酬の有効性・自動応募の許可は未確認です。'}


def draft(items, url):
    item = next((x for x in organize(items)['items'] if x.get('url') == url), None)
    if item is None or not item['eligible_for_review']:
        raise ValueError('対応可能かつ更新日の確認できる候補を選んでください')
    return {'source_url':item['url'],'title':item['title'],'draft_only':True,
        'listing_reward':item.get('reward_mention'),'reward_verified':False,
        'options':[{'service_key':key,'service_name':SERVICES[key]['name'],
            'scope':SERVICES[key]['description'],'output_format':SERVICES[key]['format'],
            'required_input':'UTF-8 CSV、1MB・10,000行以内。実データで計画を作成してください。',
            'free_verification_jpy':0,'test_checkout_jpy':100,'live_quote_jpy':None}
            for key in item['service_keys']],
        'missing_evidence':item['missing_evidence'],
        'notice':'見積もりの下書きです。入力がないため行数・成果物・本番料金は確定しません。応募や受注は行っていません。'}
