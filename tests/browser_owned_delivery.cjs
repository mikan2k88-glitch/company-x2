// Complete synthetic owned request -> inspection -> journal -> Chromium -> receipt.
const assert=require('node:assert/strict'),http=require('node:http'),crypto=require('node:crypto');
const {spawn}=require('node:child_process'),readline=require('node:readline');
const {chromium}=require('playwright');
const fs=require('node:fs');
function memory(name){
 try{const raw=fs.readFileSync('/sys/fs/cgroup/'+name,'utf8').trim();return /^\d+$/.test(raw)?Number(raw):null;}
 catch{return null;}
}
let sends=0,worker,browser;
const destination='https://synthetic.invalid/orders/1';
const server=http.createServer(async(req,res)=>{
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
  const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:false});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage();await page.goto(origin);
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
    assert.equal(new URL(page.url()).origin,origin);
    await page.locator('#artifact').setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:Buffer.from(event.artifact,'utf8')});
    const stagedBytes=await page.locator('#artifact').evaluate(async input=>Array.from(new Uint8Array(await input.files[0].arrayBuffer())));
    worker.stdin.write(JSON.stringify({destination,artifact_sha256:crypto.createHash('sha256').update(Buffer.from(stagedBytes)).digest('hex')})+'\n');
    assert.equal(sends,0); // File selection has not uploaded anything.
   }else if(event.event==='commit'){
    assert.equal(scenario,'success');assert.equal(event.destination,destination);
    await page.locator('#deliver').click();
    await page.waitForFunction(()=>document.querySelector('#receipt').textContent.length>0);
    const receipt=JSON.parse(await page.locator('#receipt').textContent());
    worker.stdin.write(JSON.stringify(receipt)+'\n');
   }else{assert.equal(event.event,'done');assert.equal(event.state,scenario==='success'?'confirmed':'uncertain');done=true;}
  }
  assert.equal(await finished,0,errors);assert.equal(done,true);assert.equal(sends,scenario==='success'?1:0);
  }
  console.log('Owned work, current consent, durable journal and Chromium delivery passed; synthetic only');
  console.log(JSON.stringify({synthetic_only:true,cgroup_limit_bytes:memory('memory.max'),cgroup_peak_bytes:memory('memory.peak')}));
 }finally{
  if(worker&&worker.exitCode===null)worker.kill();
  if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
 }
})().catch(error=>{console.error(error.message);process.exitCode=1});
