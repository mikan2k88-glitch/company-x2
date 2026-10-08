const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const {translate}=require('../company_x2/customer_i18n.js');
assert.equal(translate('入力 2行 → 納品 1行 / CSV / テスト ¥100','en'),'Input 2 rows → Output 1 rows / CSV / Test JPY 100');
assert.equal(translate('成果物の受領を記録しました','en'),'Receipt recorded');
assert.equal(translate('CSV重複除去','ja'),'CSV重複除去');
assert.equal(translate('Public CSV limit: 50 KB and 1,000 rows','ja'),'公開入力は50KB・1,000行までです');
assert.equal(translate('Public CSV limit: 50 KB and 1,000 rows','en'),'Public CSV limit: 50 KB and 1,000 rows');
assert.equal(translate('SHA-256: 001abcdef','en'),'SHA-256: 001abcdef');
const node=(text,skip=false)=>({nodeValue:text,parentElement:{closest:()=>skip}});
const title=node('CSVの依頼受付'),status=node('成果物の準備完了'),csv=node('name\nCSV重複除去\n',true);
const nodes=[title,status,csv];let change,callback;const values={};
const picker={value:'en',addEventListener:(event,fn)=>change=fn};
const context={URLSearchParams,location:{search:'?lang=en'},navigator:{language:'ja'},window:{},
 sessionStorage:{getItem:k=>values[k],setItem:(k,v)=>values[k]=v},NodeFilter:{SHOW_TEXT:4},
 document:{documentElement:{lang:'ja'},querySelector:()=>({}),querySelectorAll:()=>[],getElementById:()=>picker,
 createTreeWalker:()=>{let i=0;return {nextNode:()=>nodes[i++]}}},
 MutationObserver:class{constructor(fn){callback=fn}observe(){}}};
vm.runInNewContext(fs.readFileSync(require.resolve('../company_x2/customer_i18n.js'),'utf8'),context);
assert.equal(title.nodeValue,'CSV service intake');assert.equal(status.nodeValue,'Deliverable ready');
assert.equal(csv.nodeValue,'name\nCSV重複除去\n');
picker.value='ja';change();assert.equal(title.nodeValue,'CSVの依頼受付');
picker.value='en';change();status.nodeValue='成果物の受領を記録しました';callback();
assert.equal(status.nodeValue,'Receipt recorded');callback();assert.equal(status.nodeValue,'Receipt recorded');
assert.equal(csv.nodeValue,'name\nCSV重複除去\n');assert.equal(context.document.documentElement.lang,'en');
console.log('Customer language switching, dynamic states and CSV preservation passed');
