"""PC-independent discovery, invoked by the authenticated cloud task."""
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from .agent_scout import register,state,fetch_issue
from .public_scout import normalize
from .github_source import read_json, GitHubUnavailable

QUERIES=(
 'is:issue is:open csv bounty dedup in:title,body',
 'is:issue is:open csv bounty trim in:title,body',
 'is:issue is:open csv bounty json in:title,body',
 'is:issue is:open csv bounty audit in:title,body')

def search(query,opener=None):
    url='https://api.github.com/search/issues?'+urlencode({'q':query,'sort':'updated','order':'desc','per_page':10})
    data=read_json(url,'search',opener=opener)
    if not isinstance(data,dict) or not isinstance(data.get('items'),list):
        raise GitHubUnavailable('search','invalid_search_response')
    if data.get('incomplete_results') is not False:
        raise GitHubUnavailable('search','incomplete_search')
    return data['items'][:10]

def run(store,searcher=search,issue_fetcher=fetch_issue,now=None):
    now=now or datetime.now(timezone.utc)
    key='cloud_'+now.strftime('%Y%m%d_%H')
    saved=state(store)
    if any(x['key']==key for x in saved.get('recent_runs',[])):
        return {'saved':True,'replayed':True,'run_key':key}
    failure=saved.get('last_failure') or {}
    if failure.get('retry_at') and datetime.fromisoformat(failure['retry_at'])>now:
        diagnostic=failure['diagnostic']
        remaining=int((datetime.fromisoformat(failure['retry_at'])-now).total_seconds())
        raise GitHubUnavailable(diagnostic['stage'],diagnostic['reason'],
            status=diagnostic.get('http_status'),retry_after=remaining)
    try:
        return discover(store,saved,key,searcher,issue_fetcher,now)
    except GitHubUnavailable as exc:
        # Record source failures without pretending the source was refreshed.
        record={**saved,'last_failure':{'checked_at':now.isoformat(),
            'retry_at':(now+timedelta(seconds=exc.retry_after)).isoformat(),
            'diagnostic':exc.diagnostic()},'last_attempt_at':now.isoformat()}
        store.save_opportunity(record,record.get('decision','blocked'),
            record.get('reason','定期探索の取得待ち'))
        raise


def discover(store,saved,key,searcher,issue_fetcher,now):
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
    return {**result,'run_key':key,'query':query,'search_count':len(raw),'execution':'cloud_api'}
