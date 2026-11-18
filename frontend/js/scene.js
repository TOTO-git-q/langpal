(function (global) {
  'use strict';
  const LP = global.LP = global.LP || {};
  const titles = { talk: '聊天', today: '今天', reading: '阅读', listening: '听力', coach: '口语', drill: '复习', review: '错题本', notebook: '单词本', 'workspace-agent': '课程管家', settings: '设置' };
  const providers = new Map();
  let notes = [];

  function genericText(panel) {
    if (!panel) return '';
    const lines = [];
    const walker = document.createTreeWalker(panel, NodeFilter.SHOW_ELEMENT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.closest('script, style, [hidden], [aria-hidden="true"], input[type="password"]')) continue;
      const text = [...node.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
      if (!text) continue;
      let hidden = false;
      for (let parent = node; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') { hidden = true; break; }
      }
      if (hidden) continue;
      const box = node.getBoundingClientRect();
      if (!box.width || !box.height || box.bottom < -600 || box.top > global.innerHeight + 600 || box.right < 0 || box.left > global.innerWidth) continue;
      lines.push(text);
    }
    return lines.join('\n').slice(0, 4000);
  }

  function get() {
    const panel = document.querySelector('#app-page .page-panel.active');
    const tab = panel?.id.replace(/^page-/, '') || 'talk';
    const data = providers.get(tab)?.() || {};
    return { tab, title: data.title ?? titles[tab] ?? tab, language: data.language || null,
      text: tab === 'talk' ? '' : (data.text !== undefined ? data.text : genericText(panel)), actions: notes.slice() };
  }

  LP.scene = { titles, provide: (tab, fn) => providers.set(tab, fn), get,
    noteAction(label) { notes.push(label); notes = notes.slice(-3); },
    sent(scene) { notes.splice(0, scene.actions.length); } };
})(window);
