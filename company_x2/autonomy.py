"""Conservative acquisition-to-intake coordinator. Listing text is never a command."""
import hashlib,math,os,re
from datetime import datetime,timezone
from urllib.parse import urlencode
from . import outreach
from .intake_access import issue as invite

FREE='[company-x2: free verification accepted]'
AI='[company-x2: AI processing allowed]'

def consent(text):
    text=text if isinstance(text,str) else ''
    # Require a structured affirmative reply; surrounding conditions fail closed.
    remaining=text.replace(FREE,'').replace(AI,'').strip()
    return {'accepted':FREE in text and AI in text and not remaining,
      'reason':'明確な無料検証・AI利用の同意を確認' if FREE in text and AI in text and not remaining else '2つの同意マーカーだけの返信が必要です。追加条件・曖昧な返信は保留します。'}

def economics(metrics,env=None):
    env=os.environ if env is None else env
    def number(name,default=0):
        try:
            value=float(env.get(name,default));return value if math.isfinite(value) and value>=0 else default
        except (TypeError,ValueError):return default
    orders=int(metrics.get('live_orders',0));failed=int(metrics.get('failed',0));total=int(metrics.get('orders',0))
    revenue=int(metrics.get('live_revenue_jpy',0));refund=int(metrics.get('live_refunds_jpy',0))
    fx=number('COST_USD_JPY');fee=number('PAYMENT_FEE_RATE',0);fixed=number('MONTHLY_FIXED_COST_JPY')
    known=fx>0 and 'PAYMENT_FEE_RATE' in env and fee<=1 and 'MONTHLY_FIXED_COST_JPY' in env
    cost=math.ceil(int(metrics.get('ai_reserved_micro_usd',0))*fx/1_000_000+revenue*fee+fixed) if known else None
    net=revenue-refund-cost if cost is not None else None
    loss=number('MAX_MONTHLY_LOSS_JPY',1000)
    reasons=[]
    if not known:reasons.append('為替換算・決済手数料・固定費の設定が不足しています')
    if net is not None and net < -loss:reasons.append('月次損失上限を超えています')
    if orders>=5 and int(metrics.get('refunded_orders',0))/orders>=0.2:reasons.append('返金率が20%以上です')
    if total>=10 and failed/total>=0.3:reasons.append('加工失敗率が30%以上です')
    current=max(50,min(10000,int(number('LIVE_PRICE_JPY',100))))
    # A recommendation only. Do not silently change accepted or quoted prices.
    suggested=min(10000,max(50,math.ceil((cost or 0)/max(orders,1)/max(0.01,1-fee)*1.2))) if orders>=10 and known else current
    return {'live_allowed':not reasons,'reasons':reasons,'net_estimate_jpy':net,'estimated_cost_jpy':cost,
      'cost_basis':'AI予約額による保守的な見積もり。実際の請求額ではありません。',
      'suggested_price_jpy':suggested,'price_auto_applied':False,'metrics':metrics}

def preview(store,env=None,client=None):
    env=os.environ if env is None else env;client=client or outreach.GitHubContact(env)
    report={'checked':0,'drafts':0,'excluded':{},'source_errors':0}
    for repo in outreach.status(env)['repos']:
        try:issues=client.api('/repos/'+repo+'/issues?state=open&sort=updated&per_page=20')
        except Exception:report['source_errors']+=1;continue
        if not isinstance(issues,list):report['source_errors']+=1;continue
        for item in issues[:20]:
            report['checked']+=1
            eligible=outreach.candidate(item,env)
            if eligible:
                url=eligible['url'];id='ot_'+hashlib.sha256(url.encode()).hexdigest()[:32]
                store.outreach_rpc('prepare',{'id':id,'url':url,'issue_id':str(item['id']),'author':item['user']['login'],
                  'message':outreach.MESSAGE+'\nFor explicit consent, reply with only '+FREE+' '+AI+'\n\n<!-- company-x2-outreach:'+id+' -->'})
                report['drafts']+=1
            else:
                reason='自動応募許可なし' if outreach.PERMISSION not in (item.get('body') or '') else '対象範囲・募集状態が不適合'
                report['excluded'][reason]=report['excluded'].get(reason,0)+1
    return report

def intake_source(store,contact_id):
    contact=next((x for x in store.outreach_rpc('list') if x['id']==contact_id),None)
    if not contact or contact['status']!='sent' or not consent(contact.get('reply_text'))['accepted']:
        raise ValueError('外部案件の同意を確認できません。受付を停止しました。')
    return contact['url']

def cycle(store,env=None,client=None,signing_key=None,now=None):
    env=os.environ if env is None else env
    now=now or datetime.now(timezone.utc);run_id=now.strftime('%Y%m%d_%H')
    lease=store.autonomy_rpc('claim',{'id':run_id})
    if not lease:return {'replayed':True,'run_id':run_id}
    client=client or outreach.GitHubContact(env)
    report={'run_id':run_id,'sent':0,'followups_prepared':0,'held':0}
    try:
        report.update(preview(store,env,client))
        for contact in store.outreach_rpc('list'):
            if contact['status']!='sent':continue
            observed=client.observe(contact)
            if observed:store.outreach_rpc('observe',observed);contact.update(observed)
            decision=consent(contact.get('reply_text'))
            if decision['accepted'] and signing_key:
                grant,_=invite(signing_key,contact_id=contact['id'])
                body='Company X2 automated free verification invitation. No paid job or deadline is accepted. Confirm the work plan before processing.\nhttps://company-x2.onrender.com/intake#'+urlencode({'access':grant})
                store.autonomy_rpc('prepare_message',{'contact_id':contact['id'],'reply_id':contact['reply_id'],'body':body})
                report['followups_prepared']+=1
            elif contact.get('reply_text'):report['held']+=1
        budget=economics(store.autonomy_rpc('metrics'),env)
        risk_stop=any('設定が不足' not in reason for reason in budget['reasons'])
        report['risk_stop']=risk_stop
        if outreach.status(env)['ready'] and not risk_stop:
            message=store.autonomy_rpc('claim_message')
            if message:
                try:
                    contact=next(x for x in store.outreach_rpc('list') if x['id']==message['contact_id'])
                    observed=client.observe(contact)
                    if not observed or observed['reply_id']!=message['reply_id'] or not consent(observed['reply_text'])['accepted']:raise ValueError('Consent changed')
                    path='/repos/'+'/'.join(contact['url'].split('/')[3:5])+'/issues/'+contact['url'].rsplit('/',1)[1]
                    current=client.api(path);user=client.api('/user')
                    if not outreach.candidate(current,env) or str(current['id'])!=contact['issue_id'] or current['user']['login']!=contact['author'] or user.get('login','').lower()!=env.get('GITHUB_OUTREACH_LOGIN','').lower():raise ValueError('Source changed')
                    marker='<!-- company-x2-invite:'+message['id']+' -->'
                    comments=client.api(path+'/comments?per_page=100')
                    if current.get('comments',101)>100 or not isinstance(comments,list):raise ValueError('Comments unavailable')
                    old=next((c for c in comments if marker in (c.get('body') or '') and c.get('user',{}).get('login','').lower()==user['login'].lower()),None)
                    sent=old or client.api(path+'/comments',{'body':message['body']+'\n'+marker})
                    if type(sent.get('id')) is not int or sent.get('html_url')!=contact['url']+'#issuecomment-'+str(sent['id']):raise ValueError('Comment mismatch')
                    store.autonomy_rpc('finish_message',{'id':message['id'],'url':sent['html_url']});report['sent']=1
                except Exception:store.autonomy_rpc('uncertain_message',{'id':message['id']})
            else:
                job=store.outreach_rpc('claim')
                if job:
                    try:
                        sent=client.send(job)
                        if type(sent.get('id')) is not int or sent.get('html_url')!=job['url']+'#issuecomment-'+str(sent['id']):raise ValueError('Comment mismatch')
                        store.outreach_rpc('finish',{'id':job['id'],'comment_url':sent['html_url']});report['sent']=1
                    except Exception:store.outreach_rpc('uncertain',{'id':job['id']})
        report['economics']=economics(store.autonomy_rpc('metrics'),env)
        store.autonomy_rpc('finish',{'id':run_id,'lease':lease,'status':'success','report':report})
        return report
    except Exception:
        store.autonomy_rpc('finish',{'id':run_id,'lease':lease,'status':'failed','report':{'error':'工程を完了できませんでした。認証・取得元・DBを確認してください。'}})
        raise
