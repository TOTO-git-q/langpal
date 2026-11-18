import { getDocument, GlobalWorkerOptions, TextLayer } from '../vendor/pdfjs/legacy/build/pdf.min.mjs';

const vendor = new URL('../vendor/pdfjs/', import.meta.url);
GlobalWorkerOptions.workerSrc = new URL('legacy/build/pdf.worker.min.mjs', vendor).href;

export async function openPDF(blob) {
  return getDocument({
    data: await blob.arrayBuffer(),
    cMapUrl: new URL('cmaps/', vendor).href,
    cMapPacked: true,
    standardFontDataUrl: new URL('standard_fonts/', vendor).href,
    wasmUrl: new URL('wasm/', vendor).href,
    enableXfa: false,
  });
}

export async function pageText(doc, index) {
  const page = await doc.getPage(index);
  const { items } = await page.getTextContent();
  let text = '';
  let lineEnd = false;
  for (const item of items) {
    if (typeof item.str !== 'string') continue;
    if (lineEnd && /[A-Za-z]-$/.test(text) && /^[a-z]/.test(item.str)) {
      text = text.slice(0, -1);
    } else if (lineEnd) {
      text += '\n';
    } else if (text && !/\s$/.test(text) && item.str && !/^\s|^[,.!?;:、。]/.test(item.str)) {
      text += ' ';
    }
    text += item.str;
    lineEnd = item.hasEOL;
  }
  return text.trim();
}

export async function renderPage(doc, index, width) {
  const page = await doc.getPage(index);
  const natural = page.getViewport({ scale: 1 });
  const scale = Math.min(1.8, Math.max(200, width) / natural.width);
  const viewport = page.getViewport({ scale });
  const wrap = document.createElement('div');
  wrap.className = 'rd-pdf-sheet';
  wrap.style.width = viewport.width + 'px';
  wrap.style.height = viewport.height + 'px';
  wrap.style.setProperty('--scale-factor', scale);
  wrap.style.setProperty('--total-scale-factor', scale * (page.userUnit || 1));
  wrap.style.setProperty('--user-unit', page.userUnit || 1);
  const canvas = document.createElement('canvas');
  const ratio = Math.max(1, Math.min(window.devicePixelRatio || 1, 2.5, 3200 / Math.max(viewport.width, viewport.height)));
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = viewport.width + 'px';
  canvas.style.height = viewport.height + 'px';
  const layer = document.createElement('div');
  layer.className = 'textLayer';
  wrap.append(canvas, layer);
  await Promise.all([
    page.render({ canvas, viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] }).promise,
    new TextLayer({ textContentSource: page.streamTextContent(), container: layer, viewport }).render(),
  ]);
  return { wrap, canvas };
}

export function cropPDF(canvas, rect) {
  const [x, y, w, h] = rect || [0, 0, 1, 1];
  const output = document.createElement('canvas');
  output.width = Math.max(1, Math.round(canvas.width * w));
  output.height = Math.max(1, Math.round(canvas.height * h));
  output.getContext('2d').drawImage(canvas, x * canvas.width, y * canvas.height, output.width, output.height,
    0, 0, output.width, output.height);
  return output.toDataURL('image/png');
}
