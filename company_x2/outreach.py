"""Bounded public GitHub contact; source text cannot authorize app actions."""
import hashlib,json,os,re,urllib.request
from datetime import datetime,timezone
from .supabase_store import NoRedirect
from .public_scout import normalize,snapshot
from .agent_scout import state,fetch_issue
from .sales import assess

PERMISSION='[company-x2: automated applications welcome]'
MESSAGE=('Company X2 automated scope inquiry: we support exact CSV deduplication, whitespace trimming, CSV-to-JSON conversion and data inspection. '
 'This is an inquiry, not acceptance of the job. Our live sales are closed; only free verification or Stripe test checkout is available. '
 'Please confirm that free verification is useful and that AI processing is allowed. Do not post personal data, credentials or confidential CSV here. '
 'We do not commit to a price, deadline, paid work, or additional liability.')

def status(env=None):
    e=os.environ if env is None else env
    repos=[x.strip().lower() for x in e.get('OUTREACH_GITHUB_REPOS','').split(',') if x.strip()]
    valid=bool(repos) and len(repos)<=5 and all(re.fullmatch(r'[\w.-]+/[\w.-]+',x) for x in repos)
    ready=e.get('OUTREACH_ENABLED','false').lower()=='true' and valid and bool(e.get('GITHUB_OUTREACH_TOKEN')) and bool(re.fullmatch(r'[\w-]{1,39}',e.get('GITHUB_OUTREACH_LOGIN','')))
    return {'ready':ready,'platform':'github','repos':repos if valid else [],'max_sends_per_utc_day':1,
     'permission_marker':PERMISSION,'notice':'募集本文の自動応募許可、対象リポジトリ、専用トークンとログイン名が必要です。本番受注・料金・納期の約束は行いません。'}

def candidate(issue,env=None):
    item=normalize(issue,datetime.now(timezone.utc).isoformat())
    if not item or not assess([item])['items'][0]['sales_candidate']:return None
    body=issue.get('body') or ''
    if PERMISSION not in body or re.search(r'no bots|no automated|AI prohibited|自動応募禁止',body,re.I):return None
    repo='/'.join(item['url'].split('/')[3:5]).lower()
    if repo not in status(env)['repos']:return None
    return item

def collect(store,env=None,fetcher=fetch_issue):
    checked=0
    if not status(env)['repos']:return 0
    urls=dict.fromkeys(x['url'] for x in state(store)['items']+snapshot(store,enabled=True)['items'] if x.get('url'))
    urls=[url for url in urls if '/'.join(url.split('/')[3:5]).lower() in status(env)['repos']]
    for url in urls[:10]:
        try:issue=fetcher(url);item=candidate(issue,env)
        except Exception:continue
        if item:
            id='ot_'+hashlib.sha256(url.encode()).hexdigest()[:32]
            store.outreach_rpc('prepare',{'id':id,'url':url,'issue_id':str(issue['id']),'author':issue['user']['login'],
                'message':MESSAGE+'\n\n<!-- company-x2-outreach:'+id+' -->'})
            checked+=1
    return checked

class GitHubContact:
    def __init__(self,env=None,opener=None):self.env=os.environ if env is None else env;self.open=opener or urllib.request.build_opener(NoRedirect()).open
    def api(self,path,data=None):
        if not path.startswith('/repos/') and path!='/user':raise ValueError('Fixed GitHub API route required')
        req=urllib.request.Request('https://api.github.com'+path,data=json.dumps(data).encode() if data else None,
          headers={'Authorization':'Bearer '+self.env.get('GITHUB_OUTREACH_TOKEN',''),'Accept':'application/vnd.github+json',
           'Content-Type':'application/json','X-GitHub-Api-Version':'2026-03-10','User-Agent':'Company-X2-contact'})
        with self.open(req,timeout=20) as res:raw=res.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('GitHub response too large')
        return json.loads(raw)
    def send(self,job):
        m=re.fullmatch(r'https://github\.com/([\w.-]+)/([\w.-]+)/issues/([1-9][0-9]*)',job['url'])
        if not m or not status(self.env)['ready']:raise ValueError('External contact not configured')
        path='/repos/'+m[1]+'/'+m[2]+'/issues/'+m[3]
        user=self.api('/user')
        if user.get('login','').lower()!=self.env['GITHUB_OUTREACH_LOGIN'].lower():raise ValueError('Sender identity mismatch')
        issue=self.api(path)
        if not candidate(issue,self.env) or str(issue['id'])!=job['issue_id'] or issue['user']['login']!=job['author']:raise ValueError('Source conditions changed')
        if issue.get('comments',101)>100:raise ValueError('Too many comments to check safely')
        comments=self.api(path+'/comments?per_page=100')
        if not isinstance(comments,list):raise ValueError('Comments unavailable')
        marker='<!-- company-x2-outreach:'+job['id']+' -->'
        for c in comments:
            if c.get('user',{}).get('login','').lower()==user['login'].lower() and marker in (c.get('body') or ''):return c
        return self.api(path+'/comments',{'body':job['message']})

    def observe(self,job):
        m=re.fullmatch(r'https://github\.com/([\w.-]+)/([\w.-]+)/issues/([1-9][0-9]*)',job['url'])
        if not m or '/'.join(m.groups()[:2]).lower() not in status(self.env)['repos']:return None
        path='/repos/'+m[1]+'/'+m[2]+'/issues/'+m[3]
        issue=self.api(path)
        if str(issue['id'])!=job['issue_id'] or issue.get('comments',101)>100:return None
        comments=self.api(path+'/comments?per_page=100')
        sent=int(job['comment_url'].rsplit('-',1)[-1])
        replies=[c for c in comments if type(c.get('id')) is int and c['id']>sent and c.get('user',{}).get('login')==job['author'] and isinstance(c.get('body'),str)]
        if not replies:return None
        c=max(replies,key=lambda c:c['id'])
        return {'id':job['id'],'reply_id':c['id'],'reply_text':c['body'][:2000],
          'next_message':'Thank you. Please use https://company-x2.onrender.com/intake for free verification with non-sensitive CSV. Live sales remain closed. We have not accepted a paid job or committed to a deadline. The work plan requires your explicit confirmation.'}

def run_once(store,env=None,client=None):
    collect(store,env)
    if not status(env)['ready']:return False
    client=client or GitHubContact(env)
    for saved in store.outreach_rpc('list'):
        if saved['status']=='sent':
            try:
                observed=client.observe(saved)
                if observed:store.outreach_rpc('observe',observed)
            except Exception:pass
    job=store.outreach_rpc('claim')
    if not job:return False
    try:
        reply=client.send(job)
        if type(reply.get('id')) is not int or reply.get('html_url')!=job['url']+'#issuecomment-'+str(reply['id']):raise ValueError('Comment identity mismatch')
        store.outreach_rpc('finish',{'id':job['id'],'comment_url':reply['html_url']})
    except Exception:
        store.outreach_rpc('uncertain',{'id':job['id']})
    return True
