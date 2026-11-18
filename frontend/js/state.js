/* state.js — 共享应用状态 + 每个人设的会话兜底缓存 + 本机界面偏好。
   会话归属以后端为准（GET /api/sessions?persona_id=），localStorage 只在后端拿不到时兜底。 */
(function (global) {
  'use strict';

  const SESSION_KEY_PREFIX = 'langpal_session_persona_';

  const state = {
    personas: [],
    currentPersonaId: null,
    currentSessionId: null,
    health: { status: 'unknown', mode: 'mock', engine: 'agent_sdk', degraded: false },
  };

  function getPersona(id) {
    return state.personas.find((p) => p.id === id) || null;
  }
  function currentPersona() {
    return getPersona(state.currentPersonaId);
  }

  function loadSessionId(personaId) {
    try {
      const v = localStorage.getItem(SESSION_KEY_PREFIX + personaId);
      return v ? Number(v) : null;
    } catch { return null; }
  }
  function saveSessionId(personaId, sessionId) {
    try {
      if (sessionId == null) localStorage.removeItem(SESSION_KEY_PREFIX + personaId);
      else localStorage.setItem(SESSION_KEY_PREFIX + personaId, String(sessionId));
    } catch { /* 存不了就只靠后端 */ }
  }

  // 非语言类偏好：固定取值表，第一项是默认值。
  const fixedValues = {
    readerImages: [true, false],
    readerLookup: [false, true],
    readerPretranslate: [false, true],
    englishExam: ['toefl', 'gre'],
    paperSource: ['all', 'Europe PMC', 'Crossref', 'arXiv'],
    reviewKind: ['all', 'reading', 'listening'],
  };
  // 语言类偏好：取值跟随 LP.languages（后端语言表）。allowAll 表示允许「全部语言」（空串）。
  const languagePreferences = {
    readerLanguage: { allowAll: false, preferred: 'en' },
    listeningLanguage: { allowAll: false, preferred: 'en' },
    reviewLanguage: { allowAll: true, preferred: '' },
    notebookLanguage: { allowAll: true, preferred: '' },
  };

  function valuesFor(key) {
    if (fixedValues[key]) return fixedValues[key];
    const rule = languagePreferences[key];
    if (!rule) return [];
    const tags = (global.LP.languages?.list() || []).map((item) => item.tag);
    return rule.allowAll ? ['', ...tags] : tags;
  }
  function defaultFor(key, values) {
    const rule = languagePreferences[key];
    if (rule && values.includes(rule.preferred)) return rule.preferred;
    return values[0];
  }

  const preferences = {
    get(key) {
      const values = valuesFor(key);
      try {
        const value = JSON.parse(localStorage.getItem('jine.preference.' + key));
        if (values.includes(value)) return value;
      } catch { /* 存储被禁用时用默认值 */ }
      return defaultFor(key, values);
    },
    set(key, value) {
      if (!valuesFor(key).includes(value)) return false;
      try { localStorage.setItem('jine.preference.' + key, JSON.stringify(value)); return true; }
      catch { return false; }
    },
  };

  global.LP = global.LP || {};
  global.LP.preferences = preferences;
  global.LP.state = state;
  global.LP.getPersona = getPersona;
  global.LP.currentPersona = currentPersona;
  global.LP.loadSessionId = loadSessionId;
  global.LP.saveSessionId = saveSessionId;
})(window);
