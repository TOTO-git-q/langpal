(function (global) {
  'use strict';

  const STARTING = '声音引擎启动中……';
  const FAILED = '合成失败';
  const MISSING = '没有找到 VOICEVOX';
  const samples = { ja: 'ねえ……試験、もうすぐなんだって？', en: 'Hey… I heard your exam is coming up?' };
  const sliders = {
    ja: [
      ['speedScale', '语速', 0.5, 2], ['pitchScale', '音高', -0.15, 0.15],
      ['intonationScale', '抑扬', 0, 2], ['volumeScale', '音量', 0, 2], ['pauseLengthScale', '停顿', 0, 2],
      ['prePhonemeLength', '开头留白', 0, 1], ['postPhonemeLength', '结尾留白', 0, 1],
    ],
    en: [
      ['rate', '语速', 0.6, 1.8], ['pitch', '音高', -12, 12], ['breath', '气声', -40, 0],
      ['nasal', '鼻音', 0, 6], ['close', '闭口', 0, 4],
    ],
  };
  const recommendedStyle = /ささやき|ヒソヒソ|なみだめ|かなしい|おどおど|絶望|人見知り|ヘロヘロ|へろへろ|ツンツン|内緒話|囁き|あまあま|甘々|哀しみ|呆れ|泣き|低血圧|けだるげ|よわよわ|こわがり|恐怖/;
  const recommendedSpeakers = new Set(['冥鳴ひまり', '雨晴はう', '小夜/SAYO', '春日部つむぎ', 'ぞん子', '夜語トバリ', 'ユーレイちゃん', 'あんこもん', 'ナースロボ＿タイプＴ']);
  const excludedSpeakers = new Set(['玄野武宏', '白上虎太郎', '青山龍星', '剣崎雌雄', 'ちび式じい', '†聖騎士 紅桜†', '雀松朱司', '麒ヶ島宗麟', '離途', '黒沢冴白']);

  const markup = `<div class="voice-settings">
    <div class="seg character-voice-tabs">
      <button type="button" class="seg-opt" data-character-voice-tab="ja" aria-pressed="true">日本語</button>
      <button type="button" class="seg-opt" data-character-voice-tab="en" aria-pressed="false">English</button>
    </div>
    <div class="voice-channel-grid">
      <div class="character-voice-list" data-character-voice-list></div>
      <div>
        <h2 data-character-voice-name></h2>
        <p class="settings-note" data-character-voice-credit hidden></p>
        <div data-character-voice-sliders></div>
        <div class="field"><textarea aria-label="试听" maxlength="480" data-character-voice-text></textarea></div>
        <div class="voice-form-actions">
          <button type="button" class="voice-preview" data-character-voice-preview disabled>▶ 试听</button>
          <button type="button" class="voice-save" data-character-voice-save disabled>保存</button>
          <button type="button" data-character-voice-reset disabled>恢复默认</button>
        </div>
        <p data-character-voice-status role="status"></p>
      </div>
    </div>
  </div>`;

  async function request(path, init) {
    const response = await fetch('/api/' + path, {cache: 'no-store', ...init});
    if (!response.ok) throw new Error(response.status === 503 ? MISSING : FAILED);
    return response;
  }

  function json(method, body) {
    return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  }

  function wire(root) {
    const find = name => root.querySelector(`[data-character-voice-${name}]`);
    const list = find('list'), name = find('name'), credit = find('credit'), controls = find('sliders');
    const sample = find('text'), preview = find('preview'), save = find('save'), reset = find('reset'), status = find('status');
    const tabs = [...root.querySelectorAll('[data-character-voice-tab]')];
    const audio = new Audio();
    const catalogs = {}, loadingVoices = {}, notices = {};
    const texts = {...samples};
    let language = 'ja', saved, defaults, draft, voicevox, loading, saving, audition, audioURL;

    function stopAudio() {
      audio.pause();
      if (audioURL) URL.revokeObjectURL(audioURL);
      audioURL = undefined;
    }
    audio.addEventListener('ended', stopAudio);

    function paint() {
      const voice = draft?.[language];
      const japanese = language === 'ja';
      const missing = japanese && voicevox && !voicevox.available;
      const busy = Boolean(audition || (japanese && loadingVoices.ja && !voicevox?.running));
      name.textContent = !voice ? '' : japanese ? `${voice.speaker} · ${voice.style_name}` : voice.base;
      credit.hidden = !japanese || !voice;
      credit.textContent = japanese && voice ? `VOICEVOX:${voice.speaker}` : '';
      preview.disabled = !voice || Boolean(missing) || busy;
      preview.setAttribute('aria-busy', String(busy));
      save.disabled = !voice || Boolean(saving);
      reset.disabled = !voice || saving === language;
      status.textContent = japanese && loadingVoices.ja && !voicevox?.running ? STARTING : (notices[language] || (missing ? MISSING : ''));
      for (const button of list.querySelectorAll('[data-style]')) {
        const active = button.dataset.style === String(japanese ? voice?.style : voice?.base);
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
        button.disabled = !voice || saving === language;
      }
      for (const input of controls.querySelectorAll('input')) {
        input.disabled = !voice || saving === language;
        if (!voice) continue;
        input.value = (japanese ? voice.params : voice)[input.dataset.param];
        input.nextElementSibling.value = Number(input.value).toFixed(2);
      }
    }

    function choice(label, id, select) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'seg-opt';
      button.dataset.style = id;
      button.textContent = label;
      button.addEventListener('click', () => {
        select();
        notices[language] = '';
        paint();
      });
      return button;
    }

    function group(label) {
      const section = document.createElement('section');
      section.className = 'voice-section';
      const heading = document.createElement('h2');
      heading.textContent = label;
      section.append(heading);
      list.append(section);
      return section;
    }

    function paintList() {
      list.replaceChildren();
      const voices = catalogs[language] || [];
      if (language === 'ja') {
        for (const [label, recommended] of [['推荐', true], ['全部', false]]) {
          const section = group(label);
          for (const speaker of voices) {
            if (recommended && excludedSpeakers.has(speaker.name)) continue;
            const styles = recommended && !recommendedSpeakers.has(speaker.name)
              ? speaker.styles.filter(style => recommendedStyle.test(style.name)) : speaker.styles;
            if (!styles.length) continue;
            const heading = document.createElement('h3');
            heading.textContent = speaker.name;
            const buttons = document.createElement('div');
            buttons.className = 'settings-choices';
            for (const style of styles) {
              buttons.append(choice(style.name, style.id, () => {
                Object.assign(draft.ja, {style: style.id, speaker: speaker.name, style_name: style.name});
              }));
            }
            section.append(heading, buttons);
          }
        }
      } else {
        for (const [label, gender] of [['女声', 'f'], ['男声', 'm']]) {
          const section = group(label);
          const buttons = document.createElement('div');
          buttons.className = 'settings-choices';
          for (const base of voices.filter(id => id[1] === gender)) {
            buttons.append(choice(base, base, () => { draft.en.base = base; }));
          }
          section.append(buttons);
        }
      }
      paint();
    }

    async function loadVoices(lang) {
      if (catalogs[lang]) return true;
      if (loadingVoices[lang]) return loadingVoices[lang];
      if (!saved || (lang === 'ja' && !voicevox.available)) return false;
      const japanese = lang === 'ja';
      loadingVoices[lang] = (async () => {
        try {
          const response = await request(japanese ? 'voice/voicevox/speakers' : 'listening/synthesis');
          const result = await response.json();
          catalogs[lang] = japanese ? result : [...new Set([saved.en.base, ...result.kokoro_voices.en])].sort();
          if (japanese) voicevox.running = true;
          if (notices[lang] === FAILED) notices[lang] = '';
          return true;
        } catch {
          notices[lang] = FAILED;
          return false;
        } finally {
          delete loadingVoices[lang];
          if (lang === language) paintList();
        }
      })();
      paint();
      return loadingVoices[lang];
    }

    function show(lang) {
      audition?.abort();
      stopAudio();
      language = lang;
      for (const tab of tabs) {
        const active = tab.dataset.characterVoiceTab === lang;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-pressed', String(active));
      }
      sample.value = texts[lang];
      controls.innerHTML = sliders[lang].map(([key, label, min, max]) =>
        `<label class="voice-slider"><span>${label}</span><input id="character-voice-${key}" type="range" min="${min}" max="${max}" step="0.01" data-param="${key}"><output for="character-voice-${key}"></output></label>`).join('');
      list.scrollTop = 0;
      paintList();
      void loadVoices(lang);
    }
    tabs.forEach(tab => tab.addEventListener('click', () => {
      if (tab.dataset.characterVoiceTab !== language) show(tab.dataset.characterVoiceTab);
    }));
    sample.addEventListener('input', () => { texts[language] = sample.value; });
    controls.addEventListener('input', event => {
      const {param} = event.target.dataset;
      if (!param || !draft) return;
      const params = language === 'ja' ? draft.ja.params : draft.en;
      params[param] = event.target.valueAsNumber;
      notices[language] = '';
      paint();
    });
    reset.addEventListener('click', () => {
      draft[language] = structuredClone(defaults[language]);
      notices[language] = '';
      paint();
    });
    save.addEventListener('click', async () => {
      const lang = language;
      saving = lang;
      notices[lang] = '';
      paint();
      try {
        const result = await (await request('voice/character', json('PUT', {...saved, [lang]: draft[lang]}))).json();
        saved = result.saved;
        draft[lang] = structuredClone(saved[lang]);
        notices[lang] = '已保存';
      } catch { notices[lang] = FAILED; }
      finally { saving = undefined; paint(); }
    });
    preview.addEventListener('click', async () => {
      const lang = language;
      const body = json('POST', {language: lang, text: sample.value, voice: draft[lang]});
      const controller = new AbortController();
      audition = controller;
      stopAudio();
      notices[lang] = '';
      paint();
      try {
        if (lang === 'ja' && !await loadVoices(lang)) throw new Error(FAILED);
        const response = await request('voice/preview', {...body, signal: controller.signal});
        const wav = await response.blob();
        if (controller.signal.aborted || language !== lang) return;
        audioURL = URL.createObjectURL(wav);
        audio.src = audioURL;
        global.LP.stage?.voice?.(audio);
        await audio.play();
      } catch (error) {
        stopAudio();
        if (!controller.signal.aborted) notices[lang] = lang === 'ja' && error.message === MISSING ? MISSING : FAILED;
      } finally {
        audition = undefined;
        paint();
      }
    });

    show('ja');
    return {
      async refresh() {
        if (saved || loading) {
          void loadVoices(language);
          return;
        }
        loading = true;
        try {
          const result = await (await request('voice/character')).json();
          ({saved, defaults, voicevox} = result);
          draft = structuredClone(saved);
          notices.ja = notices.en = '';
          paint();
          void loadVoices(language);
        } catch { notices[language] = FAILED; paint(); }
        finally { loading = false; }
      },
      isDirty: () => Boolean(draft && JSON.stringify(draft) !== JSON.stringify(saved)),
      discard() {
        if (!saved) return;
        draft = structuredClone(saved);
        paint();
      },
      stop() {
        audition?.abort();
        stopAudio();
      },
    };
  }

  global.LP ||= {};
  global.LP.settingsVoice = {markup, wire};
})(window);
