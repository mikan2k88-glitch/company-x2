/* Curated UI translations only. Never translate customer CSV, hashes or identifiers. */
(() => {
const messages={
'返金対象を確認':'Refund eligibility confirmed',
'返金処理中':'Preparing refund',
'返金受付中':'Refund pending',
'返金完了':'Refund succeeded',
'返金失敗・運営確認中':'Refund failed; operator review required',
'返金取消・運営確認中':'Refund canceled; operator review required',
'返金に追加対応が必要':'Refund requires additional action',
'返金状況を運営側で確認中':'Refund under operator review',
'本番決済（実際に支払います）':'Live payment (real charge)',
'本番決済 JPY ':'Live payment JPY ',
'（実際に支払います）':' (real charge)',
'表示された処理範囲・本番料金・販売条件・返金条件に同意します。':'I agree to the displayed scope, live price, sales terms and refund conditions.',
'販売条件・返金条件を確認':'Read sales terms and refund conditions',
'Stripe本番決済へ（実際に支払います）':'Open live Stripe checkout (real charge)',
'本番入金を照合':'Live payment verified',

'E19 / 公開無料検証と招待受付の窓口です。無料・Stripeテストでは実際の支払いはありません。本番決済を選ぶと実際に支払います。':'E19 / Public free verification and invitation intake. Free and Stripe test modes do not charge you. Live payment makes a real charge.',
'公開入力は50KB・1,000行まで。JSONでは値を文字列として保持します。':'Public input: up to 50 KB and 1,000 rows. JSON values remain strings.',
'無料検証を開始':'Start free verification',
'無料検証を開始するか、招待リンクからアクセスしてください。':'Start free verification or open your invitation link.',
'アクセス期限が切れました。無料検証を開始し直すか、新しい招待リンクを使ってください。':'Access expired. Start free verification again or use a new invitation link.',
'公開受付で無料検証を開始する（招待リンクも利用できます）':'Start free verification through public intake (invitation links also work)',
'公開受付は50KB・1,000行まで、同じ利用トークンで1日2件、全体で1日10件。無料検証のみで、実際の支払いは発生しません。':'Public intake: up to 50 KB and 1,000 rows, two orders per owner token per day and ten in total per day. Free verification only. No real charge.',
'招待リンクなしで無料検証できます。公開受付は50KB・1,000行まで、同じ利用トークンで1日2件、全体で1日10件です。上限は日本時間9時に更新します。':'You can start free verification without an invitation. Public intake: 50 KB, 1,000 rows, two orders per owner token and ten total per day. Limits reset at 00:00 UTC (09:00 Japan time).',

'CSVの依頼受付':'CSV service intake',
'E19 / 期限付き受付リンクを受け取った利用者向けの検証窓口です。無料検証またはStripeテスト100円で受付します。実際の支払いは発生しません。':'E19 / Test intake for customers with an invitation link. Free verification or a JPY 100 Stripe test payment. No real charge.',
'1. サービスと入力':'1. Service and input','2. 制作・受け取り':'2. Production and delivery',
'受付条件を確認しています…':'Checking intake availability…','処理':'Service',
'CSV重複除去':'CSV exact deduplication','CSV空白整形':'CSV whitespace trimming','CSVデータ検査':'CSV data audit',
'UTF-8のCSVファイル':'UTF-8 CSV file',
'ファイルはこのブラウザーで読み込みます。計画作成時にCSV本文をサーバーへ送信します。AIには送りません。':'The file is read in this browser. Creating a plan sends the CSV to our server, not to an AI provider.',
'CSV本文（直接入力もできます）':'CSV content (you can also paste it)',
'1MB・10,000行以内。JSON変換では先頭ゼロや空欄も文字列として保持します。':'Up to 1 MB and 10,000 rows. JSON conversion preserves leading zeros and empty values as strings.',
'モード':'Mode','無料検証 ¥0':'Free verification JPY 0','Stripeテスト ¥100':'Stripe test JPY 100',
'作業計画・見積もりを作成':'Create plan and estimate',
'表示された処理範囲・検証料金に同意します。':'I agree to the displayed scope and test price.',
'この条件で依頼を受け付ける':'Submit this test request',
'依頼待ち':'Waiting for a request','Stripeのテスト決済画面へ':'Open Stripe test checkout','成果物を受け取る':'Download deliverable',
'同じブラウザー・タブで戻ると進行を再表示します。成果物のハッシュ一致を確認して受領を記録します。':'Return in the same browser tab to resume. Receipt is recorded after verifying the downloaded file hash.',
'セッション保存が使えません。このブラウザーでは受付できません。':'Session storage is unavailable. Intake cannot continue in this browser.',
'受付リンクを保存できません。':'The invitation link could not be saved.',
'受付リンクを確認してください。期限切れの場合は新しいリンクが必要です':'Check your invitation link. If it expired, request a new link.',
'受付リンクの期限切れ、または無効なリンクです。新しいリンクが必要です':'The invitation is invalid or expired. Request a new link.',
'通信に失敗しました':'The request failed. Please retry.',
'CSVファイルは1MBまでです':'CSV files must be no larger than 1 MB',
'UTF-8のCSVを選んでください':'Choose a valid UTF-8 CSV file',
'計画を作成しています…':'Creating your plan…',
'完全一致する重複行を除去。列名・値・先頭の行順を保持します。':'Remove exactly identical rows, preserving column names, values and the first occurrence order.',
'列名と各値の前後の空白を除去します。内部の空白・行順・重複は保持します。':'Trim leading and trailing whitespace from headers and values. Preserve internal spaces, row order and duplicates.',
'列名をキーにしたオブジェクト配列へ変換。数値・空欄も文字列として保持します。':'Convert to an array of objects keyed by column names. Numbers and empty values remain strings.',
'空欄・完全一致の重複・数式のような値を検査し、JSONレポートを納品します。入力は変更しません。':'Report empty cells, exact duplicate rows and formula-like values in JSON. The input is not modified.',
'受付済み':'Request accepted','制作・検品中':'Producing and checking','Stripeテスト決済待ち':'Waiting for Stripe test payment',
'成果物の準備完了':'Deliverable ready','成果物の受領を記録しました':'Receipt recorded','処理に失敗しました':'Processing failed',
'処理条件を保存':'Scope saved','テスト決済画面を作成':'Test checkout created','テスト決済を照合':'Test payment verified',
'制作・検品を開始':'Production and checks started','検品を通過':'Checks passed','成果物の受領を記録':'Receipt recorded','失敗を記録':'Failure recorded',
'決済URLを確認できません':'The checkout URL could not be verified',
'成果物を取得できません':'The deliverable could not be downloaded','ハッシュが一致しません':'The file hash does not match',
'受付準備完了。サービスとCSVを指定してください。':'Intake is ready. Select a service and provide your CSV.',
'制作または検品に失敗しました。運用画面で確認してください。':'Production or checks failed. Contact the operator.',
'対応サービスと検証モードを指定してください':'Select a supported service and test mode',
'計画か入力が変わりました。見積もりを作り直してください':'The plan or input changed. Create a new estimate.',
'処理範囲・料金・検証条件への同意が必要です':'Accept the scope, price and test conditions',
'Stripeテスト決済が未設定です':'Stripe test payments are not configured',
'E09用SQLの適用が必要です':'Intake database setup is required',
'009_company.sqlをSupabaseに適用してください':'The intake database migration is required. Contact the operator.',
'Stripeの応答を確認できませんでした。同じ注文で再確認してください':'Stripe could not be reached. Retry with the same order.',
'この注文は決済受付できません':'Checkout is unavailable for this order',
'無料注文に決済は不要です':'Free orders do not require checkout',
'所有者トークンが必要です':'An order owner token is required','受付キーを確認してください':'The request key is invalid',
'入力 ':'Input ','行 → 納品 ':' rows → Output ','行 / ':' rows / ','テスト ¥100':'Test JPY 100','無料 ¥0':'Free JPY 0',
'サービス紹介':'Service overview','検証受付を開く':'Open test intake',
'小さなCSV作業を、確実な成果物へ。':'Small CSV tasks. Clearly defined deliverables.',
'日本語・英語で利用できる、CSV加工の検証サービスです。現在は無料検証とStripeテスト決済のみ。本番課金は開始していません。':'A CSV processing test service in Japanese and English. Free verification and Stripe test payments only. Live billing has not started.',
'対応サービス':'Supported services','料金と利用条件':'Pricing and conditions',
'無料検証は0円、Stripeのテスト決済は100円相当です。実際の請求・売上は発生しません。本番料金と納期は未確定です。':'Free verification costs JPY 0. Stripe test checkout uses JPY 100 in test currency. No real charge or revenue. Live pricing and delivery commitments are not set.',
'利用の流れ':'How it works',
'運営者から7日間有効の受付リンクを受け取る':'Receive a seven-day invitation link from the operator',
'CSVを入力し、処理範囲と計画を確認する':'Provide CSV and review the scope and plan',
'無料検証またはテスト決済で依頼する':'Submit with free verification or a test payment',
'成果物をダウンロードし、受領を記録する':'Download the deliverable and record receipt',
'入力とプライバシー':'Input and privacy',
'UTF-8 CSV、最大1MB・10,000行。機密情報や個人情報を含めないでください。CSVは処理のためサーバー・Supabaseへ送信・保存します。CSV本文を外部AIへ送信しません。':'UTF-8 CSV, up to 1 MB and 10,000 rows. Do not include secrets or personal information. CSV is sent to and stored on our server and Supabase for processing. CSV content is not sent to an external AI provider.',
'受付リンクが必要です。紹介ページの閲覧だけでは依頼できません。':'An invitation link is required to submit a request. Viewing this page does not grant intake access.',
'発注募集中という表示や実売上の表示はありません。自動応募はまだ稼働していません。':'This is a test service. Automatic bidding is not active.',
'決済表示も選択した言語で開きます。既存の決済画面は作成時の言語を保持します。':'New checkout sessions use the selected language. Existing sessions keep their original language.'
};
const publicErrors={
'Public CSV limit: 50 KB and 1,000 rows':'公開入力は50KB・1,000行までです',
'Public intake supports free verification only':'公開受付は無料検証のみです',
'Daily public start limit reached; retry after 00:00 UTC':'本日の公開開始上限です。日本時間9時以降に再試行してください',
'Daily public plan limit reached; retry after 00:00 UTC':'本日の計画作成上限です。日本時間9時以降に再試行してください',
'Daily public order limit reached; retry after 00:00 UTC':'本日の公開受付上限です。日本時間9時以降に再試行してください',
'Public rate limit reached; retry in one minute':'公開APIが混み合っています。1分後に再試行してください',
'Public intake temporarily unavailable; contact the operator':'公開受付を一時停止しています。運営者へご連絡ください'
};
const keys=Object.keys(messages).sort((a,b)=>b.length-a.length);
function translate(text,lang){if(lang!=='en')return publicErrors[text]||text;for(const key of keys)text=text.split(key).join(messages[key]);return text}
if(typeof module!=='undefined')module.exports={translate,messages};
if(typeof document==='undefined')return;
let lang='ja';try{const requested=new URLSearchParams(location.search).get('lang');lang=['ja','en'].includes(requested)?requested:sessionStorage.getItem('cx2-language')||((navigator.language||'').startsWith('ja')?'ja':'en')}catch{}
if(!['ja','en'].includes(lang))lang='ja';
try{sessionStorage.setItem('cx2-language',lang)}catch{}
const originals=new WeakMap();
function render(){document.documentElement.lang=lang;document.title=lang==='en'?'Company X2 — CSV services':'Company X2 — CSVサービス';
 const walker=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);let node;
 while(node=walker.nextNode()){if(node.parentElement.closest('script,style,textarea,input,[data-no-translate]'))continue;
  const old=originals.get(node);const source=old&&node.nodeValue===old.output?old.source:node.nodeValue;const output=translate(source,lang);
  originals.set(node,{source,output});if(node.nodeValue!==output)node.nodeValue=output;
 }
 const picker=document.getElementById('customer-language');if(picker)picker.value=lang;
 document.querySelectorAll('[data-language-link]').forEach(a=>{a.href=a.getAttribute('data-language-link')+'?lang='+lang});
}
window.cx2Language={get current(){return lang},translate:text=>translate(text,lang)};
const picker=document.getElementById('customer-language');if(picker)picker.addEventListener('change',()=>{lang=picker.value;try{sessionStorage.setItem('cx2-language',lang);const query=new URLSearchParams(location.search);query.set('lang',lang);history.replaceState(null,'',location.pathname+'?'+query.toString()+location.hash)}catch{}render()});
render();new MutationObserver(render).observe(document.querySelector('main'),{subtree:true,childList:true,characterData:true});
})();
