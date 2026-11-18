import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const browser = await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true});
try {
  const page = await browser.newPage({viewport:{width:1200,height:800}}), errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  await page.setContent('<main id="words"></main><div id="word-popover" class="hidden"></div>');
  await page.evaluate(()=>{
    window.counts={batch:0,full:0,vocab:0}; window.batchDelay=40; window.fail=false;
    const delay=ms=>new Promise(r=>setTimeout(r,ms));
    window.LP={api:{
      explainWords:async body=>{ counts.batch++; await delay(batchDelay); if(fail)throw Error('offline');
        if(body.sentence==='bank bank')return {words:[{surface:'bank',lemma:'bank',occurrence:0,meaning_zh:'银行',detail:'brief'},{surface:'bank',lemma:'bank',occurrence:1,meaning_zh:'河岸',detail:'brief'}]};
        return {complete:true,words:body.sentence.split(' ').filter(Boolean).map(surface=>({lemma:surface,surface,meaning_zh:'词义：'+surface,detail:'brief'}))}; },
      explainWord:async body=>{ counts.full++; await delay(40); return {...body,meaning_zh:'详细：'+body.surface,grammar_note:'语法细节'}; },
      getVocab:async ()=>{counts.vocab++; await delay(600); return {items:[]};},
      addVocab:async body=>{window.saved=body;return {};}}, tokens:{markCollectedGlobal(){}},toast(){}};
  });
  for(const file of ['util.js','glosses.js','tokens.js','wordcard.js'])await page.addScriptTag({path:path.join(root,'frontend/js',file)});
  await page.evaluate(()=>{
    window.ts=['river','bank'].map((surface,i)=>({i,surface,lemma:surface,clickable:true,space_after:i===0}));
    LP.tokens.renderTokens(document.querySelector('#words'),ts,'en',(ev,span,t,sentence)=>LP.wordcard.open(ev.clientX,ev.clientY,span,t,sentence,'en',123));
  });
  // Concurrent prefetch callers share one request; warm clicks paint synchronously.
  await page.evaluate(()=>Promise.all([LP.glosses.prepare('en','river bank'),LP.glosses.prepare('en','river bank')]));
  const warm = await page.evaluate(()=>{
    const start=performance.now();document.querySelectorAll('.tok')[1].click();
    return {elapsed:performance.now()-start,meaning:document.querySelector('.wp-meaning')?.textContent,counts:{...counts}};
  });
  assert.equal(warm.meaning,'词义：bank'); assert.equal(warm.counts.batch,1);assert.equal(warm.counts.full,0);
  assert.ok(warm.elapsed<100,'Meaning must not wait 600 ms for vocabulary status');
  await page.locator('#wp-detail-btn').click();
  await page.waitForFunction(()=>document.querySelector('.wp-grammar')?.textContent.includes('语法细节'));
  assert.equal(await page.evaluate(()=>counts.full),1);
  await page.locator('#wp-collect-btn').click();
  await page.waitForFunction(()=>window.saved);
  assert.equal(await page.evaluate(()=>saved.context_sentence),'river bank');
  assert.equal(await page.evaluate(()=>saved.source_message_id),123);
  // Cold clicks join the pending batch, even after closing/opening another word.
  await page.evaluate(()=>{
    LP.wordcard.close();batchDelay=200;
    const sentence='quiet bookshop',word={surface:'quiet',lemma:'quiet',clickable:true};
    void LP.glosses.prepare('en',sentence);
    void LP.wordcard.open(10,10,document.querySelector('.tok'),word,sentence,'en',null);
    LP.wordcard.close();
    void LP.wordcard.open(10,10,document.querySelectorAll('.tok')[1],{surface:'bookshop',lemma:'bookshop'},sentence,'en',null);
  });
  await page.waitForFunction(()=>document.querySelector('.wp-meaning')?.textContent==='词义：bookshop');
  assert.equal(await page.evaluate(()=>counts.batch),2); assert.equal(await page.evaluate(()=>counts.full),1);
  // A failed batch falls back to exactly the clicked word and remains retryable.
  await page.evaluate(async()=>{
    fail=true;batchDelay=5;
    await LP.wordcard.open(10,10,document.querySelector('.tok'),{surface:'fallback',lemma:'fallback'},'fallback sentence','en',null);
  });
  assert.equal(await page.locator('.wp-meaning').textContent(),'详细：fallback');
  assert.equal(await page.evaluate(()=>counts.full),2);
  await page.evaluate(async()=>{fail=false;await LP.glosses.prepare('en','fallback sentence');});
  assert.equal(await page.evaluate(()=>counts.batch),4);
  await page.evaluate(async()=>{
    LP.tokens.renderTokens(document.querySelector('#words'),[0,1].map(i=>({i,surface:'bank',lemma:'bank',clickable:true,space_after:i===0})),'en',
      (ev,span,t,sentence)=>LP.wordcard.open(10,10,span,t,sentence,'en',null));
    await LP.glosses.prepare('en','bank bank');
    document.querySelectorAll('.tok')[1].click();
  });
  assert.equal(await page.locator('.wp-meaning').textContent(),'河岸');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,warmClickMs:warm.elapsed,checks:['warm click does not fetch LLM','vocab status does not block paint','detail on demand','collection keeps original context','pending prefetch shared across rapid clicks','offline fallback and retry']}));
}finally{await browser.close();}
