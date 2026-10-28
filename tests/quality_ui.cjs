// Synthetic UI only. All requests are fulfilled in-process.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const ledger=JSON.parse(fs.readFileSync(path.join(__dirname,'../company_x2/quality-ledger.json'),'utf8'));
  for(const project of ledger.projects){project.open_issues=project.issues.filter(i=>i.status!=='resolved').length;project.validation_complete=false;}
  ledger.notice='レビュー記録。ライブ監視ではありません。';
  let unavailable=false;
  await page.route('**/*',route=>{
   if(route.request().url()==='https://quality.invalid/api/company/quality')return route.fulfill({status:unavailable?503:200,contentType:'application/json',body:JSON.stringify(ledger)});
   if(route.request().url()==='https://quality.invalid/quality')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../company_x2/quality.html'),'utf8')});
   return route.abort();
  });
  await page.goto('https://quality.invalid/quality');
  await page.getByText('Company X2 限定制作基盤',{exact:true}).waitFor();
  assert.equal(await page.locator('section').count(),2);
  assert.equal(await page.locator('section').first().locator('tr').count(),4);
  if(process.env.CX2_QUALITY_SCREENSHOT)await page.screenshot({path:process.env.CX2_QUALITY_SCREENSHOT,fullPage:true});
  ledger.projects[0].issues[0].title='<img src=x onerror=alert(1)>';
  await page.locator('#refresh').click();
  await page.getByText('P1 · <img src=x onerror=alert(1)>',{exact:true}).waitFor();
  assert.equal(await page.locator('img').count(),0);
  unavailable=true;await page.locator('#refresh').click();
  await page.locator('#error').filter({hasText:'取得できません'}).waitFor();
  assert.equal(await page.locator('#refresh').isEnabled(),true);
  console.log('Quality office rendering, safe text and failure recovery passed');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
