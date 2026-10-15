"""Time-bounded free operation and content-free development feedback."""
import os
from datetime import datetime,timezone

def policy(env=None,now=None):
    env=os.environ if env is None else env;now=now or datetime.now(timezone.utc)
    enabled=env.get('FREE_TRIAL_ENABLED','false').lower()=='true'
    result={'enabled':enabled,'open':True,'orders_per_day':3 if enabled else 10,
      'starts_at':env.get('FREE_TRIAL_START',''),'ends_at':env.get('FREE_TRIAL_END',''),
      'notice':'利用状況の集計を改善に使います。CSV本文・問い合わせ本文を開発用の記録やAI学習に使いません。'}
    if enabled:
        try:
            start=datetime.fromisoformat(result['starts_at'].replace('Z','+00:00'))
            end=datetime.fromisoformat(result['ends_at'].replace('Z','+00:00'))
            if start.tzinfo is None or end.tzinfo is None or not 0<(end-start).total_seconds()<=14*86400:raise ValueError('Invalid period')
            result['open']=start<=now<end
        except (ValueError,TypeError):result['open']=False
    return result

def report(store,env=None):
    from .public_intake import records
    p=policy(env);ids=[]
    for state in sorted(records(store),key=lambda x:x['external_id'],reverse=True)[:30]:
        if p['enabled'] and state['external_id']<p['starts_at'][:10]:continue
        ids.extend(t['id'] for t in state['tickets'].values() if t.get('id'))
    rows=store.trial_rpc('report',{'ids':list(dict.fromkeys(ids))[:300],
      'since':p['starts_at'] if p['enabled'] else '1970-01-01T00:00:00Z'})
    services={};totals=dict(accepted=0,ready=0,delivered=0,failed=0,unfinished=0)
    for row in rows:
        key=row['service_key'];s=services.setdefault(key,{**dict(accepted=0,ready=0,delivered=0,failed=0,unfinished=0),'durations':[]})
        for bucket in ('accepted',row['status'] if row['status'] in ('ready','delivered','failed') else 'unfinished'):
            s[bucket]+=1;totals[bucket]+=1
        if row['processing_seconds'] is not None:s['durations'].append(row['processing_seconds'])
    for s in services.values():
        durations=s.pop('durations');s['average_processing_seconds']=round(sum(durations)/len(durations),3) if durations else None
    completed=totals['ready']+totals['delivered']+totals['failed']
    rate=totals['failed']/completed if completed else None
    pause=p['enabled'] and completed>=3 and rate>=0.3
    from .template_customer import metrics
    template=metrics(store,p['starts_at'] if p['enabled'] else '1970-01-01T00:00:00Z')
    pause=pause or (p['enabled'] and template['new_intake_paused'])
    advice=[]
    if totals['failed']:advice.append('失敗がある処理を合成CSVで再現し、安全検査・処理・納品経路を確認してください。顧客CSVはテストに転用しません。')
    if totals['ready']:advice.append('成果物の準備から受領までの案内を確認してください。未受領は処理失敗に数えません。')
    if not totals['accepted']:advice.append('実依頼の記録待ちです。実験の成功を顧客利用の成功率に混ぜません。')
    return {'endpoint':'E37','policy':p,'totals':totals,'services':services,
      'failure_rate':rate,'new_intake_paused':pause,'development_actions':advice,'template_work':template,
      'privacy':'公開受付の注文だけを集計。CSV・成果物・問い合わせ本文・利用者トークン・注文IDは含みません。',
      'cost_notice':'公開CSV加工は外部AIを呼びません。管理側のAI利用費は別の予算予約で管理します。'}

def require_open(store):
    from .public_intake import LimitReached
    p=policy()
    if not p['enabled']:return
    if not p['open']:raise LimitReached('無料試験の新規受付は期間外です。既存の成果物は受け取れます。')
    if report(store)['new_intake_paused']:raise LimitReached('無料試験の処理失敗を確認中です。新規受付を保留しています。')
