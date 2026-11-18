# LangPal Desktop Shell

Electron shell that turns LangPal into a standalone desktop app: it loads the
same frontend the browser sees, served by the FastAPI backend at
`http://127.0.0.1:8787/`. The shell does not contain any LangPal UI or logic
of its own — it is purely a native window + backend process manager.

## How to run

From the project root:

```
start-desktop.bat
```

This `cd`s into `desktop/`, runs `npm install` the first time (if
`node_modules` is missing), then launches `npx electron .`.

Or manually:

```
cd desktop
npm install     # first time only
npm start        # same as: npx electron .
```

## Backend reuse vs. self-managed

On startup, `main.js` probes `http://127.0.0.1:8787/api/health` with a 1s
timeout:

- **Backend already running** (e.g. you started it yourself with the
  project's `run.bat`, or a previous LangPal session left it up): the shell
  reuses it as-is and **never touches its lifecycle** — closing the Electron
  window will not stop that backend.
- **No backend detected**: the shell spawns its own uvicorn child process:
  ```
  <langpal-root>\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir <langpal-root>\backend --port 8787
  ```
  (all paths resolved to absolute paths from `desktop/`'s location, cwd set
  to the langpal project root). It polls the health endpoint for up to 30s;
  if the backend never becomes healthy, it shows an error dialog and quits.
  When the shell owns the backend, it tree-kills that exact child PID on
  quit via `taskkill /PID <pid> /T /F` — **never** `/IM` (which would kill
  every same-named process on the machine).

Both paths were verified end-to-end on a real Windows desktop: window loads
with zero renderer console errors, the `window.langpalDesktop` preload
contract responds correctly to IPC, and the owned-backend path frees port
8787 on quit while the reused-backend path leaves the original service
running untouched.

## Files

- `package.json` — Electron dependency + `npm start` script.
- `main.js` — app entry: single-instance lock, backend health/spawn/kill,
  frameless `BrowserWindow` creation, window-state persistence, window-control
  IPC handlers (`win:minimize` / `win:toggle-maximize` / `win:close`).
- `preload.js` — exposes the frozen `window.langpalDesktop` contract via
  `contextBridge` (`contextIsolation: true`, `nodeIntegration: false`,
  `sandbox: true`).

## Renderer contract

Any frontend page loaded into this shell can feature-test for desktop mode
and drive the frameless window's controls:

```js
if (window.langpalDesktop?.isDesktop) {
  minimizeBtn.onclick = () => window.langpalDesktop.minimize();
  maximizeBtn.onclick = () => window.langpalDesktop.toggleMaximize();
  closeBtn.onclick = () => window.langpalDesktop.close();
}
```

This same page must also work standalone in a plain browser tab (where
`window.langpalDesktop` is simply `undefined`) — that's the whole point of
loading `http://127.0.0.1:8787/` instead of shipping a separate build.

## Window behavior

- Frameless (`frame: false`), background `#f7e1fb` to avoid a white flash
  before the page paints.
- Default size 1100×760, min size 900×600.
- Position/size persisted to `<userData>/window-state.json` (hand-rolled,
  no `electron-window-state` dependency) and clamped back onto a visible
  display on restore, so an unplugged second monitor can't strand the window
  off-screen.
- Icon set from `frontend/assets/icons/jine.png` when present.

## Debugging: opt-in self-test hook

`main.js` has a small block gated by the `LANGPAL_SELFTEST_OUT` environment
variable (unset by default — inert on every normal launch). When set to a
file path, after the window finishes loading it will:

1. Capture a PNG screenshot of the window via `webContents.capturePage()`.
2. Check `window.langpalDesktop` exists with the right shape via
   `executeJavaScript`.
3. Round-trip `window.langpalDesktop.minimize()` through the real preload
   bridge and confirm the window actually minimized/restored.
4. Collect any renderer `console-message` events at `error` level.
5. Write a JSON report (screenshot path, bridge shape, IPC result, console
   errors, whether the backend is owned by this instance and its PID) to
   `LANGPAL_SELFTEST_OUT`, then quit.

Example (PowerShell):

```
$env:LANGPAL_SELFTEST_OUT = "C:\path\to\result.json"
$env:LANGPAL_SELFTEST_PNG = "C:\path\to\selftest.png"   # optional, defaults next to the JSON
npx electron .
```

This is how both the "reuse" and "self-spawn" backend paths were verified
during development without any manual clicking.

## 图标与固定到任务栏（LangPal.exe）

未打包的 Electron 应用是通过 `electron.exe` 跑起来的，所以直接把它固定到任务栏会显示
Electron 的通用图标，而且运行中的窗口不会和固定项合并。解决办法不需要整套
electron-builder：

```
cd desktop
npm install
powershell -ExecutionPolicy Bypass -File make-launcher.ps1
```

装到 **`%LOCALAPPDATA%\Programs\LangPal\`**（Windows 给用户级应用的标准位置），并建开始菜单
快捷方式「LangPal」。脚本做四件事：

1. 把 Electron 运行时整份复制过去，`electron.exe` 改名 **`LangPal.exe`**，用 `rcedit` 写入
   `LangPal.ico` 和版本信息（文件属性里就是 LangPal 而不是 Electron）。
2. 生成自包含的 `resources\app\`（`main.js` / `preload.js` / `langpal.config.json` 的副本 +
   `package.json`），并删掉 `default_app.asar`。Electron 没有命令行参数时会自动加载
   `resources\app`，所以 **LangPal.exe 可以直接双击 / 固定 / 放开始菜单**。
3. 建开始菜单快捷方式，并把 `System.AppUserModel.ID = com.langpal.desktop` 写进快捷方式——
   和 `main.js` 里 `app.setAppUserModelId` 是同一个 id。没有带这个 id 的快捷方式，Windows 没法
   重新启动一个用了显式 id 的已固定窗口，固定项和运行中的窗口会变成两个按钮。
4. `langpal.config.json` 的 `backendUrl` 决定连哪台后端（见下节）。

**为什么不放在仓库里**：第一版把 LangPal.exe 建在 `desktop\node_modules` 里，后来一次工作区
清理删掉了 node_modules，任务栏固定项就悄悄失效了。`%LOCALAPPDATA%\Programs` 不会被这类
清理（node_modules / .venv 这些可重建目录）碰到。

**改了 `main.js` / `preload.js` / `langpal.config.json` 之后**：关掉 LangPal，重跑一次
`make-launcher.ps1`（它会拒绝覆盖正在运行的程序）。

**固定方式**：右键运行中窗口的任务栏按钮选「固定到任务栏」，或在开始菜单里右键 LangPal。
不要固定 `LangPal.vbs`（会显示 Windows 脚本宿主的图标）。

`LangPal.ico` 由 `frontend/assets/icons/jine.png`（64×64 像素画）生成七个尺寸
（16/24/32/48/64/128/256）；像素画放大必须用最近邻，否则任务栏上会糊。换图标就是换源图
重新生成 ico、再跑一次这个脚本。

## 后端地址：`desktop/langpal.config.json`

```jsonc
{ "backendUrl": "http://192.168.1.10:8787" }
```

优先级：环境变量 `LANGPAL_BACKEND_URL` > 这个文件的 `backendUrl` > 空（= 本地模式，
自己拉起 8787 的 uvicorn）。之所以要配置文件而不是只认环境变量：Windows 的快捷方式和
任务栏固定项没法带环境变量，只有把地址写进文件，`LangPal.exe` 才能被直接双击启动。

远程模式下这个壳是**纯客户端**——不探活本地端口、不 spawn 后端、退出也不动远端服务。

## Packaging (not done yet — next step for whoever picks this up)

This delivery stops at "runs from source via `start-desktop.bat`". To ship a
real installer/portable exe, add `electron-builder` as a devDependency and a
`build` config. Example `package.json` additions:

```jsonc
{
  "scripts": {
    "start": "electron .",
    "dist": "electron-builder --win"
  },
  "devDependencies": {
    "electron": "^44.0.0",
    "electron-builder": "^25.0.0"
  },
  "build": {
    "appId": "com.langpal.desktop",
    "productName": "LangPal",
    "directories": { "output": "dist" },
    "files": ["main.js", "preload.js", "package.json"],
    "extraResources": [
      { "from": "../backend", "to": "backend", "filter": ["**/*", "!__pycache__"] },
      { "from": "../frontend", "to": "frontend" }
    ],
    "win": {
      "target": ["nsis", "portable"],
      "icon": "../frontend/assets/icons/jine.png"
    }
  }
}
```

Things that packaging will need to solve that this delivery deliberately
leaves alone:

- **Python runtime**: a packaged app can't assume `.venv` exists on the
  target machine. Either bundle a portable Python + the installed
  dependencies as an `extraResource`, or freeze the backend with PyInstaller
  into a standalone exe and spawn that instead of
  `python.exe -m uvicorn ...`. `main.js`'s `VENV_PYTHON` / `BACKEND_DIR`
  constants are the only two things that would need to change to point at
  the packaged location (`process.resourcesPath` instead of
  `path.resolve(__dirname, '..')`).
- Code signing (unsigned Windows exes trigger SmartScreen warnings).
- Whether the installer should also register an uninstaller cleanup step
  that kills any orphaned backend process — not a concern today since the
  shell already tree-kills its own backend on every normal quit.
