# 世界书与事件 hook

这份文档是这两套功能的规格，也是前后端之间的接口约定。字段名、接口路径以这里为准。

目标：把 SillyTavern（酒馆）的世界书（World Info / Lorebook）和事件自动化搬进 JINE，能直接导入酒馆的世界书文件；在此之上加几样酒馆没有、但对"语言学习 + 有人设的聊天对象"很有用的东西。

## 一、世界书

### 1.1 它怎么进提示词

聊天引擎（Claude 常驻会话）在连接时就把系统提示词定死了，之后每一轮只能往"这一轮的开场白"里加东西。所以世界书条目分两路进提示词：

| 位置 `position` | 进哪里 | 什么时候生效 |
|---|---|---|
| `before_persona` | 系统提示词里，人设之前 | 会话连接时；书、挂接关系或条件结果变了之后，下一条消息前会自动重连 |
| `after_persona` | 系统提示词里，人设和长期记忆之后、铁律之前 | 同上 |
| `turn` | 这一轮用户消息前面的"背景"块（和语义回忆同一个通道） | 每一轮现算 |

常驻条目（`constant`）默认 `after_persona`，靠关键词等触发的条目默认 `turn`。`turn` 位置的条目只在**新触发的那一轮**注入一次——它之后就留在对话历史里了，不会每轮重复塞。

系统提示词里只放**常驻条目**和**没有关键词、只写了条件的条目**（总共最多 8000 字，常驻优先、`order` 大的优先）。靠关键词或语义触发的条目即使位置写的是 `before_persona` / `after_persona`，会话中途新触发时也放进这一轮的背景块——系统提示词已经定死了。

### 1.2 一本书的结构（`book_json`，version 2）

```json
{
  "version": 2,
  "settings": {
    "scan_depth": 4,
    "budget_chars": 1600,
    "recursion": true,
    "max_recursion": 3,
    "lemma_match": true
  },
  "entries": [ { "...": "见下" } ]
}
```

- `scan_depth`：往回看几条消息找关键词（双方都算；0 = 只看用户刚发的这一批）。
- `budget_chars`：一轮里这本书往背景块里最多注入多少字（每本书各算各的）。超了按 `order` 从大到小留，常驻优先；被裁掉的这轮不算激活，下一轮还能再触发。
- `recursion`：已触发条目的正文还能再触发别的条目，最多 `max_recursion` 层。
- `lemma_match`：见 1.4。

书存在 `world_books` 表（`id`、`name`、`book_json`，另加 `scope`、`enabled` 两列）。`scope = "global"` 的书对所有联系人生效；`scope = "attached"` 的书只对把它挂上的联系人生效（人设资料里的 `world_book_ids`，沿用现有做法）。旧的 version 1 书（只有 `title` / `keywords` / `content` / `enabled`）在启动时原地升级成 version 2（没有关键词的旧条目变成常驻），重复跑不会再改；人设资料里内嵌的旧世界书照旧拆成一本共享书挂回去。

### 1.3 条目字段

| 字段 | 默认 | 说明 | 酒馆里对应 |
|---|---|---|---|
| `uid` | 自增 | 书内唯一编号 | `uid` |
| `title` | "" | 给人看的名字，不进提示词 | `comment` |
| `content` | "" | 进提示词的正文，支持宏（见 3） | `content` |
| `enabled` | true | | `disable` 取反 |
| `constant` | false | 常驻，不看关键词 | `constant` |
| `keys` | [] | 主关键词；写成 `/正则/i` 就按正则 | `key` |
| `secondary_keys` | [] | 次要关键词 | `keysecondary` |
| `logic` | `and_any` | 主关键词命中后，次要关键词怎么算：`and_any` 任一命中 / `and_all` 全部命中 / `not_any` 一个都不能命中 / `not_all` 不能全部命中 | `selectiveLogic` 0/3/2/1 |
| `case_sensitive` | false | | `caseSensitive` |
| `whole_words` | false | 整词匹配（对中日文无意义，自动忽略） | `matchWholeWords` |
| `lemma` | null | 是否按词的原形匹配；null = 跟书的设置 | 无 |
| `semantic` | false | 语义触发，见 1.4 | `vectorized` |
| `semantic_threshold` | 0.84 | | 无 |
| `position` | 见 1.1 | | `position` |
| `order` | 100 | 同一位置里的先后，数字大的靠后（离对话更近） | `order` |
| `probability` | 100 | 触发后有百分之几的机会真的生效 | `probability` |
| `scan_depth` | null | 单条覆盖书的扫描深度 | `scanDepth` |
| `sticky` | 0 | 触发后接下来 N 轮都算"激活中"（影响分组、递归、冷却，不重复注入） | `sticky` |
| `cooldown` | 0 | 激活结束后 N 轮内不能再触发 | `cooldown` |
| `delay` | 0 | 这段对话至少有 N 条消息后才可能触发 | `delay` |
| `group` | "" | 同组的条目一轮里只留一个 | `group` |
| `group_weight` | 100 | 同组里抽签的权重 | `groupWeight` |
| `group_override` | false | 同组里优先取 `order` 最大的，不抽签 | `groupOverride` |
| `exclude_recursion` | false | 不会被别的条目的正文触发 | `excludeRecursion` |
| `prevent_recursion` | false | 自己的正文不去触发别的条目 | `preventRecursion` |
| `delay_until_recursion` | false | 只能在递归阶段被触发 | `delayUntilRecursion` |
| `conditions` | [] | 条件触发，见 1.4；全部满足才算 | 无 |
| `automation_id` | "" | 这条生效时发出 `lore.activated` 事件，带这个 id | `automationId` |
| `extensions` | {} | 导入时认不出的酒馆字段原样留着，导出时带回去 | — |

触发规则：`enabled` → `delay` → 冷却 → （`constant`，或 关键词/语义命中）→ 次要关键词逻辑 → `conditions` → `probability` → 分组 → 预算。没有关键词、不是常驻、但写了 `conditions` 的条目，条件满足就触发。

- 轮数按（主聊天, 人设）记：每个人设在主聊天里各数各的，她主动发的、插话也算一轮。粘性中的条目占住它的分组。`group` 可以用逗号写多个组。
- 概率和分组抽签：背景块那一路每轮现抽；系统提示词那一路按（对话、条目、日期）固定，一天之内结果不变，免得每轮都重连。
- 被 hook 强制生效（`activate_entry`）的条目跳过关键词、条件和概率，只看分组和预算；被压住（`deactivate_entry`）的这几轮不生效。

### 1.4 酒馆没有的三样

**按原形匹配（`lemma`）。** 关键词写「食べる」，用户说「食べた」「食べてる」也能命中；德语、英语的变形同理。做法：扫描范围内的消息用现有分词器取每个词的原形，关键词同时和原文、原形集合比。对学语言的人来说，这比酒馆的纯字面匹配准得多。区分大小写（`case_sensitive`）的条目只按字面；递归阶段扫的是条目正文，也只按字面。

**语义触发（`semantic`）。** 不靠字面，靠意思：把条目的 `title` + `keys` 做成向量（用现有的回忆模型），这一轮的消息和它的相似度过了 `semantic_threshold` 就触发。向量按内容哈希缓存。计算放在后台线程里，每轮最多等 0.8 秒；模型还没加载好、加载失败或超时，这类条目这一轮不触发，不报错。

**条件触发（`conditions`）。** 条目可以看"现在是什么情况"，而不只是"聊天里出现了什么字"。每个条件是 `{ "field": ..., "op": ..., "value": ... }`，`op` 取 `==` `!=` `>` `>=` `<` `<=` `in` `between` `contains`。可用的 `field`：

| field | 含义 |
|---|---|
| `hour` | 现在几点（0–23，本机时间） |
| `weekday` | 星期几（1 = 周一 … 7 = 周日） |
| `date` | 今天的日期 `MM-DD` |
| `idle_days` | 距离主聊天里上一条消息过了几天（不算刚发的这一批；从没聊过 = 没有值） |
| `turns` | 主聊天已经有多少条消息 |
| `vocab_due` | 这门语言里到期该复习的生词卡数（以复习卡 `review_cards` 为准，见 LEARNING.md） |
| `reviews_due` | 这门语言里到期该复习的卡片数（生词、句型、错题都算） |
| `debts_open` | 口语课错题账本里还没改掉的条目数 |
| `course_unit` | 当前课程单元的 id |
| `last_mood` | 这个人设上一条回复的情绪 |
| `language` | 这一轮的语言（主聊天里每轮可能不同；没有这一轮的时候是她的母语） |
| `var.<名字>` | hook 变量（见 2.4）：先找这个联系人的，没有再找全局的 |
| `event.<键>` | 触发这次求值的事件带的数据（只在 hook 里有） |

例：一条 `conditions = [{field:"weekday",op:"==",value:4}]`、正文写"今天是周四，P酱的抗体到货日"的条目，只在周四进提示词。

`between` 写 `[下限, 上限]`，两头都算；下限比上限大时按跨零点算（`hour between [22, 3]` = 晚上十点到凌晨三点）。字段没有值时，只有 `!=` 成立。

### 1.5 导入导出

- 导入酒馆世界书 `.json`（`{"entries": {"0": {...}}}`）。
- 导入角色卡里自带的世界书：角色卡 `.json`（V2/V3 的 `data.character_book`）和 `.png`（`tEXt` 块 `chara` / `ccv3`，base64）。只取世界书，不建联系人。
- 酒馆位置的换算：0 → `before_persona`；1、5、6 → `after_persona`；2、3、4 → `turn`。
- 导出成酒馆格式；这里独有的字段放进每条的 `extensions.jine`，书的设置放在文件顶层的 `extensions.jine.settings`，再导入时原样恢复。
- 酒馆的 `uid` 从 0 编号，导入后加 1（导出时减回去）。认不出的酒馆字段（`depth`、`role` 等）放进条目的 `extensions.st`，导出时回到条目顶层；酒馆原来的位置号（5、6、2、3）也会带回去。
- 写错的正则关键词去掉、正文超过 4000 字截断、不是条目的跳过，都写进返回的 `warnings`。角色卡的 token 预算不换算，用默认的字数预算。

### 1.6 接口

| 方法 路径 | 说明 |
|---|---|
| `GET /api/lore/books` | `{items:[{id,name,scope,enabled,entry_count,attached_persona_ids}]}`；解析不了的书多带 `broken:true` |
| `GET /api/lore/books/{id}` | `{id,name,scope,enabled,book}` |
| `POST /api/lore/books` | 请求 `{name,scope?,enabled?,book?}`，返回同上。`book` 也收 version 1 的旧形状 |
| `PUT /api/lore/books/{id}` | 请求 `{name?,scope?,enabled?,book?}` |
| `DELETE /api/lore/books/{id}` | 同时从所有联系人上摘掉 |
| `POST /api/lore/import` | multipart，字段 `file`；返回 `{id,name,entry_count,warnings:[...]}` |
| `GET /api/lore/books/{id}/export` | 酒馆格式 JSON 下载 |
| `POST /api/lore/test` | 试触发。请求 `{persona_id,text}`；返回 `{activated:[{book_id,book_name,uid,title,position,reason,injected}],skipped:[{book_id,uid,title,why}],turn_preview,system_preview}`。`injected` 是 `system` / `turn` / `null`（激活中但这轮不重复注入）。不写任何状态、不调模型 |

把书挂到联系人上仍然走人设资料的 `world_book_ids`（最多 12 本）。旧的 `/api/teaching/world-books*` 和 `/api/teaching/import-world` 接口删除。

上限：最多 200 本书，每本最多 500 条、正文合计 40 万字；每条正文 4000 字、主/次关键词各 40 个、条件 12 个。

`reason` 是 `constant` / `conditions` / `key:词` / `lemma:词` / `regex:/…/` / `semantic:0.91` / `sticky` / `forced` / `recursion:…`；`why` 是 `disabled` / `suppressed` / `delay` / `cooldown` / `no_match` / `secondary_logic` / `semantic_unavailable` / `conditions` / `probability` / `group` / `recursion_only` / `budget` / `no_due_vocab`。

## 二、事件 hook

一条规则 = **什么时候**（事件）+ **什么条件下**（条件）+ **做什么**（动作）。全是声明式的，不执行任何脚本。

### 2.1 事件

| 事件 | 什么时候发 | 带的数据 `event.*` | 谁发 |
|---|---|---|---|
| `chat.open` | 打开某个联系人的对话 | `first_today`（今天第一次，后端算） | 前端 |
| `chat.user_message` | 用户发了消息，生成之前 | `text`、`length` | 后端 |
| `chat.reply` | 对方回完一轮（她主动发的那轮也算） | `mood`、`bubbles`、`fixes`（这轮纠正了几处）、`proactive` | 后端 |
| `chat.idle` | 对话开着但 10 分钟没动静 | `minutes` | 前端 |
| `study.vocab_saved` | 收藏了一个词 | `lemma`、`language` | 后端 |
| `study.pattern_saved` | 收藏了一个句型 | `language` | 后端 |
| `study.reading_finished` | 做完一篇阅读 | `title`、`correct`、`total`、`language` | 后端 |
| `study.listening_finished` | 做完一组听力 | `correct`、`total`、`language` | 后端 |
| `study.review_session_done` | 一次复习会话结束（学习模块发） | `count`、`forgot`、`language` | 后端 |
| `study.review_done` | 复习了一道错题 | `kind`、`correct`、`language` | 后端 |
| `study.lesson_finished` | 口语课刚下课（口语课桥读到新课；前端拉 `/api/hooks/pending` 或发 `chat.open`/`chat.idle` 时顺带检查，72 小时前的旧课不算） | `lesson_id`、`language` | 后端 |
| `course.unit_completed` | 课程里一个单元达标（单元里的知识点全部记牢） | `unit_id`、`title`、`language` | 后端 |
| `course.lesson_finished` | 上完一节课 | `unit_id`、`title`、`language`、`kind`（new / review）、`passed`（做到的知识点数） | 后端 |
| `lore.activated` | 带 `automation_id` 的世界书条目生效 | `automation_id`、`book_id`、`uid` | 后端 |

`study.*` 和 `course.*` 不属于某一个人设：规则没限定人设时，落到以这门语言为母语的人头上（先看主人设，再看启用的副人设），都不是就落到主人设（一个人设都没有时日志记 `no_persona`）；限定了人设时，落到其中语言对得上的那些。

主聊天（docs/MAIN-CHAT.md）里：`chat.open`、`chat.idle` 不带 `persona_id` 时算主人设；`chat.user_message` 算这一轮的主讲，`chat.reply` 算刚说完的那个人（主讲或插话，多带 `language`、`role`）。规则限定了人设时，`chat.*` 事件落到限定的那些人设头上——她此刻不在场也算，`say` 会让她以"进场说一句"的方式出现（见 MAIN-CHAT.md 第四节）。

发事件不拖慢主流程：`chat.user_message` 在生成前当场求值（这一轮的 `inject` 马上用上），其余后端事件丢给后台线程，判分、收藏、聊天本身不等它。规则出任何错都只记日志。

### 2.2 规则

```json
{
  "id": 1, "name": "久别重逢", "enabled": true,
  "persona_ids": null,
  "event": "chat.open",
  "conditions": [{ "field": "idle_days", "op": ">=", "value": 2 }],
  "probability": 100,
  "cooldown_minutes": 0, "cooldown_turns": 0,
  "once_per": "day",
  "actions": [{ "type": "say", "directive": "对方已经 {{idle_days}} 天没来找你了。按你的性格先开口。" }],
  "builtin": "reunion"
}
```

`persona_ids` 为 null = 所有联系人。`once_per` 取 `none` / `session`（本次启动应用期间一次）/ `day`。`cooldown_turns` 按这个联系人当前对话的轮数算。条件写法和 1.4 完全一样。最多 200 条规则，每条最多 12 个条件、10 个动作，文字 2000 字。

### 2.3 动作

| `type` | 字段 | 效果 |
|---|---|---|
| `inject` | `text`、`turns`（默认 1） | 接下来 N 轮生成时，把这段话放进这一轮的背景块 |
| `say` | `directive` | 让对方**主动发一条消息**（见 2.5） |
| `set_var` | `name`、`value`、`scope`（`persona` / `global`） | 设变量 |
| `inc_var` | `name`、`by`（默认 1）、`scope` | 变量加减 |
| `activate_entry` | `book_id`、`uid`、`turns` | 强制让一条世界书条目在接下来 N 轮生效 |
| `deactivate_entry` | `book_id`、`uid`、`turns` | 强制压住一条条目 N 轮 |
| `remember` | `content`、`category` | 往这个联系人的长期记忆里写一条（同样内容已有就不重复写） |

`inject`、`activate_entry`、`deactivate_entry` 和 `say` 一样先进队列，排队超过 6 小时没用上的作废。一条规则里某个动作作废（节流、`{{due_vocab}}` 没词）不影响别的动作；全都作废就当这次没触发。

### 2.4 变量

规则可以读写变量（数字或字符串），分"每个联系人各一份"和"全局"两种。条件里用 `var.<名字>`，正文里用 `{{getvar::名字}}`。比如每次熬夜聊天 `inc_var night_owl`，攒到 3 就触发一条她念叨你的条目。

### 2.5 她主动发消息

`say` 动作不会立刻生成，而是往这个联系人的"待发"队列里放一条。前端的表现和真的聊天软件一样：

1. 图标栏的"聊天"图标上出现提示（`GET /api/chat/main` 的 `pending`，按人设分的在 `GET /api/hooks/pending`）。
2. 你回到主聊天，如果此刻没有正在生成的回复，前端调 `POST /api/chat/proactive`，她的消息像平时一样一条条冒出来。
3. 主聊天本来就开着时（比如 `chat.idle`），直接走第 2 步。

节流：每个联系人每天最多 `hooks_say_daily_cap` 条（默认 4），两条之间至少隔 `hooks_say_min_gap_minutes` 分钟（默认 30），在排队时算，被挡掉的记进日志（`say_daily_cap` / `say_min_gap`）；排队超过 6 小时没被点开的作废。主动消息走和普通回复同一条链路（常驻会话、语言守门、拆气泡、落库、记忆、课程和世界书照常），只是没有用户消息：指令作为这一轮的背景交给模型，不落库，也要求她不要念出来。

- 正在回复用户（或用户的消息正在攒批）时，`/api/chat/proactive` 直接返回空的 `done`，待发留着。
- 她的消息还在生成/冒出来时用户发了消息，按平时的插话处理：她这轮收到 `interrupted`，没说完的话交给下一轮。
- 生成失败、一条都没发出去时，这条待发退回队列。
- 说话的人设此刻不在主聊天里（规则限定的副人设）：先插一个"某某来了"的系统胶囊，再让她说。

### 2.6 自带的规则

首次启动时写入，可以改、可以关。

| 名字 | 事件 + 条件 | 动作 | 默认 |
|---|---|---|---|
| 久别重逢 | `chat.open`，`idle_days >= 2`，每天一次 | `say` | 开 |
| 深夜 | `chat.user_message`，`hour between [1,4]`，每天一次 | `inject`：现在是深夜，可以提一句，别说教 | 开 |
| 学完来找你（阅读） | `study.reading_finished`，冷却 180 分钟 | `say`：对方刚做完一篇阅读，成绩 x/y，按你的性格说两句 | 开 |
| 学完来找你（听力） | `study.listening_finished`，冷却 180 分钟 | `say`：对方刚做完一组听力，成绩 x/y，按你的性格说两句 | 开 |
| 生词回炉 | `chat.user_message`，`vocab_due >= 1`，冷却 8 轮 | `inject`：「对方该复习这个词了：{{due_vocab::1}}。这一轮的话题用得上，就自然地用一次；用不上就完全不用。不要为了用它改变你想说的话，不要解释，不要点名」。收藏的词不再常驻在系统提示词里——实测两处叠在一起，她会连着几句硬塞同一批词 | 开 |
| 下课了 | `study.lesson_finished` | `say` | 关（口语课桥已经会在下一轮提起） |
| 单元达标 | `course.unit_completed` | `remember` + `say` | 开 |

"生词回炉"里挑词走学习模块（`learning.due_vocab`，到期以复习卡为准）：优先挑和这一轮话题意思相近的，模型不可用时按到期时间。挑中不改排期；这一轮完整发完后，用户消息里用到了到期的收藏词算一次弱的"记得"，双方消息里出现的收藏词各记一次"碰见"，每轮还记一条学习记录（都在后台，出错不影响聊天）。

一条规则只认一个事件，所以"学完来找你"拆成了阅读、听力两条。升级时，用户没改过的自带规则跟着新版定义走，改过的（包括只改了开关）不动；新加的自带规则下次启动补上。

### 2.6.1 糖糖的书和规则

`authoring/lore/` 里放着给糖糖写的一本世界书和一组规则，照《NEEDY GIRL OVERDOSE》原作台本写的（依据：`E:\dev\ngo-canon-notes.md`，
日文原句只用台本里查得到的）：

- `ame-ngo.book.json`：29 条。1 条常驻（她和你在这个软件里是什么关系、她为什么不像老师那样教），其余靠关键词触发，中日英三种写法都收，
  英文关键词按整词匹配（`rain` 不会被 `training` 触发）。每条触发后 12–30 轮内不再触发。书里没有只写条件的条目：那种条目进系统提示词，
  条件一变常驻会话就得重连，按时间变的东西都交给规则去 `inject`。
- `ame-ngo.rules.json`：8 条。已读不回（聊天开着十分钟没动，四成机会戳你一下）、刚睡醒（下午第一次打开聊天）、快开播了（晚上八点到十点）、
  连着陪她熬夜（凌晨聊天计数，满三次提一句）、复习卡攒太多（三十张以上）、复习到整数关口（第 10 / 50 / 100 / 200 次）。
- `install.py <后端地址> ame-ngo --persona 糖糖`：经接口装进一个正在跑的后端，同名的书和规则是更新不是新增，书挂到名字以「糖糖」开头的人设上。

和记忆的分工：长期记忆是她一直记着的事（身世、约定、喜恶），每轮都在；世界书是话题碰到了才想起来的细节和原话。

### 2.7 接口

| 方法 路径 | 说明 |
|---|---|
| `GET /api/hooks/meta` | `{events:[{id,label,source,fields:[{key,label,type}]}],condition_fields:[{key,label,type,ops}],actions:[{type,label,fields:[{key,label,type,required?,default?,min?,max?,options?}]}],macros:[{name,label}],once_per:[{value,label}],limits:{…}}`，编辑界面照这个画，不写死。`condition_fields` 里 `var.*` / `event.*` 两项代表前缀 |
| `GET /api/hooks/rules` | `{items:[rule]}` |
| `POST /api/hooks/rules` | 新建；请求体里的 `id`、`builtin` 忽略 |
| `PUT /api/hooks/rules/{id}` | 修改（含开关）；只传要改的字段也行 |
| `DELETE /api/hooks/rules/{id}` | 自带规则不能删，只能关（返回 409） |
| `POST /api/hooks/fire` | 前端发事件。请求 `{event,persona_id?,payload?}`，只接受 `chat.open`、`chat.idle`；不带 `persona_id` = 主人设；返回 `{fired:[rule_id],pending:[{persona_id,count}]}` |
| `GET /api/hooks/pending` | `{items:[{persona_id,count}]}` |
| `POST /api/chat/proactive` | SSE，请求 `{}` 或 `{persona_id}`。取最早的一条待发（或这个人设的），事件和 `/api/chat` 一样（speaker / guard / delta / bubble_done / done / interrupted / error，可能先有一个 system 进场胶囊），每个事件多带 `proactive:true`。没有待发就直接发 `done`，带 `empty:true` |
| `GET /api/hooks/log?limit=50` | 最近触发记录 `{items:[{at,rule_id,rule_name,event,persona_id,actions,skipped_reason}]}`（`limit` 1–500）。只记真的动了手的，和临门一脚没成的（`probability`、节流、`no_due_vocab`、`no_persona`、出错）；条件不满足、冷却中不记 |
| `GET /api/hooks/vars?persona_id=` | `{items:[{name,value,scope,persona_id}]}`；带 `persona_id` 时返回这个联系人的和全局的，全局的 `persona_id` 是 null |
| `PUT /api/hooks/vars` | 请求 `{name,value,scope,persona_id?}`；`value` 为 null = 删除 |

总开关和节流在设置里（`GET/PUT /api/settings`）：`hooks_enabled`（布尔，默认开）、`hooks_say_daily_cap`（整数 0–50，默认 4）、`hooks_say_min_gap_minutes`（整数 0–1440，默认 30）。

## 三、宏

世界书正文、`inject` 文本、`say` 指令里都能用：

| 宏 | 换成 |
|---|---|
| `{{user}}` `{{char}}` | 用户的称呼（设置里的 `user_name`，没设就是"对方"）/ 联系人名字 |
| `{{time}}` `{{date}}` `{{weekday}}` | 现在的时间、日期、星期 |
| `{{idle_days}}` | 距上次说话几天 |
| `{{getvar::名字}}` | 变量的值 |
| `{{event.键}}` | 事件带的数据 |
| `{{random::甲::乙::丙}}` | 随机挑一个 |
| `{{roll::6}}` | 1 到 N 的随机整数 |
| `{{due_vocab::2}}` | 从到期该复习的生词里挑 N 个（优先和这一轮话题意思相近的，模型不可用时按到期时间），写成「词（读音）：意思」；一个都没有时，整个动作作废 |

认不出的宏原样保留，不报错。

## 四、数据表

- `world_books`：加 `scope TEXT NOT NULL DEFAULT 'attached'`、`enabled INTEGER NOT NULL DEFAULT 1`。
- `lore_state(session_id, persona_id, book_id, uid, sticky_until, cooldown_until, activations, last_turn)`：粘性和冷却，按（对话, 人设）记。
- `hook_rules(id, name, enabled, rule_json, builtin, created_at, updated_at)`。
- `hook_vars(scope, persona_id, name, value)`。
- `hook_queue(id, persona_id, kind, payload_json, created_at, expires_at, consumed_at)`：待发的 `say` 和还没用完的 `inject`、`activate_entry`。
- `hook_log(id, at, rule_id, event, persona_id, detail_json)`：只留最近 500 条。
- `lore_vectors(hash, dim, vec)`：语义触发用的条目向量缓存，按内容哈希（生词的向量也放这里）。
- `chat_turns(session_id, persona_id, turn, last_mood)`：每个人设在每段对话里生成了第几轮、她上一条回复的情绪。这两张表只存短期状态，老形状启动时直接重建。
- `hook_rule_state(rule_id, persona_id, last_at, last_turn, last_day, last_session)`：每条规则在每个联系人上最近一次生效的时间，冷却和 `once_per` 用。
