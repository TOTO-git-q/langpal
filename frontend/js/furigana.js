/* Ruby is presentation only: queries, copy and note anchors keep the source text. */
(function (global) {
  'use strict';
  const key = 'jine.reader.furigana';
  const cache = new Map();
  const pending = new Map();
  const active = new WeakMap();
  let choice;
  const enabled = () => { if(choice!==undefined)return choice; try { return localStorage.getItem(key) === 'true'; } catch { return false; } };
  function setEnabled(value) {
    choice = Boolean(value);
    try { localStorage.setItem(key, String(Boolean(value))); } catch { /* Still updates this window. */ }
    global.dispatchEvent(new CustomEvent('lp:furigana', {detail:{enabled:Boolean(value)}}));
  }
  function sourceText(root) {
    if (!root) return '';
    const copy = root.cloneNode(true);
    copy.querySelectorAll?.('rt,rp').forEach(node => node.remove());
    return copy.textContent || '';
  }
  const rangeText = range => sourceText(range.cloneContents());
  function textNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode(node) {
      return node.parentElement?.closest('rt,rp') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    }});
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode); return nodes;
  }
  function point(root, offset) {
    const nodes = textNodes(root); let remaining = Math.max(0, offset);
    for (const node of nodes) { if (remaining <= node.length) return [node, remaining]; remaining -= node.length; }
    const last = nodes.at(-1); return last ? [last, last.length] : [root, 0];
  }
  function range(root, start, length) {
    const value = document.createRange(); value.setStart(...point(root,start)); value.setEnd(...point(root,start+length)); return value;
  }
  async function tokens(text) {
    if (cache.has(text)) return cache.get(text);
    if (!pending.has(text)) pending.set(text, fetch('/api/reader/furigana', {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),
    }).then(async response => {
      if (!response.ok) throw new Error('假名暂时不可用');
      const result = await response.json();
      if (!Array.isArray(result.tokens) || result.tokens.map(item=>item.text).join('') !== text) throw new Error('读音与原文不匹配');
      cache.set(text,result.tokens); if(cache.size>80) cache.delete(cache.keys().next().value); return result.tokens;
    }).finally(()=>pending.delete(text)));
    return pending.get(text);
  }
  function fragment(rows) {
    const result = document.createDocumentFragment();
    for (const token of rows) {
      const parts = Array.isArray(token.parts) && token.parts.map(item=>item.text).join('') === token.text ? token.parts : [{text:token.text,reading:token.reading}];
      for (const part of parts) {
        if (!part.reading) { result.append(document.createTextNode(part.text)); continue; }
        const ruby = document.createElement('ruby'); ruby.dataset.surface=token.text;
        const base = document.createElement('rb'); base.textContent=part.text;
        const reading = document.createElement('rt'); reading.textContent=part.reading; reading.setAttribute('aria-hidden','true');
        ruby.append(base,reading); result.append(ruby);
      }
    }
    return result;
  }
  async function decorate(root) {
    const text = sourceText(root), ticket = Symbol(); active.set(root,ticket);
    const rows = await tokens(text);
    if (active.get(root) !== ticket || sourceText(root) !== text || !root.isConnected) return false;
    root.replaceChildren(fragment(rows)); root.classList.add('lp-furigana'); return true;
  }
  function clear(root) { active.delete(root); root.replaceChildren(document.createTextNode(sourceText(root))); root.classList.remove('lp-furigana'); }
  global.addEventListener('storage',event=>{if(event.key===key){choice=event.newValue==='true';global.dispatchEvent(new CustomEvent('lp:furigana',{detail:{enabled:choice}}));}});
  (global.LP ||= {}).furigana = {enabled,setEnabled,sourceText,rangeText,textNodes,range,decorate,clear};
})(window);
