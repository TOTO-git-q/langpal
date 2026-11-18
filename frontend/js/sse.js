/* sse.js — 主聊天的 SSE 手动解析（EventSource 不支持 POST，用 fetch+ReadableStream）。见 docs/MAIN-CHAT.md 第四节：
   POST /api/chat {text, image_url?, sticker?, to?}；POST /api/chat/proactive {} 或 {persona_id}
   每个事件带 persona_id / persona_name / language：
   queued | system {kind:"enter",text,message_id}（主动开口时不在场的人进来）| speaker {persona_id,persona_name,language,role}
   | read {message_ids} | guard {status,retries,mood}
   | delta {text,bubble} | bubble_done {bubble,message_id,tokens,sticker} | done {message_ids} | interrupted | error {message} */
(function (global) {
  'use strict';

  function postChat(body, handlers) {
    return stream('/api/chat', body, handlers);
  }

  // 她主动开口：事件和普通回复一样（多带 proactive:true）；没有待发时直接 done{empty:true}。
  function postProactive(body, handlers) {
    return stream('/api/chat/proactive', body || {}, handlers);
  }

  // 出错时 onError({message}) 的 message 只给控制台看，界面上不直接显示
  function stream(url, body, handlers) {
    handlers = handlers || {};
    let terminal = false;
    const callbacks = handlers;
    handlers = {};
    for (const key of ['onSession', 'onQueued', 'onRead', 'onSpeaker', 'onSystem', 'onGuard', 'onDelta', 'onBubbleDone', 'onAction', 'onDone', 'onInterrupted', 'onError']) {
      handlers[key] = (data) => {
        if (terminal) return;
        if (['onQueued', 'onDone', 'onInterrupted', 'onError'].includes(key)) terminal = true;
        if (callbacks[key]) callbacks[key](data);
      };
    }

    (async () => {
      let res;
      try {
        res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
      } catch (e) {
        handlers.onError({ message: String(e) });
        return;
      }

      if (!res.ok || !res.body) {
        let detail = res.statusText;
        try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
        handlers.onError({ message: detail });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';

      try {
        while (!terminal) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let boundary;
          while (!terminal && (boundary = /\r\n\r\n|\n\n|\r\r/.exec(buf))) {
            const frame = buf.slice(0, boundary.index);
            buf = buf.slice(boundary.index + boundary[0].length);
            dispatchFrame(frame, handlers);
          }
        }
        buf += decoder.decode();
        if (!terminal && buf.trim()) dispatchFrame(buf, handlers);
        if (!terminal) handlers.onError({ message: 'stream ended early' });
      } catch (e) {
        handlers.onError({ message: String(e) });
      } finally {
        // Terminal events finish this request even if a proxy keeps the socket open.
        reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    })();
  }

  function dispatchFrame(frame, handlers) {
    let event = 'message';
    const dataLines = [];
    for (const rawLine of frame.split(/\r\n|\r|\n/)) {
      const line = rawLine.replace(/\r$/, '');
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    let data;
    try { data = JSON.parse(dataLines.join('\n')); } catch (e) { return; }

    switch (event) {
      case 'session': handlers.onSession(data); break;
      case 'queued': handlers.onQueued(data); break;
      case 'read': handlers.onRead(data); break;
      case 'speaker': handlers.onSpeaker(data); break;
      case 'system': handlers.onSystem(data); break;
      case 'guard': handlers.onGuard(data); break;
      case 'delta': handlers.onDelta(data); break;
      case 'bubble_done': handlers.onBubbleDone(data); break;
      case 'action': handlers.onAction(data); break;
      case 'done': handlers.onDone(data); break;
      case 'interrupted': handlers.onInterrupted(data); break;
      case 'error': handlers.onError(data); break;
      default: break;
    }
  }

  global.LP = global.LP || {};
  global.LP.sse = { postChat, postProactive };
})(window);
