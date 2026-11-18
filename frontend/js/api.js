/* api.js — 所有 REST 端点的 fetch 封装。相对路径，同源托管。SSE 的 POST /chat 见 sse.js。
   原样迁移自 frontend-paper-v1（数据形状不变，只有 UI 重做）。 */
(function (global) {
  'use strict';

  const BASE = '/api';

  // 出错时 message 就是后端的中文 detail（界面直接显示）；拿不到 detail 才退回状态码。
  async function failure(res) {
    let detail = '';
    try {
      const j = await res.json();
      if (typeof j?.detail === 'string') detail = j.detail;
      else if (Array.isArray(j?.detail)) detail = j.detail.map((d) => d?.msg).filter(Boolean).join('；');
    } catch (e) { /* 不是 JSON */ }
    const err = new Error(detail || `请求失败（${res.status}）`);
    err.status = res.status;
    return err;
  }

  async function req(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(BASE + path, opts);
    if (!res.ok) throw await failure(res);
    if (res.status === 204) return null;
    return res.json();
  }

  async function reqSignal(method, path, body, signal) {
    const opts = { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    if (signal) opts.signal = signal;
    const res = await fetch(BASE + path, opts);
    if (!res.ok) throw await failure(res);
    return res.json();
  }

  // 上传走 multipart：不能带 Content-Type（浏览器要自己填 boundary），所以不复用 req()
  async function uploadFile(path, file) {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(BASE + path, { method: 'POST', body: fd });
    if (!res.ok) throw await failure(res);
    return res.json();
  }

  // 返回音频这种二进制的端点
  async function blob(method, path) {
    const res = await fetch(BASE + path, { method });
    if (!res.ok) throw await failure(res);
    return res.blob();
  }

  const api = {
    messageSpeech: (id) => blob('POST', `/chat/messages/${encodeURIComponent(id)}/speech`),
    warmMessageSpeech: (id) => req('POST', `/chat/messages/${encodeURIComponent(id)}/speech/warm`),
    warmSpeech: (language) => req('POST', '/chat/speech/warm', { language }),
    getPersonas: () => req('GET', '/personas'),
    createPersona: (body) => req('POST', '/personas', body),
    updatePersona: (id, body) => req('PUT', `/personas/${id}`, body),
    deletePersona: (id) => req('DELETE', `/personas/${id}`),
    getTeachingPresets: () => req('GET', '/teaching/presets'),
    getCourse: (lang) => req('GET', `/teaching/settings/${encodeURIComponent(lang)}`),
    saveCourse: (lang, body) => req('PUT', `/teaching/settings/${encodeURIComponent(lang)}`, body),
    getLesson: () => req('GET', '/teaching/lesson'),
    startLesson: (body) => req('POST', '/teaching/lesson/start', body),
    answerLesson: (body) => req('POST', '/teaching/lesson/answer', body),
    submitLesson: (body) => req('POST', '/teaching/lesson/submit', body),
    quizLesson: (body) => req('POST', '/teaching/lesson/quiz', body),
    stopLesson: (body) => req('POST', '/teaching/lesson/stop', body),
    // 让管家照着做一门课（COURSE-KERNEL 14）
    getBuilds: () => req('GET', '/teaching/build'),
    startBuild: (body) => req('POST', '/teaching/build', body),
    resumeBuild: (id) => req('POST', '/teaching/build/' + encodeURIComponent(id) + '/resume'),
    stopBuild: (id) => req('POST', '/teaching/build/' + encodeURIComponent(id) + '/stop'),
    deleteBuild: (id) => req('DELETE', '/teaching/build/' + encodeURIComponent(id)),
    // 世界书（docs/LORE-AND-HOOKS.md 第一节）
    getLoreBooks: () => req('GET', '/lore/books'),
    getLoreBook: (id) => req('GET', `/lore/books/${id}`),
    createLoreBook: (body) => req('POST', '/lore/books', body),
    updateLoreBook: (id, body) => req('PUT', `/lore/books/${id}`, body),
    deleteLoreBook: (id) => req('DELETE', `/lore/books/${id}`),
    importLore: (file) => uploadFile('/lore/import', file),
    loreExportUrl: (id) => `${BASE}/lore/books/${id}/export`,
    testLore: (body) => req('POST', '/lore/test', body),
    // 事件 hook（第二节）
    getHooksMeta: () => req('GET', '/hooks/meta'),
    getHookRules: () => req('GET', '/hooks/rules'),
    createHookRule: (body) => req('POST', '/hooks/rules', body),
    updateHookRule: (id, body) => req('PUT', `/hooks/rules/${id}`, body),
    deleteHookRule: (id) => req('DELETE', `/hooks/rules/${id}`),
    fireHook: (body) => req('POST', '/hooks/fire', body),
    getHookPending: () => req('GET', '/hooks/pending'),
    getHookLog: (limit = 50) => req('GET', `/hooks/log?limit=${limit}`),
    getHookVars: (personaId) => req('GET', `/hooks/vars${personaId != null ? '?persona_id=' + encodeURIComponent(personaId) : ''}`),
    putHookVar: (body) => req('PUT', '/hooks/vars', body),
    uploadPersonaAvatar: (id, file) => uploadFile(`/personas/${id}/avatar`, file),
    deletePersonaAvatar: (id) => req('DELETE', `/personas/${id}/avatar`),
    uploadChatImage: (file) => uploadFile('/uploads/image', file),
    getSettings: () => req('GET', '/settings'),
    putSettings: (patch) => req('PUT', '/settings', patch),
    getHealth: () => req('GET', '/health'),
    getUsage: () => req('GET', '/usage'),
    getEnginesStatus: () => req('GET', '/engines/status'),

    // 主聊天（docs/MAIN-CHAT.md）
    getMainChat: () => req('GET', '/chat/main'),
    putMainChat: (patch) => req('PUT', '/chat/main', patch),
    getMainMessages: ({ before, limit } = {}) => req('GET', '/chat/main/messages?' + new URLSearchParams(Object.entries({ before, limit }).filter(([, v]) => v != null))),
    getChatArchives: () => req('GET', '/chat/archives'),
    getChatArchive: (id) => req('GET', `/chat/archives/${id}`),
    getStickers: () => req('GET', '/stickers'),

    explainWord: (body, signal) => reqSignal('POST', '/explain/word', body, signal),
    explainWords: (body, signal) => reqSignal('POST', '/explain/words', body, signal),
    explainSentence: (body, signal) => reqSignal('POST', '/explain/sentence', body, signal),

    getVocab: (language) => req('GET', `/vocab${language ? '?language=' + encodeURIComponent(language) : ''}`),
    addVocab: (body) => req('POST', '/vocab', body),
    deleteVocab: (id) => req('DELETE', `/vocab/${id}`),
    getPatterns: (language) => req('GET', `/patterns${language ? '?language=' + encodeURIComponent(language) : ''}`),
    addPattern: (body) => req('POST', '/patterns', body),
    deletePattern: (id) => req('DELETE', `/patterns/${id}`),

    getMemory: (personaId) => req('GET', `/memory${personaId ? '?persona_id=' + personaId : ''}`),
    createMemory: (body) => req('POST', '/memory', body),
    patchMemory: (id, patch) => req('PUT', `/memory/${id}`, patch),
    deleteMemory: (id) => req('DELETE', `/memory/${id}`),
  };

  global.LP = global.LP || {};
  global.LP.api = api;
})(window);
