"""PC-independent hourly discovery, invoked by a scoped Render cron client."""
import json
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode
from .agent_scout import register,state,fetch_issue
from .public_scout import normalize,MAX_RESPONSE
from .supabase_store import NoRedirect,StorageUnavailable

QUERIES=(
 'is:issue is:open csv bounty dedup in:title,body',
 'is:issue is:open csv bounty trim in:title,body',
 'is:issue is:open csv bounty json in:title,body',
 'is:issue is:open csv bounty audit in:title,body')

def search(query,opener=None):
    url='https://api.github.com/search/issues?'+urlencode({'q':query,'sort':'updated','order':'desc','per_page':10})
    req=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'Company-X2-cloud-scout'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect()).open)(req,timeout=20) as res:raw=res.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:raise ValueError('Search too large')
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('incomplete_results') is not False or not isinstance(data.get('items'),list):raise ValueError('Incomplete search')
        return data['items'][:10]
    except (OSError,ValueError):raise StorageUnavailable('クラウド探索の取得に失敗しました。次回再試行します') from None

def run(store,searcher=search,issue_fetcher=fetch_issue,now=None):
    now=now or datetime.now(timezone.utc)
    key='cloud_'+now.strftime('%Y%m%d_%H')
    saved=state(store)
    if any(x['key']==key for x in saved.get('recent_runs',[])):
        return {'saved':True,'replayed':True,'run_key':key}
    # A deterministic rotation can resume after a failed run without advancing.
    old=saved.get('checkpoint') or {}
    previous=old.get('next_query')
    index=QUERIES.index(previous) if previous in QUERIES else now.hour%len(QUERIES)
    query=QUERIES[index]
    raw=searcher(query)
    checked=now.isoformat()
    candidates=[item for issue in raw if (item:=normalize(issue,checked)) is not None]
    candidates.sort(key=lambda x:x['decision']!='needs_review')
    urls=list(dict.fromkeys(x['url'] for x in candidates))[:4]
    if saved.get('items'):
        previous_url=saved['items'][-1]['url']
        if previous_url not in urls:urls.append(previous_url)
    result=register(store,{'run_key':key,'urls':urls,'checkpoint':{
        'next_query':QUERIES[(index+1)%len(QUERIES)],
        'note':'Renderクラウド探索。検索 '+query+' / 取得 '+str(len(raw))+'件。募集・報酬・応募許可は未確認。'}},issue_fetcher)
    return {**result,'run_key':key,'query':query,'search_count':len(raw),'execution':'render_cron'}
