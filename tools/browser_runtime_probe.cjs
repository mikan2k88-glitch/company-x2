// Opt-in synthetic runtime probe. No remote pages, credentials or customer files.
const {execFileSync}=require('node:child_process');
const {performance}=require('node:perf_hooks');

function subtreeRssKiB(){
 if(process.platform!=='linux')return null;
 const rows=execFileSync('ps',['-eo','pid=,ppid=,rss='],{encoding:'utf8',timeout:5000})
  .trim().split('\n').map(line=>line.trim().split(/\s+/).map(Number));
 const ids=new Set([process.pid]);let changed=true;
 while(changed){changed=false;for(const [pid,parent] of rows)if(ids.has(parent)&&!ids.has(pid)){ids.add(pid);changed=true;}}
 return rows.filter(([pid])=>ids.has(pid)).reduce((sum,row)=>sum+row[2],0);
}

(async()=>{
 if(process.env.CX2_BROWSER_PROBE!=='1'){
  console.log(JSON.stringify({status:'disabled',notice:'Set CX2_BROWSER_PROBE=1 explicitly in an isolated runtime'}));return;
 }
 const {chromium}=require('playwright');
 let browser;const started=performance.now(),samples=[];
 const sample=phase=>samples.push({phase,subtree_rss_kib:subtreeRssKiB()});
 try{
  sample('before_launch');
  browser=await chromium.launch({headless:true,timeout:30000});
  const startupMs=Math.round(performance.now()-started);sample('launched');
  const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:false});
  await context.route('**/*',route=>route.abort());
  const page=await context.newPage();
  await page.setContent('<input id="artifact" type="file"><pre id="result"></pre>');
  const synthetic='SKU,Title\r\n'+Array.from({length:1000},(_,i)=>`${String(i).padStart(4,'0')},Synthetic ${i}`).join('\r\n')+'\r\n';
  await page.locator('#artifact').setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:Buffer.from(synthetic)});
  const bytes=await page.locator('#artifact').evaluate(async input=>(await input.files[0].arrayBuffer()).byteLength);
  if(bytes!==Buffer.byteLength(synthetic))throw Error('Synthetic file bytes changed');
  sample('synthetic_file_staged');
  await context.close();await browser.close();browser=null;sample('closed');
  const measured=samples.map(s=>s.subtree_rss_kib).filter(Number.isFinite);
  console.log(JSON.stringify({status:'passed',synthetic_only:true,network_requests_allowed:0,
   startup_ms:startupMs,staged_bytes:bytes,platform:process.platform,
   playwright_version:require('playwright/package.json').version,
   sampled_peak_subtree_rss_kib:measured.length?Math.max(...measured):null,samples,
   limitation:'Sampled process-tree RSS, not continuous peak or Render capacity validation'}));
 }finally{if(browser)await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1});
