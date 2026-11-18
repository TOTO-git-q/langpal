(function (global) {
  'use strict';
  const base = '/api/study-storage';
  let initialized, status = {state: 'loading', message: ''};
  const revisions = new Map(), queues = new Map(), savedFiles = new WeakSet();
  function publish(state, message) {
    status = {state, message};
    global.dispatchEvent(new CustomEvent('lp:study-storage', {detail: status}));
  }
  async function response(path, init) {
    const result = await fetch(base + path, init);
    if (!result.ok) {
      const data = await result.json().catch(() => ({}));
      const error = new Error(typeof data.detail === 'string' ? data.detail : result.status === 409 ? '别的窗口改过了' : '没连上');
      error.status = result.status; throw error;
    }
    return result;
  }
  const request = async (path, init) => (await response(path, init)).json();
  const put = (path, value) => request(path, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)});
  function serial(key, task) {
    const promise = (queues.get(key) || Promise.resolve()).catch(() => {}).then(task);
    queues.set(key, promise);
    promise.finally(() => {if (queues.get(key) === promise) queues.delete(key);}).catch(() => {});
    return promise;
  }
  async function legacyReader() {
    if (!global.indexedDB) return {documents: [], notes: []};
    if (indexedDB.databases && !(await indexedDB.databases()).some(db => db.name === 'jine-reader')) return {documents: [], notes: []};
    return new Promise((resolve, reject) => {
      const open = indexedDB.open('jine-reader');
      let absent = false;
      open.onupgradeneeded = () => { absent = true; open.transaction.abort(); };
      open.onerror = () => absent ? resolve({documents: [], notes: []}) : reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        const names = ['documents', 'notes'].filter(name => db.objectStoreNames.contains(name));
        if (!names.length) {db.close(); resolve({documents: [], notes: []}); return;}
        const tx = db.transaction(names, 'readonly'), out = {documents: [], notes: []};
        for (const name of names) {const read = tx.objectStore(name).getAll(); read.onsuccess = () => {out[name] = read.result;};}
        tx.oncomplete = () => {db.close(); resolve(out);};
        tx.onerror = tx.onabort = () => {db.close(); reject(tx.error);};
      };
    });
  }
  async function uploadDocument(doc, revision, importOnly = false) {
    const {blob, _revision, _hasFile, ...metadata} = doc;
    const form = new FormData();
    form.set('metadata', JSON.stringify(metadata)); form.set('revision', String(revision));
    form.set('importOnly', String(importOnly));
    if (blob && (importOnly || !savedFiles.has(blob))) form.set('file', blob, 'document.pdf');
    const result = await request('/document', {method: 'POST', body: form});
    if (blob && !importOnly) savedFiles.add(blob);
    return result;
  }
  async function migrate() {
    const marker = 'jine.study-storage.import.v1';
    let done;
    try { done = localStorage.getItem(marker); } catch {}
    if (done) return;   // 搬过一次就算完（以前没搬齐的那句话也不再每次报）
    const legacy = await legacyReader();
    let conflicts = 0, invalid = 0;
    async function importing(task) {try {const result = await task(); if (result.conflict || result.deleted) conflicts++;} catch (error) {if (error.status === 409) conflicts++; else if ([413, 422].includes(error.status)) invalid++; else throw error;}}
    for (const doc of legacy.documents) await importing(() => uploadDocument(doc, 0, true));
    for (const record of legacy.notes) for (const annotation of record.items || []) {
      await importing(() => put('/annotation', {documentId: record.id, annotation, revision: 0, importOnly: true}));
    }
    let text = null, drafts = {};
    try {text = localStorage.getItem('jine.listening.notes');} catch {invalid++;}
    try {drafts = JSON.parse(localStorage.getItem('jine.listening.drafts.v1') || '{}');} catch {invalid++;}
    if (!drafts || typeof drafts !== 'object' || Array.isArray(drafts)) {drafts = {}; invalid++;}
    if (text !== null) await importing(() => put('/listening-notes', {text, revision: 0, importOnly: true}));
    for (const [id, old] of Object.entries(drafts || {})) {
      if (!old || typeof old !== 'object' || Array.isArray(old)) {invalid++; continue;}
      const namedPhases = {select: 0, setup: 0, listen: 1, listening: 1, replay: 2, questions: 3, review: 4};
      let phase = old.phase ?? 0;
      if (typeof phase === 'string') phase = /^[0-4]$/.test(phase) ? Number(phase) : namedPhases[phase];
      const answers = old.answers ?? old.selections ?? [], time = old.time ?? 0;
      if (!Number.isInteger(phase) || phase < 0 || phase > 4 || typeof time !== 'number' || !Number.isFinite(time) || time < 0
        || !answers || typeof answers !== 'object') {invalid++; continue;}
      const draft = {answers, time, phase};
      await importing(() => put('/listening-draft', {id, draft, revision: 0, importOnly: true}));
    }
    try {localStorage.setItem(marker, 'complete');} catch {} // Marker only; never a second data owner.
    if (conflicts || invalid) throw new Error('有 ' + (conflicts + invalid) + ' 项旧记录没搬过来');   // 只说这一次
  }
  function ready() {
    if (!initialized) initialized = (async () => {
      try {
        const caps = await request('/capabilities');
        if (caps.version !== 1 || !caps.writable) throw new Error('没存上');
        try {await migrate(); publish('ready', '');}
        catch (error) {publish('warning', error.message);}
        return caps;
      } catch (error) {publish('unavailable', error.message); initialized = null; throw error;}
    })();
    return initialized;
  }
  function metadata(row) {
    revisions.set(row.metadata.id, row.revision);
    return {...row.metadata, _revision: row.revision, _hasFile: row.hasFile};
  }
  const api = {
    ready, request, getStatus: () => status,
    async listDocuments() {await ready(); return (await request('/documents')).documents.map(metadata);},
    async getDocument(id) {
      await ready(); let row;
      try {row = await request('/document?' + new URLSearchParams({id}));} catch (error) {if (error.status === 404) return null; throw error;}
      const doc = metadata(row);
      if (row.hasFile) {doc.blob = await (await response('/document/file?' + new URLSearchParams({id}))).blob(); savedFiles.add(doc.blob);}
      return doc;
    },
    saveDocument(doc) {return serial('doc:' + doc.id, async () => {
      await ready();
      if (!revisions.has(doc.id)) {
        try {metadata(await request('/document?' + new URLSearchParams({id: doc.id})));}
        catch (error) {if (error.status !== 404) throw error; revisions.set(doc.id, 0);}
      }
      const result = metadata(await uploadDocument(doc, revisions.get(doc.id)));
      return {...result, blob: doc.blob};
    });},
    // 删除文档（连同 PDF 和批注）。409 时 detail 是中文原因（版本不对，或附在课程管家对话里），原样抛出。
    deleteDocument(doc) {return serial('doc:' + doc.id, async () => {
      await ready();
      if (!revisions.has(doc.id)) metadata(await request('/document?' + new URLSearchParams({id: doc.id})));
      const result = await request('/document?' + new URLSearchParams({id: doc.id, revision: String(revisions.get(doc.id) ?? 0)}), {method: 'DELETE'});
      revisions.delete(doc.id);
      return result;
    });},
    async deleteListeningDraft(id) {await ready(); return request('/listening-draft?' + new URLSearchParams({id}), {method: 'DELETE'});},
    async getNotes(documentId) {await ready(); return (await request('/annotations?' + new URLSearchParams({documentId}))).annotations;},
    saveNote(documentId, annotation) {return serial('note:' + documentId + ':' + annotation.id, async () => {
      await ready(); return put('/annotation', {documentId, annotation, revision: annotation.revision || 0});
    });},
    deleteNote(documentId, annotation) {return serial('note:' + documentId + ':' + annotation.id, async () => {
      await ready(); return request('/annotation?' + new URLSearchParams({documentId, id: annotation.id, revision: annotation.revision || 0}), {method: 'DELETE'});
    });},
    async getListeningNotes() {await ready(); return request('/listening-notes');},
    async saveListeningNotes(value) {await ready(); return put('/listening-notes', value);},
    async getListeningDraft(id) {await ready(); return request('/listening-draft?' + new URLSearchParams({id}));},
    async saveListeningDraft(value) {await ready(); return put('/listening-draft', value);},
    async exportArchive() {await ready(); return (await response('/export')).blob();},
    async restoreArchive(file) {await ready(); const result = await request('/restore', {method: 'POST', headers: {'Content-Type': 'application/zip'}, body: file}); revisions.clear(); return result;},
  };
  global.LP = global.LP || {};
  global.LP.studyStorage = api;
})(window);
