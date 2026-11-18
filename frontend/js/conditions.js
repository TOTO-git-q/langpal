/* conditions.js — 条件编辑器（世界书条目和事件规则共用）。一行一个条件：字段 / 比较符 / 值，全部满足才算。
   字段和比较符来自 GET /api/hooks/meta 的 condition_fields，不写死：
     [{key, label, type, ops, options?}]   type: number | text | bool | any
   key 是 "var.*" / "event.*" 这种前缀时，后面要再填一个名字，存成 var.<名字>。
   额外字段（事件规则里的 event.*）由调用方传进来，同样的形状。
   一个条件存成 {field, op, value}；in → 数组，between → [下限, 上限]。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const OP_LABELS = { '==': '等于', '!=': '不等于', '>': '大于', '>=': '至少', '<': '小于', '<=': '至多', in: '属于', between: '介于', contains: '包含' };
  const DEFAULT_OPS = {
    number: ['==', '!=', '>', '>=', '<', '<=', 'between', 'in'],
    bool: ['==', '!='],
    text: ['==', '!=', 'contains', 'in'],
    any: ['==', '!=', '>', '>=', '<', '<=', 'in', 'between', 'contains'],
  };
  const kind = (field) => ({ boolean: 'bool', string: 'text' })[field?.type] || field?.type || 'text';
  const opsFor = (field) => (Array.isArray(field?.ops) && field.ops.length ? field.ops : DEFAULT_OPS[kind(field)] || DEFAULT_OPS.text);
  // 前缀字段：key 写成 "var.*"（旧写法 "var." 也认），返回 "var."
  const prefixOf = (field) => (field?.key.endsWith('.*') ? field.key.slice(0, -1) : field?.key.endsWith('.') ? field.key : null);

  // field 存的是完整 key（var.night_owl）；找它属于哪个定义
  function definitionFor(fields, key) {
    return fields.find((f) => f.key === key) || fields.find((f) => prefixOf(f) && key.startsWith(prefixOf(f))) || null;
  }

  function parseScalar(field, raw) {
    const text = String(raw).trim();
    const type = kind(field);
    if (type === 'number') return text === '' ? null : Number(text);
    if (type === 'bool') return text === 'true';
    // any（变量、事件数据）：像数字就存数字，true/false 存真假，其余存文字
    if (type === 'any') {
      if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
      if (text === 'true' || text === 'false') return text === 'true';
    }
    return text;
  }

  function create({ fields = [], value = [], onChange, max = Infinity } = {}) {
    let defs = fields;
    const root = el('div', '', 'cond-editor');
    const list = el('div', '', 'cond-list');
    const add = button('+ 条件', () => { if (list.children.length < max) { list.append(row({})); changed(); } }, 'cond-add');
    root.append(list, add);

    function changed() { add.disabled = list.children.length >= max; onChange?.(read()); }

    function row(cond) {
      const line = el('div', '', 'cond-row');
      const fieldSel = el('select', '', 'cond-field');
      fieldSel.setAttribute('aria-label', '字段');
      const nameInput = el('input', '', 'cond-name');
      nameInput.placeholder = '名字';
      nameInput.setAttribute('aria-label', '名字');
      const opSel = el('select', '', 'cond-op');
      opSel.setAttribute('aria-label', '比较');
      const valueBox = el('span', '', 'cond-value');
      const remove = button('×', () => { line.remove(); changed(); }, 'cond-remove');
      remove.setAttribute('aria-label', '删除这个条件');

      const known = definitionFor(defs, cond.field || '');
      const options = [...defs];
      // 当前值的字段不在列表里（比如换了事件之后的 event.*）：照样留着，不偷偷删掉
      if (cond.field && !known) options.push({ key: cond.field, label: cond.field, type: typeof cond.value === 'number' ? 'number' : 'text' });
      fieldSel.append(...options.map((f) => new Option(f.label || f.key, f.key)));
      fieldSel.value = known ? known.key : (cond.field || defs[0]?.key || '');
      if (prefixOf(known)) nameInput.value = cond.field.slice(prefixOf(known).length);

      function def() { return definitionFor(options, fieldSel.value); }
      function paintOps(keep) {
        const ops = opsFor(def());
        opSel.replaceChildren(...ops.map((op) => new Option(OP_LABELS[op] || op, op)));
        opSel.value = ops.includes(keep) ? keep : ops[0];
      }
      function input(initial) {
        const d = def();
        if (Array.isArray(d?.options) && d.options.length) {
          const select = el('select');
          select.append(...d.options.map((o) => (typeof o === 'object' ? new Option(o.label ?? o.value, o.value) : new Option(o, o))));
          if (initial != null) select.value = String(initial);
          return select;
        }
        if (kind(d) === 'bool') {
          const select = el('select');
          select.append(new Option('是', 'true'), new Option('否', 'false'));
          select.value = String(initial ?? true);
          return select;
        }
        const field = el('input');
        field.type = kind(d) === 'number' ? 'number' : 'text';
        if (initial != null) field.value = String(initial);
        return field;
      }
      function paintValue(current) {
        valueBox.replaceChildren();
        if (opSel.value === 'between') {
          const [lo, hi] = Array.isArray(current) ? current : [current, null];
          const a = input(lo), b = input(hi);
          a.setAttribute('aria-label', '下限'); b.setAttribute('aria-label', '上限');
          valueBox.append(a, el('span', '到', 'cond-to'), b);
        } else if (opSel.value === 'in') {
          const field = el('input');
          field.placeholder = '用逗号分开';
          field.setAttribute('aria-label', '可选值');
          field.value = Array.isArray(current) ? current.join(', ') : (current ?? '');
          valueBox.append(field);
        } else {
          const field = input(Array.isArray(current) ? current[0] : current);
          field.setAttribute('aria-label', '值');
          valueBox.append(field);
        }
      }
      line.read = () => {
        const d = def();
        const key = prefixOf(d) ? prefixOf(d) + nameInput.value.trim() : fieldSel.value;
        const controls = [...valueBox.querySelectorAll('input, select')];
        let v;
        if (opSel.value === 'between') v = controls.map((c) => parseScalar(d, c.value));
        else if (opSel.value === 'in') v = controls[0].value.split(/[,，、]/).map((x) => x.trim()).filter(Boolean).map((x) => parseScalar(d, x));
        else v = parseScalar(d, controls[0]?.value ?? '');
        return { field: key, op: opSel.value, value: v };
      };
      function paintName() { nameInput.hidden = !prefixOf(def()); }

      paintOps(cond.op);
      paintValue(cond.value);
      paintName();
      fieldSel.onchange = () => { paintOps(opSel.value); paintValue(null); paintName(); changed(); };
      opSel.onchange = () => { paintValue(null); changed(); };
      line.addEventListener('input', changed);
      line.append(fieldSel, nameInput, opSel, valueBox, remove);
      return line;
    }

    // 前缀字段没填名字的不算（var. 后面空着）
    function read() { return [...list.children].map((line) => line.read()).filter((c) => c.field && !c.field.endsWith('.')); }
    function set(conditions) { list.replaceChildren(...(conditions || []).map(row)); add.disabled = list.children.length >= max; }
    // 换了一套可选字段（比如事件规则换了事件）：保留已填的条件，重画下拉
    function setFields(next) { const current = read(); defs = next; set(current); }

    set(value);
    return { element: root, read, set, setFields };
  }

  // 一句话概括条件（列表里用）
  function summarize(conditions, fields = []) {
    return (conditions || []).map((c) => {
      const d = definitionFor(fields, c.field);
      const label = d ? (prefixOf(d) ? c.field : d.label || d.key) : c.field;
      const value = Array.isArray(c.value) ? c.value.join(c.op === 'between' ? '–' : '、') : String(c.value);
      return `${label}${OP_LABELS[c.op] || c.op}${value}`;
    }).join('，');
  }

  // GET /api/hooks/meta 只读一次（失败了下次再试）；世界书和事件页共用
  let metaRequest = null;
  function meta() {
    metaRequest ||= global.LP.api.getHooksMeta().catch((error) => { metaRequest = null; throw error; });
    return metaRequest;
  }

  global.LP = global.LP || {};
  global.LP.conditions = { create, summarize, meta, OP_LABELS };
})(window);
