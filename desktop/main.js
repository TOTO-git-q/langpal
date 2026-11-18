// LangPal desktop shell — main process.
//
// Responsibilities:
//   1. Single-instance lock (second launch focuses the existing window).
//   2. Backend lifecycle: reuse an already-running backend on :8787 if one
//      exists (e.g. started by the user's run.bat), otherwise spawn our own
//      uvicorn child process and tree-kill it on quit. Never touch a backend
//      we did not start ourselves.
//   3. A frameless BrowserWindow loading the backend-served frontend, with
//      window position/size persisted across launches.
//   4. IPC for the custom window-control buttons the frontend draws itself
//      (win:minimize / win:toggle-maximize / win:close).

const { app, BrowserWindow, ipcMain, dialog, screen, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn, spawnSync } = require('child_process');

// ---------------------------------------------------------------------------
// Paths — everything resolved to absolute paths from this file's location so
// it does not matter what the current working directory is when launched.
// ---------------------------------------------------------------------------
function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, 'langpal.config.json'), 'utf8'));
  } catch {
    return {}; // 没有配置文件 / 格式坏了 = 本地模式，和以前一样
  }
}
const CONFIG = readConfig();

// 装到 %LOCALAPPDATA%\Programs\LangPal 的启动器里 __dirname 是 resources\app，
// 本地模式要靠 config 的 projectRoot 找回项目目录（.venv / backend / data 都在那）。
// 发给别人的便携版：projectRoot、python 写相对路径，相对的是 LangPal.exe 所在的文件夹。
const EXE_DIR = path.dirname(process.execPath);
const ROOT_DIR = CONFIG.projectRoot ? path.resolve(EXE_DIR, CONFIG.projectRoot) : path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const VENV_PYTHON = CONFIG.python ? path.resolve(ROOT_DIR, CONFIG.python) : path.join(ROOT_DIR, '.venv', 'Scripts', 'python.exe');
const ICON_PATH = path.join(ROOT_DIR, 'frontend', 'assets', 'icons', 'jine.png');

const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8787;

// 远程后端模式：只当纯客户端——不探活本地、不 spawn、不 kill，退出也不动远端服务。
// 地址来源优先级：环境变量 LANGPAL_BACKEND_URL > desktop/langpal.config.json 的 backendUrl。
// 之所以要支持配置文件：Windows 的快捷方式/任务栏固定项没法带环境变量，只有把地址写进
// 文件，LangPal.exe 才能被直接双击或固定到任务栏（见 README 的"图标与固定"一节）。
function readConfiguredBackendUrl() {
  const fromEnv = (process.env.LANGPAL_BACKEND_URL || '').trim();
  if (fromEnv) return fromEnv;
  return String(CONFIG.backendUrl || '').trim();
}

const REMOTE_URL = readConfiguredBackendUrl().replace(/\/+$/, '');
const BASE_URL = REMOTE_URL || `http://${BACKEND_HOST}:${BACKEND_PORT}`;
const HEALTH_URL = `${BASE_URL}/api/health`;
const APP_URL = `${BASE_URL}/`;

const WINDOW_STATE_FILE = () => path.join(app.getPath('userData'), 'window-state.json');
const SELFTEST = !!process.env.LANGPAL_SELFTEST_OUT;
if (SELFTEST) {
  app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
  app.commandLine.appendSwitch('disable-renderer-backgrounding');
}

const DEFAULT_WIDTH = 1100;
const DEFAULT_HEIGHT = 760;
const MIN_WIDTH = 900;
const MIN_HEIGHT = 600;
const BG_COLOR = '#f7e1fb';

let win = null;
let backendProcess = null; // set only when WE spawned the backend
let backendOwnedByUs = false;

// ---------------------------------------------------------------------------
// Single instance lock
// ---------------------------------------------------------------------------
// Windows 任务栏身份：不设的话每个 Electron 应用都被归到"Electron"这个通用身份下，
// 固定到任务栏时拿的是 electron.exe 的默认图标、而且运行中的窗口和固定项不合并。
// 这个 id 要和 LangPal.exe 的身份一致（见 desktop/README.md 的"图标与固定"）。
if (process.platform === 'win32') {
  app.setAppUserModelId('com.langpal.desktop');
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      if (!win.isVisible()) win.show();
      win.focus();
    }
  });

  app.whenReady().then(bootstrap);

  app.on('activate', () => {
    // macOS-style re-activate; harmless no-op on Windows since we don't quit
    // on window-all-closed until backend cleanup finishes anyway.
    if (BrowserWindow.getAllWindows().length === 0 && win === null) {
      createWindow();
    }
  });
}

// ---------------------------------------------------------------------------
// Backend health check / spawn / tree-kill
// ---------------------------------------------------------------------------
function checkHealth(timeoutMs = 1000, url = HEALTH_URL) {
  return new Promise((resolve) => {
    let settled = false;
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      // Drain the response so the socket can be reused/closed cleanly.
      res.resume();
      if (!settled) {
        settled = true;
        resolve(res.statusCode === 200);
      }
    });
    req.on('timeout', () => {
      if (!settled) {
        settled = true;
        req.destroy();
        resolve(false);
      }
    });
    req.on('error', () => {
      if (!settled) {
        settled = true;
        resolve(false);
      }
    });
  });
}

async function waitForHealth(maxMs, intervalMs) {
  const start = Date.now();
  // Try immediately once before the first wait.
  if (await checkHealth(1000)) return true;
  while (Date.now() - start < maxMs) {
    await new Promise((r) => setTimeout(r, intervalMs));
    if (await checkHealth(1000)) return true;
  }
  return false;
}

function spawnBackend() {
  if (!fs.existsSync(VENV_PYTHON)) {
    throw new Error(
      `找不到 venv 的 python.exe：${VENV_PYTHON}\n` +
      '请先在项目根目录运行一次 run.bat 建好虚拟环境，或手动创建 .venv。'
    );
  }
  // 便携版自带的 Kokoro（听力的发声）：路径写在 config 里，相对 projectRoot；没写就照旧读后端的 .env
  const env = { ...process.env };
  if (CONFIG.kokoro?.python && CONFIG.kokoro?.assets) {
    env.LANGPAL_LISTENING_TTS_PYTHON = path.resolve(ROOT_DIR, CONFIG.kokoro.python);
    env.LANGPAL_LISTENING_TTS_ASSETS = path.resolve(ROOT_DIR, CONFIG.kokoro.assets);
  }
  if (CONFIG.voicevox) {
    env.LANGPAL_VOICEVOX_ENGINE = path.resolve(EXE_DIR, CONFIG.voicevox);
  }
  const child = spawn(
    VENV_PYTHON,
    ['-m', 'uvicorn', 'app.main:app', '--app-dir', BACKEND_DIR, '--port', String(BACKEND_PORT)],
    {
      cwd: ROOT_DIR,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    }
  );
  backendProcess = child;
  backendOwnedByUs = true;
  child.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`));
  child.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`));
  child.on('exit', (code, signal) => {
    console.log(`[backend] child process exited (code=${code} signal=${signal})`);
    if (backendProcess === child) {
      backendProcess = null;
      backendOwnedByUs = false;
    }
  });
  child.on('error', (err) => {
    console.error('[backend] failed to start:', err);
  });
  return child;
}

// Kill only the backend process WE spawned, by PID, tree-killed via taskkill
// /PID <pid> /T /F. Never taskkill /IM — that would kill every process with
// the same image name system-wide.
function killOwnedBackend() {
  if (!backendOwnedByUs || !backendProcess || backendProcess.pid == null) return;
  const pid = backendProcess.pid;
  backendOwnedByUs = false;
  const target = backendProcess;
  backendProcess = null;
  try {
    console.log(`[backend] tree-killing owned backend pid=${pid}`);
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true });
  } catch (e) {
    console.error('[backend] taskkill failed:', e);
    try { target.kill(); } catch {}
  }
}

// ---------------------------------------------------------------------------
// 口语课（speaking-coach）：JINE 的「授業」页嵌的是它自己的 Node 服务（127.0.0.1:3210，
// 转写服务 3211 由它自己带起）。第一次点开那个 tab 时前端经 IPC 请求启动，开机不启动、不占显卡。
// 已经在跑（用户自己开了 start.bat）就复用、不管它的死活；没在跑就拉起 scripts/serve.mjs
// （不开浏览器），退出时按 PID 树杀——只杀自己拉起的那一棵。
// ---------------------------------------------------------------------------
const COACH_ROOT = CONFIG.coachRoot ? path.resolve(EXE_DIR, CONFIG.coachRoot) : path.resolve(ROOT_DIR, '..', 'speaking-coach');
const COACH_URL = 'http://127.0.0.1:3210';
const COACH_HEALTH = `${COACH_URL}/api/health`;
let coachProcess = null;   // set only when WE spawned it
let coachStarting = null;  // in-flight ensure, so two clicks never spawn twice

// 优先用系统装的 node；找不到就让 Electron 自己当 node 跑（ELECTRON_RUN_AS_NODE）。
function resolveNode() {
  try {
    const r = spawnSync('where', ['node'], { windowsHide: true, encoding: 'utf8' });
    const hit = String(r.stdout || '').split(/\r?\n/).map((s) => s.trim()).find((p) => p && fs.existsSync(p));
    if (hit) return { exe: hit, env: {} };
  } catch {}
  return { exe: process.execPath, env: { ELECTRON_RUN_AS_NODE: '1' } };
}

function spawnCoach() {
  if (CONFIG.coach === false) throw new Error('这个版本没有带口语课程序。');   // 便携版不带口语课（它有好几个 G）
  const script = path.join(COACH_ROOT, 'scripts', 'serve.mjs');
  if (!fs.existsSync(script)) {
    throw new Error(`找不到口语课：${COACH_ROOT}\n在 desktop/langpal.config.json 的 coachRoot 里填口语课所在的文件夹。`);
  }
  if (!fs.existsSync(path.join(COACH_ROOT, 'server', 'dist', 'index.js')) || !fs.existsSync(path.join(COACH_ROOT, 'web', 'dist', 'index.html'))) {
    throw new Error('口语课还没有构建。先双击 speaking-coach 文件夹里的 start.bat 一次（会自动安装和构建），关掉它再回来点「再试一次」。');
  }
  const node = resolveNode();
  const child = spawn(node.exe, [script], {
    cwd: COACH_ROOT,
    env: { ...process.env, ...node.env },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  coachProcess = child;
  child.stdout.on('data', (d) => process.stdout.write(`[coach] ${d}`));
  child.stderr.on('data', (d) => process.stderr.write(`[coach] ${d}`));
  child.on('exit', (code, signal) => {
    console.log(`[coach] process exited (code=${code} signal=${signal})`);
    if (coachProcess === child) coachProcess = null;
  });
  child.on('error', (err) => console.error('[coach] failed to start:', err));
  return child;
}

function killOwnedCoach() {
  if (!coachProcess || coachProcess.pid == null) return;
  const target = coachProcess;
  coachProcess = null;
  try {
    console.log(`[coach] tree-killing owned coach pid=${target.pid}`);
    spawnSync('taskkill', ['/PID', String(target.pid), '/T', '/F'], { windowsHide: true });
  } catch (e) {
    console.error('[coach] taskkill failed:', e);
    try { target.kill(); } catch {}
  }
}

async function ensureCoach() {
  if (await checkHealth(1000, COACH_HEALTH)) return { ok: true, url: COACH_URL };
  if (!coachStarting) {
    coachStarting = (async () => {
      try {
        if (!coachProcess) spawnCoach();
      } catch (e) {
        return { ok: false, error: String((e && e.message) || e) };
      }
      const start = Date.now();
      while (Date.now() - start < 45000) {
        if (await checkHealth(1000, COACH_HEALTH)) return { ok: true, url: COACH_URL };
        if (!coachProcess) {
          return { ok: false, error: '口语课服务一启动就退出了。双击 speaking-coach 文件夹里的 start.bat，看窗口里报什么错。' };
        }
        await new Promise((r) => setTimeout(r, 400));
      }
      killOwnedCoach();
      return { ok: false, error: '口语课服务 45 秒内没有就绪。' };
    })().finally(() => { coachStarting = null; });
  }
  return coachStarting;
}

ipcMain.handle('coach:ensure', () => ensureCoach());

ipcMain.handle('chatgpt:open-sign-in', async (event, value) => {
  if (!win || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame) {
    throw new Error('请从 JINE 设置打开登录。');
  }
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port ||
      url.username || url.password || url.hash || url.pathname !== '/begin' ||
      [...url.searchParams.keys()].join(',') !== 'ticket' ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(url.searchParams.get('ticket') || '')) {
    throw new Error('登录地址无效。');
  }
  await shell.openExternal(url.href);
  return { opened: true };
});

// ---------------------------------------------------------------------------
// Bootstrap: decide reuse vs spawn, then create the window.
// ---------------------------------------------------------------------------
async function bootstrap() {
  if (REMOTE_URL) {
    // 纯客户端模式：只等远端就绪，不管理任何进程
    const ok = await waitForHealth(15000, 1000);
    if (!ok) {
      dialog.showErrorBox(
        'LangPal 远程后端不可达',
        `${HEALTH_URL}\n请确认小主机上的 langpal 服务在跑、本机 Tailscale 已连接。`
      );
      app.quit();
      return;
    }
    createWindow();
    return;
  }
  const alreadyRunning = await checkHealth(1000);
  if (alreadyRunning) {
    console.log('[backend] found an existing healthy backend on :8787 — reusing it (will not manage its lifecycle)');
  } else {
    console.log('[backend] no backend detected on :8787 — spawning our own uvicorn process');
    try {
      spawnBackend();
    } catch (e) {
      dialog.showErrorBox('LangPal 启动失败', String((e && e.message) || e));
      app.quit();
      return;
    }
    const ok = await waitForHealth(30000, 500);
    if (!ok) {
      dialog.showErrorBox(
        'LangPal 启动失败',
        `后端服务在 30 秒内未就绪：${HEALTH_URL}\n请检查 backend 依赖是否已安装（.venv 是否完整）。`
      );
      killOwnedBackend();
      app.quit();
      return;
    }
    console.log('[backend] our spawned backend is healthy');
  }
  createWindow();
}

// ---------------------------------------------------------------------------
// Window state persistence (hand-written userData JSON)
// ---------------------------------------------------------------------------
function loadWindowState() {
  try {
    const raw = fs.readFileSync(WINDOW_STATE_FILE(), 'utf8');
    const s = JSON.parse(raw);
    if (typeof s.width === 'number' && typeof s.height === 'number') return s;
  } catch {}
  return null;
}

function clampToVisibleArea(bounds, least = { width: MIN_WIDTH, height: MIN_HEIGHT }) {
  const displays = screen.getAllDisplays();
  const width = Math.max(least.width, Math.round(bounds.width || DEFAULT_WIDTH));
  const height = Math.max(least.height, Math.round(bounds.height || DEFAULT_HEIGHT));
  let x = bounds.x;
  let y = bounds.y;
  const fitsSomewhere = typeof x === 'number' && typeof y === 'number' && displays.some((d) => {
    const a = d.workArea;
    return x + 50 > a.x && x < a.x + a.width - 50 && y + 50 > a.y && y < a.y + a.height - 50;
  });
  if (!fitsSomewhere) {
    x = undefined;
    y = undefined;
  }
  return { width, height, x, y };
}

// 关掉时什么样，下次就什么样：记「还原时」的位置大小（最小化、最大化时 getBounds 给的是 -32000 或整屏，
// 不能记），另记是不是最大化。拖动时事件很密，攒 300ms 写一次；关窗前再同步写一次。
let saveTimer = null;
function saveWindowState() {
  if (SELFTEST || !win || win.isDestroyed()) return;
  clearTimeout(saveTimer);
  saveTimer = null;
  try {
    const bounds = win.getNormalBounds();
    bounds.maximized = win.isMaximized();
    bounds.zoom = win.webContents.getZoomFactor();
    fs.writeFileSync(WINDOW_STATE_FILE(), JSON.stringify(bounds));
  } catch (e) {
    console.error('[window-state] failed to save:', e);
  }
}
function saveWindowStateSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveWindowState, 300);
}

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------
function createWindow() {
  const saved = loadWindowState();
  const bounds = clampToVisibleArea(
    saved || { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
  );

  const options = {
    width: bounds.width,
    height: bounds.height,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    backgroundColor: BG_COLOR,
    frame: false,
    // 无边框窗口的可缩放性显式钉死：thickFrame 提供 Windows 原生的边缘缩放热区
    // （顶边被标题栏 drag 区覆盖的部分由前端 #win-resize-topstrip 让出来）。
    resizable: true,
    thickFrame: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  };
  if (bounds.x !== undefined && bounds.y !== undefined) {
    options.x = bounds.x;
    options.y = bounds.y;
  }
  if (SELFTEST) {
    // 自检窗口放到屏幕外、不节流，不弹到用户桌面上
    options.x = -20000;
    options.y = -20000;
    options.webPreferences.backgroundThrottling = false;
  }
  if (fs.existsSync(ICON_PATH)) {
    options.icon = ICON_PATH;
  }

  win = new BrowserWindow(options);

  win.once('ready-to-show', () => {
    if (saved?.maximized && !SELFTEST) win.maximize();
    win.show();
  });
  for (const event of ['resize', 'move', 'maximize', 'unmaximize']) win.on(event, saveWindowStateSoon);
  win.on('close', saveWindowState);

  // 界面缩放：无菜单栏的 frameless 窗口没有默认加速键，这里手接 Ctrl+= / Ctrl+- / Ctrl+0。
  // 倍率跟随 window-state 持久化，下次启动恢复。
  const ZOOM_MIN = 0.6, ZOOM_MAX = 1.8, ZOOM_STEP = 0.1;
  win.webContents.on('before-input-event', (e, input) => {
    if (!input.control || input.type !== 'keyDown') return;
    const z = win.webContents.getZoomFactor();
    if (input.key === '=' || input.key === '+') {
      win.webContents.setZoomFactor(Math.min(ZOOM_MAX, Math.round((z + ZOOM_STEP) * 10) / 10));
    } else if (input.key === '-') {
      win.webContents.setZoomFactor(Math.max(ZOOM_MIN, Math.round((z - ZOOM_STEP) * 10) / 10));
    } else if (input.key === '0') {
      win.webContents.setZoomFactor(1);
    } else {
      return;
    }
    e.preventDefault();
    saveWindowState();
  });
  win.webContents.once('did-finish-load', () => {
    if (saved && typeof saved.zoom === 'number' && saved.zoom >= ZOOM_MIN && saved.zoom <= ZOOM_MAX) {
      win.webContents.setZoomFactor(saved.zoom);
    }
  });
  win.on('closed', () => { win = null; });

  win.webContents.on('console-message', (event) => {
    // Electron >=9 passes a single event object with level/message/lineNumber/sourceId.
    const { level, message, lineNumber, sourceId } = event;
    console.log(`[renderer:${level}] ${message} (${sourceId}:${lineNumber})`);
  });
  win.webContents.on('did-fail-load', (_e, errorCode, errorDescription, validatedURL) => {
    console.error(`[renderer] did-fail-load ${errorCode} ${errorDescription} ${validatedURL}`);
  });

  // 前端大改版后，持久 profile 里的启发式 HTTP 缓存会拿旧 JS 配新 HTML（真踩过：
  // 旧版 setWallpaper 报错）。后端已加 Cache-Control: no-cache，这里再清一次兜底。
  win.webContents.session.clearCache().finally(() => win.loadURL(APP_URL));
}

// ---------------------------------------------------------------------------
// 角色窗口：一扇跟着主窗口的小窗（frontend/stage.html?c=<角色>）。它是主窗口的子窗口，
// 所以只浮在主窗口上面、不盖别的程序，主窗口最小化/关闭时一起走。位置大小单独记。
// 主进程每 60ms 把鼠标位置（相对她的脸、按屏幕归一化）发过去，她的视线才能跟到窗口外面。
// ---------------------------------------------------------------------------
const STAGE_STATE_FILE = () => path.join(app.getPath('userData'), 'stage-window.json');
const STAGE_DEFAULT = { width: 340, height: 620 };
let stageWin = null;
let stageCursorTimer = null;

function stageBounds() {
  let saved = null;
  try { saved = JSON.parse(fs.readFileSync(STAGE_STATE_FILE(), 'utf8')); } catch (e) { /* 第一次打开 */ }
  if (saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)) return clampToVisibleArea(saved, { width: 220, height: 320 });
  // 默认贴在主窗口右边；右边放不下就压在主窗口右沿里面
  const main = win.getBounds();
  const area = screen.getDisplayMatching(main).workArea;
  let x = main.x + main.width + 8;
  if (x + STAGE_DEFAULT.width > area.x + area.width) x = main.x + main.width - STAGE_DEFAULT.width - 16;
  const y = Math.max(area.y, Math.min(main.y + 56, area.y + area.height - STAGE_DEFAULT.height));
  return { x, y, ...STAGE_DEFAULT };
}

function saveStageBounds() {
  if (SELFTEST || !stageWin || stageWin.isDestroyed() || stageWin.isMinimized()) return;
  try { fs.writeFileSync(STAGE_STATE_FILE(), JSON.stringify(stageWin.getNormalBounds())); } catch (e) { console.error('[stage-window] failed to save:', e); }
}

function openStage(character) {
  if (!win || win.isDestroyed()) return;
  const id = /^[a-z0-9_-]{1,40}$/i.test(character || '') ? character : 'ame';
  if (stageWin && !stageWin.isDestroyed()) { if (stageWin.isMinimized()) stageWin.restore(); stageWin.show(); return; }
  const bounds = stageBounds();
  const options = {
    ...bounds, minWidth: 220, minHeight: 320, parent: win, frame: false, resizable: true, thickFrame: true,
    skipTaskbar: true, maximizable: false, fullscreenable: false, show: false, backgroundColor: '#e29de4',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true, backgroundThrottling: false },
  };
  if (SELFTEST) { options.x = -20000; options.y = -20000; }
  if (fs.existsSync(ICON_PATH)) options.icon = ICON_PATH;
  stageWin = new BrowserWindow(options);
  stageWin.once('ready-to-show', () => stageWin.showInactive());
  stageWin.on('resize', saveStageBounds);
  stageWin.on('move', saveStageBounds);
  stageWin.on('closed', () => { stageWin = null; clearInterval(stageCursorTimer); stageCursorTimer = null; });
  stageWin.webContents.on('console-message', (event) => console.log(`[stage:${event.level}] ${event.message}`));
  stageWin.loadURL(`${BASE_URL}/stage.html?c=${encodeURIComponent(id)}`);
  stageCursorTimer = setInterval(() => {
    if (!stageWin || stageWin.isDestroyed() || !stageWin.isVisible() || stageWin.isMinimized()) return;
    const cursor = screen.getCursorScreenPoint();
    const b = stageWin.getBounds();
    const area = screen.getDisplayNearestPoint(cursor).workArea;
    stageWin.webContents.send('stage:cursor', {
      x: (cursor.x - (b.x + b.width / 2)) / (area.width * 0.5),
      y: -(cursor.y - (b.y + b.height * 0.3)) / (area.height * 0.6),
    });
  }, 60);
}

ipcMain.on('stage:open', (_event, character) => openStage(character));
ipcMain.on('stage:close', () => { if (stageWin && !stageWin.isDestroyed()) stageWin.close(); });
ipcMain.on('stage:minimize', () => { if (stageWin && !stageWin.isDestroyed()) stageWin.minimize(); });

// ---------------------------------------------------------------------------
// Quit lifecycle
// ---------------------------------------------------------------------------
app.on('window-all-closed', () => {
  killOwnedBackend();
  killOwnedCoach();
  if (process.platform !== 'darwin') app.quit();
});
app.on('before-quit', () => {
  killOwnedBackend();
  killOwnedCoach();
});

// ---------------------------------------------------------------------------
// IPC — frameless window controls (contract exposed via preload.js)
// ---------------------------------------------------------------------------
ipcMain.on('win:minimize', () => { if (win && !win.isDestroyed()) win.minimize(); });
ipcMain.on('win:toggle-maximize', () => {
  if (!win || win.isDestroyed()) return;
  if (win.isMaximized()) win.unmaximize();
  else win.maximize();
});
ipcMain.on('win:close', () => { if (win && !win.isDestroyed()) win.close(); });

// ---------------------------------------------------------------------------
// Opt-in self-test hook — inert unless LANGPAL_SELFTEST_OUT is set in the
// environment. Used for manual verification during development: captures a
// screenshot of the loaded window, checks for renderer console errors,
// verifies the preload contract, and round-trips the minimize IPC channel
// through the real preload bridge (not a reimplementation of it). Writes a
// JSON report to the given path and quits automatically. Does not affect
// normal (non-test) launches in any way.
// ---------------------------------------------------------------------------
if (process.env.LANGPAL_SELFTEST_OUT) {
  const outPath = process.env.LANGPAL_SELFTEST_OUT;
  const shotPath = process.env.LANGPAL_SELFTEST_PNG || path.join(path.dirname(outPath), 'selftest.png');
  const consoleErrors = [];

  const attachSelfTest = () => {
    if (!win || win.isDestroyed()) { setTimeout(attachSelfTest, 200); return; }
    win.webContents.on('console-message', (e) => {
      if (e.level === 'error') consoleErrors.push(e.message);
    });
    win.webContents.once('did-finish-load', async () => {
      // let renderer JS settle; LANGPAL_SELFTEST_SETTLE_MS lengthens it when the first screen loads more
      await new Promise((r) => setTimeout(r, Number(process.env.LANGPAL_SELFTEST_SETTLE_MS) || 800));
      const result = { ts: new Date().toISOString() };
      try {
        const image = await win.webContents.capturePage();
        fs.writeFileSync(shotPath, image.toPNG());
        result.screenshot = shotPath;
      } catch (e) {
        result.screenshotError = String(e);
      }
      try {
        result.bridge = await win.webContents.executeJavaScript(
          '({exists: typeof window.langpalDesktop !== "undefined",' +
          ' isDesktop: window.langpalDesktop && window.langpalDesktop.isDesktop,' +
          ' keys: window.langpalDesktop ? Object.keys(window.langpalDesktop) : []})'
        );
      } catch (e) {
        result.bridgeError = String(e);
      }
      try {
        await win.webContents.executeJavaScript('window.langpalDesktop.minimize()');
        await new Promise((r) => setTimeout(r, 500));
        result.minimizedAfterIpc = win.isMinimized();
        win.restore();
        await new Promise((r) => setTimeout(r, 300));
        result.restoredAfterIpc = !win.isMinimized();
      } catch (e) {
        result.ipcError = String(e);
      }
      // LANGPAL_SELFTEST_TAB=coach：再点开「授業」，确认口语课被拉起、iframe 载入、iframe 里能拿到麦克风
      if (process.env.LANGPAL_SELFTEST_TAB === 'coach') {
        try {
          await win.webContents.executeJavaScript('LP.appShell.switchTab("coach")');
          let coachFrame = null;
          for (let i = 0; i < 150 && !coachFrame; i++) {
            await new Promise((r) => setTimeout(r, 400));
            coachFrame = win.webContents.mainFrame.framesInSubtree.find((f) => f.url.startsWith(COACH_URL));
            if (coachFrame) {
              const ready = await coachFrame.executeJavaScript('document.readyState === "complete" && !!document.querySelector("main, header, aside")').catch(() => false);
              if (!ready) coachFrame = null;
            }
          }
          result.coachFrameUrl = coachFrame ? coachFrame.url : null;
          result.coachSpawnedByUs = !!coachProcess;
          result.coachPid = coachProcess ? coachProcess.pid : null;
          if (coachFrame) {
            await new Promise((r) => setTimeout(r, 1500));
            result.coachMic = await coachFrame.executeJavaScript(
              'navigator.mediaDevices.getUserMedia({audio:true}).then(s=>{s.getTracks().forEach(t=>t.stop());return "ok"}).catch(e=>e.name+": "+e.message)'
            );
            const shot = await win.webContents.capturePage();
            const coachShot = shotPath.replace(/\.png$/i, '') + '-coach.png';
            fs.writeFileSync(coachShot, shot.toPNG());
            result.coachScreenshot = coachShot;
          }
        } catch (e) {
          result.coachError = String(e);
        }
      }
      if (stageWin && !stageWin.isDestroyed()) {
        try {
          if (process.env.LANGPAL_SELFTEST_STAGE_JS) await stageWin.webContents.executeJavaScript(process.env.LANGPAL_SELFTEST_STAGE_JS);
          await new Promise((r) => setTimeout(r, Number(process.env.LANGPAL_SELFTEST_STAGE_MS) || 1500));
          const stageShot = shotPath.replace(/\.png$/i, '') + '-stage.png';
          fs.writeFileSync(stageShot, (await stageWin.webContents.capturePage()).toPNG());
          result.stageScreenshot = stageShot;
          result.stageReady = await stageWin.webContents.executeJavaScript('Boolean(window.stageReady)');
          result.stageError = await stageWin.webContents.executeJavaScript('window.stageError || null');
        } catch (e) { result.stageError = String(e); }
      } else {
        result.stageScreenshot = null;
      }
      await new Promise((r) => setTimeout(r, 300));
      result.consoleErrors = consoleErrors.slice();
      result.backendOwnedByUs = backendOwnedByUs;
      result.backendPid = backendProcess ? backendProcess.pid : null;
      try { fs.writeFileSync(outPath, JSON.stringify(result, null, 2)); } catch (e) { console.error(e); }
      setTimeout(() => app.quit(), 500);
    });
  };
  app.whenReady().then(() => setTimeout(attachSelfTest, 100));
}
