# JINE 扩展接口与 Agent 工具盘点

适用于当前的 JINE 工作副本。本文分别记录可用的应用接口、已接入 Agent 的操作，以及下一层插件接口。接口示例统一省略 `/api` 前缀。

## 入口与运行边界

| 层 | 当前入口 | 扩展时的责任 |
| --- | --- | --- |
| 桌面与 Web | `frontend/index.html`、`frontend/js/app.js`、桌面 Electron 壳 | 页面在 `APP_DEFS` 登记，Agent 在左栏「复习」下方。新功能应有明确入口、加载与离开时的状态处理。 |
| 本机数据与服务 | `backend/app/main.py`、`backend/app/db.py`、`backend/db/schema.sql` | FastAPI 下按领域挂载路由，SQLite 持久化设置和学习数据。更新数据结构须复用原 ID、兼容旧库并检查外键。 |
| 浏览器状态 | `frontend/js/state.js`、`languages.js`、`reading.js` | 页面偏好用 localStorage。阅读文档和批注已存进 SQLite，浏览器旧数据只做一次性导入。 |
| 模型与工具 | `backend/app/services/workspace_agent*.py`、`routers/workspace_agent.py` | 上游 Codex CLI 执行推理和 MCP 调用。JINE 维护领域工具、参数验证、预览、提交和撤销。 |
| 技能 | `backend/app/data/skills/jine-workspace/SKILL.md` 和 `references/` | 路由分为来源、考试、课程、视觉和偏好。参考按当前请求加载。界面重构等源码任务使用技能给出的仓库入口与验证步骤。 |

Agent 请求使用本机回环和同源检查。Codex 在临时目录运行，使用结构化输出、独立配置和只读沙箱。请求级 stdio MCP 只提供 `inspect` 和 `read_skill`，读取已准备好的配置摘要和领域参考。MCP 工具和下文的配置变更目录属于两层接口。配置变更由用户在 JINE 内看过差异后提交。参考 [Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode) 和 [Codex 开源仓库](https://github.com/openai/codex)。

### 现有 Agent 合同

- `GET /workspace-agent/catalog` 返回工具 ID、名称与 JSON Schema。它是变更覆盖范围的运行时来源。
- `POST /workspace-agent/plan` 接收 `message`、可选的浏览器 `preferences` 及最近 `previous`，返回说明、领域路由和可选预览 ID。Agent 可以在一份预览里提出多项相关配置变更。
- `POST /workspace-agent/apply` 与 `POST /workspace-agent/undo` 接收预览 ID。服务逐项比对预览时的值，出现并发更改时返回冲突。预览和撤销记录保存在进程内，期限 30 分钟。浏览器复习偏好单独预览，由发起浏览器更新。
- `POST /workspace-agent/test-source` 接收已有来源 ID 和可选搜索词。界面提供独立的测试按钮。专用的来源页面可测试尚未保存的接入配置。

## 领域、可调用操作和扩展点

表中的“手动”包括现有界面和配套应用 API。“后续”是可接入点，表示还需实现独立合同或工具。

| 领域 | 数据归属与手动路径 | 当前 Agent | 可接入的最小扩展 |
| --- | --- | --- | --- |
| 主聊天、主副角色、趣味模式 | `chat_room.py` 的 `MainSettings` 管主角色、语言池、来客规则和主会话。角色资料在 `personas`，说话人及实际语言随 `messages` 保存。用 `/chat/main` 管舞台，`/chat` 流式生成，旧会话可通过 `/chat/archives` 查阅。常驻和时段来客可选，关键词规则可自动选中回复者。时段按后端本地时钟判断。 | `chat.room` 可更改主角色、语言池与来客规则，`persona.edit` 编辑已有卡的设定与世界书挂接。卡片创建和归档经手动路径。 | 来客规则可增加明确的时区或节奏类型。新建卡片可复用角色 Schema。归档类操作单列并保留记录。 |
| 目标语言 | `languages.py` 和 `/languages` 管已登记标签和显示名。现有规范化接受常见语言、文字和地区组合。通用文本适配复用该目录，阅读、听力和口语再判断自己的可用能力。 | 读取语言目录，`language.add` 登记。 | 给目录补充可查询的分词、阅读、合成及口语能力。语言依赖查询应覆盖消息、角色、学习记录、课程、来源、格式、音色和浏览器默认项，供隐藏和撤销检查共用。 |
| 学习大纲 | `teaching.py` 的 `Outline`、`Unit` 和 `/teaching/schema` 定义结构。预制 JSON 在 `data/teaching/`，启用项按语言写入设置，`teaching_evidence` 保留实际语言运用证据。资料库提供导入、导出和制纲。 | `course.set` 可启用预制或结构化自定义大纲，摘要包含预制和每语言课程选择。 | `course.inspect` 可按语言取得明确授权的单元、版本与进度。大纲若要独立管理多个版本，可加课程库 ID 和版本引用，保留原来按纲版本计算的进度。 |
| 世界书与挂接 | `world_books` 保存具名的常驻和关键词条目。每张角色卡在 `world_book_ids` 中选择引用。资料库维护与导入导出，角色卡只处理挂接。旧嵌入条目可迁移成可挂接的书。 | `world.save` 新建或替换共享书。挂接由 `persona.edit` 负责。摘要包含书名和条目数。 | `world.entry.patch` 用稳定条目 ID 改一条而保留其余条目。公开摘要之外的全书文本应按书授权读取。删书前显示所有引用。 |
| 阅读来源与论文 | `reading_sources.py` 一张有序列表放内置和自定义来源（JSON 字段映射、RSS/Atom），`/reader/sources` 增删改、排序、启停、试连。每行一个 `connector`，`collect()` 统一取回。密钥 DPAPI 加密、只回掩码；抓取先查 DNS 再固定地址连接，不跟跳转，限时限量；私网开关只认本机请求。 | `source.save`、`source.enable`、`source.test`，`reading.defaults` 设默认。私网开关和密钥不经管家。 | 新协议加一种 `connector`，沿用同一套传输和密钥隔离。 |
| 阅读题型与证据 | `reading_formats.py` 定义内置题型与通用题型，`reading_format_settings.py` 保存自定义项与语言默认值。`/reader/formats`、`/reader/options/defaults` 和 `/reader/exercises` 分别管理格式、默认、生成。公开材料走出题流程，错题保存题目与可核对的原文证据。 | `reading.format` 新建或编辑自定义格式，`reading.defaults` 修改默认。真实试做经阅读流程。 | `reading.format.check` 用指定或合成样文核对格式和题目。新题型须先扩展题目与评分 Schema，给旧题留可读取的版本。 |
| 阅读排版与 PDF | `reading_style.Style`、`/reader/style` 和浏览器 CSS 变量提供字号、行距、行宽、字体类型及纸色。PDF 由 `reading-pdf.mjs` 渲染。书架文档和批注存 SQLite（`/study-storage`）。Zotero 走 `/reader/zotero`，阅读器共享桥走 `/reader/bridge` 和 `backend/reader_mcp.py`，都只接受本机回环请求。 | `reading.style` 可改与手调一致的排版项。Agent 的配置摘要没有阅读页、书架或批注内容。 | 阅读器 agent 可经共享桥读当前页、选区和批注，用户先共享当前窗口；批注回复用独立写权限。 |
| 听力生成、合成与评分 | `listening_formats.py` 的题型和稿件 Schema 约束说话人、选项和证据行。`/listening/options` 与 `/listening/practice` 提供准备、回放、答题、评分，练习、错题和相关音频存 SQLite，可逐组删除，满了自动删最早的已交卷练习。`/listening/synthesis` 配置 Kokoro 或兼容语音接口、每语言音色和语速。题目生成用设置里给听力选的文字模型。 | `voice.listening` 切换已配置合成方式及调整声音。密钥、服务地址、练习生成和播放在专用界面处理。 | `synthesis.test` 用短样句验证语言和音色，显示时长、音频格式与错误。`ListeningFormat` 后续可扩展成受校验的用户题型接口，复用逐行证据、评分和重放合同。 |
| 独立口语服务 | `coach.js`、`coach_bridge.py`、`/listening/coach` 管独立服务 URL 与语言能力，前端连接其 `/voice`。桌面只按需启动默认本机服务。外部服务自己控制可用语言、实时音频和课后反馈。 | `coach.preferences` 可更换用户明确指定的服务、声明支持语言并调整聊天联动。练习经口语服务进行。 | 版本化的服务清单可声明语言、嵌入限制、练习路由和读写能力。只读诊断和测试可独立接入。麦克风、录音与课程事件由浏览器和口语服务管理。 |
| 复习、单词本与记忆 | `review.js` 汇总听读错题。`notebook.js`、`/vocab`、`/patterns` 提供查询、收藏、删除和跳回原句。`/memory` 管角色记忆；消息位置由 `/messages/{id}/location` 查找。默认筛选属于浏览器。 | `review.preference` 改本浏览器错题本的语言或题型筛选。正文、私有学习记录和记忆不进入当前快照。 | 先做汇总与去标识的学习建议。`review.summary` 应只读授权集合。`notebook.add` 可按真实来源消息提议新增收藏，删除和编辑记忆单独预览。 |
| 模型、账号与运行参数 | `config.py`、`providers/registry.py`、`providers/` 管模型选择、连接、状态、用量和聊天客户端。口语音频、听力合成、听力出题、聊天和 Agent 使用不同入口。 | Agent 推理由本机 Codex CLI 及其登录态提供。模型配置、账号、密钥和本地二进制在专用设置管理。 | `engine.status` 可返回脱敏健康信息。引擎切换应复用已有校验及会话恢复流程。密钥操作保持专用输入、遮蔽和存储路径。 |
| 页面和编辑器 | 应用区域、路由、样式和可视状态由前端脚本及 CSS 管理。资料库、来源、排版和合成各使用领域配置。`APP_DEFS` 仍是仓库内页面注册。 | 仅阅读排版等明确参数可直接应用。界面结构、CSS 和源码变更可由技能整理成仓库任务。 | 可声明的导航、页签和设置区需要稳定 ID、翻译键、窄窗口布局及统一能力检查。自定义脚本和完整页面插件需独立运行边界和权限。 |

## 可复用的插件合同

1. **先登记领域能力。** 定义稳定的 `id`、`version`、参数 Schema、资源归属和可用条件。数据型扩展按现有注册表加载，优先提供来源映射、语言能力、阅读题型、教学 JSON、世界书和样式变量。实现需要改代码的插件时，由领域适配器明确注册入口。
2. **手动界面和 Agent 共用校验与资源层。** HTTP 路由及工具包装同一个领域服务。现有工具中还有对 SQLite 设置、领域私有函数与前端事件的直接耦合。新增时把资源读写、依赖检查及变更通知提到领域接口，避免单独复制规则。
3. **区分只读、试用和写入。** 只读摘要声明会返回哪些字段。试用限定输入、网络端点、数据量和时间。写入携带 `before`、`after`、目标资源标识、冲突检查和适用的撤销方式。多个资源变更优先同一事务。浏览器文档通过显式共享桥处理，账号密钥通过专用表单处理。
4. **以版本适配运行器。** 当前可用运行器是 Codex。若以后接入 Pi，可实现同一个 `plan(prompt, context, tools) → proposal` 适配器，保留 JINE 工具语义和确认界面。运行器只获得本次任务允许的 MCP 能力和结构化输出。Pi 是可评估的上游运行器。参考 [Pi 项目仓库](https://github.com/earendil-works/pi)。
5. **刷新既有页面。** 插件或 Agent 写入后使用领域变更事件刷新已打开的阅读、听力、角色资料和语言选择。浏览器偏好仍由该浏览器应用。更换角色、会话、输出语言和课程应各自有独立 ID 或标签。

### 扩展的验证清单

- 通过用户平时使用的页面和接口走一遍新增与保存。校验无效 JSON、未知语言、失效来源和模型失败。
- 用实际旧库结构的临时副本验证原会话、批注关联、错题和进度。对照旧记录数量与外键。
- Agent 至少走一次预览、提交、冲突、撤销和到期。外部网络测试用指定来源与测试词，敏感凭证只走专用接口。
- 复习按实际语言回放原句、引用、听力证据和选项。随机回复时分别检查主会话、说话人和实际回复语言。
- 手动设置页用正常桌面尺寸和窄窗口核对键盘焦点、弹层关闭和滚动，确认 Agent 写入能刷新已经打开的页面。
