# JINE 阅读、听力与资料

## 入口

- 「阅读」有文章、找论文和书架。PDF 可选字、框选、批注、导出 Markdown，也能在独立窗口读。
- 「练习」有口语、听力、单词本和错题。听力细节见 [LISTENING.md](LISTENING.md)。
- 拖入的 PDF、TXT、Markdown 存在本机 SQLite（`study_documents`），批注在 `study_annotations`。导入时不出题；主动查词、翻译、提问时，所需文字才发给所选文字模型。

## 接口

所有接口都要求同源请求；Zotero、阅读器共享桥、声音设置和口语服务代理还要求两端都是本机回环地址。

| 模块 | 入口 | 说明 |
| --- | --- | --- |
| 来源 | `/api/reader/sources`、`GET /api/reader/news`、`GET /api/reader/papers` | 内置与自定义来源在同一张有序列表里，见下文。每个来源单独失败，只有摘要时给原文链接。 |
| Zotero | `/api/reader/zotero/*` | 读同机 Zotero 的本机接口：连接设置与测试、条目搜索、取已下载的 PDF。 |
| 阅读器共享桥 | `/api/reader/bridge/*`、`backend/reader_mcp.py` | 用户在阅读器里点「共享给 AI」后，本机 MCP 能读当前文档、页码和选区，取页文字、截图选区、读批注、打开书架条目；回复批注要另开写权限。关窗或停止共享即撤销。 |
| 开放文献 | `GET /api/reader/papers/oa/{pmcid}`、`GET /api/reader/papers/pdf/{ref}` | Europe PMC 开放 XML、arXiv PDF。 |
| 阅读格式 | `GET /api/reader/options`、`/api/reader/formats`、`/api/reader/style` | 内置与自定义阅读格式、默认来源、排版。 |
| 阅读题 | `POST /api/reader/exercises`、`POST /api/reader/exercises/{id}/submit`、`GET /api/reader/errors` | 校验题目、选项、答案位置和逐字证据，交卷后才给答案；错题存 SQLite。 |
| 阅读讲解 | `/api/explain/*`、`POST /api/reader/translations`、`POST /api/reader/question` | 只显示能在给定文字里找到的引用。 |
| 资料库 | `/api/study-storage/*` | 书架文档、批注、听力笔记和听力草稿。`DELETE /document?id=&revision=` 删文档及其全部批注；附在助手对话里的文档会被拒绝删除（409）。`GET /export`、`POST /restore` 导出／导入 ZIP，导入只补缺不覆盖。 |
| 错题复习 | `/api/review/*` | 阅读、听力错题的间隔复习。 |
| 课程 | `/api/teaching/*` | 按语言的课程、进度、世界书。 |

删除的批注留一条墓碑，旧备份或旧浏览器数据导入时不会把它带回来；删整份文档则连墓碑一起删。

## 来源

- 内置：文章 BBC World、NASA、ITmedia、経済産業省、サイエンスポータル（JST 的科学解说，RSS 里带全文）、青空文库（寺田寅彦、中谷宇吉郎、和辻哲郎、夏目漱石的新字新假名随笔评论，公有领域）、Wikipedia（英/日，从秀逸・良质条目里随机取）、BCcampus 大学教材；论文 Europe PMC、Crossref、arXiv、DataCite、HAL。可停用、排序，不能删改。
- 日语长文按 JLPT 读解的长度切成节选：短文 ~200 字、中文 ~500 字、长文 ~1000 字，在句末切、尽量从段首开始；标题后注（短文/中文/長文）。
- 自定义：JSON 接口（用点分字段路径映射标题、链接、正文、作者、日期、DOI）或 RSS/Atom，最多 16 个。论文来源要填搜索参数名。
- 每行带 `connector`：`feed`/`papers`/`textbooks` 是 `services/reading.py` 里的专用读取器，`spec` 是通用 JSON/RSS 读取器。`/reader/news`、`/reader/papers` 都经 `reading_sources.collect()` 按列表顺序取回。
- 密钥：在鉴权字段填（请求头或查询参数），DPAPI 加密存库，接口只回 `configured` 和掩码。换主机或鉴权方式时旧密钥作废。查询参数里不许放密钥。
- 抓取：先解析域名、检查全部地址，再只连这些地址；不跟随跳转；7 秒超时、2 MB 上限。默认只连公网；「允许私有网络」只有本机请求能打开，课程管家改不了；带密钥或允许私网的来源，只有本机打开的阅读页会去取。
- 增删改、排序、启停、试连（含未保存的配置）需要本机请求；设 `LANGPAL_READER_REMOTE_ADMIN=1` 后同源的远程页面也可以，但仍不能打开私网开关。

## 本机 MCP

`backend/reader_mcp.py` 是 stdio MCP（需要 `mcp` 包），工具：`reader_state`、`read_pages`、`capture_region`、`list_annotations`、`reply_annotation`、`list_shelf`、`open_paper`。可注册成用户级 MCP，让别的会话读到「刚才读的那段」：

```text
command: <项目 Python> backend/reader_mcp.py
env: LANGPAL_READER_ORIGIN=http://127.0.0.1:8787
```

只有阅读器开着共享时有数据。Zotero 需要在其设置里启用本机接口。

## 加来源或题型

1. 来源：普通 JSON/RSS 接口在设置页直接加（或在 `reading_sources.py` 的 `_BUILTINS` 里写成内置）；需要特殊协议时，在 `reading_sources.py` 加一种 `connector` 并在 `collect()` 里加一个分支。
2. 题型：在 `reading_formats.py` 或 `listening_formats.py` 里加，写清语言、材料条件和作答方式。
3. 用一份可读材料、一次来源失败、一次筛选拒绝和一次有错题的提交验收。

题型参考 [ETS TOEFL iBT](https://www.ets.org/toefl/test-takers/ibt/about/content.html) 和 [JLPT](https://www.jlpt.jp/e/guideline/testsections.html)，都是按体例生成的练习，不代表考试成绩。
