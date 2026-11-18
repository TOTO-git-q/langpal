# LangPal API 契约（冻结版 v1）

Base URL: `http://localhost:8787/api`。改动此文档需两边（后端/前端）同步，不允许单方面变更形状。

## SSE：POST /chat（v1.2）

请求：

```json
{ "persona_id": 1, "session_id": null, "text": "ただいま！" }
```

`session_id` 为空 = 新开会话。响应为 `text/event-stream`。一条回复可能被拆成多条「气泡」
逐条投递（拆条+节奏+连发合并/打断规则见后端 services/prompts.py、bubbles.py、interject.py），
事件顺序固定为下面三种分支之一：

- 本条消息被并入连发攒批（同 session 短时间内连发，见下）：只有一个 `queued` 事件，流立即
  结束——这条请求不会再有后续事件，真正的回复由触发 flush 的那条请求的 SSE 流承载。
- 正常完整生成：`guard` → 对每条气泡 i（0 起）先若干次 `delta`、再一个 `bubble_done` →
  全部气泡发完后一个 `done`。贴纸气泡（见下）没有「文字」可流，不会有 `delta`，直接是
  一个 `bubble_done`。
- 投递中途被对方新消息（判定为「实质插话」而非语气词/表情级别的琐碎插话）打断：`guard` →
  若干组 `delta*`/`bubble_done`（不到全部气泡）→ 一个 `interrupted` 代替 `done`。

任何阶段异常都用 `error` 代替当前分支后面本该发生的事件。

| 事件 | data 形状 | 说明 |
|---|---|---|
| `queued` | `{}` | 本条消息被并入攒批，流立即结束；回复由触发 flush 的那条请求承载 |
| `guard` | `{"status": "pass"\|"retried"\|"failed", "retries": 0, "mood": "happy"\|null}` | 整轮生成+语言守门完成后、第一条气泡投递前发一次；failed = 二次重试仍未过、照发打标；`mood` 见下 |
| `delta` | `{"text": "...", "bubble": 0}` | 某条气泡的文字增量，按节奏分片多次；`bubble` 是这段增量所属的气泡序号（0 起）；贴纸气泡没有这个事件 |
| `bubble_done` | `{"bubble": 0, "message_id": 2, "tokens": [Token, ...], "sticker": "cho_peace"\|null}` | 该气泡投递完毕：已单独落库为一行 assistant 消息；文本气泡已单独分词完毕、`sticker` 为 `null`；贴纸气泡 `tokens` 恒为 `[]`、`sticker` 为清单里的 id，见下 |
| `done` | `{"session_id": 1, "message_ids": [2, 3]}` | 全部气泡都发完；`message_ids` 按气泡顺序排列（含贴纸气泡自己的 message_id） |
| `interrupted` | `{"delivered": 1, "session_id": 1}` | 投递中途被实质插话打断，代替 `done`；`delivered` = 已经发出去（有对应 `bubble_done`）的气泡数 |
| `error` | `{"message": "..."}` | 异常时代替对应分支后续事件 |

被打断后没发完的内容不会丢：下一轮生成时会由服务端把「已发的/没发完的」总结进新回复里，
前端不需要自己做任何补偿，只需要正常展示 `interrupted` 之后下一轮的新消息。

### mood（每轮一个，驱动头像/桌宠）

`guard.mood` 是这一整轮回复的情绪，冻结十词表：
`normal / happy / excited / shy / smug / pout / sad / tired / surprised / thinking`
（smug=得意，pout=嘟嘴装凶，thinking=思考/欲言又止）。模型在系统提示词里被要求在回复
最末尾单独一行输出 `⟦mood:xxx⟧` 标记，后端在语言守门之前就把这一行剥离——这行标记永远
不会出现在任何 `delta`/`bubble_done` 的文字里，也不会落库。标记缺失或值不在十词表里都
报 `null`。前端优雅降级：`mood` 为 `null` 时用默认头像，不特殊处理。

### 贴纸气泡

模型可以在回复中单独占一行输出 `⟦sticker:<id>⟧`（system prompt 会注入当前可用贴纸清单：
id + 一句话描述），后端识别后把它拆成一条独立的气泡，不与前后文字气泡合并。贴纸气泡的
特点（对照上面 `bubble_done` 表格）：

- `tokens` 恒为 `[]`（没有分词这回事）。
- DB 里这一行 `content` 存 `[sticker:<id>]`（方括号占位，跟 `⟦⟧` 线格式不是同一个东西），
  `tokens_json` 是 SQL `NULL`（不是字符串 `"[]"`）。
- 投递节奏：紧邻贴纸气泡的停顿（贴纸前、贴纸后）都用固定的短停顿（约 1 秒），不按文字
  长度套用普通气泡的节奏公式。
- id 不在当前清单里（模型编造/清单已变化）→ 这个标记整行直接丢弃，不产生任何气泡、不
  留任何原始标记文字。
- 贴纸清单的唯一真相是 `frontend/assets/stickers/manifest.json`
  （`[{"id": "...", "file": "...", "desc": "一句话中文描述"}]`）。这个文件不存在时，
  贴纸功能对模型和后端都整体静默关闭：system prompt 完全不提贴纸，任何 `⟦sticker:...⟧`
  标记都会被当非法丢弃。前端优雅降级：没有贴纸气泡时纯文本流程完全不变。

Token 形状：

```json
{ "i": 5, "surface": "一日", "lemma": "一日", "reading": "いちにち",
  "pos": "名詞", "clickable": true, "collected": true, "space_after": false }
```

- `reading` 仅日语有值（假名），英/德为空串或 null。
- `collected: true` → 前端淡色高亮（已在单词本）。
- 标点 `clickable: false`。
- `space_after`：该 token 后是否紧跟空格（bool）；日语恒为 `false`，英/德取自分词器的空格信息。前端按 `i` 顺序拼接 surface 时据此还原词间距。

## 会话

- `GET /sessions?persona_id=1` → `{"items": [{id, persona_id, started_at, ended_at, summary}]}`
- `GET /sessions/{id}/messages` → `{"items": [{id, session_id, role, content, tokens, guard_flag, created_at}]}`
  （文本类 assistant 消息带 tokens；user 消息、以及贴纸气泡这一行 assistant 消息，
  tokens 均为 null。贴纸气泡的行 `content` 是 `[sticker:<id>]`，前端渲染历史消息时按
  `[sticker:...]` 前缀自行识别、单独渲染成贴纸，不当普通文字显示）

## 解析

`POST /explain/word`：

```json
{ "language": "ja", "lemma": "一日", "surface": "一日", "sentence": "今日はどんな一日だった？" }
```

返回（词卡）：

```json
{ "lemma": "一日", "surface": "一日", "reading": "いちにち", "pos": "名詞",
  "meaning_zh": "一天；一整天",
  "usage_in_context": "在这句话里的具体用法说明",
  "register_note": "语体提示，可空",
  "grammar_note": "德语=冠词/复数/格；英语=不规则变化；日语=活用。可空",
  "cached": true }
```

`POST /explain/sentence`：`{ "language": "ja", "sentence": "..." }` 返回：

```json
{ "translation_zh": "整句中文翻译",
  "chunks": [ { "text": "今日は", "role": "主题", "note": "「は」标记谈论主题" } ],
  "grammar_points": [ { "pattern": "〜せて", "explanation_zh": "...", "example": "..." } ],
  "cached": false }
```

`chunks` 前端渲染为色块横排；`grammar_points` 每项渲染为可收藏小卡。

## 收藏

- `GET /vocab?language=ja` / `POST /vocab` / `DELETE /vocab/{id}`
- `GET /patterns?language=ja` / `POST /patterns` / `DELETE /patterns/{id}`

POST /vocab 请求体：

```json
{ "language": "ja", "lemma": "一日", "surface": "一日", "reading": "いちにち",
  "meaning": "一天", "pos": "名詞",
  "context_sentence": "今日はどんな一日だった？", "source_message_id": 2 }
```

POST /patterns 请求体：

```json
{ "language": "ja", "pattern_name": "〜せて", "explanation": "...",
  "example_sentence": "...", "translation": "...", "source_message_id": 2 }
```

列表返回均为 `{"items": [...]}`，条目含 `id` 与 `created_at`。

## 人设 / 记忆 / 设置

- `GET /personas` → `{"items": [{id, name, language, profile}]}`；`POST /personas`、`PUT /personas/{id}` 请求体 `{name, language, profile}`（profile 为自由 dict：relation/tone/keigo/interests/free_text）
- `GET /memory?persona_id=1` → `{"items": [{id, persona_id, category, content, active, created_at}]}`；`PUT /memory/{id}` 部分更新 `{content?, category?, active?}`；`DELETE /memory/{id}`
- `GET /settings` / `PUT /settings`（部分更新）→ `{"explain_language": "zh", "engine": "agent_sdk", "degraded": false, "websearch_enabled": false}`
- `GET /health` → `{"status": "ok", "mode": "mock"|"live", "engine": "...", "degraded": false}`（前端顶栏状态点 + 降级横幅数据源）
- `GET /usage` → `{"available": true, "five_hour_pct": 37.2, "five_hour_resets": "<ISO>", "seven_day_pct": 12.4, "seven_day_resets": "<ISO>"}`（Claude 订阅额度，60s 缓存；不可用时 `{"available": false}`。任务栏「額度」chip 数据源）

## 错误

非 200 统一 `{"detail": "..."}`（FastAPI 默认）。SSE 内错误走 `error` 事件。

## v2 预告（前端可先留 UI 位，接口未上线）

- `GET /review/queue?language=ja`、`POST /review/answer`（M6）
- `GET /tts?text=...&language=ja`（M7，返回 mp3）
- quiz 卡片：SSE 增加 `quiz` 事件 `{question, options[], answer_index, quiz_id}`（M6）
- `GET /reminders/due`（M8）
