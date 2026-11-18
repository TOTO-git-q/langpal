// LangPal desktop shell — preload script.
//
// Exposes a small, frozen contract on window.langpalDesktop so the frontend
// (which also has to run standalone in a plain browser tab) can feature-test
// `window.langpalDesktop?.isDesktop` and draw its own window-control buttons
// when running inside the Electron shell.
//
// contextIsolation is on and nodeIntegration is off, so this is the only
// bridge between the renderer and the main process.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('langpalDesktop', Object.freeze({
  minimize: () => ipcRenderer.send('win:minimize'),
  toggleMaximize: () => ipcRenderer.send('win:toggle-maximize'),
  close: () => ipcRenderer.send('win:close'),
  // 「授業」页：确保口语课服务在跑（必要时由主进程拉起），返回 {ok, url} 或 {ok:false, error}
  ensureCoach: () => ipcRenderer.invoke('coach:ensure'),
  openChatGPTLogin: url => ipcRenderer.invoke('chatgpt:open-sign-in', url),
  // 角色窗口（frontend/stage.html）：主窗口用 open/close，角色窗口自己用 minimize/close/onCursor
  stage: Object.freeze({
    open: character => ipcRenderer.send('stage:open', String(character || '')),
    close: () => ipcRenderer.send('stage:close'),
    minimize: () => ipcRenderer.send('stage:minimize'),
    onCursor: callback => { ipcRenderer.on('stage:cursor', (_event, point) => callback(point)); },
  }),
  isDesktop: true,
}));
