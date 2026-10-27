// Private pipe worker. No HTTP listener, credentials, profile or payload logging.
const readline=require('node:readline');
const {FixedFileBackend}=require('./fixed_file_backend.cjs');
let browser,backend,step=0;
const emit=value=>process.stdout.write(JSON.stringify(value)+'\n');
(async()=>{
 if(process.env.CX2_BROWSER_WORKER!=='1')throw Error('Disabled');
 for await(const line of readline.createInterface({input:process.stdin})){
  if(Buffer.byteLength(line)>75000)throw Error('Oversize message');
  const message=JSON.parse(line);
  if(step===0&&message.command==='stage'){
   const artifact=Buffer.from(message.artifact_base64,'base64');
   if(!artifact.length||artifact.length>50000)throw Error('Invalid artifact');
   const {chromium}=require('playwright');
   browser=await chromium.launch({headless:true,timeout:15000});
   backend=new FixedFileBackend(browser,message.config);
   emit({event:'staged',...await backend.stage(message.destination,artifact)});step=1;
  }else if(step===1&&message.command==='commit'){
   step=2;emit({event:'receipt',receipt:await backend.commit(message.staged)});break;
  }else throw Error('Invalid worker sequence');
 }
})().catch(()=>{emit({event:'error'});process.exitCode=1;})
 .finally(async()=>{if(backend)await backend.close();if(browser)await browser.close();});
