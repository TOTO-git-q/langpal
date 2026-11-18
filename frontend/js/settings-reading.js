/* settings-reading.js — 设置 › 阅读：排版、来源（settings-sources.js：可以自己加 RSS / JSON 接口）、自定义题型、默认安排、Zotero。 */
(function (global) {
  'use strict';
  const rootPath = '/api/reader';
  const localeList = () => global.LP?.languages?.list() || [{ tag: 'en', label: '英语' }, { tag: 'ja', label: '日语' }];
  const langLabel = tag => localeList().find(item => item.tag === tag)?.label || tag;
  const formatTemplate = `
    <dialog class="reading-settings-editor" aria-labelledby="reader-format-heading">
    <form class="reading-settings-form" data-reader-form="format">
      <h4 id="reader-format-heading" data-rs="format-heading">新建题型</h4>
      <div class="reading-settings-grid">
        <label>名称<input name="name" required maxlength="60" placeholder="例如：文献速读"></label>
        <label>语言<select name="language"><option value="en">英语</option><option value="ja">日语</option></select></label>
        <label>最短<input type="number" name="min_length" required min="1" max="3200"></label>
        <label>最长<input type="number" name="max_length" required min="1" max="3200"></label>
        <label>目标篇幅<input type="number" name="target_length" required min="1" max="3200"></label>
        <label>每组题数<input type="number" name="question_count" required min="1" max="8" value="4"></label>
        <label class="reading-settings-wide">出题重点<textarea name="skills" required minlength="5" maxlength="600" rows="3" placeholder="比如：多考推断和作者态度"></textarea></label>
      </div>
      <output data-rs="format-unit" class="reading-format-unit"></output>
      <div class="reading-settings-actions"><button type="submit">保存题型</button><button type="button" data-rs="cancel-format">取消</button>
        <button type="button" class="reading-settings-agent" data-rs="format-agent">问管家</button></div>
      <p role="status" data-rs="format-notice"></p>
    </form></dialog>`;

  const template = `
    <div class="reading-settings">
      <section class="reading-style-settings">
        <div class="reading-settings-heading"><h2>排版</h2><button type="button" class="reading-settings-agent" data-rs="style-agent">问管家</button></div>
        <form class="reading-settings-form" data-reader-form="style">
          <div class="reading-style-desk">
            <div class="reading-style-preview"><div class="reading-preview-page"><span class="reading-preview-mark">JINE</span><h3>雨上がりの本屋</h3><p>雨が上がると、店先には小さな本棚が戻ってきた。今日は、どんな物語に出会えるだろう。</p><p>When the rain stopped, the bookshop brought its shelf back outside. There was always another story waiting.</p></div></div>
            <div class="reading-style-fields">
              <label>字号<span><input name="size" type="range" min="14" max="26" step="1" required><output data-style-value="size"></output></span></label>
              <label>行距<span><input name="line_height" type="range" min="1.35" max="2.25" step=".05" required><output data-style-value="line_height"></output></span></label>
              <label>行宽<span><input name="measure" type="range" min="44" max="90" step="1" required><output data-style-value="measure"></output></span></label>
              <label>字体<select name="font"><option value="serif">书页</option><option value="sans">简洁</option></select></label>
              <label>底色<select name="theme"><option value="lilac">淡紫</option><option value="paper">暖纸</option><option value="night">夜读</option></select></label>
              <div class="reading-settings-actions"><button type="submit">保存排版</button><button type="button" data-rs="style-reset">重置</button></div>
            </div>
          </div>
          <p role="status" data-rs="style-notice"></p>
        </form>
      </section>
      <nav class="reading-settings-tabs" role="tablist" aria-label="阅读资料设置">
        <button type="button" role="tab" aria-selected="true" data-reading-tab="sources">来源 <span data-rs="sources-total"></span></button>
        <button type="button" role="tab" aria-selected="false" data-reading-tab="formats">题型 <span data-rs="formats-total"></span></button>
        <button type="button" role="tab" aria-selected="false" data-reading-tab="defaults">默认安排</button>
        <button type="button" role="tab" aria-selected="false" data-reading-tab="zotero">Zotero</button>
      </nav>
      <section class="reading-settings-section" role="tabpanel" data-reading-panel="sources">
        <div data-rs="sources"></div>
      </section>
      <section class="reading-settings-section" role="tabpanel" data-reading-panel="zotero" hidden>
        <div data-rs="zotero"></div>
      </section>
      <section class="reading-settings-section" role="tabpanel" data-reading-panel="formats" hidden>
        <div class="reading-settings-heading"><h3>题型</h3><button type="button" data-rs="add-format">＋ 自定义题型</button></div>
        <div class="reading-settings-list" data-rs="formats"></div>${formatTemplate}
      </section>
      <section class="reading-settings-section" role="tabpanel" data-reading-panel="defaults" hidden>
        <form class="reading-settings-form" data-reader-form="defaults">
          <div class="reading-settings-grid">
            <label>论文来源<select name="paper"></select></label><label>英语来源<select name="article_en"></select></label>
            <label>日语来源<select name="article_ja"></select></label><label>英语题型<select name="format_en"></select></label>
            <label>日语题型<select name="format_ja"></select></label>
          </div><div class="reading-settings-grid" data-rs="more-defaults"></div>
          <div class="reading-settings-actions"><button type="submit">保存安排</button></div><p role="status" data-rs="defaults-notice"></p>
        </form>
      </section><p role="status" data-rs="notice"></p>
    </div>`;

  async function request(path, method = 'GET', payload) {
    const options = { method, cache: 'no-store' };
    if (payload !== undefined) {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(rootPath + path, options);
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.detail;
      const message = Array.isArray(detail) ? detail.map(item => item.msg?.replace(/^Value error, /, '')).filter(Boolean).join('。') : detail;
      throw new Error(message || body.message || '没连上，再试一次');
    }
    return body;
  }

  const element = (tag, label, css) => global.LP.util.el(tag, label, css);
  const button = (label, action) => global.LP.util.button(label, action);

  // 删除：和别处一样弹确认框（不再点两次）
  function confirmDelete(name, callback) {
    const control = button('删除', async () => {
      if (!await global.LP.util.confirm({ title: '删掉「' + name + '」？', ok: '删除' })) return;
      await callback(control);
    });
    control.className = 'reading-settings-delete';
    return control;
  }

  function mount(root) {
    if (!root || root.dataset.mounted) return;
    root.dataset.mounted = 'true';
    root.innerHTML = template;
    global.LP.readingPreferences?.wire(root.closest('#settings-reader') || root);
    for (const tab of root.querySelectorAll('[data-reading-tab]')) tab.onclick = () => {
      root.querySelectorAll('[data-reading-tab]').forEach(item=>item.setAttribute('aria-selected',String(item===tab)));
      root.querySelectorAll('[data-reading-panel]').forEach(panel=>{panel.hidden=panel.dataset.readingPanel!==tab.dataset.readingTab;});
    };
    root.querySelector('.reading-settings-tabs').onkeydown = event => {
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      const tabs=[...root.querySelectorAll('[data-reading-tab]')],index=tabs.indexOf(document.activeElement);
      if(index<0)return;event.preventDefault();
      const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
      tabs[next].click();tabs[next].focus();
    };
    const $ = key => root.querySelector('[data-rs="' + key + '"]');
    // 来源编辑和 Zotero 在 settings-sources.js；来源变了刷新默认安排里的下拉
    const sourceEditor = global.LP.settingsSources.mount($('sources'), { onChange: () => void changed() });
    global.LP.settingsSources.mountZotero($('zotero'));
    api.addSource = (opts) => {
      root.querySelector('[data-reading-tab="sources"]').click();
      sourceEditor.addSource(opts);
    };
    const form = name => root.querySelector('[data-reader-form="' + name + '"]');
    const formatForm = form('format'), defaultForm = form('defaults'), styleForm = form('style');
    const formatField = name => formatForm.elements.namedItem(name);
    const openEditor = form => { if (!form.parentElement.open) form.parentElement.showModal(); };
    const closeEditor = form => { if (form.parentElement.open) form.parentElement.close(); };
    const delegate = (text, editor) => {
      if (editor) closeEditor(editor);
      global.LP.appShell?.switchTab('workspace-agent');
      global.LP.workspaceAgent?.prefill(text);
    };
    let sources = [], options = { sources: [], formats: [], defaults: {} };
    let formatDraft, saving = false;
    const publish = () => global.dispatchEvent(new CustomEvent('lp:reading-settings', { detail: { origin: root } }));

    function notice(key, text) { $(key).textContent = text; }

    async function act(control, key, operation) {
      if (saving) return;
      saving = true;
      if (control) control.disabled = true;
      notice(key, '');
      try { notice(key, await operation()); }
      catch (error) { notice(key, global.LP.util.message(error)); }
      finally { if (control) control.disabled = false; saving = false; }
    }

    async function load() {
      const [sourceData, config] = await Promise.all([request('/sources'), request('/options')]);
      sources = sourceData.items || [];
      options = config;
      render();
    }

    async function changed() {
      await load();
      publish();
    }

    function row(title, description) {
      const wrapper = element('article', '', 'reading-settings-row');
      const text = element('div');
      text.append(element('strong', title), element('span', description, 'reading-settings-meta'));
      const actions = element('div', '', 'reading-settings-actions');
      wrapper.append(text, actions);
      return [wrapper, actions];
    }

    function renderSources() { notice('sources-total', sources.length); }

    function renderFormats() {
      const list = $('formats');
      list.replaceChildren();
      const items = options.formats || [];
      notice('formats-total', items.length);
      for (const item of items) {
        const detail = item.builtin ? '内置' : item.min_length + '–' + item.max_length + ' · ' + item.question_count + ' 题';
        const [wrapper, actions] = row(item.name, langLabel(item.language) + ' · ' + detail);
        if (!item.builtin) {
          actions.append(button('编辑', () => editFormat(item)), confirmDelete(item.name, control => act(control, 'notice', async () => {
            await request('/formats/' + encodeURIComponent(item.id), 'DELETE');
            if (formatDraft?.id === item.id) closeEditor(formatForm);
            await changed(); return '已删除';
          })));
        }
        list.append(wrapper);
      }
    }

    function fill(field, choices) {
      field.replaceChildren(...choices.map(([id, name]) => {
        const option = element('option', name); option.value = id; return option;
      }));
      field.value = options.defaults?.[field.name] || '';
    }

    function renderDefaults() {
      const choices = (kind, lang) => options.sources.filter(item => item.kind === kind && (!lang || !item.lang || item.lang === lang))
        .map(item => [item.id, item.name]);
      fill(defaultForm.elements.namedItem('paper'), [['', '自动'], ['all', '全部来源'], ...choices('paper')]);
      for (const lang of ['en', 'ja']) {
        fill(defaultForm.elements.namedItem('article_' + lang), [['', '自动'], ['all', '全部来源'], ...choices('article', lang)]);
        const formats = options.formats.filter(item => item.language === lang).map(item => [item.id, item.name]);
        fill(defaultForm.elements.namedItem('format_' + lang), [['', '自动'], ...formats]);
      }
      $('more-defaults').replaceChildren();
      for (const { tag, label } of localeList().filter(item => !['en', 'ja'].includes(item.tag))) {
        const formats = options.formats.filter(item => item.language === tag).map(item => [item.id, item.name]);
        for (const [type, name, values] of [['article', '来源', [['all', '全部来源'], ...choices('article', tag)]],
          ['format', '题型', formats]]) {
          const line = element('label', label + ' · ' + name), select = element('select');
          select.dataset.language = tag; select.dataset.defaultType = type;
          fill(select, [['', '自动'], ...values]);
          select.value = options.defaults?.[type + '_by_language']?.[tag] || '';
          line.append(select);
          $('more-defaults').append(line);
        }
      }
    }

    function renderLanguageFields() {
      const rows = localeList().map(({ tag, label }) => [tag, label]);
      const field = formatField('language');
      const current = field.value;
      fill(field, rows);
      field.value = rows.some(([tag]) => tag === current) ? current : rows[0][0];
    }

    function render() { renderLanguageFields(); renderSources(); renderFormats(); renderDefaults(); }

    function updateFormatUnit() {
      const lang = formatField('language').value.split('-')[0];
      const unit = ['ja', 'zh', 'th', 'lo', 'km', 'my'].includes(lang) ? '字符数' : '单词数';
      notice('format-unit', unit);
    }

    function editFormat(item) {
      formatDraft = item || null;
      const values = item || { name: '', language: 'en', min_length: 150, max_length: 250, target_length: 200, question_count: 4, skills: '' };
      for (const name of ['name', 'language', 'min_length', 'max_length', 'target_length', 'question_count', 'skills']) {
        formatField(name).value = values[name];
      }
      $('format-heading').textContent = item ? '编辑 ' + item.name : '新建题型';
      notice('format-notice', '');
      openEditor(formatForm);
      updateFormatUnit();
      formatField('name').focus();
    }

    $('add-format').addEventListener('click', () => editFormat());
    $('cancel-format').addEventListener('click', () => closeEditor(formatForm));
    $('format-agent').onclick = () => {
      const value = name => formatField(name).value.trim();
      const name = value('name'), lang = value('language');
      const spec = [value('min_length'), value('max_length'), value('target_length'), value('question_count')];
      const details = spec.every(Boolean) ? '篇幅 ' + spec[0] + '–' + spec[1] + '，目标 ' + spec[2] + '，每组 ' + spec[3] + ' 题。' : '';
      delegate((formatDraft ? '调整' : '新建') + ' ' + langLabel(lang) + ' 阅读题型'
        + (name ? '「' + name + '」' : '') + '。' + details + value('skills'), formatForm);
    };
    formatField('language').addEventListener('change', updateFormatUnit);
    formatForm.addEventListener('submit', event => {
      event.preventDefault();
      void act(event.submitter, 'format-notice', async () => {
        const payload = Object.fromEntries(['name', 'language', 'skills'].map(name => [name, formatField(name).value.trim()]));
        for (const name of ['min_length', 'max_length', 'target_length', 'question_count']) payload[name] = formatField(name).valueAsNumber;
        const existing = formatDraft?.id;
        await request('/formats' + (existing ? '/' + encodeURIComponent(existing) : ''), existing ? 'PUT' : 'POST', payload);
        closeEditor(formatForm);
        await changed(); notice('notice', '已保存');
        return '';
      });
    });
    defaultForm.addEventListener('submit', event => {
      event.preventDefault();
      void act(event.submitter, 'defaults-notice', async () => {
        const payload = Object.fromEntries(Array.from(new FormData(defaultForm), ([key, value]) => [key, value || null]));
        for (const type of ['article', 'format']) {
          payload[type + '_by_language'] = Object.fromEntries([...defaultForm.querySelectorAll('[data-default-type="' + type + '"]')]
            .filter(select => select.value).map(select => [select.dataset.language, select.value]));
        }
        await request('/options/defaults', 'PUT', payload);
        await changed(); return '已保存';
      });
    });
    const styles = global.LP?.readerStyle;
    let refreshStyle = () => {};
    if (styles) {
      let editRevision = 0;
      let dirty = false;
      const fields = ['size', 'line_height', 'measure', 'font', 'theme'];
      const currentStyle = () => Object.fromEntries(fields.map(key => {
        const control = styleForm.elements.namedItem(key);
        return [key, ['number','range'].includes(control.type) ? control.valueAsNumber : control.value];
      }));
      const preview = () => {
        const value = currentStyle(), target = styleForm.querySelector('.reading-style-preview');
        styles.apply(target,value); target.style.setProperty('--reading-preview-width',(value.measure/90*100)+'%');
        for(const key of ['size','line_height','measure']) styleForm.querySelector('[data-style-value="'+key+'"]').value=value[key];
      };
      const show = style => {
        fields.forEach(key => { styleForm.elements.namedItem(key).value = style[key]; });
        preview();
      };
      show(styles.defaults);
      styleForm.addEventListener('input', () => { editRevision++; dirty = true; preview(); });
      $('style-reset').onclick = () => { editRevision++; dirty = true; show(styles.defaults); };
      $('style-agent').onclick = () => {
        const value = currentStyle();
        if (!dirty || !styleForm.checkValidity()) { delegate('帮我调整阅读排版。'); return; }
        delegate('把阅读排版改为字号 ' + value.size + '、行距 ' + value.line_height + '、正文宽度 ' + value.measure
          + '、' + (value.font === 'sans' ? '无衬线' : '衬线') + '、' + { lilac: '淡紫', paper: '暖纸', night: '夜读' }[value.theme] + '。');
      };
      styleForm.addEventListener('submit', event => {
        event.preventDefault();
        void act(event.submitter, 'style-notice', async () => {
          show(await styles.save(currentStyle()));
          dirty = false;
          publish();
          return '已保存排版';
        });
      });
      refreshStyle = () => {
        if (dirty) return;
        const revision = editRevision;
        void styles.get().then(value => {
          if (editRevision === revision) show(value);
        }).catch(error => notice('style-notice', global.LP.util.message(error)));
      };
      refreshStyle();
    }
    document.addEventListener('lp:languages', () => void load().catch(error => notice('notice', global.LP.util.message(error))));
    global.addEventListener('lp:reading-settings', event => {
      if (event.detail?.origin === root || saving) return;
      void load().catch(error => notice('notice', global.LP.util.message(error)));
      refreshStyle();
    });
    load().catch(error => notice('notice', global.LP.util.message(error)));
  }

  const api = { mount, addSource() {} };
  global.LP ||= {};
  global.LP.settingsReading = api;
})(window);
