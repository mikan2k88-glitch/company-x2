"""Single-coordinator scout inbox using the existing durable opportunity RPC."""
import hashlib
import json
import re
from datetime import datetime, timezone
from .public_scout import normalize
from .github_source import read_json, GitHubUnavailable

SOURCE = 'scheduled_agent_scout'
KEY = 'main'

def state(store):
    saved = next((x for x in store.opportunities() if x.get('source') == SOURCE and x.get('external_id') == KEY), None)
    return saved or {'source':SOURCE,'external_id':KEY,'items':[], 'checkpoint':None, 'recent_runs':[]}

def fetch_issue(url, opener=None):
    match = re.fullmatch(r'https://github\.com/([\w.-]+)/([\w.-]+)/issues/([1-9][0-9]*)',url)
    if not match:
        raise ValueError('GitHubの公開Issue URLを指定してください')
    issue=read_json('https://api.github.com/repos/'+match[1]+'/'+match[2]+'/issues/'+match[3],
                    'issue',opener=opener,timeout=15)
    if not isinstance(issue,dict) or issue.get('html_url') != url:
        raise GitHubUnavailable('issue','identity_mismatch')
    return issue

def register(store, data, fetcher=fetch_issue):
    urls=data.get('urls'); run=data.get('run_key'); checkpoint=data.get('checkpoint')
    if not isinstance(run,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',run):
        raise ValueError('16〜80文字のrun_keyが必要です')
    if not isinstance(urls,list) or len(urls)>5 or any(not isinstance(x,str) for x in urls):
        raise ValueError('1回の登録は最大5件のURLです')
    if not isinstance(checkpoint,dict) or set(checkpoint)-{'next_query','note'} or any(not isinstance(v,str) or len(v)>1000 for v in checkpoint.values()):
        raise ValueError('checkpointはnext_queryとnote（各1000文字以内）です')
    for url in urls:
        if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*',url):
            raise ValueError('GitHubの公開Issue URLを指定してください')
    fingerprint=hashlib.sha256(json.dumps({'urls':urls,'checkpoint':checkpoint},sort_keys=True).encode()).hexdigest()
    saved=state(store)
    failed_attempt=run.startswith('attempt_')
    if failed_attempt and (urls or checkpoint.get('next_query') != (saved.get('checkpoint') or {}).get('next_query')):
        raise ValueError('失敗記録では候補と探索範囲を変更できません')
    previous=next((r for r in saved.get('recent_runs',[]) if r['key']==run),None)
    if previous:
        if previous['fingerprint']!=fingerprint: raise ValueError('run_keyは同じ内容で再試行してください')
        return {'saved':True,'replayed':True,'checkpoint':saved['checkpoint']}
    checked=datetime.now(timezone.utc).isoformat()
    incoming=[]
    for url in dict.fromkeys(urls):
        item=normalize(fetcher(url),checked)
        if item is not None:
            incoming.append(item)
    # All network reads succeed before one durable upsert. Retrying does not duplicate candidates.
    by_url={i['url']:i for i in incoming}
    items=incoming+[i for i in saved.get('items',[]) if i['url'] not in by_url and i['url'] not in urls]
    result={'source':SOURCE,'external_id':KEY,'items':items[:30],'checkpoint':checkpoint,
        'checked_at':checked,'recent_runs':([{'key':run,'fingerprint':fingerprint,'checked_at':checked,'collected':len(incoming),'new_candidates':sum(i['url'] not in {x['url'] for x in saved.get('items',[])} for i in incoming)}]+saved.get('recent_runs',[]))[:24],
        'decision':'blocked','reason':'定期探索の状態。募集・報酬・応募許可は未確認です'}
    if failed_attempt:
        result['last_attempt_at']=checked
        if saved.get('last_failure'):
            result['last_failure']=saved['last_failure']
    store.save_opportunity(result,result['decision'],result['reason'])
    return {'saved':True,'replayed':False,'collected':len(incoming),'retained':len(result['items']),'checkpoint':checkpoint}


def summary(store, saved=None):
    from .sales import assess
    saved=state(store) if saved is None else saved
    counts=assess(saved.get('items',[]))['summary']
    runs=saved.get('recent_runs',[])
    successful=next((r for r in runs if not r['key'].startswith('attempt_')),None)
    checked=successful.get('checked_at') if successful else None
    age=None
    if checked:
        age=max(0,int((datetime.now(timezone.utc)-datetime.fromisoformat(checked)).total_seconds()))
    return {'last_success_at':checked,'last_attempt_at':saved.get('last_attempt_at',saved.get('checked_at')),
        'last_failure':saved.get('last_failure'),
        'seconds_since_success':age,'attention_required':age is None or age>7200,
        'retained':len(saved.get('items',[])),'review':counts['scope_candidate'],
        'recent_runs':saved.get('recent_runs',[])[:24],
        'notice':'2時間以上成功がない場合は確認が必要です。attempt_は失敗記録で、探索成功に数えません。クラウドタスクの実行履歴を確認してください。'}

