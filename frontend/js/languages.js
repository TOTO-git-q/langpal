(function (global) {
  'use strict';
  const LP = global.LP ||= {};
  let items = [{ tag: 'ja', label: '日本語' }, { tag: 'en', label: 'English' }, { tag: 'de', label: 'Deutsch' }];
  let primary = null;

  async function request(body) {
    const response = await fetch('/api/languages', body ? {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    } : { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '这门语言加不上');
    return payload;
  }

  async function reload() {
    const next = await request();
    if (!Array.isArray(next.items) || !next.items.length) return items;
    const changed = JSON.stringify(next.items) !== JSON.stringify(items) || primary !== (next.persona_id ?? null);
    items = next.items;
    primary = next.persona_id ?? null;
    if (changed) document.dispatchEvent(new CustomEvent('lp:languages'));
    return items;
  }

  LP.languages = {
    reload, list: () => items, primary: () => primary,
    label: tag => items.find(item => item.tag === tag)?.label || tag,
    async add(input) {
      const item = await request(input);
      await reload();
      return item;
    },
  };
})(window);
