(() => {
  'use strict';
  const LP = window.LP;
  // ISO 639-1 plus common written/region variants. Stored tags stay BCP 47.
  const tags = ('aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu yue zh-Hans zh-Hant en-US en-GB es-419 pt-BR pt-PT').split(' ');
  const common = 'en ja zh-Hans zh-Hant ko fr es de it pt ru ar hi vi th id tr yue'.split(' ');
  const synonyms = { ja: '日文 japanese nihongo', en: '英文 english', de: '德文', fr: '法文', es: '西文 西语', ko: '韩文 朝鲜语', zh: '华语 普通话 汉语 中文 mandarin', 'zh-Hans': '简体中文 简中', 'zh-Hant': '繁體中文 繁体中文 繁中', yue: '广东话 粤语 廣東話 粵語 cantonese', ru: '俄文', it: '意大利语', pt: '葡文', tl: '菲律宾语 filipino tagalog' };
  const fold = value => value.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().trim();
  const names = locale => new Intl.DisplayNames(locale, { type: 'language', fallback: 'none' });
  const zh = names('zh-CN');
  const english = names('en');
  const collator = new Intl.Collator('zh-CN');
  const catalog = tags.map(tag => {
    const localized = zh.of(tag);
    if (!localized) return null;
    const label = names(tag).of(tag) || localized;
    return { tag, label, localized, aliases: [localized, label, english.of(tag) || '', synonyms[tag] || '', tag].map(fold) };
  }).filter(Boolean);

  function mount(dialog, opener, select) {
    const input = dialog.querySelector('input');
    const list = dialog.querySelector('.jine-language-results');
    const notice = dialog.querySelector('[role="status"]');
    const custom = dialog.querySelector('.jine-language-custom');
    const form = custom.querySelector('form');
    const submit = form.querySelector('button');
    let busy = false;

    async function choose(item) {
      if (busy) return;
      busy = true;
      input.disabled = true;
      submit.disabled = true;
      for (const button of list.querySelectorAll('button')) button.disabled = true;
      notice.textContent = '';
      try {
        const registered = item.registered ? item : await LP.languages.add({ tag: item.tag, label: item.label });
        if (dialog.open) { select(registered.tag); dialog.close(); }
      } catch (error) {
        notice.textContent = error.message || '添加失败';
      } finally {
        busy = false;
        input.disabled = false;
        submit.disabled = false;
        render();
      }
    }

    function render() {
      const query = fold(input.value);
      const known = new Map(LP.languages.list().map(item => [item.tag.toLowerCase(), item]));
      const entries = catalog.map(item => {
        const current = known.get(item.tag.toLowerCase());
        return current ? { ...item, ...current, aliases: [...item.aliases, fold(current.label)], registered: true } : item;
      });
      for (const item of known.values()) {
        if (!entries.some(entry => entry.tag === item.tag)) {
          entries.push({ ...item, localized: item.label, aliases: [fold(item.label), fold(item.tag)], registered: true });
        }
      }
      const matching = query ? entries.filter(item => item.aliases.some(alias => alias.includes(query))) : entries;
      matching.sort((a, b) => {
        if (query) return Number(b.aliases.some(alias => alias.startsWith(query))) - Number(a.aliases.some(alias => alias.startsWith(query)))
          || collator.compare(a.localized, b.localized);
        const rank = item => common.includes(item.tag) ? common.indexOf(item.tag) : common.length;
        return rank(a) - rank(b) || collator.compare(a.localized, b.localized);
      });
      list.replaceChildren(...matching.map(item => {
        const row = document.createElement('li');
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.language = item.tag;
        const title = document.createElement('strong');
        title.textContent = item.localized;
        const native = document.createElement('span');
        native.lang = item.tag;
        native.textContent = item.label === item.localized ? '' : item.label;
        const action = document.createElement('span');
        action.className = 'jine-language-action';
        action.textContent = item.registered ? '已添加' : '+';
        if (!item.registered) action.setAttribute('aria-hidden', 'true');
        button.append(title, native, action);
        button.addEventListener('click', () => void choose(item));
        row.append(button);
        return row;
      }));
      if (!matching.length) {
        const empty = document.createElement('li');
        empty.textContent = '没有找到匹配的语言';
        list.append(empty);
      }
      custom.hidden = !dialog.classList.contains('language-drawer') && Boolean(matching.length);
      list.scrollTop = 0;
    }

    opener.onclick = () => {
      if (busy) return;
      input.value = '';
      form.reset();
      custom.open = false;
      notice.textContent = '';
      render();
      dialog.showModal();
    };
    input.addEventListener('input', render);
    document.addEventListener('lp:languages', () => { if (dialog.open) render(); });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const data = new FormData(form);
      const tag = data.get('tag').trim();
      const label = data.get('label').trim();
      if (tag && label) void choose({ tag, label });
    });
    dialog.addEventListener('keydown', event => {
      if (event.isComposing || busy || custom.contains(event.target)) return;
      const buttons = [...list.querySelectorAll('button')];
      const index = buttons.indexOf(document.activeElement);
      if (event.key === 'Enter' && event.target === input && input.value.trim() && buttons.length) {
        event.preventDefault();
        buttons[0].click();
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (event.key === 'ArrowUp' && index <= 0) input.focus();
        else buttons[Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1))]?.focus();
      }
    });
  }
  LP.languagePicker = { mount };
})();
