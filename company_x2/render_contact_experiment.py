"""One owned-issue transport experiment using Render's registered credentials."""
import hashlib,os,re,tempfile,json,urllib.request
from contextlib import nullcontext
from datetime import datetime,timezone
from pathlib import Path
from . import outreach
from .store import Store
from .supabase_store import NoRedirect,SupabaseStore
from .settings import build_store

REPO='mikan2k88-glitch/company-x2'
FIXTURE='[company-x2: owned Render transport experiment]'
TITLE='[EXPERIMENT] Please deduplicate CSV rows (virtual $25)'
REPLY='[SIMULATED REQUESTER REPLY] Free verification and AI processing are welcome for this experiment. No paid job or payment is offered.'

def run(env=None,client=None,closer=None,store=None):
    env=os.environ if env is None else env
    url=env.get('CX2_CONTACT_EXPERIMENT_URL','')
    if not url:return {'status':'disabled'}
    match=re.fullmatch(r'https://github\.com/'+re.escape(REPO)+r'/issues/([1-9][0-9]*)',url)
    if env.get('RENDER')!='true' or not match or outreach.status(env)['repos']!=[REPO]:
        raise ValueError('Owned Render fixture configuration required')
    persistent=env.get('CX2_CONTACT_EXPERIMENT_STORAGE')=='supabase'
    if persistent and (not isinstance(store,SupabaseStore) or env.get('OUTREACH_ENABLED','false').lower()!='false'):
        raise ValueError('Persistent experiment requires Supabase and ordinary outreach disabled')
    client=client or outreach.GitHubContact(env)
    path='/repos/'+REPO+'/issues/'+match[1]
    issue=client.api(path)
    identity=client.api('/user')
    if not isinstance(issue,dict) or issue.get('html_url')!=url or issue.get('title')!=TITLE or FIXTURE not in (issue.get('body') or '') or issue.get('user',{}).get('login','').lower()!=str(identity.get('login','')).lower() or str(identity.get('login','')).lower()!=env.get('GITHUB_OUTREACH_LOGIN','').lower():
        raise ValueError('Owned experiment identity mismatch')
    if issue.get('state')=='closed':return {'status':'already_closed','issue_url':url}
    if not outreach.candidate(issue,env):raise ValueError('Fixture conditions changed')
    # Only this test overrides the sending flag; the normal worker stays disabled.
    test_env=dict(env,OUTREACH_ENABLED='true')
    client.env=test_env
    job_id='ot_'+hashlib.sha256(url.encode()).hexdigest()[:32]
    comments=client.api(path+'/comments?per_page=100')
    if comments:raise ValueError('Experiment requires an untouched fixture')
    report={'issue_url':url,'storage':'supabase' if persistent else 'temporary SQLite','same_account_simulates_requester':True}
    job=None
    try:
        with (nullcontext(None) if persistent else tempfile.TemporaryDirectory()) as tmp:
            store=store if persistent else Store(Path(tmp)/'experiment.db')
            if persistent:
                rows=store.outreach_rpc('list')
                today=datetime.now(timezone.utc).date().isoformat()
                if any(row['status'] in ('draft','sending') or str(row.get('attempted_at') or '')[:10]==today for row in rows):
                    raise ValueError('Existing pending contact or daily attempt prevents experiment')
            store.outreach_rpc('prepare',{'id':job_id,'url':url,'issue_id':str(issue['id']),'author':issue['user']['login'],'message':outreach.MESSAGE+'\n\n<!-- company-x2-outreach:'+job_id+' -->'})
            job=store.outreach_rpc('claim')
            if not job or job['id']!=job_id:raise ValueError('Experiment did not claim its fixture')
            sent=client.send(job)
            if type(sent.get('id')) is not int or sent.get('html_url')!=url+'#issuecomment-'+str(sent['id']):raise ValueError('Unexpected comment identity')
            store.outreach_rpc('finish',{'id':job_id,'comment_url':sent['html_url']})
            replay=client.send(job)
            if replay.get('id')!=sent['id'] or len(client.api(path+'/comments?per_page=100'))!=1:raise ValueError('Duplicate check failed')
            response=client.api(path+'/comments',{'body':REPLY})
            saved=next(row for row in store.outreach_rpc('list') if row['id']==job_id)
            observed=client.observe(saved)
            if not observed or observed['reply_id']!=response['id'] or not store.outreach_rpc('observe',observed):raise ValueError('Reply ingestion failed')
            if store.outreach_rpc('claim') is not None or len(client.api(path+'/comments?per_page=100'))!=2:raise ValueError('Daily or draft-only check failed')
            report.update(status='passed',initial_comment_url=sent['html_url'],reply_url=response['html_url'],duplicate_prevented=True,reply_saved=True,follow_up_draft_only=True)
            if persistent:
                reread=next(row for row in build_store(env).outreach_rpc('list') if row['id']==job_id)
                if reread['status']!='sent' or reread['comment_url']!=sent['html_url'] or reread['reply_id']!=response['id'] or reread['reply_text']!=REPLY or 'not accepted' not in reread['next_message']:
                    raise ValueError('Persisted contact verification failed')
                report['persisted_reread']=True
    except Exception:
        if job and job['id']==job_id:store.outreach_rpc('uncertain',{'id':job_id})
        raise
    finally:
        if closer:closer(path)
        else:
            req=urllib.request.Request('https://api.github.com'+path,method='PATCH',data=b'{"state":"closed"}',headers={'Authorization':'Bearer '+env.get('GITHUB_OUTREACH_TOKEN',''),'Content-Type':'application/json','X-GitHub-Api-Version':'2026-03-10','User-Agent':'Company-X2-experiment'})
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as res:
                if json.loads(res.read(2_000_001)).get('state')!='closed':raise ValueError('Fixture cleanup failed')
        report['closed']=True
    return report
