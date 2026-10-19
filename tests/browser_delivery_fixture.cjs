// Local synthetic-site browser experiment. Never opens an external site.
const assert=require('node:assert/strict'),http=require('node:http'),crypto=require('node:crypto');
const {chromium}=require('playwright');
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
  await page.locator('#deliver').click();
  await page.waitForFunction(()=>document.querySelector('#receipt').textContent.length>0);
  const receipt=JSON.parse(await page.locator('#receipt').textContent());
  assert.equal(receipt.destination,destination);
  assert.equal(receipt.artifact_sha256,crypto.createHash('sha256').update(artifact).digest('hex'));
  assert.equal(sends,1);
  await context.close();console.log('Synthetic loopback Chromium delivery passed; no external site used');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error.message);process.exitCode=1});
