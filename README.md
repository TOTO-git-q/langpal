# LangPal

LangPal 是一个面向个人使用的语言学习应用，将 AI 对话、阅读、听力、口语和间隔复习放在同一个界面中。项目以 Windows 桌面端为主，也可以通过本机浏览器使用。

界面参考《NEEDY GIRL OVERDOSE》中的 JINE，默认角色为糖糖，并提供 Live2D 陪伴窗口。本项目是爱好者二次创作，与原作方无关。

## 主要功能

- **AI 对话**：选择目标语言和角色，支持多角色聊天、长期记忆、单词释义与句子解析。
- **阅读练习**：阅读文章、论文、教材或导入的 PDF，并生成相关练习。
- **听力练习**：支持语音合成、盲听、答题、逐句精听和听写。
- **口语练习**：对接独立的 speaking-coach 服务，查看课程、对话记录和学习报告。
- **课程与复习**：提供备考课程，将生词、句型和阅读、听力错题加入间隔复习队列。
- **课程管家**：通过对话调整课程、资料来源和练习设置，修改前可预览，并支持撤销。
- **角色自定义**：配置人设、世界书和事件规则；Live2D 小窗支持对话、朗读及部分应用操作。

快捷键：`Ctrl+1` 至 `Ctrl+5` 切换聊天、学习、复习、课程管家和设置；`Ctrl+K` 返回聊天输入框。

## 安装与运行

目前仓库尚未发布可下载的 Release。以下为源码运行方式；语音引擎、模型文件及独立口语服务需要另行配置，不包含在普通源码下载中。

### 环境准备

- Windows，以及可在终端中调用的 Python。
- 如需运行桌面窗口，还需安装 Node.js 和 npm。
- 至少配置一个可用的模型服务或账号，才能使用 AI 功能。

后端依赖见 [backend/requirements.txt](backend/requirements.txt)。前端使用原生 HTML、CSS 和 JavaScript，无需构建。

### 从源码启动

克隆仓库：

```powershell
git clone https://github.com/TOTO-git-q/langpal.git
cd langpal
```

启动后端：

```powershell
.\run.bat
```

脚本会创建 `.venv`、安装后端依赖，并在 <http://127.0.0.1:8787> 启动服务。首次运行需要联网下载依赖。

需要桌面窗口时，在项目根目录的另一个终端运行：

```powershell
.\start-desktop.bat
```

脚本会安装 Electron 依赖并启动窗口。桌面端会复用已运行的后端；如果后端未启动，则尝试使用项目的 `.venv` 启动它。关闭窗口只会停止由该窗口启动的后端。

### 配置模型

打开 **设置 → 模型与账号**，选择连接方式：

| 连接方式 | 所需配置 |
| --- | --- |
| DeepSeek | API 密钥 |
| 自定义 OpenAI 兼容接口 | 服务地址、API 密钥及可用模型 |
| Claude | 本机 Claude Code 登录 |
| ChatGPT | 应用内账号授权 |

具体可用模型和功能取决于连接的服务及账号权限；使用费用由对应服务商收取。接口配置详见 [模型与账号](docs/model-capabilities.md)。

### 可选组件

- **英语等语言的语音合成**：Kokoro。需准备运行环境和模型文件，并设置 `LANGPAL_LISTENING_TTS_PYTHON` 与 `LANGPAL_LISTENING_TTS_ASSETS`。
- **日语语音合成**：VOICEVOX。开发环境通过 `LANGPAL_VOICEVOX_ENGINE` 指定引擎 `run.exe` 的绝对路径。
- **口语服务**：需单独准备 speaking-coach，在 `desktop/langpal.config.json` 的 `coachRoot` 中填写目录。语音识别模型由对应服务管理。
- **英语、德语分词模型**：按需在项目虚拟环境中安装：

```powershell
.venv\Scripts\python -m spacy download en_core_web_sm
.venv\Scripts\python -m spacy download de_core_news_sm
```

语音配置与使用方式见 [听力说明](LISTENING.md)。桌面配置见 [桌面端说明](desktop/README.md)。

## 数据与隐私

聊天记录、学习记录、上传文件和头像保存在本机的 `backend/data/` 中，数据库为 `langpal.db`。备份或迁移前，请先退出应用并停止后端，再复制该目录。

**本地保存不代表完全离线。** 使用在线模型或外部语音服务时，处理请求所需的对话、文本或其他内容会发送至所选服务商。请根据资料的敏感程度选择服务，不要上传无权分享的内容。

后端从 `backend/.env` 读取环境配置；该文件和用户数据目录不应提交到 Git。Windows 上的 ChatGPT 授权使用 DPAPI 加密保存于 `%LOCALAPPDATA%\LangPal\`。

服务默认只监听本机，适用于个人使用。不要直接将默认配置暴露到公网。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| `backend/app/` | FastAPI 后端：接口、业务逻辑及模型连接 |
| `backend/db/schema.sql` | SQLite 表结构 |
| `backend/data/` | 运行时生成的用户数据，不纳入版本控制 |
| `frontend/` | 静态前端与资源 |
| `desktop/` | Electron 窗口、后端进程管理及启动配置 |
| `authoring/` | 课程内容生成脚本 |
| `tests/` | 后端测试、浏览器测试及界面预览 |
| `docs/` | 功能设计和接口说明 |

## 开发与测试

修改后端代码后需要重启服务，默认启动脚本不启用热重载。

后端测试：

```powershell
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"
```

界面测试：

```powershell
powershell -File tests\ui\run-ui-tests.ps1
```

界面测试脚本的默认 Playwright 和 Chromium 路径与开发者本机有关。在其他电脑运行前，需通过 `LANGPAL_PLAYWRIGHT_MODULE` 和 `LANGPAL_CHROME_PATH` 指定本机对应路径。

使用模拟数据预览界面，无需启动后端：

```powershell
node tests/ui/preview.mjs
```

## 相关文档

- [主聊天](docs/MAIN-CHAT.md)
- [世界书与事件规则](docs/LORE-AND-HOOKS.md)
- [学习模块与复习调度](docs/LEARNING.md)
- [课程管家](docs/COURSE-CONCIERGE.md)
- [模型与账号](docs/model-capabilities.md)
- [阅读与听力](READING-AND-LISTENING.md)
- [听力配置](LISTENING.md)
- [桌面端](desktop/README.md)

`docs/history/` 保留了早期接口记录，阅读时请与当前实现和对应模块文档核对。

## 致谢与素材说明

- 日语语音：[VOICEVOX](https://voicevox.hiroshiba.jp/)，默认声线标注为 **VOICEVOX:ナースロボ＿タイプＴ**。使用或分发时请遵守引擎及声线各自的使用规定。
- 英语语音：[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)，采用 Apache-2.0 许可证。
- Live2D 显示使用 Live2D Cubism SDK。
- 糖糖角色与 JINE 界面元素来自《NEEDY GIRL OVERDOSE》（WSS playground），相关权利属于原权利方。

第三方代码、模型、角色和美术素材各有其许可或使用条款；本仓库的公开不代表这些内容可不受限制地使用或再分发。
