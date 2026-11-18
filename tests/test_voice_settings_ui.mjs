import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const voices={a:'af_heart',b:'am_michael',speed:1,speed_b:null};
let synthesis={provider:'kokoro',kokoro_en:voices,kokoro_ja:{...voices,a:'jf_alpha',b:'jm_kumo'},api_en:{...voices,a:'alloy',b:'echo'},api_ja:{...voices,a:'alloy',b:'echo'},api_languages:{},base_url:'',model:'',pause_ms:300,volume:1,api_key_configured:false,kokoro_voices:{en:['af_heart','am_michael'],ja:['jf_alpha','jm_kumo']},synthesis:{en:true,ja:true}};
let settings={language:'ja',lessonMinutes:25,budgetUsd:2,models:{realtime:'saved-exact-live1.1',grading:'saved-audio',lessonCard:'saved-text',tts:'saved-tts'},voice:'marin',ttsVoice:'alloy',voicePreset:'yami',voices:['marin','new-voice'],phaseWeights:[3,3,5,10,4],timezone:'Asia/Tokyo'};
let connection={provider:'openai',baseUrl:'https://api.openai.com/v1',textProvider:'jine',realtime:{vad:'semantic_vad',eagerness:'auto',threshold:.5,silenceMs:500,prefixMs:300,interrupt:true,speed:1,noiseReduction:'off',transcriptionModel:'',maxOutputTokens:null},keyConfigured:true};
const calls=[],errors=[];
let finishPreview, previewStarted=false, failSpeaking=false;
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH,headless:true});
try{
 const page=await browser.newPage({viewport:{width:1180,height:1000}});
 page.setDefaultTimeout(8000);
 await page.addInitScript(()=>{HTMLMediaElement.prototype.play=async function(){};});
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('http://voice.test/**',async route=>{
  const request=route.request(),url=new URL(request.url()),body=request.postDataJSON();calls.push({path:url.pathname,method:request.method(),body});
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh"><head><meta charset="utf-8"></head><body style="margin:0;padding:36px;background:#fbf9fd"><main style="max-width:900px;margin:auto" id="root"></main></body></html>'});
  if(url.pathname==='/api/listening/synthesis'){
   if(request.method()==='PUT'){const{api_key,...saved}=body;synthesis={...synthesis,...saved,api_key_configured:!!api_key};}
   return route.fulfill({json:synthesis});
  }
  if(url.pathname==='/api/voice-settings/listening/preview'){previewStarted=true;await new Promise(resolve=>{finishPreview=resolve;});return route.fulfill({status:409,json:{detail:'Busy'}});}
  if(failSpeaking&&['/api/speaking/settings','/api/speaking/connection'].includes(url.pathname))return route.fulfill({status:502,json:{detail:'Offline'}});
  if(url.pathname==='/api/speaking/settings')return route.fulfill({json:{settings,voicePresets:[{id:'sweet',label:'甜'},{id:'salt',label:'盐'},{id:'onee',label:'御'},{id:'yami',label:'病'},{id:'plain',label:'标准'}],keyConfigured:true,mock:false}});
  if(url.pathname==='/api/speaking/connection')return route.fulfill({json:connection});
  if(url.pathname==='/api/speaking/models')return route.fulfill({json:{data:[{id:'future/live+2027'},{id:'live1.1'}]}});
  if(url.pathname==='/api/voice-settings/listening/models')return route.fulfill({json:{models:[{id:'future-tts/1.1',label:'Future voice'}]}});
  if(url.pathname==='/api/speaking/setup'){settings=body.settings;connection={...connection,...body.connection};delete connection.apiKey;return route.fulfill({json:{settings,connection,keyConfigured:true,mock:false}});}
  return route.fulfill({status:404,json:{detail:'Missing fixture'}});
 });
 await page.goto('http://voice.test/');
 for (const sheet of ['windose.css','settings.css']) await page.addStyleTag({content:await fs.readFile(path.join(root,'frontend/css',sheet),'utf8')});
 await page.addScriptTag({content:await fs.readFile(path.join(root,'frontend/js/util.js'),'utf8')});
 await page.addScriptTag({content:await fs.readFile(path.join(root,'frontend/js/settings-providers.js'),'utf8')});
 await page.evaluate(()=>{LP.languages={list:()=>[{tag:'en',label:'English'},{tag:'ja',label:'日本語'},{tag:'fr',label:'Français'}]};const root=document.querySelector('#root');root.innerHTML='<h1>听力</h1>'+LP.settingsProviders.listeningMarkup+'<h1 style="margin-top:70px">口语</h1>'+LP.settingsProviders.speakingMarkup;window.voiceApi=LP.settingsProviders.wire(root);});
 assert.equal(await page.locator('#speaking-read-models').isDisabled(),true);
 await page.evaluate(()=>Promise.all([voiceApi.loadListening(),voiceApi.loadSpeaking()]));
 assert.equal(await page.locator('#speaking-read-models').isEnabled(),true);
 assert.equal(await page.locator('#f-speaking-model').inputValue(),'saved-exact-live1.1');
 // 音色预设：按服务给的清单顺序画分段开关；不是「标准」时自选声音那两格收起
 assert.deepEqual(await page.locator('.voice-preset label').allInnerTexts(),['甜','盐','御','病','标准']);
 assert.equal(await page.locator('.voice-preset input:checked').inputValue(),'yami');
 assert.equal(await page.locator('#f-speaking-voice').isVisible(),false);
 assert.equal(await page.locator('#f-speaking-tts-voice').isVisible(),false);
 await page.locator('.voice-preset label',{hasText:'标准'}).click();
 assert.equal(await page.locator('#f-speaking-voice').isVisible(),true);
 await page.locator('.voice-preset label',{hasText:'甜'}).click();
 assert.equal(await page.locator('#f-speaking-voice').isVisible(),false);
 assert.equal(await page.locator('#f-speaking-authoring').inputValue(),'jine');
 assert.equal(await page.locator('#f-speaking-key').inputValue(),'');
 assert.equal(await page.locator('[data-speaking-transcription]').isVisible(),false);
 await page.locator('#f-speaking-subtitles').check();
 assert.equal(await page.locator('[data-speaking-transcription]').isVisible(),true);
 await page.locator('#f-speaking-transcription').fill('future-transcriber');
 await page.locator('#f-speaking-vad').selectOption('server_vad');
 assert.equal(await page.locator('[data-speaking-vad="server_vad"]').isVisible(),true);
 await page.locator('#f-speaking-model').fill('');
 await page.locator('#f-speaking-key').fill('synthetic-speaking-probe-token');
 const beforeProbe=JSON.stringify(connection);
 await page.locator('#speaking-read-models').click();
 await page.waitForFunction(()=>document.querySelectorAll('#speaking-models option').length===2);
 assert.equal(await page.locator('#f-speaking-model').inputValue(),'');
 assert.equal(JSON.stringify(connection),beforeProbe);
 assert.equal(await page.locator('#f-speaking-key').inputValue(),'synthetic-speaking-probe-token','draft key stays until explicit save');
 assert.equal(await page.locator('#speaking-models option').first().getAttribute('value'),'future/live+2027');
 await page.locator('#f-speaking-model').fill('live1.1');
 await page.locator('#settings-speaking-service button[type=submit]').click();
 await page.waitForFunction(()=>document.querySelector('[data-speaking-feedback]').textContent==='已保存');
 assert.equal(settings.models.realtime,'live1.1');assert.equal(settings.voicePreset,'sweet');assert.equal(connection.realtime.transcriptionModel,'future-transcriber');assert.equal(connection.realtime.vad,'server_vad');
 await page.locator('#f-synthesis-provider').selectOption('compatible');
 await page.locator('#f-synthesis-url').fill('https://speech.example/v1');
 await page.locator('#f-synthesis-key').fill('synthetic-voice-ui-token');
 await page.locator('#synthesis-read-models').click();
 await page.waitForFunction(()=>document.querySelectorAll('#synthesis-models option').length===1);
 assert.equal(calls.filter(c=>c.path==='/api/listening/synthesis'&&c.method==='PUT').length,0,'reading model catalog must not need a chosen model or persist a draft');
 await page.locator('#f-synthesis-model').fill('future-tts/1.1');
 await page.locator('#voice-api-fr-a').fill('fr-a');await page.locator('#voice-api-fr-b').fill('fr-b');
 await page.locator('#f-synthesis-pause').fill('650');await page.locator('#voice-api-en-speed-b').fill('1.25');
 await page.locator('#settings-listening-synthesis button[type=submit]').click();
 await page.waitForFunction(()=>document.querySelector('[data-synthesis-feedback]').textContent==='已保存');
 assert.equal(synthesis.pause_ms,650);assert.equal(synthesis.api_en.speed_b,1.25);assert.equal(synthesis.api_languages.fr.a,'fr-a');assert.equal(await page.locator('#f-synthesis-key').inputValue(),'');
 assert.equal(await page.locator('a[href*="/settings"]').count(),0);
 await page.locator('[data-synthesis-panel="compatible"] [data-voice-preview]').first().click();
 for(let i=0;i<100&&!previewStarted;i++)await page.waitForTimeout(50); // 试听中：按钮全部禁用，不写「试音中…」
 assert.equal(previewStarted,true);
 assert.equal(await page.locator('[data-voice-preview]:not([disabled])').count(),0);
 assert.equal(calls.filter(c=>c.path==='/api/voice-settings/listening/preview').length,1);
 finishPreview();
 await page.waitForFunction(()=>document.querySelector('[data-synthesis-feedback]').textContent==='Busy');
 assert.ok(await page.locator('[data-synthesis-panel="compatible"] [data-voice-preview]:not([disabled])').count()>1);
 failSpeaking=true;
 await page.evaluate(()=>voiceApi.loadSpeaking(true));
 assert.equal(await page.locator('#speaking-read-models').isDisabled(),true);
 failSpeaking=false;
 await page.evaluate(()=>voiceApi.loadSpeaking(true));
 assert.equal(await page.locator('#speaking-read-models').isEnabled(),true);
 await page.locator('#settings-speaking-service').scrollIntoViewIfNeeded();
 if(process.env.LANGPAL_VOICE_SCREENSHOTS){await fs.mkdir(process.env.LANGPAL_VOICE_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.LANGPAL_VOICE_SCREENSHOTS,'voice-settings-desktop.png'),fullPage:true});}
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 assert.deepEqual(errors,[]);console.log('Voice settings UI: dynamic catalogs, exact model retention, inline controls, saved audio parameters, custom language and mobile layout passed.');
}finally{await browser.close();}
