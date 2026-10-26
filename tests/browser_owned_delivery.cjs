// Complete synthetic owned request -> inspection -> journal -> Chromium -> receipt.
const assert=require('node:assert/strict'),http=require('node:http'),crypto=require('node:crypto');
const {spawn}=require('node:child_process'),readline=require('node:readline');
const {chromium}=require('playwright');
const {FixedFileBackend}=require('../company_x2/browser/fixed_file_backend.cjs');
const fs=require('node:fs');
function memory(name){
 try{const raw=fs.readFileSync('/sys/fs/cgroup/'+name,'utf8').trim();return /^\d+$/.test(raw)?Number(raw):null;}
 catch{return null;}
}
let sends=0,worker,browser,backend;
const destination='https://synthetic.invalid/orders/1';
const server=http.createServer(async(req,res)=>{
 if(req.method==='GET'&&req.url==='/redirect'){
  res.writeHead(302,{Location:'/'});res.end();return;
 }
 if(req.method==='GET'&&req.url==='/auto'){
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<input type="file" id="artifact"><button id="deliver">Deliver</button>
   <script>document.querySelector('#artifact').onchange=async()=>{
    try{await fetch('/deliver',{method:'POST',body:await document.querySelector('#artifact').files[0].arrayBuffer()});}catch{}
   };</script>`);return;
 }
 if(req.method==='GET'&&req.url==='/'){
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<input type="file" id="artifact"><button id="deliver">Deliver</button><pre id="receipt"></pre>
   <script>document.querySelector('#deliver').onclick=async()=>{
    const r=await fetch('/deliver',{method:'POST',body:await document.querySelector('#artifact').files[0].arrayBuffer()});
    document.querySelector('#receipt').textContent=await r.text();};</script>`);return;
 }
 if(req.method==='POST'&&req.url==='/deliver'){
  let body='';for await(const chunk of req){body+=chunk;if(body.length>50000){res.writeHead(413);res.end();return;}}
  sends++;res.setHeader('Content-Type','application/json');
  res.end(JSON.stringify({id:'synthetic-owned-receipt',destination,artifact_sha256:crypto.createHash('sha256').update(body).digest('hex')}));return;
 }
 res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  if(process.env.CX2_EXPECT_MEMORY_LIMIT_BYTES && memory('memory.max')!==Number(process.env.CX2_EXPECT_MEMORY_LIMIT_BYTES))
   throw Error('Expected isolated cgroup limit not applied');
  const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({headless:true});
  assert.throws(()=>new FixedFileBackend(browser,{pageUrl:origin+'/',uploadUrl:origin+'/deliver',destination,loopbackFixture:true}));
  assert.throws(()=>new FixedFileBackend(browser,{enabled:true,pageUrl:'https://synthetic.invalid/',uploadUrl:'https://other.invalid/deliver',destination:'https://synthetic.invalid/'}));
  backend=new FixedFileBackend(browser,{enabled:true,pageUrl:origin+'/',uploadUrl:origin+'/deliver',destination,loopbackFixture:true});
  const staged=await backend.stage(destination,Buffer.from('synthetic-original'));
  await backend.page.locator('#artifact').setInputFiles({name:'changed.csv',mimeType:'text/csv',buffer:Buffer.from('synthetic-changed')});
  await assert.rejects(()=>backend.commit(staged),/Selected artifact changed/);
  assert.equal(sends,0);await backend.close();backend=null;
  for(const path of ['/auto','/redirect']){
   backend=new FixedFileBackend(browser,{enabled:true,pageUrl:origin+path,uploadUrl:origin+'/deliver',destination,loopbackFixture:true});
   await assert.rejects(()=>backend.stage(destination,Buffer.from('synthetic-original')));
   assert.equal(backend.tainted,true);assert.equal(sends,0);
   await backend.close();backend=null;
  }
  // HTTPS permit target is mapped to this loopback fixture only by test code.
  for(const scenario of ['revoke-after-stage','success']){
  worker=spawn(process.env.PYTHON||'python',['tests/browser_owned_delivery_helper.py',scenario],{stdio:['pipe','pipe','pipe']});
  let errors='';worker.stderr.on('data',data=>errors+=data);
  const finished=new Promise((resolve,reject)=>{worker.once('error',reject);worker.once('exit',code=>resolve(code));});
  let done=false;
  for await(const line of readline.createInterface({input:worker.stdout})){
   const event=JSON.parse(line);
   if(event.event==='stage'){
    assert.equal(event.destination,destination);assert.equal(sends,0);
    backend=new FixedFileBackend(browser,{enabled:true,pageUrl:origin+'/',uploadUrl:origin+'/deliver',destination,loopbackFixture:true});
    worker.stdin.write(JSON.stringify(await backend.stage(destination,Buffer.from(event.artifact)))+'\n');
    assert.equal(sends,0); // File selection has not uploaded anything.
   }else if(event.event==='commit'){
    assert.equal(scenario,'success');assert.equal(event.destination,destination);
    const receipt=await backend.commit({destination,artifact_sha256:backend.hash});
    worker.stdin.write(JSON.stringify(receipt)+'\n');
   }else{assert.equal(event.event,'done');assert.equal(event.state,scenario==='success'?'confirmed':'uncertain');done=true;}
  }
  assert.equal(await finished,0,errors);assert.equal(done,true);assert.equal(sends,scenario==='success'?1:0);
  await backend.close();backend=null;
  }
  console.log('Owned work, current consent, durable journal and Chromium delivery passed; synthetic only');
  console.log(JSON.stringify({synthetic_only:true,cgroup_limit_bytes:memory('memory.max'),cgroup_peak_bytes:memory('memory.peak')}));
 }finally{
  if(worker&&worker.exitCode===null)worker.kill();
  if(backend)await backend.close();
  if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
 }
})().catch(error=>{console.error(error.message);process.exitCode=1});
