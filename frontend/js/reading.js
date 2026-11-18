(function (global) {
  'use strict';

  const MAX_FILE = 35_000_000;
  const LENGTH_LIMITS = { en: [15, 1400, '词'], ja: [420, 3200, '字'] };
  const CHARACTER_LANGS = new Set(['ja', 'zh', 'th', 'lo', 'km', 'my']);
  const lengthLimits = lang => LENGTH_LIMITS[lang] || (CHARACTER_LANGS.has(lang.split('-')[0]) ? [40, 3200, '字'] : [15, 1400, '词']);
  const locales = () => window.LP?.languages?.list() || [{ tag: 'en', label: 'English' }, { tag: 'ja', label: '日本語' }];
  const $ = (root, selector) => root.querySelector(selector);
  const node = (tag, text, cls) => global.LP.util.el(tag, text, cls);
  const button = (text, click, cls) => global.LP.util.button(text, click, cls);
  const id = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  // Origin is independent of reading progress: imports never become history on reopen.
  const isReadingDocument = doc => doc.source !== 'workspace-agent';
  function libraryOrigin(doc) {
    if (['import', 'history'].includes(doc.libraryOrigin)) return doc.libraryOrigin;
    return doc.source === '本地文件' || ['用户粘贴正文', '用户粘贴全文'].includes(doc.scope) ? 'import' : 'history';
  }
  const normalize = value => value.replace(/\s+/g, ' ').trim();
  const sourceText = root => global.LP.furigana?.sourceText(root) ?? root.textContent;
  const rangeText = range => global.LP.furigana?.rangeText(range) ?? range.toString();
  function decodeText(bytes) {
    const lead = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
    if (lead[0] === 0xff && lead[1] === 0xfe) return new TextDecoder('utf-16le').decode(bytes);
    if (lead[0] === 0xfe && lead[1] === 0xff) return new TextDecoder('utf-16be').decode(bytes);
    try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
    catch { return new TextDecoder('shift_jis').decode(bytes); }
  }
  const pdfModule = () => import('./reading-pdf.mjs');
  const storage = () => {
    if (!global.LP?.studyStorage) throw new Error('没连上');
    return global.LP.studyStorage;
  };

  async function api(path, body, signal) {
    const response = await fetch('/api/reader' + path, body === undefined ? { signal } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : '没连上');
    }
    return response;
  }

  const json = async (path, body, signal) => (await api(path, body, signal)).json();

  function sentences(text, language) {
    return [...new Intl.Segmenter(language, { granularity: 'sentence' }).segment(text)]
      .map(part => part.segment.trim()).filter(Boolean);
  }

  function paginate(text) {
    const pages = [];
    let current = '';
    for (const paragraph of text.split(/\n\s*\n/)) {
      if (current && current.length + paragraph.length > 4900) { pages.push(current.trim()); current = ''; }
      for (let start = 0; start < paragraph.length; start += 4900) {
        if (start) { pages.push(current.trim()); current = ''; }
        current += paragraph.slice(start, start + 4900) + '\n\n';
      }
    }
    if (current.trim()) pages.push(current.trim());
    return pages.length ? pages : [''];
  }

  function safeLink(url, label) {
    if (!url || !/^https?:\/\//i.test(url)) return null;
    const anchor = node('a', label);
    anchor.href = url;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    return anchor;
  }

  function mount(root) {
    const isWindow = root.id === 'reading-root';
    const localReader = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
    const glyph = name => '<svg class="rd-glyph" viewBox="0 0 16 16" aria-hidden="true"><use href="#rd-glyph-' + name + '"/></svg>';
    root.innerHTML = `
      <div class="rd-workbench">
        <svg class="rd-glyphs" aria-hidden="true" width="0" height="0" xmlns="http://www.w3.org/2000/svg">
          <symbol id="rd-glyph-sheet" viewBox="0 0 16 16">
            <path d="M3 1h7v1h1v1h1v1h1v1h1v10H3z" fill="#fff8ff" stroke="#4d23cf"/>
            <path d="M10 1v4h4M5 8h7m-7 2h7m-7 2h4" fill="none" stroke="#4d23cf"/>
            <path d="M4 5h5v2H4z" fill="#f991d5"/>
          </symbol>
          <symbol id="rd-glyph-search" viewBox="0 0 16 16">
            <path d="M3 2h6l2 2v6l-2 2H3l-2-2V4z" fill="#9af3e8" stroke="#4d23cf"/>
            <path d="M4 4h3M3 5v2" fill="none" stroke="#fff"/>
            <path d="m10 10 4 4" stroke="#4d23cf" stroke-width="3"/>
            <path d="m10 10 4 4" stroke="#f292c1"/>
          </symbol>
          <symbol id="rd-glyph-shelf" viewBox="0 0 16 16">
            <path d="M1 3h4v10H1z" fill="#f6a7d3" stroke="#4d23cf"/>
            <path d="M5 2h4v11H5z" fill="#fff8ff" stroke="#4d23cf"/>
            <path d="m9 4 3-1 3 10h-4z" fill="#9af3e8" stroke="#4d23cf"/>
            <path d="M0 14h16" stroke="#4d23cf"/>
          </symbol>
          <symbol id="rd-glyph-folder" viewBox="0 0 16 16">
            <path d="M1 3h5l2 2h6v8H1z" fill="#ffe48b" stroke="#4d23cf"/>
            <path d="M2 7h13l-2 7H1z" fill="#fff1a1" stroke="#4d23cf"/>
            <path d="M3 9h9" stroke="#fff9d9"/>
          </symbol>
        </svg>
        <section class="rd-home rd-catalog" aria-labelledby="rd-page-title">
          <h1 id="rd-page-title" class="visually-hidden">阅读</h1>
          <div class="rd-selector workspace-tools">
            <nav class="rd-tabs" aria-label="阅读来源">
              <button type="button" data-view="news">${glyph('sheet')}文章</button>
              <button type="button" data-view="papers">${glyph('search')}找论文</button>
              <button type="button" data-view="library">${glyph('shelf')}书架</button>
            </nav>
            <div class="rd-selector-actions">
              <div class="rd-languages" role="group" aria-label="文章语言"></div>
              <button type="button" class="rd-open-file" data-rd="pick" aria-label="打开文件" title="打开文件">${glyph('folder')}<span>打开文件</span></button>
              <input type="file" data-rd="file" accept=".pdf,.txt,.md" hidden>
            </div>
          </div>
          <div class="rd-controls"></div>
          <div class="rd-results">
            <section class="rd-catalog-index" aria-label="材料列表">
              <details class="rd-filters" data-rd="filters">
              <summary data-rd="filter-summary">筛选</summary>
              <div class="rd-materials" data-rd="materials" hidden>
                <div class="rd-source-switch">
                  <label><span>来源</span> <select data-rd="news-source" aria-label="文章来源"></select></label>
                </div>
                <div class="rd-source-switch">
                  <label><span>出题格式</span> <select data-rd="news-format" aria-label="阅读出题格式"></select></label>
                </div>
              </div>
              <details class="rd-length" data-rd="length">
                <summary><span>文章长度</span><span data-rd="length-label"></span></summary>
                <form class="rd-length-form" data-rd="length-form">
                  <label>最短<input type="number" data-rd="min-length" required></label>
                  <span aria-hidden="true">–</span>
                  <label>最长<input type="number" data-rd="max-length" required></label>
                  <span data-rd="length-unit"></span>
                  <button type="submit" class="rd-primary">应用</button>
                  <button type="button" data-rd="length-clear">清除</button>
                </form>
                <div class="rd-length-presets" data-rd="length-presets"></div>
              </details>
              </details>
              <div class="rd-file-list"></div>
            </section>
            <section class="rd-preview-stage" aria-label="材料预览">
              <div class="rd-preview-content"></div>
            </section>
          </div>
          <footer class="rd-catalog-status">
            <p class="rd-status" role="status"></p>
          </footer>
        </section>
        <section class="rd-open" hidden>
          <header class="rd-toolbar workspace-tools">
            <button type="button" data-rd="back">← 返回</button>
            <div class="rd-doclabel"><strong></strong><div class="rd-origin"></div></div>
            <div class="rd-reader-actions">
              <button type="button" data-rd="furigana" aria-pressed="false" title="汉字注音" hidden>あ</button>
              <button type="button" data-rd="lookup" aria-pressed="false">点词／句</button>
              <button type="button" data-rd="annotate" hidden>批注选段</button>
              <button type="button" data-rd="exam-back" hidden>继续阅读</button>
              <details class="rd-more">
                <summary aria-label="更多阅读选项" title="更多阅读选项">⋯</summary>
                <div class="rd-more-items">
                  <button type="button" data-rd="ask" aria-expanded="false">问这篇</button>
                  <label>这篇是 <select data-rd="language" aria-label="这篇是哪种语言"></select></label>
                  <button type="button" data-rd="notes">批注</button>
                  <button type="button" data-rd="window">新窗口</button>
                  <button type="button" data-rd="share" hidden>共享给 AI</button>
                </div>
              </details>
            </div>
          </header>
          <p class="rd-storage-status" data-rd="storage-status" role="status"></p>
          <div class="rd-pager" hidden>
            <button type="button" data-rd="prev" aria-label="上一页">‹</button>
            <label>第 <input type="number" min="1" value="1" data-rd="page" aria-label="页码"> 页</label><span data-rd="count"></span>
            <button type="button" data-rd="next" aria-label="下一页">›</button>
          </div>
          <div class="rd-document">
            <article class="rd-body" tabindex="0" aria-label="阅读正文"></article>
            <aside class="rd-panel" aria-labelledby="rd-panel-title" hidden>
              <header class="rd-panel-head"><h2 id="rd-panel-title" tabindex="-1"></h2><button type="button" data-rd="close-side" aria-label="关闭阅读面板">×</button></header>
              <div class="rd-ask-view" data-rd="question-view" hidden>
                <div class="rd-ask-thread" data-rd="question-thread" aria-live="polite"></div>
                <form class="rd-question" data-rd="question-form">
                  <div class="rd-ask-selection" data-rd="question-selection" hidden>
                    <p data-rd="question-excerpt"></p>
                    <button type="button" data-rd="question-clear" aria-label="清除选段" title="清除选段">×</button>
                  </div>
                  <div class="rd-ask-compose">
                    <textarea data-rd="question-input" rows="2" maxlength="1200" required aria-label="阅读问题" placeholder="问一个关于原文的问题…"></textarea>
                    <button type="submit" data-rd="question-send" aria-label="发送问题" title="发送问题（Ctrl / ⌘ + Enter）" disabled>
                      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M8 13V3m-4 4 4-4 4 4"/></svg>
                    </button>
                  </div>
                </form>
              </div>
              <div class="rd-tool" data-rd="side-content"></div>
            </aside>
          </div>
          <dialog class="rd-sheet" data-rd="sheet" aria-labelledby="rd-sheet-title">
            <div class="rd-sheet-grab" aria-hidden="true"></div>
            <header class="rd-panel-head"><h2 id="rd-sheet-title"></h2><button type="button" data-rd="close-sheet" aria-label="关闭">×</button></header>
            <div class="rd-tool" data-rd="sheet-content"></div>
          </dialog>
        </section>
      </div>`;
    const home = $(root, '.rd-home'), reader = $(root, '.rd-open');
    const body = $(reader, '.rd-body'), side = $(reader, '.rd-panel'), more = $(reader, '.rd-more');
    const list = $(home, '.rd-file-list'), preview = $(home, '.rd-preview-content');
    const status = $(home, '.rd-status'), controls = $(home, '.rd-controls');
    const languages = $(home, '.rd-languages');
    const action = name => $(root, '[data-rd="' + name + '"]');
    function paintFilterSummary() {
      const pick = (name) => { const sel = action(name); return sel && !sel.closest('[hidden]') ? sel.selectedOptions?.[0]?.textContent?.trim() : ''; };
      const parts = [pick('news-source'), pick('news-format'), action('length-label')?.textContent?.trim() || '不限'].filter(Boolean);
      const label = action('filter-summary');
      if (label) label.textContent = parts.join(' · ') || '筛选';
    }
    root.addEventListener('change', (ev) => { if (ev.target.closest('[data-rd="filters"]')) setTimeout(paintFilterSummary); });
    new MutationObserver(paintFilterSummary).observe(root.querySelector('[data-rd="length-label"]'), { childList: true, characterData: true, subtree: true });
    setTimeout(paintFilterSummary, 0);
    const sheet = action('sheet');
    const unsavedNotes = new Set();
    function storageStatus(message, failed = false) {
      action('storage-status').textContent = message;
      action('storage-status').dataset.unsaved = String(failed);
    }
    async function persistDocument(doc) {
      if (doc === current) storageStatus('');
      try {
        await storage().saveDocument({ ...doc, libraryOrigin: libraryOrigin(doc), page: doc === current ? page : doc.page, openedAt: Date.now() });
        if (doc === current) storageStatus(unsavedNotes.size ? '批注没存上' : '', unsavedNotes.size > 0);
        return true;
      } catch (error) {
        if (doc === current) storageStatus('没存上', true);
        return false;
      }
    }
    global.addEventListener('lp:study-storage', event => {
      if (event.detail.state !== 'ready') {status.textContent = event.detail.message; storageStatus(event.detail.message, true);}
    });
    const ranges = {};
    const prefs = global.LP.preferences;
    let panel = action('side-content');
    let view = 'news', language = prefs?.get('readerLanguage') || 'en', source = 'all', search = '', shelf = 'import', zoteroSearch = '';
    let readerOptions = { sources: [], formats: [], defaults: {} };
    // 学习记录（docs/LEARNING.md 5.1）：文章用 URL 或书架编号认
    const docRef = doc => String(doc?.url || doc?.id || '').slice(0, 700);
    const learningCall = (path, body) => fetch('/api' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).catch(() => {});
    let questionsFirst = false;
    fetch('/api/learning/settings', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(v => { questionsFirst = Boolean(v?.reading_questions_first); }).catch(() => {});
    global.addEventListener('lp:learning-settings', event => { questionsFirst = Boolean(event.detail?.reading_questions_first); });
    const SKILL = { detail: '事实细节', inference: '推断', vocabulary: '词义', reference: '指代', insertion: '句子插入', summary: '主旨与总结', attitude: '作者态度',
      jlpt_content: '内容理解', jlpt_claim: '主张理解', jlpt_search: '信息检索', jlpt_integrated: '综合理解' };
    void window.LP.util.loadTypes?.();
    let optionsReady = false;
    const articleSources = { en: 'all', ja: 'all' };
    const formatIds = { en: prefs?.get('englishExam') || 'toefl', ja: 'jlpt' };
    const defaultFormat = lang => lang === 'en' ? prefs?.get('englishExam') || 'toefl' : lang === 'ja' ? 'jlpt' : 'general';
    let optionsRequest;
    let selectedKey;
    let listRequest, screenRequest, dataRevision = 0, pageRevision = 0, actionRevision = 0;
    let current, pdf, pdfTask, page = 1, textPages = [], currentText = '', rendered, picked = '', hover = '';
    let lookupSentence = '', noteAnchor = null;
    let tool = 'read', lookup = false, notes = [], box = null, drawing = false, answer = null, exercise = null;
    let choices = [], grade = null, submitting = false, translations = new Map(), warming = false;
    let translationTask = null;
    let sharing = null, shareNote = '';
    let pdfWidth = 0, resizeTimer, lookupTimer, examIndex = 0, readingOffset = 0, readingPage = 1;

    const languageDrawer = LP.languageDrawer.create({
      title: '阅读语言', selected: () => language,
      onSelect(tag) { language = tag; prefs?.set('readerLanguage', tag); showHome('news'); },
      onSource() { LP.settings.open('reader'); void LP.appShell.ready('settings').then(() => LP.settingsReading?.addSource({ lang: language, kind: 'article' })); },
      onImport() { action('file').click(); },
    });

    function indicate(selector, dataset, value) {
      root.querySelectorAll(selector).forEach(item => item.setAttribute('aria-pressed', item.dataset[dataset] === value));
    }

    function sourceRows(kind, lang) {
      return readerOptions.sources.filter(row => row.kind === kind && (!lang || !row.lang || row.lang === lang));
    }

    function formatRecord(lang, id = formatIds[lang]) {
      return readerOptions.formats.find(row => row.language === lang && row.id === id);
    }

    function selection(field, rows, value) {
      if (!field) return;
      field.replaceChildren(...rows.map(([id, label]) => {
        const option = node('option', label); option.value = id; return option;
      }));
      field.value = value;
    }

    function renderOptions() {
      const docLanguages = locales().map(({ tag, label }) => [tag, label]);
      if (current?.lang && !docLanguages.some(([tag]) => tag === current.lang)) docLanguages.push([current.lang, current.lang]);
      selection(action('language'), docLanguages, current?.lang || language);
      action('furigana').hidden = !global.LP.furigana || (current?.lang || language).split('-')[0] !== 'ja';
      action('furigana').setAttribute('aria-pressed',String(global.LP.furigana?.enabled() || false));
      action('furigana').title='汉字注音';
      selection(action('news-source'), [
        ['all', '全部'], ...sourceRows('article', language).map(row => [
          row.id, row.id === 'builtin-textbooks' ? '大学教材' : row.name,
        ]),
      ], articleSources[language] || 'all');
      const formats = readerOptions.formats.filter(row => row.language === language).map(row => [row.id, row.name]);
      const format = formatIds[language] || defaultFormat(language);
      selection(action('news-format'), formats.length ? formats : [[format, language === 'ja' ? 'JLPT N1' : language === 'en' ? format.toUpperCase() : '通用阅读']], format);
      selection(action('paper-source'), [['all', '全部来源'], ...sourceRows('paper').map(row => [row.id, row.name])], source);
    }

    async function loadReaderOptions() {
      try {
        const loaded = await json('/options');
        if (!Array.isArray(loaded.sources) || !Array.isArray(loaded.formats)) return;
        const previous = readerOptions.defaults || {};
        readerOptions = loaded;
        const defaults = readerOptions.defaults || {};
        const legacyPaper = prefs?.get('paperSource');
        const changed = key => !optionsReady || defaults[key] !== previous[key];
        const available = (kind, lang, id) => id === 'all' || sourceRows(kind, lang).some(row => row.id === id);
        if (changed('paper') || !available('paper', null, source)) {
          source = defaults.paper || sourceRows('paper').find(row => row.name === legacyPaper)?.id || 'all';
        }
        for (const { tag: lang } of locales()) {
          const key = (type, data) => lang === 'en' || lang === 'ja' ? data[type + '_' + lang] : data[type + '_by_language']?.[lang];
          if (!optionsReady || key('article', defaults) !== key('article', previous) || !available('article', lang, articleSources[lang])) {
            articleSources[lang] = key('article', defaults) || 'all';
          }
          if (!optionsReady || key('format', defaults) !== key('format', previous) || !formatRecord(lang)) {
            const next = key('format', defaults) || defaultFormat(lang);
            if (next !== formatIds[lang]) delete ranges[lang];
            formatIds[lang] = next;
          }
        }
        optionsReady = true;
      } catch {
        // A previously opened reader can still display its local shelf.
      }
      renderOptions();
      if (!home.hidden && view === 'news') updateLength();
    }

    function activeFormat(lang, preferred) {
      const existing = preferred && (formatRecord(lang, preferred) || ['toefl', 'gre', 'jlpt'].includes(preferred));
      const selected = existing ? preferred : formatIds[lang];
      const custom = formatRecord(lang, selected);
      if (custom && !custom.builtin) return { format_id: custom.id };
      return lang === 'en' && selected === 'gre' ? { exam: 'gre' } : {};
    }

    function updateLength() {
      const [min, max, unit] = lengthLimits(language);
      const format = formatRecord(language);
      const custom = format && !format.builtin ? format : null;
      const [lower, upper] = custom ? [custom.min_length, custom.max_length] : [min, max];
      const range = ranges[language];
      for (const [key, value] of [['min-length', range?.[0] ?? lower], ['max-length', range?.[1] ?? upper]]) {
        const field = action(key);
        field.min = lower; field.max = upper; field.value = value; field.setCustomValidity('');
      }
      action('length-label').textContent = range ? range.join('–') + ' ' + unit
        : custom ? lower + '–' + upper + ' ' + unit : '不限';
      action('length-unit').textContent = unit;
      const presets = action('length-presets');
      presets.replaceChildren();
      if (!custom && language === 'en') {
        const choices = formatIds.en === 'gre' ? [['短篇', 75, 165], ['长篇', 350, 500]]
          : [...(articleSources.en !== 'builtin-textbooks' ? [['日常', 15, 150]] : []), ['学术', 180, 220], ['长文', 650, 800]];
        for (const [label, min, max] of choices) {
          const preset = button(label + ' ' + min + '–' + max, () => applyLength([min, max]));
          preset.setAttribute('aria-pressed', String(range?.[0] === min && range?.[1] === max));
          presets.append(preset);
        }
      }
    }

    function applyLength(range) {
      if (range) ranges[language] = range;
      else delete ranges[language];
      selectedKey = undefined;
      updateLength(); action('length').open = false;
      void refresh();
    }

    function showList(items, unavailable = [], emptyLabel = '') {
      const keyFor = item => item.id || item.zoteroKey || item.url || item.title;
      const dateFor = item => {
        if (!item.date) return '';
        if (/^\d{4}(?:-\d\d(?:-\d\d)?)?$/.test(item.date)) return item.date;
        const timestamp = Date.parse(item.date);
        return Number.isFinite(timestamp) ? new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(timestamp) : '';
      };
      const metaFor = item => [item.source, dateFor(item),
        Number.isInteger(item.length) ? item.length + ' ' + lengthLimits(item.lang || language)[2] : ''].filter(Boolean).join(' · ');
      const rows = [];
      const activeRow = list.contains(document.activeElement) ? document.activeElement : null;
      function select(index) {
        rows.forEach((row, i) => {
          row.tabIndex = i === index ? 0 : -1;
          row.setAttribute('aria-pressed', i === index);
        });
        const item = items[index];
        preview.replaceChildren();
        preview.parentElement.scrollTop = 0;
        preview.classList.toggle('rd-preview-empty', !item);
        if (!item) {
          const mark = node('span', '', 'rd-empty-icon');
          mark.innerHTML = glyph(view === 'papers' ? 'search' : view === 'library' ? 'shelf' : 'sheet');
          preview.append(mark);
          if (emptyLabel) preview.append(node('p', emptyLabel));
          return;
        }
        const meta = node('div', '', 'rd-preview-meta');
        meta.append(node('small', metaFor(item)));
        if (item.format) {
          const format = node('span', item.format_id ? item.format : item.lang === 'ja' ? 'N1' : item.exam === 'gre' ? 'GRE' : 'TOEFL', 'rd-format-mark');
          format.title = item.format;
          meta.append(format);
        }
        const heading = node('h2', item.title);
        if (item.lang) heading.lang = item.lang;
        preview.append(meta, heading);
        if (item.attribution || item.author) preview.append(node('small', item.attribution || item.author, 'rd-preview-author'));
        if (item.text) {
          const capped = item.text.slice(0, 360);
          const excerpt = item.text.length > capped.length
            ? sentences(capped, item.lang || language).slice(0, -1).join(' ') || capped.trimEnd()
            : capped;
          const shown = item.text.length > excerpt.length ? excerpt.replace(/[.。]$/, '') + '…' : excerpt;
          const paragraph = node('p', shown, 'rd-preview-excerpt');
          if (item.lang) paragraph.lang = item.lang;
          preview.append(paragraph);
        }
        if (item.feedOnly) {
          preview.append(node('p', '只有摘要', 'rd-feed-notice'));
        }
        const links = node('div', '', 'rd-actions');
        if (item.feedOnly && item.text?.trim()) {
          links.append(button('读摘要', () => void openItem({ ...item, scope: '订阅摘要（非全文）', abstractOnly: true }), 'rd-read'));
        }
        if (!item.feedOnly && (item.zoteroKey || item.access || item.id || item.text)) {
          const open = button(item.zoteroKey || item.access === 'pdf' ? '读 PDF' : item.access === 'oa-text' ? '读开放全文' : view === 'library' ? '继续读' : '开始读',
            () => void openItem(item), 'rd-read');
          const arrow = node('span', ' →');
          arrow.setAttribute('aria-hidden', 'true');
          open.append(arrow);
          links.append(open);
        }
        const original = safeLink(item.url, item.feedOnly ? '打开来源' : '来源');
        if (original) links.append(original);
        const license = safeLink(item.license_url, '许可');
        if (license) links.append(license);
        const imageSource = item.image && prefs?.get('readerImages') !== false && safeLink(item.imageSource, '配图来源');
        if (imageSource) links.append(imageSource);
        if ((item.access || item.zoteroKey) && item.text) {
          links.append(button('读摘要', () => void openItem({ ...item, access: '', scope: '摘要', abstractOnly: true })));
        }
        if (view === 'library' && item.id) {
          const remove = button('删除', async () => {
            const ok = await LP.util.confirm({ title: '删除这份文档？', text: '「' + item.title + '」和它的批注会一起删除，不能恢复。', ok: '删除' });
            if (!ok) return;
            remove.disabled = true;
            try { await storage().deleteDocument(item); selectedKey = undefined; await refresh(); }
            catch (error) { status.textContent = error.message; remove.disabled = false; }
          }, 'rd-delete');
          links.append(remove);
        }
        if (links.childElementCount) preview.append(links);
        if (item.feedOnly) {
          const paste = node('details', '', 'rd-paste');
          paste.append(node('summary', '粘贴正文阅读'));
          const form = node('form');
          const label = node('label', '文章正文');
          const input = node('textarea');
          input.rows = 8; input.maxLength = 240000; input.required = true;
          input.setAttribute('aria-label', '粘贴文章正文');
          input.placeholder = '把正文贴进来';
          label.append(input);
          const submit = node('button', '开始读粘贴正文', 'rd-read'); submit.type = 'submit';
          input.addEventListener('input', () => input.setCustomValidity(''));
          form.append(label, submit);
          form.addEventListener('submit', event => {
            event.preventDefault();
            const text = input.value.trim();
            if (!text) { input.setCustomValidity('请先粘贴正文'); input.reportValidity(); return; }
            void openItem({ id: id(), title: item.title, text, lang: item.lang || language,
              source: item.source, url: item.url, scope: '用户粘贴正文', libraryOrigin: 'import', public: false });
          });
          paste.append(form); preview.append(paste);
        }
      }
      const scroll = list.scrollTop;
      list.replaceChildren();
      let lastGroup;
      items.forEach((item, index) => {
        const feed = Boolean(item.feedOnly);
        if (view === 'news' && feed !== lastGroup) {
          lastGroup = feed;
          list.append(node('div', feed ? '摘要' : '全文', 'rd-file-group'));
        }
        const activate = () => { selectedKey = keyFor(item); select(index); };
        const row = button('', activate, view === 'news' ? 'rd-file rd-article-row' : 'rd-file');
        row.dataset.readerKey = keyFor(item);
        const icon = node('span', '', 'rd-file-icon');
        icon.setAttribute('aria-hidden', 'true');
        icon.innerHTML = glyph('sheet');
        if (view === 'news' && prefs?.get('readerImages') !== false && typeof item.image === 'string') {
          try {
            const url = new URL(item.image);
            if (url.protocol === 'https:' && !url.username && !url.password) {
              const thumbnail = node('img', '', 'rd-thumbnail');
              thumbnail.alt = '';
              thumbnail.loading = 'lazy';
              thumbnail.decoding = 'async';
              thumbnail.referrerPolicy = 'no-referrer';
              thumbnail.addEventListener('error', () => thumbnail.remove(), { once: true });
              thumbnail.src = url.href;
              icon.append(thumbnail);
            }
          } catch { /* Keep the article placeholder. */ }
        }
        const label = node('span', '', 'rd-file-copy');
        const title = node('strong', item.title);
        title.title = item.title;
        if (item.lang) title.lang = item.lang;
        label.append(title);
        const meta = metaFor(item);
        if (meta) label.append(node('small', meta));
        row.append(icon, label);
        row.addEventListener('keydown', event => {
          const target = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 }[event.key];
          if (target === undefined) return;
          event.preventDefault();
          rows[target]?.focus();
          rows[target]?.click();
        });
        rows.push(row);
        list.append(row);
      });
      const currentKey = selectedKey ?? activeRow?.dataset.readerKey;
      let index = items.findIndex(item => keyFor(item) === currentKey);
      if (index < 0) index = Math.max(0, items.findIndex(item => !item.feedOnly));
      select(index);
      list.scrollTop = scroll;
      if (activeRow) rows[index]?.focus({ preventScroll: true });
      status.textContent = unavailable.length ? unavailable.join('、') + ' 没打开' : '';
    }

    async function refresh() {
      listRequest?.abort();
      const controller = new AbortController();
      listRequest = controller;
      showList([], [], view === 'papers' && !search ? '输入关键词或 DOI' : '');
      status.textContent = '';
      list.replaceChildren(...Array.from({ length: 4 }, () => { const row = node('div', '', 'rd-skeleton'); row.setAttribute('aria-hidden', 'true'); return row; }));
      try {
        if (view !== 'library') await optionsRequest;
        if (controller.signal.aborted) return;
        if (view === 'library') {
          if (shelf === 'zotero') {
            const data = await json('/zotero/items?' + new URLSearchParams({ q: zoteroSearch }), undefined, controller.signal);
            if (!controller.signal.aborted) showList(data.items, [], '没有找到论文');
          } else {
            const docs = await storage().listDocuments();
            if (!controller.signal.aborted) showList(docs.filter(doc => isReadingDocument(doc) && libraryOrigin(doc) === shelf).sort((a, b) => (b.openedAt || 0) - (a.openedAt || 0)), [], shelf === 'import' ? '还没有导入' : '还没读过');
          }
        } else if (view === 'news') {
          const filter = new URLSearchParams({ lang: language, ...activeFormat(language) });
          if (articleSources[language] && articleSources[language] !== 'all') filter.set('source', articleSources[language]);
          const textbook = articleSources[language] === 'builtin-textbooks';
          if (textbook) filter.set('material', 'textbook');
          const range = ranges[language];
          const customSource = sourceRows('article', language).some(row => !row.builtin &&
            (articleSources[language] === 'all' || articleSources[language] === row.id));
          if (range || textbook || customSource) {
            if (range) {
              filter.set('min_length', range[0]); filter.set('max_length', range[1]);
            }
            const data = await json('/news?' + filter, undefined, controller.signal);
            if (!controller.signal.aborted) showList(data.items, data.unavailable, range ? '这个区间内暂无文章' : textbook ? '暂无大学教材' : '暂无文章');
            return;
          }
          const url = '/news?' + filter;
          const links = await json(url + '&view=links', undefined, controller.signal);
          if (controller.signal.aborted) return;
          showList(links.items, links.unavailable, '暂无文章');
          if (!links.has_candidates) return;
          const data = await json(url, undefined, controller.signal);
          if (!controller.signal.aborted) showList(data.items, data.unavailable, '暂无文章');
        } else if (search) {
          const data = await json('/papers?' + new URLSearchParams({ q: search, source }), undefined, controller.signal);
          if (!controller.signal.aborted) showList(data.items, data.unavailable, '没有找到论文');
        } else status.textContent = '';
      } catch (error) {
        if (!controller.signal.aborted) status.textContent = error.message;
      }
    }

    function showHome(next) {
      stopSharing();
      chooseTool('read');
      screenRequest?.abort();
      dataRevision++; pageRevision++; actionRevision++;
      closePDF();
      current = null;
      reader.hidden = true; home.hidden = false; view = next;
      selectedKey = undefined;
      indicate('[data-view]', 'view', next);
      controls.replaceChildren();
      languages.replaceChildren();
      action('materials').hidden = next !== 'news';
      action('length').hidden = next !== 'news';
      action('length').open = false;
      if (next === 'news') {
        updateLength();
        const picker = button((LP.languages?.label(language) || language) + ' ▾', () => languageDrawer.open());
        picker.className = 'rd-language-drawer-open';
        picker.setAttribute('aria-label', '选择或添加阅读语言');
        picker.setAttribute('aria-haspopup', 'dialog');
        languages.append(picker);
      } else if (next === 'library') {
        for (const [key, label] of [['import', '已导入'], ['history', '已读'], ...(localReader ? [['zotero', 'Zotero']] : [])]) {
          const control = button(label, () => { shelf = key; showHome('library'); });
          control.dataset.shelf = key;
          control.setAttribute('aria-pressed', shelf === key);
          controls.append(control);
        }
        
        if (shelf === 'zotero') {
          const form = node('form');
          const input = node('input'); input.type = 'search'; input.value = zoteroSearch;
          input.placeholder = '在本机 Zotero 中找论文'; input.setAttribute('aria-label', '搜索 Zotero');
          const submit = node('button', '搜索'); submit.type = 'submit';
          form.append(input, submit);
          form.addEventListener('submit', event => { event.preventDefault(); zoteroSearch = input.value.trim(); selectedKey = undefined; void refresh(); });
          controls.append(form);
        }
      } else if (next === 'papers') {
        const form = node('form');
        const input = node('input');
        input.type = 'search'; input.required = true; input.minLength = 2; input.maxLength = 220; input.value = search;
        input.placeholder = '论文标题、关键词或 DOI';
        input.setAttribute('aria-label', '搜索论文');
        const select = node('select');
        select.dataset.rd = 'paper-source';
        select.setAttribute('aria-label', '论文来源');
        const submit = node('button', '搜索'); submit.type = 'submit';
        form.addEventListener('submit', event => { event.preventDefault(); search = input.value.trim(); source = select.value; selectedKey = undefined; void refresh(); });
        form.append(input, select, submit); controls.append(form);
      }
      if (next === 'library') {
        const archiveStatus = node('span', '', 'rd-archive-status'); archiveStatus.setAttribute('role', 'status');
        const exportButton = button('导出学习数据', async () => {
          exportButton.disabled = true; archiveStatus.textContent = '导出中…';
          try {
            const blob = await storage().exportArchive(); const url = URL.createObjectURL(blob);
            download(url, 'langpal-study-' + new Date().toISOString().slice(0, 10) + '.zip');
            setTimeout(() => URL.revokeObjectURL(url), 60000);
            archiveStatus.textContent = '已导出';
          } catch (error) { archiveStatus.textContent = error.message; }
          finally { exportButton.disabled = false; }
        });
        const restoreInput = node('input'); restoreInput.type = 'file'; restoreInput.accept = '.zip'; restoreInput.hidden = true;
        const restoreButton = button('恢复学习数据', () => restoreInput.click());
        restoreInput.addEventListener('change', async () => {
          const file = restoreInput.files[0]; restoreInput.value = ''; if (!file) return;
          restoreButton.disabled = true; archiveStatus.textContent = '恢复中…';
          try { const result = await storage().restoreArchive(file); archiveStatus.textContent = '恢复好了' + (result.conflicts ? '，有 ' + result.conflicts + ' 条没恢复' : ''); await refresh(); }
          catch (error) { archiveStatus.textContent = error.message; }
          finally { restoreButton.disabled = false; }
        });
        controls.append(exportButton, restoreButton, restoreInput, archiveStatus);
        const state = storage().getStatus(); if (state.state === 'warning' || state.state === 'unavailable') archiveStatus.textContent = state.message;
      }
      renderOptions();
      void refresh();
    }

    async function openItem(item) {
      const rev = ++dataRevision;
      status.textContent = '正在打开…';
      try {
        let doc = item._hasFile && !item.blob ? await storage().getDocument(item.id) : item;
        if (!doc) throw new Error('书架上没有这篇');
        if (!doc.id) {
          let { text, scope } = item;
          let blob;
          if (item.zoteroKey && !item.abstractOnly) {
            blob = await (await api('/zotero/items/' + encodeURIComponent(item.zoteroKey) + '/pdf')).blob();
            scope = '本地 PDF';
          } else if (item.access === 'oa-text') {
            text = (await json('/papers/oa/' + encodeURIComponent(item.ref))).text;
            scope = '开放全文';
          } else if (item.access === 'pdf') {
            blob = await (await api('/papers/pdf/' + item.ref.split('/').map(encodeURIComponent).join('/'))).blob();
            scope = '预印本 PDF';
          }
          const record = item.zoteroKey ? 'zotero:' + item.zoteroKey : item.url || (item.source_id ? 'source:' + item.source_id + ':' + item.title : id());
          const version = item.excerpt_id ? ':' + item.excerpt_id : '';
          doc = { ...item, id: record + '#' + (scope || 'feed') + version, text, blob, scope, access: '', zoteroKey: undefined, public: !item.zoteroKey };
        }
        if (rev !== dataRevision) return;
        await openDocument(doc, rev);
      } catch (error) {
        if (rev === dataRevision) status.textContent = error.message;
      }
    }

    async function importFile(file) {
      const rev = ++dataRevision;
      const extension = file.name.split('.').pop().toLowerCase();
      if (!['pdf', 'txt', 'md'].includes(extension) || !file.size) { status.textContent = '打不开这种文件'; return; }
      if (file.size > MAX_FILE) { status.textContent = '文件太大'; return; }
      status.textContent = '正在打开文件…';
      try {
        const text = extension === 'pdf' ? '' : decodeText(await file.slice(0, 1_000_000).arrayBuffer()).slice(0, 240_000);
        const doc = { id: id(), title: file.name, lang: /[\u3040-\u30ff]/.test(text || file.name) ? 'ja' : language,
          text, blob: extension === 'pdf' ? file : undefined, source: '本地文件', libraryOrigin: 'import', public: false };
        if (rev === dataRevision) await openDocument(doc, rev);
      } catch (error) {
        if (rev === dataRevision) status.textContent = '没打开';
      }
    }

    function closePDF() {
      if (pdfTask) void pdfTask.destroy().catch(() => {});
      pdfTask = null;
      pdf = null;
    }

    async function openDocument(doc, rev, keepSharing = false) {
      const task = doc.blob ? await (await pdfModule()).openPDF(doc.blob) : null;
      let pdfDoc;
      try { pdfDoc = task ? await task.promise : null; }
      catch (error) { if (task) void task.destroy().catch(() => {}); throw error; }
      if (rev !== dataRevision) { if (task) void task.destroy().catch(() => {}); return; }
      if (!keepSharing) stopSharing();
      screenRequest?.abort();
      closePDF();
      pdf = pdfDoc; pdfTask = task; current = doc; picked = ''; hover = ''; box = null;
      chooseTool('read');
      setLookup(prefs?.get('readerLookup') === true);
      answer = null; action('question-input').value = ''; exercise = null; choices = []; grade = null; submitting = false; examIndex = 0;
      translations = new Map(); translationTask = null; warming = prefs?.get('readerPretranslate') === true;
      textPages = paginate(doc.text || '');
      page = Math.max(1, Math.min(totalPages(), doc.page || 1));
      home.hidden = true; reader.hidden = false;
      $(reader, '.rd-doclabel strong').textContent = doc.title;
      const origin = $(reader, '.rd-origin');
      origin.replaceChildren(node('small', [doc.attribution || doc.source, doc.scope, doc.license].filter(Boolean).join(' · ')));
      const link = safeLink(doc.url, '来源'); if (link) origin.append(link);
      const license = safeLink(doc.license_url || (doc.source === 'Wikipedia' ? 'https://creativecommons.org/licenses/by-sa/4.0/' : ''), '许可');
      if (license) origin.append(license);
      renderOptions();
      action('window').hidden = isWindow;
      action('share').hidden = !localReader;
      notes = []; unsavedNotes.clear();
      await renderPage();
      if (doc.public && !doc.feedOnly && doc.text) void learningCall('/learning/encounters', { language: doc.lang, text: doc.text.slice(0, 20000), ref: docRef(doc) });
      if (questionsFirst && doc.public && !doc.feedOnly && !doc.abstractOnly) beginExercise();
      try {
        const saved = await storage().getNotes(doc.id);
        if (rev === dataRevision) notes = [...new Map([...saved, ...notes].map(n => [n.id, n])).values()];
        await persistDocument(doc);
      } catch (error) {
        if (rev === dataRevision) storageStatus('没存上', true);
      }
      if (rev === dataRevision) {
        markOnPage();
        renderTool();
      }
    }

    const totalPages = () => pdf ? pdf.numPages : textPages.length;
    async function getText(pageNumber) {
      return pdf ? (await pdfModule()).pageText(pdf, pageNumber) : textPages[pageNumber - 1] || '';
    }

    function markOnPage() {
      if (!rendered) {
        if (!CSS.highlights) return;
        const ranges = [];
        const paragraphs = [...body.querySelectorAll('.rd-prose p')];
        for (const note of notes) {
          if (note.page !== page || !note.quote) continue;
          const anchor = note.anchor;
          const paragraph = anchor ? paragraphs[anchor.paragraph] : paragraphs.find(p => sourceText(p).includes(note.quote));
          if (!paragraph) continue;
          const start = anchor?.start ?? sourceText(paragraph).indexOf(note.quote);
          const length = anchor?.length ?? note.quote.length;
          if (start < 0) continue;
          let range;
          if (global.LP.furigana) range = global.LP.furigana.range(paragraph, start, length);
          else {
            range = document.createRange(); let offset = 0;
            const units = [...paragraph.querySelectorAll('.rd-unit')];
            for (const unit of units) {
              const next = offset + unit.textContent.length;
              if (offset <= start && start < next) range.setStart(unit.firstChild, start-offset);
              if (offset < start+length && start+length <= next) { range.setEnd(unit.firstChild,start+length-offset); break; }
              offset = next;
            }
          }
          if (!range.collapsed) ranges.push(range);
        }
        CSS.highlights.set('jine-notes', new Highlight(...ranges));
        return;
      }
      CSS.highlights?.delete('jine-notes');
      rendered.wrap.querySelectorAll('.rd-mark').forEach(mark => mark.remove());
      for (const area of [...notes.filter(n => n.page === page && n.rect).map(n => n.rect), ...(box ? [box] : [])]) {
        const mark = node('span', '', 'rd-mark');
        for (const [property, ratio] of ['left', 'top', 'width', 'height'].map((key, i) => [key, area[i]])) {
          mark.style[property] = ratio * 100 + '%';
        }
        rendered.wrap.append(mark);
      }
    }

    async function renderPage() {
      const stamp = ++pageRevision, display = page;
      clearTimeout(lookupTimer);
      picked = ''; hover = ''; box = null; drawing = false; rendered = null; currentText = '';
      lookupSentence = ''; noteAnchor = null;
      action('annotate').hidden = true;
      $(reader, '.rd-pager').hidden = totalPages() <= 1;
      action('page').value = page; action('page').max = totalPages();
      action('count').textContent = '/ ' + totalPages();
      action('prev').disabled = page <= 1; action('next').disabled = page >= totalPages();
      body.replaceChildren(node('p', '正在打开这一页…', 'rd-empty'));
      body.scrollTop = 0;
      try {
        const text = await getText(display);
        pdfWidth = Math.min(830, body.clientWidth - 28);
        const rubyText = current.lang.split('-')[0] === 'ja' && global.LP.furigana?.enabled();
        const visual = pdf && !rubyText ? await (await pdfModule()).renderPage(pdf, display, pdfWidth) : null;
        if (stamp !== pageRevision) return;
        currentText = text;
        body.replaceChildren();
        if (visual) {
          rendered = visual; body.append(visual.wrap);
          installBox(visual.wrap); markOnPage();
        } else {
          const paper = node('div', '', 'rd-prose');
          paper.dir = 'auto';
          paper.lang = current.lang;
          if (!text) paper.append(safeLink(current.url, '去原网站读') || node('p', '只有标题', 'rd-empty'));
          for (const paragraph of text.split(/\n\s*\n/)) {
            if (!paragraph.trim()) continue;
            const element = node('p');
            for (const unit of new Intl.Segmenter(current.lang, { granularity: 'sentence' }).segment(paragraph)) {
              element.append(node('span', unit.segment, 'rd-unit'));
            }
            paper.append(element);
          }
          body.append(paper);
          if (rubyText) {
            await Promise.allSettled([...paper.querySelectorAll('.rd-unit')].map(unit => global.LP.furigana.decorate(unit)));   // 注不上的句子就留原文
            if (stamp !== pageRevision) return;
          }
        }
        if (current.public && !current.feedOnly && !current.abstractOnly && display === totalPages()) {
          const end = node('footer', '', 'rd-end');
          const show = button('显示题目', beginExercise, 'rd-primary');
          show.hidden = tool === 'exercise';
          end.append(show, lookedUp(current)); body.append(end);
        }
        markOnPage();
        renderTool();
        warmVisibleWords();
        if (warming && lookup && tool !== 'exercise') void warmTranslations();
      } catch (error) {
        if (stamp === pageRevision) body.replaceChildren(node('p', '这一页没打开', 'rd-empty'));
      }
    }

    function setPage(target) {
      if (!current || !Number.isFinite(target)) return;
      page = Math.min(totalPages(), Math.max(1, Math.trunc(target)));
      current.page = page;
      void persistDocument(current);
      void renderPage();
    }

    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(async () => {
          const width = Math.min(830, body.clientWidth - 28);
          if (!pdf || !rendered || drawing || global.LP.furigana?.enabled() && current?.lang.split('-')[0] === 'ja' || width < 120 || Math.abs(width - pdfWidth) < 4) return;
          const stamp = pageRevision, model = pdf, display = page;
          pdfWidth = width;
          try {
            const visual = await (await pdfModule()).renderPage(model, display, width);
            if (stamp !== pageRevision || model !== pdf || pdfWidth !== width || drawing) return;
            rendered.wrap.replaceWith(visual.wrap);
            rendered = visual; installBox(visual.wrap); markOnPage();
          } catch { /* Keep the visible page on resize failure. */ }
        }, 150);
      }).observe(body);
    }

    function installBox(sheet) {
      let start;
      const point = event => {
        const r = sheet.getBoundingClientRect();
        const clamp = x => Math.max(0, Math.min(1, x));
        return [clamp((event.clientX - r.left) / r.width), clamp((event.clientY - r.top) / r.height)];
      };
      sheet.addEventListener('pointerdown', event => {
        if (!drawing || event.button !== 0) return;
        getSelection()?.removeAllRanges();
        picked = '';
        event.preventDefault(); start = point(event); sheet.setPointerCapture(event.pointerId);
      });
      sheet.addEventListener('pointermove', event => {
        if (!start) return;
        const end = point(event);
        box = [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.abs(start[0] - end[0]), Math.abs(start[1] - end[1])];
        markOnPage();
      });
      sheet.addEventListener('pointerup', () => {
        if (!start) return;
        start = null; drawing = false; sheet.classList.remove('rd-drawing');
        if (box && box[2] > 0.01 && box[3] > 0.01) { picked = ''; chooseTool('notes'); }
        else box = null;
        markOnPage(); renderTool();
      });
      sheet.addEventListener('pointercancel', () => {
        start = null; drawing = false; box = null; sheet.classList.remove('rd-drawing'); markOnPage();
      });
    }

    function selected() {
      const selection = getSelection();
      return selection?.anchorNode && selection.focusNode && body.contains(selection.anchorNode) && body.contains(selection.focusNode)
        ? normalize(rangeText(selection.getRangeAt(0))) : '';
    }

    function sentenceFor(value) {
      const line = normalize(value);
      if (!line) return '';
      return sentences(normalize(currentText), current.lang).find(sentence => sentence.includes(line))?.slice(0, 1400) || line.slice(0, 1400);
    }

    function excerpt(value) {
      if (value) panel.append(node('blockquote', value, 'rd-quote'));
    }

    function section(title, value) {
      if (!value) return;
      panel.append(node('h3', title), node('p', value));
    }

    function setLookup(enabled) {
      lookup = enabled;
      action('lookup').setAttribute('aria-pressed', String(enabled));
      reader.classList.toggle('rd-lookup-on', enabled);
    }

    function chooseTool(next) {
      clearTimeout(lookupTimer);
      actionRevision++;
      tool = next;
      more.open = false;
      const question = next === 'ask', exam = next === 'exercise';
      const title = { language: '词句释义', notes: '批注', share: '共享给 AI' }[next];
      action('lookup').hidden = exam;
      action('ask').hidden = exam;
      action('ask').setAttribute('aria-expanded', String(question));
      action('exam-back').hidden = !exam;
      action('close-side').hidden = exam;
      action('annotate').hidden = exam || !picked;
      reader.classList.toggle('rd-exam', exam);
      reader.classList.toggle('rd-asking', question);
      action('question-view').hidden = !question;
      action('side-content').hidden = question;
      body.querySelector('.rd-end button')?.toggleAttribute('hidden', exam);
      side.hidden = !question && !exam;
      $(reader, '#rd-panel-title').textContent = question ? '问这篇文章' : '阅读题';
      if (title) {
        panel = action('sheet-content');
        $(sheet, '#rd-sheet-title').textContent = title;
        renderTool();
        if (!sheet.open) sheet.showModal();
      } else {
        if (sheet.open) sheet.close();
        panel = action('side-content');
        renderTool();
      }
    }

    // 这篇查过的词：可多选，一键收进复习（语境就是它在这篇里的那句话）
    function lookedUp(doc) {
      const box = node('details', '', 'rd-lookups');
      const summary = node('summary', '这篇查过的词');
      box.append(summary);
      box.addEventListener('toggle', async () => {
        if (!box.open || box.dataset.loaded) return;
        box.dataset.loaded = '1';
        let items = [];
        try { items = (await json('/lookups?' + new URLSearchParams({ language: doc.lang, doc: docRef(doc) }))).items || []; }
        catch { box.append(node('p', '没连上', 'rd-empty')); return; }
        if (!items.length) { box.append(node('p', '—', 'rd-empty')); return; }
        const list = node('div', '', 'rd-lookup-list');
        for (const item of items) {
          const label = node('label', '', 'rd-lookup' + (item.saved ? ' saved' : ''));
          const check = node('input'); check.type = 'checkbox'; check.checked = Boolean(item.saved); check.disabled = Boolean(item.saved);
          check.dataset.lemma = item.lemma;
          const word = node('span', item.lemma); word.lang = doc.lang;
          label.append(check, word);
          label.title = item.sentence || '';
          list.append(label);
        }
        const keep = button('收藏', async event => {
          const picked = items.filter(item => !item.saved && list.querySelector('input[data-lemma="' + CSS.escape(item.lemma) + '"]')?.checked);
          if (!picked.length) return;
          const btn = event.currentTarget;
          btn.disabled = true;
          for (const item of picked) {
            try { await LP.api.addVocab({ language: doc.lang, lemma: item.lemma, surface: item.word || item.lemma, reading: item.reading || '', meaning: item.meaning || '', context_sentence: item.sentence || '', source_kind: 'reading', source_ref: docRef(doc) }); item.saved = true; }
            catch { LP.toast?.('没收藏上'); }
          }
          // 收好的那几个勾变灰，就是结果；不另弹提示
          list.querySelectorAll('input').forEach(input => { const it = items.find(x => x.lemma === input.dataset.lemma); if (it?.saved) { input.checked = true; input.disabled = true; input.parentElement.classList.add('saved'); } });
          btn.disabled = false;
        }, 'rd-primary');
        box.append(list, keep);
      });
      return box;
    }

    function beginExercise() {
      readingOffset = body.scrollTop;
      readingPage = page;
      chooseTool('exercise');
      // 做题时翻回第 1 页，但不记成书签：没点「继续阅读」就关掉，下次还从原来那页开始
      if (page > 1) { page = 1; void renderPage(); }
      else body.scrollTop = 0;
      if (!exercise) void prepareExercise(dataRevision);
      $(side, 'h2').focus();
    }

    async function endExercise() {
      chooseTool('read');
      if (page !== readingPage) {
        page = readingPage;
        if (current) {
          current.page = page;
          void persistDocument(current);
        }
        await renderPage();
      }
      body.scrollTop = readingOffset;
    }

    function renderTool() {
      if (!current || tool === 'read') return;
      if (tool === 'ask') { renderQuestion(); return; }
      panel.replaceChildren();
      if (tool === 'language') {
        const actions = node('div', '', 'rd-actions');
        if (picked) excerpt(picked);
        if (picked && [...new Intl.Segmenter(current.lang, { granularity: 'word' }).segment(picked)].filter(part => part.isWordLike).length === 1) {
          actions.append(button('查词', () => void explain(true)));
        }
        // 什么都没选（也没指着哪句）时，讲解和翻译没有对象：不给这两个按钮
        if (picked || hover) actions.append(button('解释这句', () => void explain(false)),
          button('翻译句子', () => void translate(sentenceFor(picked || hover))));
        actions.append(button('批注选段', () => chooseTool('notes')));
        panel.append(actions);
      } else if (tool === 'notes') renderNotes();
      else if (tool === 'share') shareControls();
      else if (tool === 'exercise') renderExercise();
    }

    async function explain(word, detailed = false) {
      const value = picked || hover;
      if (!value || (word && value.length > 64)) return;
      const token = word ? value : '';
      const sentence = lookupSentence || sentenceFor(value);
      const language = current.lang, stamp = ++actionRevision, doc = current;
      panel.replaceChildren(node('h3', word ? token : '句子解析', 'rd-sheet-word'), node('p', '查找中…', 'rd-empty'));
      try {
        const request = { language, lemma: token, surface: token, sentence };
        const data = await (word ? (!detailed && LP.glosses ? LP.glosses.word(request) : LP.api.explainWord(request)) : LP.api.explainSentence({ language, sentence }));
        if (stamp !== actionRevision || doc !== current) return;
        panel.replaceChildren();
        if (word) {
          void json('/lookups', { language, doc: docRef(doc), word: token, lemma: data.lemma || token, sentence: (sentence || '').slice(0, 600) }).catch(() => {});
          const wordHeading = node('h3', data.lemma || token, 'rd-sheet-word');
          wordHeading.lang = language;
          panel.append(wordHeading, node('p', [data.reading, data.pos].filter(Boolean).join(' · '), 'rd-sheet-meta'));
          section('词义', data.meaning_zh);
          excerpt(sentence);
          section('文中用法', data.usage_in_context); section('语法', data.grammar_note);
          const save = button('收藏', async () => {
            save.disabled = true;
            try {
              await LP.api.addVocab({ language, lemma: data.lemma || token, surface: token, reading: data.reading || '',
                meaning: data.meaning_zh, pos: data.pos || '', context_sentence: sentence });
              save.textContent = '已收藏';
            } catch { LP.toast?.('没收藏上'); save.disabled = false; }   // 面板和释义留着，能再点
          }, 'rd-primary');
          const actions = node('div', '', 'rd-actions');
          actions.append(save, button('解释这句', () => void explain(false)), button('批注选段', () => chooseTool('notes')));
          if (data.detail === 'brief') actions.prepend(button('用法与语法', () => void explain(true, true)));
          panel.append(actions);
        } else {
          excerpt(sentence);
          section('中文', data.translation_zh);
          for (const part of data.chunks || []) section(part.text + ' · ' + part.role, part.note);
          for (const point of data.grammar_points || []) section(point.pattern, [point.explanation_zh, point.example].filter(Boolean).join('\n'));
          panel.append(button('批注选段', () => chooseTool('notes')));
        }
      } catch (error) {
        if (stamp === actionRevision) {
          panel.replaceChildren(button('返回', renderTool), node('p', '没查到', 'rd-empty'));
        }
      }
    }

    let wordWarmTimer;
    function warmVisibleWords() {
      if (!lookup || !current || tool === 'exercise' || !LP.glosses || !root.getClientRects().length) return;
      const viewport = body.getBoundingClientRect();
      const visible = [...body.querySelectorAll('.rd-unit, .textLayer span')].filter(unit => {
        const rect = unit.getBoundingClientRect();
        return rect.bottom >= viewport.top && rect.top <= viewport.bottom;
      }).slice(0, 3);
      for (const unit of visible) {
        const sentence = unit.classList.contains('rd-unit') ? normalize(sourceText(unit)).slice(0, 1400) : sentenceFor(sourceText(unit));
        void LP.glosses.prepare(current.lang, sentence).catch(() => {});
      }
    }
    body.addEventListener('scroll', () => {
      clearTimeout(wordWarmTimer); wordWarmTimer = setTimeout(warmVisibleWords, 180);
    });

    async function warmTranslations() {
      if (translationTask) return;
      const available = sentences(normalize(currentText), current.lang)
        .filter(line => line.length > 8 && line.length <= 1400 && !translations.has(line)).slice(0, 12);
      if (!available.length) return;
      const cache = translations, title = current.title.slice(0, 320), language = current.lang;
      const request = json('/translations', { title, language, abstract: current.blob && current.public ? (current.text || '').slice(0, 1200) : '', sentences: available }).then(data => {
        data.translations.forEach((line, i) => cache.set(available[i], line));
      }).catch(() => {});
      translationTask = { request, available };
      await request;
      if (translationTask?.request === request) translationTask = null;
    }

    async function translate(value) {
      if (!value) return;
      chooseTool('language');
      const stamp = ++actionRevision, doc = current, cache = translations;
      panel.replaceChildren(node('p', '正在翻译…', 'rd-empty'));
      try {
        if (translationTask?.available.includes(value)) await translationTask.request;
        if (!cache.has(value)) {
          const result = await json('/translations', { title: doc.title.slice(0, 320), language: doc.lang,
            abstract: doc.blob && doc.public ? (doc.text || '').slice(0, 1200) : '', sentences: [value] });
          cache.set(value, result.translations[0]);
        }
        if (stamp === actionRevision && doc === current) {
          panel.replaceChildren(); excerpt(value); section('中文', cache.get(value));
        }
      } catch (error) {
        if (stamp === actionRevision) panel.replaceChildren(button('返回', renderTool), node('p', error.message, 'rd-empty'));
      }
    }

    function renderNotes() {
      const actions = node('div', '', 'rd-actions');
      if (pdf) actions.append(button('框选 PDF', () => {
        if (!rendered) return;
        drawing = true; rendered.wrap.classList.add('rd-drawing'); sheet.close();
      }));
      actions.append(button('导出笔记', exportNotes));
      if (box && rendered) actions.append(button('下载选区', async () => {
        const canvas = rendered.canvas, area = box;
        download((await pdfModule()).cropPDF(canvas, area), 'page-' + page + '.png');
      }));
      panel.append(actions);
      const editor = node('div', '', 'rd-note-editor');
      const edit = note => {
        editor.replaceChildren();
        const quote = note?.quote || picked;
        if (quote) editor.append(node('blockquote', quote, 'rd-note-quote'));
        const field = node('textarea');
        field.placeholder = box ? '给选区写批注…' : '写一条批注…';
        field.value = note?.text || '';
        field.setAttribute('aria-label', '批注内容');
        editor.append(field, button('保存批注', () => void saveNote(field.value, null, note), 'rd-primary'));
        if (note) field.focus();
      };
      panel.append(editor); edit();
      for (const note of notes.filter(item => !item.parent)) {
        const item = node('div', '', 'rd-note');
        const noteActions = node('div', '', 'rd-actions');
        noteActions.append(button('第 ' + note.page + ' 页', () => { chooseTool('read'); setPage(note.page); }),
          button('编辑批注', () => edit(note)), button('删除', async () => {
            if (!await LP.util.confirm({ title: '删掉这条批注？' })) return;
            const doc = current;
            try {
              await storage().deleteNote(doc.id, note);
              if (doc !== current) return;
              notes = notes.filter(row => row.id !== note.id);
              unsavedNotes.delete(note.id);
              markOnPage(); renderTool();
            } catch (error) { LP.toast?.(error.message); }
          }));
        item.append(noteActions, node('p', note.text));
        if (note.quote) item.append(node('blockquote', note.quote, 'rd-note-quote'));
        for (const reply of notes.filter(row => row.parent === note.id)) item.append(node('p', reply.text, 'rd-reply'));
        const details = node('details'); details.append(node('summary', '回复'));
        const input = node('input'); input.placeholder = '写回复'; input.setAttribute('aria-label', '回复批注');
        details.append(input, button('保存回复', () => void saveNote(input.value, note)));
        item.append(details); panel.append(item);
      }
    }

    async function saveNote(text, parent, existing) {
      const value = text.trim().slice(0, 4000);
      if (!value) return;
      const doc = current;
      const item = existing ? { ...existing, text: value } : { id: id(), page: parent?.page || page, text: value, parent: parent?.id || null,
        quote: parent ? '' : picked.slice(0, 1400), rect: parent ? null : box, anchor: parent ? null : noteAnchor };
      notes = [...notes.filter(note => note.id !== item.id), item];
      unsavedNotes.add(item.id);
      if (!parent) { box = null; picked = ''; noteAnchor = null; }
      action('annotate').hidden = true;
      markOnPage(); renderTool();
      try {
        storageStatus('');
        const stored = await storage().saveNote(doc.id, item);
        if (doc === current) {
          notes = notes.map(note => note.id === stored.id ? stored : note);
          unsavedNotes.delete(item.id);
          storageStatus(unsavedNotes.size ? '批注没存上' : '', unsavedNotes.size > 0);
          if (tool === 'notes') renderTool();
        }
        return item;
      } catch (error) {
        if (doc === current) storageStatus('批注没存上', true);   // 批注面板上有「导出笔记」
        return null;
      }
    }

    function download(url, name) {
      const anchor = node('a'); anchor.href = url; anchor.download = name; anchor.click();
    }

    function exportNotes() {
      const text = '# ' + current.title + '\n\n' + notes.map(note =>
        (note.parent ? '> ' : '## 第 ' + note.page + ' 页\n\n') + note.text + (note.quote ? '\n\n> ' + note.quote : '')
      ).join('\n\n');
      const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
      download(url, current.title.replace(/[<>:"/\\|?*]/g, '-') + '-批注.md');
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function updateQuestionInput() {
      action('question-send').disabled = Boolean(answer?.pending) || !action('question-input').value.trim();
      action('question-selection').hidden = !picked;
      action('question-excerpt').textContent = picked;
    }

    function renderQuestion() {
      updateQuestionInput();
      const thread = action('question-thread');
      const offset = thread.scrollTop;
      thread.replaceChildren();
      if (!answer) {
        const empty = node('div', '', 'rd-ask-empty');
        const icon = node('img');
        icon.src = '/assets/icons/reading.svg'; icon.alt = '';
        const prompts = node('div', '', 'rd-ask-prompts');
        for (const prompt of ['概括当前页', '找出主要论据']) {
          prompts.append(button(prompt, () => {
            const input = action('question-input');
            input.value = prompt;
            updateQuestionInput(); input.focus();
          }));
        }
        empty.append(icon, prompts);
        thread.append(empty);
        return;
      }
      thread.append(node('p', answer.question, 'rd-ask-query'));
      if (answer.pending) {
        thread.append(node('p', '查找原文…', 'rd-ask-status'));
      } else {
        thread.append(node('p', answer.answer, answer.error ? 'rd-ask-status' : 'rd-ask-answer'));
        if (answer.evidence?.length) {
          const sources = node('section', '', 'rd-ask-evidence');
          sources.append(node('h3', '原文依据'));
          for (const { page, quote } of answer.evidence) {
            const entry = node('div', '', 'rd-ask-reference');
            entry.append(button('第 ' + page + ' 页', () => setPage(page)), node('blockquote', quote));
            sources.append(entry);
          }
          thread.append(sources);
        }
      }
      thread.scrollTop = offset;
    }

    function stopSharing() {
      if (!sharing) return;
      const { token, timer } = sharing;
      clearTimeout(timer);
      sharing = null;
      void json('/bridge/release', { token }).catch(() => {});
      action('share').textContent = '共享给 AI';
    }

    function shareControls() {
      panel.replaceChildren();
      const state = node('p', sharing ? 'AI 正在看这篇' : '', 'rd-share-state');
      if (sharing) state.dataset.on = 'true';
      panel.append(state);
      if (shareNote) panel.append(node('p', shareNote, 'rd-share-note'));
      if (sharing) {
        panel.append(button('停止共享', () => { stopSharing(); shareNote = ''; shareControls(); }));
        return;
      }
      const label = node('label', '', 'rd-option'), allow = node('input');
      allow.type = 'checkbox';
      label.append(allow, document.createTextNode('允许回复批注'));
      panel.append(label, button('开始共享', async event => {
        event.currentTarget.disabled = true;
        const doc = current;
        try {
          const { token } = await json('/bridge/claim', { writable: allow.checked });
          if (doc !== current || tool !== 'share' || !sheet.open || root.getClientRects().length === 0) {
            void json('/bridge/release', { token }).catch(() => {});
            return;
          }
          sharing = { token }; shareNote = '';
          action('share').textContent = '共享中';
          shareControls(); void pollShare(sharing);
        } catch (error) { if (tool === 'share') { shareNote = error.message; shareControls(); } }
      }));
    }

    async function pollShare(share) {
      if (sharing !== share || !current) return;
      if (root.getClientRects().length === 0) { stopSharing(); shareNote = '共享停了'; return; }
      const { token } = share;
      try {
        const state = await json('/bridge/poll', {
          token, id: current.id.slice(0, 800), title: current.title.slice(0, 320), page, total: totalPages(), selection: picked.slice(0, 1400),
        });
        for (const command of state.commands) {
          if (sharing !== share) return;
          let result;
          try { result = await runCommand(command); }
          catch (error) { result = { error: error.message }; }
          if (sharing !== share) return;
          await json('/bridge/result', { token, command: command.id, result: JSON.stringify(result) });
        }
      } catch (error) {
        if (sharing === share) { stopSharing(); shareNote = error.message; }
      }
      if (sharing === share) share.timer = setTimeout(() => void pollShare(share), 1100);
    }

    async function runCommand(command) {
      const doc = current, { args, tool: name } = command;
      if (!doc || command.document !== doc.id.slice(0, 800)) throw new Error('阅读文件已经切换');
      const validPage = p => Number.isInteger(p) && p >= 1 && p <= totalPages();
      if (name === 'list_shelf') {
        const docs = await storage().listDocuments();
        return docs.filter(isReadingDocument).sort((a, b) => b.openedAt - a.openedAt).slice(0, 30).map(({ id, title, source }) => ({ id, title, source }));
      }
      if (name === 'open_paper') {
        if (typeof args.document_id !== 'string' || args.document_id.length > 800) throw new Error('无效的书架编号');
        const requested = await storage().getDocument(args.document_id);
        if (!requested || doc !== current) throw new Error('书架里没有这篇');
        await openDocument(requested, ++dataRevision, true);
        return { opened: requested.title };
      }
      if (name === 'list_annotations') return notes.slice(-100);
      if (name === 'reply_annotation') {
        const parent = notes.find(item => item.id === args.annotation_id && !item.parent);
        if (!parent || typeof args.text !== 'string' || !args.text.trim()) throw new Error('找不到这条批注，或回复为空');
        const saved = await saveNote(args.text, parent);
        if (!saved) throw new Error('批注暂时无法保存');
        return saved;
      }
      if (name === 'read_pages') {
        if (!Array.isArray(args.pages) || !args.pages.length || args.pages.length > 5 || !args.pages.every(validPage)) {
          throw new Error('请选择 1–5 个有效页码');
        }
        const pages = [];
        for (const number of new Set(args.pages)) {
          if (doc !== current) throw new Error('阅读文件已经切换');
          pages.push({ page: number, text: (await getText(number)).slice(0, 12_000) });
        }
        return pages;
      }
      if (name === 'capture_region') {
        const area = args.rect;
        if (!pdf || !validPage(args.page) || !Array.isArray(area) || area.length !== 4
          || !area.every(value => Number.isFinite(value) && value >= 0 && value <= 1)
          || area[2] <= 0 || area[3] <= 0 || area[0] + area[2] > 1.000001 || area[1] + area[3] > 1.000001) {
          throw new Error('请选择 PDF 的有效页码和框选范围');
        }
        const module = await pdfModule();
        if (doc !== current) throw new Error('阅读文件已经切换');
        const visual = args.page === page && rendered ? rendered : await module.renderPage(pdf, args.page, 1100);
        if (doc !== current) throw new Error('阅读文件已经切换');
        const png = module.cropPDF(visual.canvas, area).split(',')[1];
        if (png.length > 5_400_000) throw new Error('选区过大，请缩小范围');
        return { png };
      }
      throw new Error('阅读器不支持这个动作');
    }

    async function ask(question) {
      if (!current || !question || answer?.pending) return;
      const doc = current, origin = page, total = Math.min(5000, totalPages());
      const selection = picked.slice(0, 1400);
      const pending = { question, pending: true };
      const isCurrent = () => doc === current && answer === pending;
      answer = pending;
      action('question-input').value = '';
      action('question-thread').scrollTop = 0;
      renderQuestion();
      const pages = [];
      async function addPage(num) {
        if (doc !== current || pages.some(row => row.page === num)) return;
        const text = normalize(await getText(num)).slice(0, 5600);
        if (text) pages.push({ page: num, text });
      }
      try {
        for (const num of [origin, origin - 1, origin + 1]) if (num >= 1 && num <= total) await addPage(num);
        if (!isCurrent()) return;
        if (!pages.length) throw new Error('这几页是图片');
        const body = { title: doc.title.slice(0, 320), question, selection, pages, total_pages: total, allow_more: true };
        let result = await json('/question', body);
        if (!isCurrent()) return;
        if (result.need_pages.length) {
          for (const num of result.need_pages) await addPage(num);
          if (!isCurrent()) return;
          result = await json('/question', { ...body, allow_more: false });
        }
        if (isCurrent()) { answer = { ...result, question }; if (tool === 'ask') renderQuestion(); }
      } catch (error) {
        if (isCurrent()) {
          answer = { question, answer: error.message, error: true };
          const input = action('question-input');
          if (!input.value) input.value = question;
          if (tool === 'ask') renderQuestion();
        }
      }
    }

    async function prepareExercise(rev) {
      const doc = current;
      const controller = new AbortController();
      screenRequest?.abort();
      screenRequest = controller;
      exercise = { busy: true };
      if (tool === 'exercise') renderTool();
      try {
        let text = pdf ? '' : doc.text || '';
        if (pdf) {
          for (let num = 1; num <= Math.min(3, totalPages()); num++) {
            if (controller.signal.aborted || rev !== dataRevision) return;
            text += '\n\n' + await getText(num);
          }
        }
        if (rev !== dataRevision || controller.signal.aborted) return;
        const result = await json('/exercises', { title: doc.title.slice(0, 320), language: doc.lang,
          text: text.slice(0, 12_000), url: (doc.url || '').slice(0, 700),
          ...activeFormat(doc.lang, doc.format_id || (doc.lang === 'en' ? doc.exam : null)),
          ...(doc.lang === 'en' && doc.material_type === 'open_textbook' ? { material: 'textbook' } : {}) }, controller.signal);
        // 出题用的原文留着：PDF 没有 doc.text，「写两句」要拿它对照
        if (rev === dataRevision && !controller.signal.aborted) exercise = { ...result, source: text.slice(0, 12_000) };
      } catch (error) {
        if (rev === dataRevision && !controller.signal.aborted) exercise = { reason: error.message, failed: true };
      }
      if (rev === dataRevision && tool === 'exercise') renderTool();
    }

    function renderExercise() {
      if (!exercise || exercise.busy) { panel.append(node('p', '出题中…', 'rd-empty')); return; }
      if (!exercise.items?.length) {
        panel.append(node('p', exercise.reason || '这篇出不了题', 'rd-empty'));
        if (exercise.failed) panel.append(button('再试一次', () => void prepareExercise(dataRevision)));
        return;
      }
      const count = exercise.items.length;
      const index = examIndex;
      const item = exercise.items[index];
      const answered = choices.filter(Number.isInteger).length;
      const meta = node('div', '', 'rd-exam-meta');
      meta.append(node('small', exercise.format), node('strong', (index + 1) + ' / ' + count));
      panel.append(meta);
      const progress = node('progress');
      progress.max = count;
      progress.value = answered;
      progress.setAttribute('aria-label', '阅读答题进度');
      panel.append(progress);
      if (grade) {
        panel.append(node('p', '答对 ' + grade.correct + ' / ' + count));
        panel.append(skillSpread(exercise, grade));
        if (grade.saved_errors) {
          panel.append(node('p', grade.saved_errors + ' 题进了错题本'));
          if (global.LP.appShell) panel.append(button('查看错题', () => global.LP.appShell.openMistakes('reading', current.lang)));
        }
      }
      const form = node('form', '', 'rd-exam-form');
      const field = node('fieldset');
      const question = node('legend', item.question);
      question.lang = current.lang;
      field.append(question);
      const submit = node('button', submitting ? '核对中…' : '交卷', 'rd-primary');
      submit.type = 'submit'; submit.disabled = submitting || answered < count;
      item.options.forEach((option, i) => {
        // 交卷后：对的那项标 right，选错的那项标 wrong（不再另写「答案 2」让人去数）
        const graded = grade?.items?.[index];
        const label = node('label', '', 'rd-option rd-exam-option' + (graded ? (i === graded.answer ? ' right' : i === choices[index] ? ' wrong' : '') : '')), radio = node('input');
        radio.type = 'radio'; radio.name = 'answer'; radio.value = i; radio.checked = choices[index] === i;
        radio.disabled = !!grade || submitting;
        radio.addEventListener('change', () => {
          choices[index] = i;
          progress.value = choices.filter(Number.isInteger).length;
          submit.disabled = progress.value < count;
        });
        const text = node('span', option); text.lang = current.lang;
        label.append(radio, text); field.append(label);
      });
      form.append(field);
      if (grade) {
        const graded = grade.items[index];
        form.append(node('p', graded.explanation),
          node('blockquote', graded.paragraph, 'rd-quote'));
      }
      const actions = node('div', '', 'rd-actions rd-exam-actions');
      const move = next => {
        examIndex = next;
        renderTool();
        panel.querySelector('input:not(:disabled), .rd-exam-actions button:not(:disabled)')?.focus();
      };
      const prev = button('上一题', () => move(index - 1));
      const next = button('下一题', () => move(index + 1));
      prev.disabled = index === 0 || submitting;
      next.disabled = index + 1 === count || submitting;
      actions.append(prev, next);
      if (!grade) actions.append(submit);
      form.append(actions);
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (choices.filter(Number.isInteger).length === count) void submitExercise();
      });
      panel.append(form);
      if (grade && index + 1 === count) panel.append(writeBack(), global.LP.util.nextActions('reading'));
    }

    // 这次按题型的对错：一行一个题型，格子 = 题，实心 = 对
    function skillSpread(set, result) {
      const groups = new Map();
      set.items.forEach((item, i) => {
        const key = item.skill || result.items?.[i]?.skill;
        if (!key) return;
        const ok = result.items?.[i]?.correct ?? (result.items?.[i]?.answer === choices[i]);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(Boolean(ok));
      });
      const box = node('div', '', 'rd-skills');
      for (const [key, marks] of groups) {
        const row = node('div', '', 'rd-skill');
        row.append(node('span', window.LP.util.typeLabel('reading', key, SKILL)));
        const cells = node('span', '', 'rd-skill-cells');
        for (const ok of marks) cells.append(node('i', '', ok ? 'ok' : 'bad'));
        row.append(cells);
        box.append(row);
      }
      return box;
    }

    // 读完写两句（可选）：说对的、要改的（原文片段标在你写的句子上）、漏掉的一点
    function writeBack() {
      const doc = current;
      const box = node('details', '', 'rd-writeback');
      box.append(node('summary', '用' + languageName(doc.lang) + '写两句'));
      const area = node('textarea'); area.rows = 3; area.lang = doc.lang; area.maxLength = 1200; area.setAttribute('aria-label', '写两句这篇讲了什么');
      const send = button('看看', async () => {
        const text = area.value.trim();
        if (!text) { area.focus(); return; }
        send.disabled = true;
        out.replaceChildren(node('p', '…', 'rd-empty'));
        try {
          const body = { language: doc.lang, title: doc.title.slice(0, 320), text: (doc.text || exercise?.source || '').slice(0, 12000), summary: text, doc: docRef(doc) };
          const r = await json('/summary-feedback', body);
          out.replaceChildren();
          if (r.points_right?.length) { const ok = node('ul', '', 'rd-wb-right'); for (const p of r.points_right) { const li = node('li', p); li.lang = doc.lang; ok.append(li); } out.append(ok); }
          if (r.fixes?.length) {
            const mine = node('p', '', 'rd-wb-mine'); mine.lang = doc.lang;
            let rest = text;
            for (const fix of r.fixes) {
              const at = rest.indexOf(fix.original);
              if (at < 0) continue;
              mine.append(document.createTextNode(rest.slice(0, at)));
              const mark = node('mark', fix.original); mark.title = fix.why || '';
              const better = node('ins', fix.better);
              mine.append(mark, better);
              rest = rest.slice(at + fix.original.length);
            }
            mine.append(document.createTextNode(rest));
            out.append(mine);
          }
          if (r.missed) { const miss = node('p', r.missed, 'rd-wb-missed'); miss.lang = doc.lang; out.append(miss); }
        } catch (error) { out.replaceChildren(node('p', error.message, 'rd-empty')); }
        finally { send.disabled = false; }
      }, 'rd-primary');
      const out = node('div', '', 'rd-wb-out');
      box.append(area, send, out);
      return box;
    }
    const languageName = tag => global.LP.languages?.label(tag) || tag;

    async function submitExercise() {
      if (submitting || !exercise?.id) return;
      const set = exercise, doc = current;
      submitting = true;
      renderTool();
      try {
        const result = await json('/exercises/' + encodeURIComponent(set.id) + '/submit', { choices, doc: docRef(doc) });
        if (current === doc && exercise === set) grade = result;
        global.LP.jine?.refreshPending?.();
      } catch (error) {
        if (current === doc && exercise === set) {
          submitting = false;
          if (tool === 'exercise') { renderTool(); panel.append(node('p', error.message, 'rd-empty')); }
          return;
        }
      }
      if (current === doc && exercise === set) { submitting = false; if (tool === 'exercise') renderTool(); }
    }

    home.querySelectorAll('[data-view]').forEach(el => el.addEventListener('click', () => showHome(el.dataset.view)));
    action('news-source').addEventListener('change', event => {
      articleSources[language] = event.currentTarget.value;
      showHome('news');
    });
    action('news-format').addEventListener('change', event => {
      formatIds[language] = event.currentTarget.value;
      delete ranges[language];
      if (language === 'en' && ['toefl', 'gre'].includes(formatIds.en)) prefs?.set('englishExam', formatIds.en);
      showHome('news');
    });
    function loadStyle() {
      const style = global.LP?.readerStyle;
      if (style) void style.get().then(value => style.apply(reader, value)).catch(() => {});
    }
    global.addEventListener('lp:reading-settings', () => {
      loadStyle();
      optionsRequest = loadReaderOptions();
      if (!home.hidden && view !== 'library') void refresh();
    });
    document.addEventListener('lp:languages', () => {
      optionsRequest = loadReaderOptions();
      if (!home.hidden && view === 'news') showHome('news');
      else renderOptions();
    });
    action('length-form').addEventListener('input', () => action('max-length').setCustomValidity(''));
    action('length-form').addEventListener('submit', event => {
      event.preventDefault();
      const max = action('max-length');
      const min = action('min-length').valueAsNumber;
      if (min > max.valueAsNumber) {
        max.setCustomValidity('最长须大于或等于最短');
        max.reportValidity();
        return;
      }
      applyLength([min, max.valueAsNumber]);
    });
    action('length-clear').addEventListener('click', () => {
      applyLength(null);
    });
    action('lookup').addEventListener('click', () => {
      clearTimeout(lookupTimer);
      setLookup(!lookup);
      warmVisibleWords();
      if (lookup && warming && currentText) void warmTranslations();
    });
    action('ask').addEventListener('click', () => {
      more.open = false;
      chooseTool(tool === 'ask' ? 'read' : 'ask');
      if (tool === 'ask') action('question-input').focus({ preventScroll: true });
    });
    action('close-side').addEventListener('click', () => { chooseTool('read'); more.querySelector('summary').focus(); });
    action('question-input').addEventListener('input', updateQuestionInput);
    action('question-input').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.isComposing && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        if (!action('question-send').disabled) action('question-form').requestSubmit();
      }
    });
    action('question-form').addEventListener('submit', event => {
      event.preventDefault();
      void ask(action('question-input').value.trim());
    });
    action('question-clear').addEventListener('click', () => {
      if (selected()) getSelection().removeAllRanges();
      picked = ''; lookupSentence = ''; noteAnchor = null;
      action('annotate').hidden = true;
      updateQuestionInput();
      action('question-input').focus();
    });
    side.addEventListener('keydown', event => {
      if (event.key === 'Escape' && tool === 'ask') action('close-side').click();
    });
    action('notes').addEventListener('click', () => chooseTool('notes'));
    action('annotate').addEventListener('click', () => chooseTool('notes'));
    action('close-sheet').addEventListener('click', () => sheet.close());
    sheet.addEventListener('close', () => {
      if (!sheet.open && !drawing && ['language', 'notes', 'share'].includes(tool)) chooseTool('read');
    });
    sheet.addEventListener('click', event => { if (event.target === sheet) sheet.close(); });
    action('exam-back').addEventListener('click', endExercise);
    action('pick').addEventListener('click', () => action('file').click());
    action('file').addEventListener('change', () => {
      const file = action('file').files[0]; action('file').value = ''; if (file) void importFile(file);
    });
    action('furigana').onclick = () => global.LP.furigana?.setEnabled(!global.LP.furigana.enabled());
    global.addEventListener('lp:furigana', () => { if (current?.lang.split('-')[0] === 'ja') { renderOptions(); void renderPage(); } });
    action('back').addEventListener('click', () => showHome(view));
    action('prev').addEventListener('click', () => setPage(page - 1));
    action('next').addEventListener('click', () => setPage(page + 1));
    action('page').addEventListener('change', event => setPage(event.currentTarget.valueAsNumber));
    action('language').addEventListener('change', () => {
      if (!current) return;
      current.lang = action('language').value; translations = new Map(); answer = null; choices = []; grade = null; submitting = false;
      void persistDocument(current);
      void renderPage();
      exercise = null; examIndex = 0; screenRequest?.abort();
      if (tool === 'exercise') void prepareExercise(dataRevision);
    });
    action('window').addEventListener('click', () => {
      more.open = false;
      if (current) window.open('/reader.html?id=' + encodeURIComponent(current.id), '_blank', 'popup,width=1150,height=820,noopener');
    });
    action('share').addEventListener('click', () => chooseTool('share'));
    document.addEventListener('pointerdown', event => { if (more.open && !more.contains(event.target)) more.open = false; });
    window.addEventListener('pagehide', stopSharing);
    home.addEventListener('dragover', event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); home.classList.add('rd-drag'); } });
    home.addEventListener('dragleave', event => { if (!home.contains(event.relatedTarget)) home.classList.remove('rd-drag'); });
    home.addEventListener('drop', event => {
      event.preventDefault(); home.classList.remove('rd-drag');
      if (event.dataTransfer.files[0]) void importFile(event.dataTransfer.files[0]);
    });
    function trackSelection() {
      if (drawing || box || tool === 'exercise') return;
      const value = selected();
      if (!value) return;
      picked = value;
      lookupSentence = ''; noteAnchor = null;
      const range = getSelection().getRangeAt(0);
      const paragraph = range.startContainer.parentElement?.closest('.rd-prose p');
      if (paragraph?.contains(range.endContainer) && rangeText(range).length <= 1400) {
        const before = document.createRange();
        before.selectNodeContents(paragraph);
        before.setEnd(range.startContainer, range.startOffset);
        noteAnchor = { paragraph: [...body.querySelectorAll('.rd-prose p')].indexOf(paragraph),
          start: rangeText(before).length, length: rangeText(range).length };
      }
      action('annotate').hidden = false;
      if (tool === 'ask') updateQuestionInput();
      else if (lookup) {
        clearTimeout(lookupTimer);
        lookupTimer = setTimeout(() => { if (lookup && tool === 'read') chooseTool('language'); }, 250);
      }
    }
    body.addEventListener('copy', event => { const text = selected(); if(text && global.LP.furigana?.enabled() && current?.lang.split('-')[0] === 'ja' && event.clipboardData) { event.clipboardData.setData('text/plain',text); event.preventDefault(); } });
    body.addEventListener('pointerup', trackSelection);
    body.addEventListener('keyup', trackSelection);
    body.addEventListener('click', event => {
      if (!lookup || drawing || box || tool === 'exercise' || event.detail !== 1 || selected()) return;
      const unit = event.target.closest('.rd-unit, .textLayer span');
      const caret = document.caretRangeFromPoint?.(event.clientX, event.clientY);
      if (!unit || !caret || !unit.contains(caret.startContainer) || caret.startContainer.nodeType !== Node.TEXT_NODE) return;
      const annotated = event.target.closest('ruby');
      const value = annotated?.dataset.surface || caret.startContainer.textContent;
      const word = new Intl.Segmenter(current.lang, { granularity: 'word' }).segment(value)
        .containing(Math.min(caret.startOffset, value.length - 1));
      if (!word?.isWordLike) return;
      lookupTimer = setTimeout(() => {
        if (!lookup || tool === 'exercise' || !root.getClientRects().length) return;
        picked = annotated?.dataset.surface || word.segment; noteAnchor = null;
        lookupSentence = unit.classList.contains('rd-unit') ? normalize(sourceText(unit)).slice(0, 1400) : '';
        chooseTool('language'); void explain(true);
      }, current.lang === 'ja' ? 0 : 230);
    });
    body.addEventListener('dblclick', event => {
      clearTimeout(lookupTimer);
      if (!lookup || tool === 'exercise') return;
      const unit = event.target.closest('.rd-unit, .textLayer span');
      if (!unit) return;
      picked = sentenceFor(sourceText(unit)); lookupSentence = picked;
      chooseTool('language'); void explain(false);
    });
    body.addEventListener('pointermove', event => {
      const unit = event.target.closest('.rd-unit, .textLayer span');
      const next = unit ? sourceText(unit) : '';
      if (hover !== next && lookup && tool !== 'exercise' && current && LP.glosses && next) {
        clearTimeout(wordWarmTimer);
        const language = current.lang;
        const sentence = unit.classList.contains('rd-unit') ? normalize(next).slice(0, 1400) : sentenceFor(next);
        wordWarmTimer = setTimeout(() => { if (lookup && tool !== 'exercise') void LP.glosses.prepare(language, sentence).catch(() => {}); }, 120);
      }
      hover = next;
    });
    // 单按一下 Ctrl（按下又松开，中间没按别的键、没点鼠标）= 翻译；Ctrl+C、Ctrl+F 这类组合键不算
    let ctrlAlone = false;
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && drawing) {
        drawing = false; rendered?.wrap.classList.remove('rd-drawing'); box = null; markOnPage(); chooseTool('read');
      }
      ctrlAlone = event.key === 'Control' && !event.repeat ? true : event.key === 'Control' ? ctrlAlone : false;
    });
    document.addEventListener('pointerdown', () => { ctrlAlone = false; });
    document.addEventListener('keyup', event => {
      if (event.key !== 'Control' || !ctrlAlone) return;
      ctrlAlone = false;
      if (!lookup || tool === 'exercise' || !current || root.getClientRects().length === 0 || event.altKey) return;
      if (event.target.closest('input,textarea,select,[contenteditable]')) return;
      const value = picked || hover;
      if (value) void translate(event.shiftKey ? value.slice(0, 1400) : sentenceFor(value));
    });
    optionsRequest = loadReaderOptions();
    loadStyle();
    showHome(isWindow ? 'library' : 'news');
    const requested = isWindow && new URLSearchParams(location.search).get('id');
    if (requested) void storage().getDocument(requested).then(doc => doc ? openItem(doc) : null).catch(error => { status.textContent = error.message; });
  }

  global.LP = global.LP || {};
  global.LP.reading = { mount };
})(window);
