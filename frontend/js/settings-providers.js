/* Voice credentials stay with the voice service; text authoring follows JINE. */
(function (global) {
  'use strict';
  const languages = [['en','English'],['ja','日本語']];
  const escape = value => global.LP.util.escapeHtml(value);
  const fail = error => global.LP.util.message(error, '没连上，再试一次');
  // 自定义语言的 tag 由用户输入：拼进 id 前先换成只含 [A-Za-z0-9-] 的形式，拼进属性值前先转义。
  const idPart = tag => String(tag).replace(/[^A-Za-z0-9-]/g, char => '_' + char.codePointAt(0).toString(16) + '_');
  const voicePrefix = (provider, language) => `voice-${provider}-${idPart(language)}`;
  const range = (id,label,min,max,step,value=1) => `<label class="voice-slider" for="${id}"><span>${label}</span><input id="${id}" type="range" min="${min}" max="${max}" step="${step}" value="${value}"><output for="${id}"></output></label>`;
  function voiceFields(provider, language, label) {
    const prefix = voicePrefix(provider, language);
    const tag = escape(language);
    return `<fieldset class="voice-language" data-voice-language="${tag}"><legend>${escape(label)}</legend><div class="voice-channel-grid">${['a','b'].map(speaker=>`<section class="voice-channel"><label class="voice-label" for="${prefix}-${speaker}">声音 ${speaker.toUpperCase()}</label>${provider!=='api'?`<select id="${prefix}-${speaker}"></select>`:`<input id="${prefix}-${speaker}" type="text" maxlength="100" placeholder="音色 ID">`}${range(`${prefix}-speed-${speaker}`,'语速',.5,2,.05)}<button type="button" class="voice-preview" data-voice-preview="${tag}" data-speaker="${speaker.toUpperCase()}">▶ 保存并试听</button></section>`).join('')}</div></fieldset>`;
  }
  const listeningMarkup = `<form class="voice-settings" id="settings-listening-synthesis">
    <div class="voice-setting-row"><label for="f-synthesis-provider">合成方式</label><select id="f-synthesis-provider" disabled><option value="kokoro">Kokoro · 本机</option><option value="compatible">语音 API</option></select></div>
    <div data-synthesis-panel="compatible" hidden>
      <div class="voice-setting-row"><label for="f-synthesis-vendor">服务商</label><select id="f-synthesis-vendor"><option value="openai">OpenAI</option><option value="compatible">自定义接口</option></select></div>
      <div class="voice-setting-row"><label for="f-synthesis-url">API 地址</label><input id="f-synthesis-url" type="url" maxlength="300" placeholder="https://api.openai.com/v1"></div>
      <div class="voice-setting-row"><label for="f-synthesis-key">API 密钥</label><input id="f-synthesis-key" type="password" maxlength="1024" autocomplete="new-password" placeholder="未设置"></div>
      <label class="voice-toggle"><input id="f-synthesis-clear-key" type="checkbox">清除已存密钥</label>
      <div class="voice-setting-row"><label for="f-synthesis-model">模型</label><div class="voice-input-action"><input id="f-synthesis-model" type="text" maxlength="256" list="synthesis-models" placeholder="选择或填写模型"><button type="button" id="synthesis-read-models">读模型</button></div><datalist id="synthesis-models"></datalist></div>
    </div>
    <div data-synthesis-panel="kokoro">${languages.map(([tag,label])=>voiceFields('kokoro',tag,label)).join('')}</div>
    <div data-synthesis-panel="compatible" hidden>${languages.map(([tag,label])=>voiceFields('api',tag,label)).join('')}<div data-extra-voices></div></div>
    <div data-synthesis-panel="voicevox" hidden>${voiceFields('voicevox','ja','日本語')}</div>
    <section class="voice-audio-controls"><h3>音频</h3>${range('f-synthesis-pause','句间停顿',0,1500,50,300)}${range('f-synthesis-volume','音量',.25,1.5,.05,1)}</section>
    <div class="voice-setting-row"><label for="f-voice-sample">试音文本</label><input id="f-voice-sample" type="text" maxlength="180" placeholder="写一句，听听看"></div>
    <div class="voice-form-actions"><button type="submit" class="voice-save" disabled>保存声音</button><audio data-voice-audio controls hidden></audio></div>
    <p data-synthesis-feedback role="status"></p>
  </form>`;
  const speakingMarkup = `<form class="voice-settings" id="settings-speaking-service">
    <section class="voice-section"><h2>语音连接</h2>
      <div class="voice-setting-row"><label for="f-speaking-provider">服务商</label><select id="f-speaking-provider"><option value="openai">OpenAI</option><option value="compatible">Realtime 兼容服务</option></select></div>
      <div class="voice-setting-row"><label for="f-speaking-base">API 地址</label><input id="f-speaking-base" type="url" maxlength="300" placeholder="https://api.openai.com/v1"></div>
      <div class="voice-setting-row"><label for="f-speaking-key">API 密钥</label><input id="f-speaking-key" type="password" maxlength="1024" autocomplete="new-password" placeholder="未设置"></div>
      <label class="voice-toggle"><input id="f-speaking-clear-key" type="checkbox">清除已存密钥</label>
    </section>
    <section class="voice-section"><h2>实时口语</h2>
      <div class="voice-setting-row"><label for="f-speaking-model">模型</label><div class="voice-input-action"><input id="f-speaking-model" type="text" maxlength="256" list="speaking-models"><button id="speaking-read-models" type="button" disabled>读模型</button></div></div><datalist id="speaking-models"></datalist>
      <div class="voice-setting-row" data-speaking-preset-row hidden><span id="speaking-preset-label">音色</span><div class="voice-preset" role="radiogroup" aria-labelledby="speaking-preset-label"></div></div>
      <div class="voice-setting-row" data-speaking-plain><label for="f-speaking-voice">声音</label><input id="f-speaking-voice" type="text" list="speaking-voices" maxlength="100"></div><datalist id="speaking-voices"></datalist>
      ${range('f-speaking-speed','老师语速',.5,1.5,.05,1)}
      <label class="voice-toggle"><input id="f-speaking-interrupt" type="checkbox">允许打断老师</label>
      <div class="voice-setting-row"><label for="f-speaking-tokens">单次回复上限</label><input id="f-speaking-tokens" type="number" min="64" max="4096" step="64" placeholder="默认"></div>
    </section>
    <section class="voice-section"><h2>轮到谁说</h2>
      <div class="voice-setting-row"><label for="f-speaking-vad">接话方式</label><select id="f-speaking-vad"><option value="semantic_vad">听懂后接话</option><option value="server_vad">停顿后接话</option></select></div>
      <div data-speaking-vad="semantic_vad"><div class="voice-setting-row"><label for="f-speaking-eagerness">接话节奏</label><select id="f-speaking-eagerness"><option value="auto">自动</option><option value="low">多等一会</option><option value="medium">正常</option><option value="high">快点接话</option></select></div></div>
      <div data-speaking-vad="server_vad" hidden>${range('f-speaking-threshold','收音阈值',0,1,.05,.5)}${range('f-speaking-silence','停顿等待',100,2000,100,500)}${range('f-speaking-prefix','保留开头',0,2000,100,300)}</div>
      <div class="voice-setting-row"><label for="f-speaking-noise">降噪</label><select id="f-speaking-noise"><option value="off">关闭</option><option value="near_field">近距离麦克风</option><option value="far_field">远距离麦克风</option></select></div>
    </section>
    <section class="voice-section"><h2>字幕</h2><label class="voice-toggle"><input id="f-speaking-subtitles" type="checkbox">开启实时字幕</label>
      <div class="voice-setting-row" data-speaking-transcription hidden><label for="f-speaking-transcription">转写模型</label><input id="f-speaking-transcription" type="text" list="speaking-models" maxlength="256" placeholder="选择或填写转写模型"></div>
    </section>
    <section class="voice-section"><h2>出题与反馈</h2>
      <div class="voice-setting-row"><label for="f-speaking-authoring">出题模型</label><select id="f-speaking-authoring"><option value="jine">跟随主模型</option><option value="voice_api">使用此 API</option></select></div>
      <div class="voice-setting-row" data-speaking-text-model hidden><label for="f-speaking-card-model">文字模型</label><input id="f-speaking-card-model" type="text" list="speaking-models" maxlength="256"></div>
      <div class="voice-setting-row"><label for="f-speaking-grading">原音反馈模型</label><input id="f-speaking-grading" type="text" list="speaking-models" maxlength="256"></div>
      <div class="voice-setting-row"><label for="f-speaking-tts-model">跟读示范模型</label><input id="f-speaking-tts-model" type="text" list="speaking-models" maxlength="256"></div>
      <div class="voice-setting-row" data-speaking-plain><label for="f-speaking-tts-voice">示范音色</label><input id="f-speaking-tts-voice" type="text" maxlength="100"></div>
    </section>
    <div class="voice-form-actions"><button class="voice-save" type="submit" disabled>保存口语设置</button></div><p data-speaking-feedback role="status"></p>
  </form>`;

  async function request(base, resource, body, method='PUT') {
    const response = await fetch(`/api/${base}/${resource}`, body === undefined ? {cache:'no-store'} : {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result = await response.json().catch(()=>({}));   // 服务没起来时网关回的是 HTML，不是 JSON
    if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:typeof result.error==='string'?result.error:'没连上，再试一次');
    return result;
  }
  function wire(root) {
    const field = id => root.querySelector('#'+id), synth=field('settings-listening-synthesis'), speaking=field('settings-speaking-service');
    const feedback=synth.querySelector('[data-synthesis-feedback]'), speakingFeedback=speaking.querySelector('[data-speaking-feedback]');
    const synthSave=synth.querySelector('[type=submit]'), speakingSave=speaking.querySelector('[type=submit]');
    let synthState, speakingState, connectionState, loadingSynthesis=false, loadingSpeaking=false, previewing=false, audioURL;
    let voicevoxStyles = [];
    const number = id => field(id).valueAsNumber;
    function ranges(scope) { for(const input of scope.querySelectorAll('input[type=range]')) {
      if(input.dataset.rangeBound)continue;input.dataset.rangeBound='true';
      const output=scope.querySelector(`output[for="${input.id}"]`);
      const paint=()=>{output.value=input.id.endsWith('volume')?Math.round(input.valueAsNumber*100)+'%':/pause|silence|prefix/.test(input.id)?input.value+' ms':/threshold/.test(input.id)?input.value:input.value+'×';};
      input.addEventListener('input',paint); paint();
    } }
    function paintRanges(scope){for(const input of scope.querySelectorAll('input[type=range]'))input.dispatchEvent(new Event('input'));}
    ranges(synth); ranges(speaking);
    function showSynth(){
      const provider=field('f-synthesis-provider').value;
      for(const panel of synth.querySelectorAll('[data-synthesis-panel]')){
        const japanese = panel.querySelector('[data-voice-language="ja"]');
        const voicevox = panel.dataset.synthesisPanel === 'voicevox';
        panel.hidden = voicevox ? !synthState?.voicevox_available : panel.dataset.synthesisPanel !== provider;
        if (japanese) japanese.hidden = !voicevox && Boolean(synthState?.voicevox_available);
        panel.querySelectorAll('input,select,button').forEach(el=>{el.disabled=panel.hidden||Boolean(el.closest('[data-voice-language]')?.hidden)||(previewing&&el.matches('[data-voice-preview]'));});
      }
    }
    function writeVoices(provider,language,value,installed=[]){
      const prefix=voicePrefix(provider,language);
      for(const speaker of ['a','b']){
        const input=field(prefix+'-'+speaker);
        if(provider==='kokoro')input.replaceChildren(...[...new Set([value[speaker],...installed])].filter(Boolean).map(id=>new Option(id.replace(/^[a-z]{2}_/,'').replaceAll('_',' '),id)));
        if (provider === 'voicevox') {
          input.replaceChildren(...voicevoxStyles.map(({id, label}) => new Option(label, id)));
          if (!voicevoxStyles.some(style => style.id === value[speaker])) input.add(new Option('', value[speaker]));
        }
        input.value=value[speaker];
      }
      field(prefix+'-speed-a').value=value.speed;
      field(prefix+'-speed-b').value=value.speed_b??value.speed;
    }
    function readVoices(provider,language){const p=voicePrefix(provider,language);return {a:field(p+'-a').value,b:field(p+'-b').value,speed:number(p+'-speed-a'),speed_b:number(p+'-speed-b')};}
    function renderSynthesis(result){
      synthState=result;field('f-synthesis-provider').value=result.provider;
      field('f-synthesis-url').value=result.base_url;field('f-synthesis-model').value=result.model;
      field('f-synthesis-vendor').value=result.base_url.startsWith('https://api.openai.com/')?'openai':'compatible';
      field('f-synthesis-key').value='';field('f-synthesis-key').placeholder=result.api_key_configured?'已存':'未设置';field('f-synthesis-clear-key').checked=false;
      for(const [language]of languages){writeVoices('kokoro',language,result['kokoro_'+language],result.kokoro_voices[language]);writeVoices('api',language,result['api_'+language]);}
      if (result.voicevox_available) writeVoices('voicevox', 'ja', result.voicevox_ja);
      const extra=synth.querySelector('[data-extra-voices]');extra.replaceChildren();
      for(const {tag,label}of global.LP.languages?.list()||[]){if(['en','ja'].includes(tag))continue;const wrap=document.createElement('div');wrap.innerHTML=voiceFields('api',tag,label);extra.append(wrap);writeVoices('api',tag,result.api_languages?.[tag]||{a:'',b:'',speed:1});}
      field('f-synthesis-pause').value=result.pause_ms??300;field('f-synthesis-volume').value=result.volume??1;
      field('f-synthesis-provider').disabled=false;synthSave.disabled=false;showSynth();ranges(synth);paintRanges(synth);
    }
    async function loadListening(force=false){
      if((synthState&&!force)||loadingSynthesis)return;loadingSynthesis=true;
      try {
        const result = await request('listening', 'synthesis');
        let message = '';
        if (result.voicevox_available && !voicevoxStyles.length) {
          try {
            const speakers = await request('voice', 'voicevox/speakers');
            voicevoxStyles = speakers.flatMap(speaker => speaker.styles.map(style => ({id: style.id, label: `${speaker.name} · ${style.name}`})));
          } catch { message = '合成失败'; }
        }
        renderSynthesis(result);
        feedback.textContent = message;
      } catch(error){feedback.textContent=fail(error);}finally{loadingSynthesis=false;}
    }
    function synthesisBody(){
      const data={...synthState,provider:field('f-synthesis-provider').value,pause_ms:number('f-synthesis-pause'),volume:number('f-synthesis-volume')};
      for(const key of ['api_key_configured','synthesis','kokoro_voices','voicevox_available'])delete data[key];
      const local=data.provider==='kokoro';
      for(const [lang]of languages){
        if (lang === 'ja' && synthState.voicevox_available) continue;
        data[(local?'kokoro_':'api_')+lang]=readVoices(local?'kokoro':'api',lang);
      }
      if (synthState.voicevox_available) {
        const voice = readVoices('voicevox', 'ja');
        data.voicevox_ja = {...voice, a: Number(voice.a), b: Number(voice.b)};
      }
      if(!local){data.base_url=field('f-synthesis-url').value.trim();data.model=field('f-synthesis-model').value.trim();data.api_languages={...data.api_languages};
        for(const wrap of synth.querySelectorAll('[data-extra-voices] [data-voice-language]')){const lang=wrap.dataset.voiceLanguage,value=readVoices('api',lang);if(!value.a&&!value.b)delete data.api_languages[lang];else data.api_languages[lang]=value;}
        if(field('f-synthesis-key').value.trim())data.api_key=field('f-synthesis-key').value.trim();else if(field('f-synthesis-clear-key').checked)data.api_key='';
      }
      return data;
    }
    async function saveSynthesis(){
      if(!synthState)return false;synthSave.disabled=true;feedback.textContent='';
      try{renderSynthesis(await request('listening','synthesis',synthesisBody()));feedback.textContent='已保存';synth.dispatchEvent(new Event('lp:form-saved',{bubbles:true}));global.dispatchEvent(new CustomEvent('lp:listening-settings',{detail:{origin:synth}}));return true;}
      catch(error){feedback.textContent=fail(error);return false;}finally{synthSave.disabled=false;}
    }
    synth.addEventListener('submit',event=>{event.preventDefault();void saveSynthesis();});
    field('f-synthesis-provider').onchange=showSynth;
    field('f-synthesis-vendor').onchange=()=>{if(field('f-synthesis-vendor').value==='openai')field('f-synthesis-url').value='https://api.openai.com/v1';};
    field('synthesis-read-models').onclick=async()=>{
      const connection={base_url:field('f-synthesis-url').value.trim()};
      if(field('f-synthesis-key').value.trim())connection.api_key=field('f-synthesis-key').value.trim();else if(field('f-synthesis-clear-key').checked)connection.api_key='';
      feedback.textContent='';
      try{const result=await request('voice-settings','listening/models',connection,'POST');field('synthesis-models').replaceChildren(...result.models.map(item=>new Option(item.label,item.id)));global.LP.util.tick(field('synthesis-read-models'),true);}catch(error){feedback.textContent=fail(error);}
    };
    synth.addEventListener('click',async event=>{
      const button=event.target.closest('[data-voice-preview]');if(!button||button.disabled||previewing)return;
      previewing=true;synth.querySelectorAll('[data-voice-preview]').forEach(item=>{item.disabled=true;});
      try{
        if(!await saveSynthesis())return;feedback.textContent='';
        const response=await fetch('/api/voice-settings/listening/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({language:button.dataset.voicePreview,speaker:button.dataset.speaker,text:field('f-voice-sample').value.trim()})});
        if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(typeof data.detail==='string'?data.detail:'试听不了');}
        const audio=synth.querySelector('[data-voice-audio]');if(audioURL)URL.revokeObjectURL(audioURL);audioURL=URL.createObjectURL(await response.blob());audio.src=audioURL;audio.hidden=false;await audio.play().catch(()=>{});feedback.textContent='';
      }catch(error){feedback.textContent=fail(error);}finally{previewing=false;showSynth();}
    });

    function showSpeaking(){
      const vad=field('f-speaking-vad').value;
      speaking.querySelectorAll('[data-speaking-vad]').forEach(panel=>{panel.hidden=panel.dataset.speakingVad!==vad;});
      speaking.querySelector('[data-speaking-transcription]').hidden=!field('f-speaking-subtitles').checked;
      speaking.querySelector('[data-speaking-text-model]').hidden=field('f-speaking-authoring').value==='jine';
      // 音色预设：选的不是「标准」时，自选声音不生效，收起
      const preset=speaking.querySelector('input[name="speaking-preset"]:checked')?.value;
      const hasPreset=!speaking.querySelector('[data-speaking-preset-row]').hidden;
      speaking.querySelectorAll('[data-speaking-plain]').forEach(row=>{row.hidden=hasPreset&&Boolean(preset)&&preset!=='plain';});
    }
    let voicePresets=null;
    function renderSpeaking(settings,connection,presets=voicePresets){
      speakingState=settings;connectionState=connection;voicePresets=Array.isArray(presets)&&presets.length?presets:null;
      field('speaking-read-models').disabled=!connectionState;
      field('f-speaking-provider').value=connection.provider;field('f-speaking-base').value=connection.baseUrl;
      field('f-speaking-key').value='';field('f-speaking-key').placeholder=connection.keyConfigured?'已存':'未设置';field('f-speaking-clear-key').checked=false;
      field('f-speaking-model').value=settings.models.realtime;field('f-speaking-grading').value=settings.models.grading;
      field('f-speaking-card-model').value=settings.models.lessonCard;field('f-speaking-tts-model').value=settings.models.tts;
      field('f-speaking-voice').value=settings.voice;field('f-speaking-tts-voice').value=settings.ttsVoice;
      field('speaking-voices').replaceChildren(...settings.voices.map(id=>new Option(id,id)));
      // 预设清单由口语课服务给（顺序照给的画）；没给就整行隐藏
      const presetRow=speaking.querySelector('[data-speaking-preset-row]');presetRow.hidden=!voicePresets;
      speaking.querySelector('.voice-preset').replaceChildren(...(voicePresets||[]).map(p=>{const label=document.createElement('label');const input=document.createElement('input');input.type='radio';input.name='speaking-preset';input.value=p.id;input.checked=p.id===(settings.voicePreset||voicePresets[0].id);input.onchange=showSpeaking;label.append(input,document.createTextNode(p.label||p.id));return label;}));
      const realtime=connection.realtime;
      for(const [id,key]of [['speed','speed'],['vad','vad'],['eagerness','eagerness'],['threshold','threshold'],['silence','silenceMs'],['prefix','prefixMs'],['noise','noiseReduction']])field('f-speaking-'+id).value=realtime[key];
      field('f-speaking-interrupt').checked=realtime.interrupt;field('f-speaking-tokens').value=realtime.maxOutputTokens??'';
      field('f-speaking-transcription').value=realtime.transcriptionModel;field('f-speaking-subtitles').checked=!!realtime.transcriptionModel;
      field('f-speaking-authoring').value=connection.textProvider;speakingSave.disabled=false;paintRanges(speaking);showSpeaking();
    }
    async function loadSpeaking(force=false){
      if((speakingState&&!force)||loadingSpeaking)return;loadingSpeaking=true;field('speaking-read-models').disabled=true;
      try{const [result,connection]=await Promise.all([request('speaking','settings'),request('speaking','connection')]);renderSpeaking(result.settings,connection,result.voicePresets);speakingFeedback.textContent='';}
      catch(error){speakingState=null;connectionState=null;speakingSave.disabled=true;field('speaking-read-models').disabled=true;speakingFeedback.textContent=fail(error);}finally{loadingSpeaking=false;}
    }
    function speakingBody(){
      const settings=structuredClone(speakingState);
      settings.models={realtime:field('f-speaking-model').value.trim(),grading:field('f-speaking-grading').value.trim(),lessonCard:field('f-speaking-card-model').value.trim(),tts:field('f-speaking-tts-model').value.trim()};
      settings.voice=field('f-speaking-voice').value.trim();settings.ttsVoice=field('f-speaking-tts-voice').value.trim();
      if(voicePresets){const picked=speaking.querySelector('input[name="speaking-preset"]:checked')?.value;if(picked)settings.voicePreset=picked;}
      const transcribe=field('f-speaking-subtitles').checked?field('f-speaking-transcription').value.trim():'';
      if(field('f-speaking-subtitles').checked&&!transcribe)throw new Error('选一个字幕模型');
      const connection={provider:field('f-speaking-provider').value,baseUrl:field('f-speaking-base').value.trim(),textProvider:field('f-speaking-authoring').value,
        realtime:{vad:field('f-speaking-vad').value,eagerness:field('f-speaking-eagerness').value,threshold:number('f-speaking-threshold'),silenceMs:number('f-speaking-silence'),prefixMs:number('f-speaking-prefix'),interrupt:field('f-speaking-interrupt').checked,speed:number('f-speaking-speed'),noiseReduction:field('f-speaking-noise').value,transcriptionModel:transcribe,maxOutputTokens:field('f-speaking-tokens').value?number('f-speaking-tokens'):null},clearKey:field('f-speaking-clear-key').checked};
      if(field('f-speaking-key').value.trim())connection.apiKey=field('f-speaking-key').value.trim();return {settings,connection};
    }
    async function saveSpeaking(){
      if(!speakingState||!connectionState)return false;speakingSave.disabled=true;speakingFeedback.textContent='';
      try{const result=await request('speaking','setup',speakingBody());renderSpeaking(result.settings,result.connection,result.voicePresets||voicePresets);speakingFeedback.textContent='已保存';global.dispatchEvent(new CustomEvent('lp:coach-settings',{detail:{origin:speaking}}));return true;}
      catch(error){speakingFeedback.textContent=fail(error);return false;}finally{speakingSave.disabled=false;}
    }
    speaking.addEventListener('submit',event=>{event.preventDefault();void saveSpeaking();});
    field('f-speaking-vad').onchange=showSpeaking;field('f-speaking-subtitles').onchange=showSpeaking;field('f-speaking-authoring').onchange=showSpeaking;
    field('f-speaking-provider').onchange=()=>{if(field('f-speaking-provider').value==='openai')field('f-speaking-base').value='https://api.openai.com/v1';};
    field('speaking-read-models').onclick=async()=>{
      if(!connectionState)return;
      const connection={provider:field('f-speaking-provider').value,baseUrl:field('f-speaking-base').value.trim(),textProvider:connectionState.textProvider,realtime:connectionState.realtime,clearKey:field('f-speaking-clear-key').checked};
      if(field('f-speaking-key').value.trim())connection.apiKey=field('f-speaking-key').value.trim();
      speakingFeedback.textContent='';
      try{const result=await request('speaking','models',connection,'POST');field('speaking-models').replaceChildren(...result.data.map(item=>new Option(item.id,item.id)));global.LP.util.tick(field('speaking-read-models'),true);}catch(error){speakingFeedback.textContent=fail(error);}
    };
    global.addEventListener('lp:listening-settings',event=>{if(event.detail?.origin!==synth&&synthState&&!synthSave.disabled)void loadListening(true);});
    global.addEventListener('lp:coach-settings',event=>{if(event.detail?.origin!==speaking&&speakingState&&!speakingSave.disabled)void loadSpeaking(true);});
    return {loadListening,loadSpeaking};
  }
  global.LP ||= {}; global.LP.settingsProviders={listeningMarkup,speakingMarkup,wire};
})(window);
