// Internal fixed-form backend. Operator configuration only; no production route.
const crypto=require('node:crypto');
const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');

class FixedFileBackend{
 constructor(browser,{enabled=false,pageUrl,uploadUrl,destination,loopbackFixture=false}){
  if(enabled!==true)throw Error('Browser delivery disabled');
  const page=new URL(pageUrl),upload=new URL(uploadUrl);
  const local=loopbackFixture===true&&page.protocol==='http:'&&page.hostname==='127.0.0.1';
  if((page.protocol!=='https:'&&!local)||upload.origin!==page.origin||page.username||page.password||
     upload.username||upload.password||page.search||page.hash||upload.search||upload.hash||
     (!local&&destination!==page.href))throw Error('Fixed operator destination required');
  if(typeof destination!=='string'||!destination)throw Error('Destination identity required');
  Object.assign(this,{browser,pageUrl:page.href,uploadUrl:upload.href,destination,tainted:false,committed:false});
 }
 async stage(destination,artifact){
  if(this.context||destination!==this.destination||!Buffer.isBuffer(artifact)||!artifact.length||artifact.length>50000)
   throw Error('Bounded fixed artifact required');
  this.hash=digest(artifact);
  this.context=await this.browser.newContext({serviceWorkers:'block',acceptDownloads:false});
  await this.context.routeWebSocket('**/*',socket=>socket.close());
  this.page=await this.context.newPage();let navigationAllowed=true;
  await this.context.route('**/*',async route=>{
   const request=route.request();
   if(navigationAllowed&&request.url()===this.pageUrl&&request.method()==='GET'&&
      request.isNavigationRequest()&&request.frame()===this.page.mainFrame()){
    navigationAllowed=false;return route.continue();
   }
   if(this.armed&&request.url()===this.uploadUrl&&request.method()==='POST'&&
      request.frame()===this.page.mainFrame()&&digest(request.postDataBuffer()||Buffer.alloc(0))===this.hash){
    this.armed=false;return route.continue();
   }
   this.tainted=true;return route.abort();
  });
  await this.page.goto(this.pageUrl,{timeout:15000});
  if(this.page.url()!==this.pageUrl)throw Error('Page destination changed');
  await this.page.locator('#artifact').setInputFiles({name:'result.csv',mimeType:'text/csv',buffer:artifact});
  await this.checkSelectedFile();
  if(this.tainted)throw Error('Unexpected request during staging');
  return {destination:this.destination,artifact_sha256:this.hash};
 }
 async checkSelectedFile(){
  const bytes=await this.page.locator('#artifact').evaluate(async input=>Array.from(new Uint8Array(await input.files[0].arrayBuffer())));
  if(digest(Buffer.from(bytes))!==this.hash)throw Error('Selected artifact changed');
 }
 async commit(staged){
  if(this.committed||this.tainted||!this.page||this.page.url()!==this.pageUrl||
     staged.destination!==this.destination||staged.artifact_sha256!==this.hash)throw Error('Staged scope changed');
  await this.checkSelectedFile();
  if(this.tainted)throw Error('Unexpected staging request');
  this.committed=true;this.armed=true;
  try{
   const [response]=await Promise.all([
    this.page.waitForResponse(r=>r.url()===this.uploadUrl&&r.request().method()==='POST',{timeout:15000}),
    this.page.locator('#deliver').click()
   ]);
   if(!response.ok())throw Error('Delivery response rejected');
   const receipt=await response.json();
   if(!receipt||typeof receipt.id!=='string'||!receipt.id||receipt.id.length>200||
      receipt.destination!==this.destination||receipt.artifact_sha256!==this.hash)throw Error('Receipt scope changed');
   return receipt;
  }finally{this.armed=false;}
 }
 async close(){if(this.context)await this.context.close();}
}
module.exports={FixedFileBackend};
