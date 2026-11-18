(function (global) {
  'use strict';
  const defaults = { size: 17, line_height: 1.85, measure: 75, font: 'serif', theme: 'lilac' };
  async function request(style) {
    const response = await fetch('/api/reader/style', style ? {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(style),
    } : { cache: 'no-store' });
    if (!response.ok) throw new Error('排版设置暂时不可用');
    const data = await response.json();
    return { ...defaults, ...data };
  }
  function apply(root, style) {
    const clamp = (value, fallback, min, max) => Number.isFinite(Number(value)) && value !== ''
      ? Math.max(min, Math.min(max, Number(value))) : fallback;
    root.style.setProperty('--rd-size', clamp(style.size, 17, 14, 26) + 'px');
    root.style.setProperty('--rd-leading', clamp(style.line_height, 1.85, 1.35, 2.25));
    const size = clamp(style.size, 17, 14, 26);
    root.style.setProperty('--rd-measure', Math.round(size * clamp(style.measure, 75, 44, 90) * 0.5) + 'px');
    root.dataset.readerFont = style.font === 'sans' ? 'sans' : 'serif';
    root.dataset.readerTheme = ['lilac', 'paper', 'night'].includes(style.theme) ? style.theme : 'lilac';
  }
  (global.LP ||= {}).readerStyle = { defaults, get: () => request(), save: request, apply };
})(window);
