# 糖糖绝密外语私教（LangPal）

和糖糖一起备考外语的桌面 app：托福、雅思、四级、六级、高考英语、日语 N1 六门备考课，阅读、听力、口语、复习，JINE 聊天，糖糖的 Live2D 小窗。

## 下载

到 [Releases](../../releases) 下载两个分卷 `.7z.001` 和 `.7z.002`，放在同一个文件夹，用 [7-Zip](https://www.7-zip.org/) 解压 `.001`，打开里面的 `LangPal.exe`。

- 只支持 Windows 64 位。解压后约 6.5 GB。
- 第一次打开要在「设置 → 模型与账号」填一个模型的 API 密钥（推荐 DeepSeek，也能用 Claude、ChatGPT 或任何 OpenAI 兼容接口）。
- 朗读的声音已经自带（英语 Kokoro、日语 VOICEVOX）；口语课第一次用时会提示下载语音识别模型（约 1.6 GB）。
- 所有数据只存在你自己的电脑上。

## 致谢与说明

- 日语语音：VOICEVOX:ナースロボ＿タイプＴ（[VOICEVOX](https://voicevox.hiroshiba.jp/) 引擎，按各声线的使用规定使用）。
- 英语语音：[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)（Apache-2.0）。
- Live2D 显示用 Live2D Cubism SDK。
- 糖糖、JINE 的形象和界面取自《NEEDY GIRL OVERDOSE》（WSS playground），本项目是爱好者二次创作，与原作方无关。

---

# LangPal（界面叫 JINE）

一个只说目标语言的聊天对象，加上围着它长出来的学习工具。单人自用，跑在本机。

外观取自《NEEDY GIRL OVERDOSE》里的聊天软件 JINE。

## 里面有什么

- **聊天**：一条主聊天。一个主人设（默认是糖糖），可以拨语言、开趣味模式（随机语言）；副人设按时机进场、会插话。她有长期记忆、会回忆以前聊过的事、会主动开口。点词出释义，点句出解析。
- **她的小窗**：糖糖在一扇独立的小窗里陪着你，切到别的页面她还在。小窗底下能直接跟她说话（像直播间发弹幕），她知道你正开着哪一页，回答冒在头顶，可以念出来；你让她做，她能替你切页面、开听力、开复习、改设置。
- **学习**：今天做什么 → 阅读（新闻、论文、教材、自己的 PDF；读完出题）→ 听力（本机合成，两个女声；盲听、答题、逐句精听和听写）→ 口语（嵌入的口语课程序；有字幕，能导出 SRT）。
- **复习**：生词、句型、阅读和听力的错题在同一个队列里按间隔复习。
- **课程管家**：用对话改设置——课程、世界书、来源、题型、排版。改动先预览再生效，能撤销。
- **世界书和事件规则**：酒馆式的世界书，能导入酒馆的文件；事件规则让她在合适的时候做合适的事。糖糖自带一本照原作写的书和一组规则（`authoring/lore/`）。

快捷键：Ctrl+1…5 切分区（聊天、学习、复习、课程管家、设置），Ctrl+K 回到聊天输入框。

## 怎么跑

日常用装好的 `LangPal.exe`（开始菜单或任务栏）。它启动时自己拉起后端，退出时关掉。

开发时：

```bash
run.bat
```

然后浏览器开 <http://127.0.0.1:8787>。桌面壳：`start-desktop.bat`。

后端只接受本机访问。要从局域网别的设备开，把那个地址写进环境变量 LANGPAL_ALLOWED_HOSTS（逗号分隔），再设一个至少 16 位的 LANGPAL_ACCESS_TOKEN；那台设备先打开 http://<地址>:<端口>/unlock?code=<访问码> 一次。

改完后端代码要重启服务（没有热重载）；按进程号关，别按名字关。

## 目录

| 位置 | 内容 |
|---|---|
| `backend/app/` | FastAPI 后端。`routers/` 是接口，`services/` 是逻辑，`providers/` 是各家模型 |
| `backend/db/schema.sql` | 表结构；启动时自动迁移 |
| `frontend/` | 纯静态前端，没有打包器。`js/` 一页一个文件，`css/` 一页一张表，设计变量在 `css/windose.css` |
| `desktop/` | Electron 壳。改了 `main.js` / `preload.js` 要拷到 `%LOCALAPPDATA%\Programs\LangPal\resources\app\` |
| `data/` | 用户数据：`langpal.db`、上传的图、头像、备份。不进 git |
| `tests/` | `test_*.py` 是后端测试；`*.mjs` 是界面测试；`tests/ui/` 是带假数据的界面预览 |
| `authoring/` | 生成预制课程的脚本 |

## 文档

设计和接口约定在 `docs/`，每份都写了为什么这么做：

- [主聊天](docs/MAIN-CHAT.md)：谁说话、说哪门语言、她怎么说话、界面
- [世界书与事件规则](docs/LORE-AND-HOOKS.md)
- [学习模块](docs/LEARNING.md)：复习调度、今天、难度、各模块的流程和依据的研究
- [模型与账号](docs/model-capabilities.md)：四个引擎、会话与指针
- [阅读与听力](READING-AND-LISTENING.md)、[听力](LISTENING.md)
- 课程：`docs/COURSE-*.md`、`docs/CURRICULUM-SOURCES.md`
- `docs/history/`：早期的接口记录。词卡、图片、密钥掩码那几部分仍然成立；聊天接口以 MAIN-CHAT.md 为准。

## 测试

```bash
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"
```

```bash
powershell -File tests\ui\run-ui-tests.ps1
```

看界面（假数据，不需要后端）：

```bash
node tests/ui/preview.mjs
```

截图在 `tests/ui/shots/`。

## 密钥和账号

- `.env`：DeepSeek 的 key、本机语音合成的路径。不进 git。
- Claude 用本机 Claude Code 的登录；ChatGPT 在 设置 › 模型与账号 里登录，授权加密存在 `%LOCALAPPDATA%\LangPal\`。
