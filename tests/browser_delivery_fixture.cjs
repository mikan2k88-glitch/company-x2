// Local synthetic-site browser experiment. Never opens an external site.
const assert=require('node:assert/strict'),http=require('node:http'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const journalDirectory=fs.mkdtempSync(path.join(os.tmpdir(),'cx2-browser-delivery-'));
const journalPath=path.join(journalDirectory,'journal.db');
const journalKey=crypto.createHash('sha256').update('synthetic-fixed-delivery').digest('hex');
const postgres=process.env.CX2_BROWSER_POSTGRES==='1';
const journalSchema='browser_delivery_'+crypto.randomUUID().replaceAll('-','');let schemaReady=false;
function postgresAction(action){
 const result=spawnSync(process.env.PYTHON||'python',['tests/browser_postgres_helper.py',journalSchema,action,journalKey],{encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);return result.stdout;
}
function claim(){
 if(postgres){if(!schemaReady){postgresAction('init');schemaReady=true;}return JSON.parse(postgresAction('claim'));}
 const script='import sys,json;from company_x2.delivery_journal import Journal;print(json.dumps(Journal(sys.argv[1]).claim(sys.argv[2],allowed=True)))';
 const result=spawnSync(process.env.PYTHON||'python',['-c',script,journalPath,journalKey],{encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
const artifact='sku\n001\n',destination='synthetic-order-001';let sends=0;
const server=http.createServer(async(req,res)=>{
 if(req.method==='GET'&&req.url==='/'){
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<textarea id="artifact"></textarea><button id="deliver">Deliver synthetic file</button><pre id="receipt"></pre>
  <script>document.querySelector('#deliver').onclick=async()=>{
   const response=await fetch('/deliver',{method:'POST',body:document.querySelector('#artifact').value});
   document.querySelector('#receipt').textContent=await response.text();
  }</script>`);return;
 }
 if(req.method==='POST'&&req.url==='/deliver'){
  let body='';for await(const chunk of req){body+=chunk;if(body.length>50000){res.writeHead(413);res.end();return;}}
  sends++;res.setHeader('Content-Type','application/json');
  res.end(JSON.stringify({id:'synthetic-receipt',destination,artifact_sha256:crypto.createHash('sha256').update(body).digest('hex')}));return;
 }
 res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try{
  const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:false});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage();await page.goto(origin);
  assert.equal(new URL(page.url()).origin,origin);
  await page.locator('#artifact').fill(artifact);
  assert.equal(typeof claim(),'string');
  await page.locator('#deliver').click();
  await page.waitForFunction(()=>document.querySelector('#receipt').textContent.length>0);
  const receipt=JSON.parse(await page.locator('#receipt').textContent());
  assert.equal(receipt.destination,destination);
  assert.equal(receipt.artifact_sha256,crypto.createHash('sha256').update(artifact).digest('hex'));
  assert.equal(sends,1);
  // Simulate worker loss after the click, before storing acknowledgement.
  await context.close();
  assert.equal(claim(),null); // Fresh Python process sees the durable sending claim.
  assert.equal(sends,1); // Coordinator must not perform a second click.
  console.log('Synthetic Chromium delivery and durable restart guard passed; no external site used');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
  if(schemaReady)postgresAction('drop');
  if(fs.existsSync(journalPath))fs.unlinkSync(journalPath);fs.rmdirSync(journalDirectory);}
})().catch(error=>{console.error(error.message);process.exitCode=1});
