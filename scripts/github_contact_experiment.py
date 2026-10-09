"""An explicitly requested experiment on this repository only, with real GitHub I/O."""
import json,os,tempfile,urllib.request
from pathlib import Path
from company_x2 import outreach
from company_x2.agent_scout import register
from company_x2.store import Store
from company_x2.supabase_store import NoRedirect

REPO='mikan2k88-glitch/company-x2'
if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('Only the owned repository Actions experiment is supported')
base='/repos/'+REPO
env=dict(os.environ,OUTREACH_ENABLED='true',OUTREACH_GITHUB_REPOS=REPO)
client=outreach.GitHubContact(env)
repository=client.api(base)
if repository.get('full_name')!=REPO or repository.get('private') is not True:
    raise SystemExit('Experiment requires the owned private repository')
issue=None;report={}
try:
    issue=client.api(base+'/issues',{'title':'[EXPERIMENT] Please deduplicate CSV rows (virtual $25)',
      'body':outreach.PERMISSION+'\nOwner-authorized integration experiment only. This is not a real hiring request or payment offer. '
       'The virtual $25 is a parser test value with no monetary value. No work, contract or payment is being solicited. '
       'Test CSV exact deduplication: id\\n001\\n001\\n. Use no personal data. Close after verification.'})
    number=issue['number'];url=issue['html_url'];identity=issue['user']['login']
    if url!='https://github.com/'+REPO+'/issues/'+str(number):raise ValueError('Fixture issue identity mismatch')
    # The Actions installation token cannot use GET /user. The created issue's
    # authenticated author verifies its sender identity for this isolated fixture.
    env['GITHUB_OUTREACH_LOGIN']=identity
    class ExperimentClient(outreach.GitHubContact):
        def api(self,path,data=None):
            if path=='/user':return {'login':identity}
            allowed=base+'/issues/'+str(number)
            if path not in (allowed,allowed+'/comments',allowed+'/comments?per_page=100'):
                raise ValueError('Experiment escaped its fixture issue')
            return super().api(path,data)
    client=ExperimentClient(env)
    with tempfile.TemporaryDirectory() as tmp:
        store=Store(Path(tmp)/'experiment.db')
        register(store,{'urls':[url],'run_key':'experiment-'+os.environ['GITHUB_RUN_ID'],'checkpoint':{}},fetcher=lambda _:client.api(base+'/issues/'+str(number)))
        assert outreach.run_once(store,env,client) is True
        saved=store.outreach_rpc('list')[0];assert saved['status']=='sent'
        initial=client.api(base+'/issues/'+str(number)+'/comments?per_page=100')
        assert len(initial)==1
        replay=client.send(saved)
        assert replay['html_url']==saved['comment_url']
        assert len(client.api(base+'/issues/'+str(number)+'/comments?per_page=100'))==1
        response=client.api(base+'/issues/'+str(number)+'/comments',{'body':'[SIMULATED REQUESTER REPLY] Free verification and AI processing are welcome for this experiment. No paid job, deadline or liability agreement is offered.'})
        assert outreach.run_once(store,env,client) is False
        observed=store.outreach_rpc('list')[0]
        assert observed['reply_id']==response['id']
        assert 'not accepted' in observed['next_message']
        assert len(client.api(base+'/issues/'+str(number)+'/comments?per_page=100'))==2
        report={'issue_url':url,'initial_comment_url':saved['comment_url'],'simulated_reply_url':response['html_url'],
          'sender':identity,'scope':'owned private repository only; same bot simulates requester',
          'checks':['real source read','real initial inquiry POST','duplicate replay did not add a comment',
           'real requester reply read','follow-up stayed a draft','daily claim blocked repeat'],
          'render_credentials_changed':False,'real_customer_contacted':False,'payment_submitted':False}
finally:
    if issue:
        request=urllib.request.Request('https://api.github.com'+base+'/issues/'+str(issue['number']),
          method='PATCH',data=b'{"state":"closed"}',headers={'Authorization':'Bearer '+env['GITHUB_OUTREACH_TOKEN'],
            'Content-Type':'application/json','X-GitHub-Api-Version':'2026-03-10','User-Agent':'Company-X2-experiment'})
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:
            closed=json.loads(response.read());assert closed['state']=='closed'
        report['issue_closed']=True
Path('contact-experiment-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
