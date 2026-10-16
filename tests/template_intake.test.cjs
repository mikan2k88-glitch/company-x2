const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require.resolve('../company_x2/template-intake.html'),'utf8');
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(x=>x[1]);
const elements=Object.fromEntries(ids.map(id=>[id,{value:'',checked:false,disabled:false,hidden:false,
 addEventListener(){},replaceChildren(){},append(){}}]));
const buttons=['start','restore','suggest','plan','execute','receive'].map(id=>elements[id]);
const controls=['purpose','source','template','columns','mapping','required','scope','consent','existing-key'].map(id=>elements[id]);
Object.assign(elements.purpose,{value:'Prepare product file'});
Object.assign(elements.source,{value:'sku\n001\n'});
elements.columns.value='["SKU"]';elements.mapping.value='{"SKU":"sku"}';elements.required.value='[]';elements.scope.checked=true;
let calls=[],release,deny=false;
const context={URLSearchParams,location:{hash:''},crypto:{randomUUID:()=> 'synthetic-request-001'},sessionStorage:{getItem:()=>null,setItem(){}},
 Blob,URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},
 document:{getElementById:id=>elements[id],body:{setAttribute(){}},
 querySelectorAll:s=>s==='button'?buttons:controls,createElement:()=>({append(){}}),createTextNode:s=>s},
 fetch:async(path,options)=>{calls.push(path);if(deny)return {ok:false,json:async()=>({error:'Access expired'})};if(path==='/api/public/start')await new Promise(r=>release=r);
 let data=path.endsWith('/status')?{items:[{request_key:'synthetic-request-001',status:'received',approval_sha256:'plan-hash'}]}:
 path==='/api/public/start'?{access:'synthetic-grant'}:
 path.endsWith('/plan')?{approval_sha256:'plan-hash',plan:{questions:[]}}:
 path.endsWith('/process')?{artifact_sha256:'artifact-hash',csv:'SKU\n001\n',report:{verified:true}}:{status:'received'};
 return {ok:true,json:async()=>data};}};
vm.runInNewContext(html.split('<script>')[1].split('</script>')[0],context);
(async()=>{
 const pending=elements.start.onclick();await Promise.resolve();
 await elements.start.onclick();assert.equal(calls.length,1);assert(controls.every(x=>x.disabled));
 release();await pending;assert(controls.every(x=>!x.disabled));
 await elements.plan.onclick();assert.equal(elements['existing-key'].value,'synthetic-request-001');
 elements.consent.checked=true;await elements.execute.onclick();
 assert.equal(elements.download.hidden,false);assert.equal(elements.receive.disabled,false);
 await elements.receive.onclick();assert.equal(elements.receive.disabled,true);
 assert.deepEqual(calls,['/api/public/start','/api/intake/template/plan','/api/intake/template/request',
 '/api/intake/template/process','/api/intake/template/receive']);
 elements['existing-key'].value='synthetic-request-001';
 await elements.restore.onclick();assert.equal(elements.execute.disabled,false);
 elements.consent.checked=true;await elements.execute.onclick();assert.equal(elements.download.hidden,false);
 deny=true;elements['existing-key'].value='synthetic-request-001';
 await elements.restore.onclick();assert.equal(elements.result.textContent,'Access expired');
 assert.equal(elements.execute.disabled,true);assert.equal(elements.download.hidden,true);
 assert(controls.every(x=>!x.disabled));
 const count=calls.length;
 vm.runInNewContext(html.split('<script>')[1].split('</script>')[0],{
  ...context,sessionStorage:{getItem(){throw Error('Storage blocked')},setItem(){throw Error('Storage blocked')}}
 });
 await elements.start.onclick();assert.equal(calls.length,count);
 assert.match(elements.result.textContent,/Session storage unavailable/);
 console.log('Synthetic UI flow and concurrent-click guard passed');
})().catch(e=>{console.error(e);process.exitCode=1});
