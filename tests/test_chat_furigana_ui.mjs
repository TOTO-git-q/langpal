import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH,headless:true});
try {
 const page=await browser.newPage();
 await page.route('http://furigana.test/**',route=>route.fulfill({contentType:'text/html',body:'<span id="tokens"></span>'}));
 await page.goto('http://furigana.test/');
 await page.addScriptTag({path:path.join(root,'frontend/js/furigana.js')});
 await page.addScriptTag({path:path.join(root,'frontend/js/tokens.js')});
 const result=await page.evaluate(()=>{
  window.fetch=()=>{throw Error('Token readings must not fetch');};
  const el=document.getElementById('tokens'),tokens=[{i:0,surface:'日本語',reading:'ニホンゴ',lemma:'日本語',clickable:true},{i:1,surface:'です。',reading:'デス',clickable:false}];
  const clicks=[]; LP.furigana.setEnabled(true);
  LP.tokens.renderTokens(el,tokens,'ja',(event,span,token,sentence)=>clicks.push({surface:token.surface,sentence}));
  el.querySelector('rb').click();
  const range=document.createRange();range.selectNodeContents(el);getSelection().removeAllRanges();getSelection().addRange(range);
  const data=new DataTransfer();el.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));
  const first={ruby:el.querySelector('rt').textContent,raw:LP.furigana.sourceText(el),copied:data.getData('text/plain'),clicks};
  LP.furigana.setEnabled(false);
  return {...first,rubyAfter:el.querySelectorAll('ruby').length,textAfter:el.textContent};
 });
 assert.deepEqual(result,{ruby:'にほんご',raw:'日本語です。',copied:'日本語です。',clicks:[{surface:'日本語',sentence:'日本語です。'}],rubyAfter:0,textAfter:'日本語です。'});
 console.log('PASS chat furigana: dictionary reading, original lookup/copy, toggle, no extra network.');
} finally {await browser.close();}
