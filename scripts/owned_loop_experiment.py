"""E36: real owned GitHub I/O, synthetic consent, isolated HTTP delivery."""
import hashlib,json,os,secrets,tempfile,threading,urllib.request,urllib.error
from datetime import datetime,timezone,timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from company_x2 import autonomy,outreach
from company_x2.company import process_transaction
from company_x2.server import handler_for
from company_x2.store import Store
from company_x2.supabase_store import NoRedirect

REPO='mikan2k88-glitch/company-x2'

def main():
    if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_ACTIONS')!='true':
        raise ValueError('Only the owned repository Actions experiment is supported')
    env=dict(os.environ,OUTREACH_ENABLED='true',OUTREACH_GITHUB_REPOS=REPO)
    raw=outreach.GitHubContact(env);base='/repos/'+REPO
    repository=raw.api(base)
    if repository.get('full_name')!=REPO or repository.get('private') is not True:
        raise ValueError('Owned private repository required')
    issue=None;report={'status':'failed','real_customer':False,'payment_submitted':False,
      'production_settings_changed':False,'storage':'isolated SQLite',
      'scope':'Real GitHub transport; same account simulates requester; isolated HTTP intake and delivery.'}
    try:
        issue=raw.api(base+'/issues',{'title':'[E36 EXPERIMENT] Please deduplicate CSV rows (virtual $25)',
          'body':outreach.PERMISSION+'\nOwned integration fixture only. Same account simulates the requester. '
           'Virtual $25 has no monetary value. No paid job or deadline. Synthetic CSV only. '
           'Any intake link is for an isolated test server and cannot authorize access to the public app. Close after testing.'})
        url=issue['html_url'];number=issue['number'];identity=issue['user']['login']
        if url!='https://github.com/'+REPO+'/issues/'+str(number):raise ValueError('Fixture mismatch')
        path=base+'/issues/'+str(number);env['GITHUB_OUTREACH_LOGIN']=identity
        report['issue_url']=url
        # Installation tokens cannot GET /user. The real created issue's author
        # supplies fixture identity, not proof of the production PAT identity.
        class FixtureClient(outreach.GitHubContact):
            def api(self,route,data=None):
                if route=='/user':return {'login':identity}
                if route==base+'/issues?state=open&sort=updated&per_page=20' and data is None:
                    return [super().api(path)]
                if route not in (path,path+'/comments',path+'/comments?per_page=100'):
                    raise ValueError('Experiment escaped its fixture')
                if data and 'Company X2 automated free verification invitation.' in data.get('body',''):
                    # Production-shaped grant is consumed by the isolated HTTP
                    # server below. Never publish a misleading public-app link.
                    data={**data,'body':'[E36 FIXTURE ONLY — NOT A CUSTOMER INVITATION]\n'+data['body'].replace(
                      'https://company-x2.onrender.com/intake#','http://127.0.0.1/isolated-fixture/intake#')}
                return super().api(route,data)
        client=FixtureClient(env);key=secrets.token_urlsafe(32)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'fixture.db');now=datetime.now(timezone.utc)
            first=autonomy.cycle(store,env,client,signing_key=key,now=now)
            if first['sent']!=1:raise ValueError('Initial scope inquiry missing')
            contact=store.outreach_rpc('list')[0];report['initial_comment_url']=contact['comment_url']
            replay=client.send(contact)
            if replay['html_url']!=contact['comment_url'] or len(client.api(path+'/comments?per_page=100'))!=1:
                raise ValueError('Duplicate scope inquiry')
            reply=client.api(path+'/comments',{'body':autonomy.FREE+' '+autonomy.AI})
            observed=client.observe(contact);store.outreach_rpc('observe',observed)
            if observed['reply_id']!=reply['id'] or not autonomy.consent(observed['reply_text'])['accepted']:
                raise ValueError('Structured consent missing')
            report['simulated_consent_url']=reply['html_url']
            # Explicit virtual-day advance in isolated SQLite only. Do not
            # weaken or advance any production daily limit or Supabase rows.
            with store.connect() as db:db.execute("update outreach_contacts set attempted_at=datetime('now','-1 day')")
            second=autonomy.cycle(store,env,client,signing_key=key,now=now+timedelta(hours=1))
            if second['sent']!=1:raise ValueError('Fixture intake invitation missing')
            message=store.autonomy_rpc('status')['messages'][0]
            report['fixture_invitation_url']=message['comment_url']
            with store.connect() as db:body=db.execute('select body from autonomy_messages').fetchone()[0]
            grant=parse_qs(body.split('#',1)[1])['access'][0]
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(store,'fixture-admin',access_password=key))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            owner=secrets.token_urlsafe(32);local='http://127.0.0.1:'+str(server.server_port)
            def call(route,data=None,token=grant,decode=True):
                headers={'Content-Type':'application/json','X-Order-Token':owner,'X-Intake-Access':token}
                req=urllib.request.Request(local+route,data=json.dumps(data).encode() if data is not None else None,headers=headers)
                with urllib.request.urlopen(req,timeout=5) as response:
                    content=response.read();return json.loads(content) if decode else content
            try:
                payload={'service_key':'csv_exact_dedup','csv':'id\n001\n001\n','payment_mode':'sandbox',
                  'source_url':'https://wrong.example/','risk_context':dict(sensitive_data='no',critical_use='no',extra_liability='no')}
                plan=call('/api/company/quote',payload)['plan']
                payload.update(plan_sha256=plan['plan_sha256'],terms_accepted=True,request_key='e36-synthetic-intake')
                order=call('/api/company/transactions',payload)['id']
                if not process_transaction(store):raise ValueError('Processing missing')
                artifact=call('/api/company/transactions/'+order+'/download',decode=False)
                if artifact.decode().replace('\r\n','\n')!='id\n001\n':raise ValueError('Artifact mismatch')
                digest=hashlib.sha256(artifact).hexdigest()
                if digest!=call('/api/company/transactions/'+order)['result']['download_sha256']:raise ValueError('Hash mismatch')
                call('/api/company/receipt',{'id':order,'download_sha256':digest})
                if call('/api/company/transactions/'+order)['status']!='delivered':raise ValueError('Receipt missing')
                saved=store.company_rpc('get',{'id':order,'token_hash':store.digest(owner)})
                if saved['source_url']!=url:raise ValueError('Source provenance mismatch')
                # A subsequent real reply revokes consent. Old grant must no
                # longer authorize creating a new quote.
                revoked=client.api(path+'/comments',{'body':'[E36 SIMULATION] Consent withdrawn. Do not process another request.'})
                store.outreach_rpc('observe',client.observe(contact))
                try:call('/api/company/quote',payload)
                except urllib.error.HTTPError as error:
                    if error.code!=400:raise
                else:raise ValueError('Revocation did not stop new intake')
                if not autonomy.cycle(store,env,client,signing_key=key,now=now+timedelta(hours=1))['replayed']:
                    raise ValueError('Hourly replay guard failed')
                if store.autonomy_rpc('claim_message') is not None:raise ValueError('Daily invitation limit failed')
                if len(client.api(path+'/comments?per_page=100'))!=4:raise ValueError('Unexpected external posts')
                report.update(status='passed',download_sha256=digest,revocation_url=revoked['html_url'],
                  checks=['real inquiry','duplicate prevented','real synthetic consent read','real fixture invitation',
                    'source-bound HTTP plan and intake','synthetic CSV deduplication','download hash','receipt',
                    'real consent revocation blocks new intake','hourly replay blocked','virtual-day daily limit blocked'],
                  virtual_day_advance=True,public_render_intake_tested=False)
            finally:server.shutdown();server.server_close();thread.join()
    finally:
        if issue:
            req=urllib.request.Request('https://api.github.com'+base+'/issues/'+str(issue['number']),method='PATCH',
              data=b'{"state":"closed"}',headers={'Authorization':'Bearer '+env['GITHUB_OUTREACH_TOKEN'],
                'Content-Type':'application/json','User-Agent':'Company-X2-E36'})
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
                if json.load(response).get('state')!='closed':raise ValueError('Fixture cleanup failed')
            report['closed']=True
        Path('owned-loop-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
