# 学习模块：怎么学、凭什么这么做

这份文档是学习这一侧（复习、单词本、错题、阅读、听力、课程、统计）的规格，也是前后端的接口约定。每一条机制后面写了它依据的学习研究，方便以后判断该不该改。

目标是用户自己定的：英语到托福 110，日语到 N1 高分。所以这里优先做对考试成绩真有用的事——**记得住、练在弱项上、难度合适**——不做打卡、连胜、等级徽章这类只让人感觉在学的东西。课程和安排一律用"做到哪了"表示，不用时间表：什么时候学由用户自己定。

## 一、总原则

| 做法 | 依据 | 落在哪 |
|---|---|---|
| **先回想，再看答案**（检索练习） | 把内容从脑子里提出来，比再看一遍记得牢得多（Roediger & Karpicke 2006；Karpicke & Blunt 2011） | 卡片复习、错题重做、听写 |
| **隔开来复习，间隔越拉越长** | 分散练习优于集中练习（Cepeda 等 2006 的综述）；间隔按每张卡自己的遗忘情况算 | FSRS 调度（第二节） |
| **错了的题要在不同的日子里连对几次才算过** | 连续再学习（Rawson & Dunlosky 2011） | 错题进同一个复习队列 |
| **混着练** | 不同类型穿插练习，辨别力和迁移更好（Rohrer & Taylor 2007） | 复习队列默认把生词、句型、阅读错题、听力错题混排 |
| **难度卡在"够得着"的地方** | 读得懂大部分才学得进（词汇覆盖率 95–98%，Hu & Nation 2000；Nation 2006）；正确率 85% 左右学得最快（Wilson 等 2019） | 按最近的正确率和查词率给难度建议（第四节） |
| **练在弱项上** | 刻意练习：针对具体弱点、带反馈地练（Ericsson 等 1993） | 题型诊断，出题向弱题型倾斜（第四节） |
| **学了要用出来** | 输出迫使人注意到自己不会说的地方（Swain 1985） | 读完写两句、聊天里用到期的词、口语课 |
| **同一个词要在不同语境里碰见多次** | 附带习得一个词大约需要 8–12 次相遇（Webb 2007） | 一个词存多条语境；记"遇见次数" |
| **判断自己懂没懂往往不准** | 元认知校准差的人会在已经会的东西上浪费时间（Dunlosky & Rawson 2012） | 只统计真实作答；看过答案的不算对 |

不做的事：不显示连续天数；不把"收藏了""看过了"算成进度；不显示没法从数据里算出来的东西（比如"你的托福预估分"）。

## 二、统一的复习调度

所有需要记住的东西——生词、句型、阅读错题、听力错题——是同一种东西：一张卡。它们进同一个队列，用同一套算法排期。

### 2.1 算法：FSRS-4.5

每张卡有两个量：**稳定性 S**（过多少天回忆概率降到 90%）和**难度 D**（1–10）。评分四档：1 忘了、2 费劲、3 记得、4 很轻松。

- 回忆概率：`R(t, S) = (1 + (19/81) · t / S) ^ (-0.5)`，t 是距上次复习的天数。
- 下次间隔：`I = S · (81/19) · (r^(-2) − 1)`，r 是目标保持率（默认 0.90，可在 0.80–0.95 之间调），间隔最少 1 天、最多 365 天。
- 第一次评分：`S = w[G−1]`；`D = w4 − (G−3)·w5`，夹在 1–10。
- 之后记得（G≥2）：`S' = S · (1 + e^w8 · (11−D) · S^(−w9) · (e^(w10·(1−R)) − 1) · a · b)`，G=2 时 `a = w15`，G=4 时 `b = w16`，其余为 1。
- 忘了（G=1）：`S' = min(S, w11 · D^(−w12) · ((S+1)^w13 − 1) · e^(w14·(1−R)))`。
- 难度更新：`D' = w7·D0(3) + (1−w7)·(D − w6·(G−3))`，夹在 1–10；`D0(3) = w4`。
- 默认参数 `w = [0.4072, 1.1829, 3.1262, 15.4722, 7.2102, 0.5316, 1.0651, 0.0234, 1.616, 0.1544, 1.0824, 1.9813, 0.0953, 0.2975, 2.2042, 0.2407, 2.9466]`。

同一天内忘了的卡，10 分钟后在本次复习里再出现一次（学习步骤），当天再答对不改稳定性，只是让人离开前至少想起来一次；当天又忘也不再罚第二次。隔天才回来答的，照正常公式按经过的天数算。

实现：`backend/app/services/learning/fsrs.py`（纯函数，不碰数据库）。聊天里用对一个到期的词（5.6）也走这里，稳定性的增长乘 0.7。

### 2.2 卡的种类

| kind | 正面（先回想） | 反面（再对答案） | 评分 |
|---|---|---|---|
| `vocab` | 这个词所在的一句话，词被挖空；只给释义的头两个字作提示可选 | 词、读音、释义、它出现过的其它句子 | 四档，自评 |
| `vocab_produce` | 中文释义 + 挖空的语境句（库里没有语境句的中文大意，所以给原句挖空） | 要求打出这个词；按原形、写法或读音比对 | 打对 = 3（5 秒内 = 4），打错 = 1 |
| `pattern` | 用这个句型的一句话，句型部分挖空 | 句型、说明、例句 | 四档 |
| `reading_q` | 原题 + 当时的证据段落（不带答案） | 正确选项和依据 | 选对 = 3，选错 = 1（服务端判，不信客户端的评分） |
| `listening_q` | 原音频 + 依据句在音频里的起止秒（`clips`）+ 原题 | 正确选项、原文、依据句 | 同上 |

`vocab_produce` 在对应的 `vocab` 卡稳定性超过 7 天后自动生成——先认得，再要求写得出。

### 2.3 一个词，多条语境

同一个词（语言 + 原形）只有一条词条，但可以挂多条语境：它在哪句话里出现、来自聊天/阅读/听力、哪一天。再次收藏已有的词不报"已收藏"，而是给它加一条语境。复习时每次从语境里换一句来挖空（按复习次数轮换），避免背的是"这句话"而不是"这个词"；句子里找不到这个词（变形太大）时，正面改成给释义。词条上记 `encounters`（在阅读、聊天、听力里碰见它的次数，不管有没有点）：听力在第一次交卷时自动按原文数，阅读由前端在打开文章时调 `POST /api/learning/encounters {language, text, ref}`（同一个 ref 只数一次），聊天调 `learning.encounter_lemmas`。

### 2.4 数据表

- `review_cards(id, kind, language, ref_table, ref_id, state, stability, difficulty, due_at, last_review_at, reps, lapses, suspended, created_at)`；`state` 取 new / learning / review / relearning。
- `review_log(id, card_id, at, rating, elapsed_days, stability_before, stability_after, retrievability, answer_ms, peeked, request_id, was_due, weak)`；`peeked = 1` 表示先看了答案，这次按 1 记；`was_due = 1` 是到期后的复习（算保持率只用这些）；`weak = 1` 是聊天里用对记的弱证据（不算保持率、不占每日新卡）。
- `review_cards` 另有 `revealed_at / reveal_peeked / reveal_answer` 三列，记住翻面时的状态：翻面时带了答案，评分就按那个答案判，翻面后不能再改。
- `vocab_contexts(id, vocab_id, sentence, source_kind, source_ref, created_at)`。
- 迁移：现有 `vocab_entries`、`pattern_entries` 每条生成一张卡（reps > 0 的按旧的 interval_days 当稳定性、due_at 带过来；没复习过的是新卡）；现有 `review_states` 里的阅读/听力错题各生成一张卡（旧阶段 1/3/7/14/30 天当稳定性）；`review_attempts` 并入 `review_log`（request_id = 旧的 attempt_id，`was_due = 0`，不算保持率）。迁移幂等，不删旧表；以后新收藏的词、新错题也由同一个同步函数补卡，源头删了卡也删。
- `vocab_entries.encounters` 列由启动时的迁移补上（`services/learning/store.py`）。

### 2.5 接口

| 方法 路径 | 说明 |
|---|---|
| `GET /api/review/queue?language=&kinds=&limit=` | `{cards, later, due_now, new_left_today}`：到期的卡（混排）+ 新卡（每天上限 `review_new_per_day`，默认 12，从今天第一次复习的卡数算）。每张带正面内容；反面不在这里给。`later` 是 10 分钟内会回来的学习步骤卡（`{id, due_at, in_seconds}`） |
| `POST /api/review/cards/{id}/reveal` | 请求 `{answer?, gave_up?}`，返回 `{back, peeked, correct, intervals}`；`intervals` 是四个评分各自的下次间隔天数（0 = 10 分钟），给评分按钮用。自评卡（vocab、pattern）翻面就是正常流程，只有 `gave_up` 才记 peeked；要作答的卡（reading_q、listening_q、vocab_produce）不带答案就翻 = peeked |
| `POST /api/review/cards/{id}/grade` | 请求 `{rating?, answer?, answer_ms?, request_id}`（`request_id` 保证重复提交只算一次，重复的返回 `replayed: true`）；返回 `{next_due_at, interval_days, again_in_session, rating, peeked, stability, correct?, session?}`。要作答的卡由服务端判分，`rating` 不用传 |
| `GET /api/review/summary?language=` | `{due_now, new_available, by_kind, retention_7d, retention_30d, reviews_7d, forecast:[{date, due}×7]}`。保持率 = 到期后第一次复习里没忘的比例，样本少于 20 次时返回 null |
| `PUT /api/review/cards/{id}` | 暂停/恢复一张卡 |
| `POST /api/review/session/end` | `{language}`：离开复习页时调。从上次结束算起评过的卡算一次复习会话，记学习记录、发事件；队列清空时评分接口会自己结束会话（返回里的 `session`） |
| `GET/POST /api/vocab/{id}/contexts`、`DELETE /api/vocab/{id}/contexts?context_id=` | 语境管理（最后一条不能删）；`GET /api/vocab/{id}` 是词条详情：语境、遇见次数、卡、`remember_days` |
| `PUT /api/notebook/{id}` | `{meaning}`：修改词义（1–300 字） |
| `DELETE /api/reading/errors/{exercise_id}:{item_index}` | 删除一道阅读错题及其复习卡；`/api/reader/errors/{id}` 同样可用 |
| `/api/review/state`、`/api/review/attempt` | 旧的错题复习接口照旧能用；旧接口的一次作答同时给对应的统一卡记一次分（同一个 attempt_id 只记一次） |

设置项：`review_target_retention`（0.80–0.95）、`review_new_per_day`（0–50）、`review_mix`（混排开关，默认开）、`reading_questions_first`（5.1，默认关）。写入走通用的 `PUT /api/settings`，`GET /api/learning/settings` 读当前值（越界的值按边界夹住，不合法的按默认）。

## 三、今天做什么

学习页的第一屏不是功能列表，是"现在可以做的事"，按对记忆最有利的顺序排：

1. **先复习**：到期的卡有几张（检索练习放最前面，趁还没看新东西）。
2. **再输入**：阅读和听力里，最近 7 天做得少的那个排前面；附一条难度建议（第四节）。
3. **最后输出**：课程当前该练的点，或到期生词里适合聊的两三个——点了进聊天或口语课。

每一项只显示数量和做没做，不显示时间，不排日程。做完的打勾，当天的勾在本地时间零点清掉。

完成的算法：复习 = 今天评过卡且现在没有待复习的；阅读/听力 = 今天做完过一次；输出 = 今天在这门语言里发过消息或上过口语课。阅读和听力最近 7 天次数一样时阅读在前。输出这一步带 `target: {lesson, course, words, speaking_debts, last_lesson}`：lesson 是课程的下一课（`{unit_id, title, kind}`，点了就在聊天里开课；没有可上的为 null），course 是课程里到期该回头用的知识点（最多三个），words 是到期生词里的三个。

`GET /api/today?language=` → `{steps:[{kind:"review"|"reading"|"listening"|"output", count?, done, suggestion?, target?}], language}`。它只读，不写任何东西；完成与否从当天的学习记录里算。

## 四、难度和弱项

### 4.1 学习记录

每完成一件事记一行 `study_events(id, at, language, kind, ref, data_json)`。kind：`reading`（第一次交卷：words、correct、total、lookups、items[{type, correct}]）、`lookup`（阅读里点开词卡，ref = 文章）、`reading_summary`、`listening`（第一次交卷：correct、total、replays、items）、`listening_play`、`listening_cause`、`dictation`、`review`（一次复习会话：count、forgot）、`encounter`、`chat`（聊天那边记：轮数、被纠正几处）。口语课不进这张表，直接读口语课桥。所有统计和建议都从这张表和 `review_log` 算，不另存汇总数。

### 4.2 难度建议

对阅读和听力各自看最近 5 次：

- 正确率 > 90% 且（阅读）查词率 < 2% → 建议升一档；
- 正确率 < 65% 或（阅读）查词率 > 8% → 建议降一档；
- 其余 → 保持。
- 不满 3 次时不给建议（`level: null`），前端不显示。

查词率 = 这篇里点开词卡的不同词数 ÷ 总词数。它是"这篇对这个人有多难"最直接的量：不需要词频表，也不需要先做分级测试。建议只是建议，带一句依据（"最近 5 篇平均答对 4.6/5，查词 1.2%"），用户点一下采纳；不自动改设置。

### 4.3 题型诊断

出题时每道题带一个题型标签（阅读：事实细节 / 推断 / 词义 / 指代 / 句子插入 / 主旨与总结 / 作者态度；JLPT 另有 内容理解 / 主张理解 / 信息检索 / 综合理解；听力：主旨 / 细节 / 功能与态度 / 组织结构 / 推断）。按题型累计正确率（最近 90 天），样本够 8 题的题型才显示。下一次出题时，正确率最低的题型多出一题。听力的题数由题型格式定死（即时回应只有一题），所以听力不加题，改为让模型优先出一道这种题。题型标签放在每道题的 `skill` 字段里。英语等：阅读 `detail / inference / vocabulary / reference / insertion / summary / attitude`，听力 `gist / detail / function / organization / inference`，由模型逐题标，不认识的存成 null、统计里跳过。日语 JLPT 套题按 N1 的大题出、按大题标（一套题就是一个大题，标签由服务端写，不靠模型）：读解 `jlpt_short`（内容理解·短文 ~200 字，1 题）、`jlpt_mid`（中文 ~500 字，3 题）、`jlpt_long`（长文 ~1000 字，4 题）、`jlpt_claim`（主张理解，3 题）；听解 `jlpt_task / jlpt_points / jlpt_gist / jlpt_response / jlpt_integrated`。统合理解（两篇对读）和信息检索（通知、表格）的读解还没有合适的素材，暂不出。日语的"多出一题"只在这次选中的大题正好是最弱大题时生效；听力选"自动"题型时，直接出最弱的那个大题。

### 4.4 听力错因

听力答错后先让用户自己判断是哪种——**没听清**（声音没辨出来）、**听清了没听懂**（词或句子不懂）、**听懂了答错**（推断或粗心）——再给看原文。三种的对策不同：没听清的去做逐句听写，没听懂的把词收进复习，答错的看依据句。这一步是用户自己点的（`POST /api/listening/practice/{id}/causes {items:[{index, cause}]}`，cause 取 `not_heard / not_understood / misjudged`，只能给答错的题标），记进学习记录，统计页按错因分布显示。返回里每题带 `next`：dictation / save_words / evidence。

`GET /api/learning/advice?language=` → `{reading:{level, suggestion, basis}, listening:{...}, weak_types:[{skill, type, accuracy, n}]}`。
`GET /api/learning/stats?language=&days=30` → `{reading:{count, accuracy, types}, listening:{count, accuracy, types, causes, dictation, replays}, review:{count, forgot, retention_7d, retention_30d}, words_encountered}`。没有数据的项返回 null，前端不画。

## 五、各模块的改动

### 5.1 阅读

流程照托福：先读，读完在文末点"显示题目"，题目和文章并排。在这个基础上：

- **记录查词**：读的时候点开过的词记下来（`POST /api/reader/lookups {language, doc, word, lemma, sentence}`，doc 是文章的 URL 或书架文档 id）。交卷时请求里带同一个 `doc`，查词率才算得出来。
- **读完之后**：文末除了"显示题目"，多一块"这篇查过的词"（`GET /api/reader/lookups?language=&doc=`，按原形去重，带 `saved`）——一键把其中想留的收进复习（`POST /api/vocab`，`source_kind: "reading"`），语境就是它在这篇里的那句话。
- **读完写两句**（可选，不强制）：用目标语言写一两句这篇讲了什么。`POST /api/reader/summary-feedback {language, title, text, summary, doc?}` 返回 `{points_right, fixes:[{original, better, why}], missed}`：说对了的要点、需要改的地方（原文片段必须真的出现在用户写的内容里，对不上的条目丢掉）、漏掉的一个关键点（没有为 null）。不打分。走杂活引擎，提示词里带输出的 JSON 结构。
- **先看题再读**（设置 `reading_questions_first`，默认关；后端只存开关，题目本来就能在读之前取到）：有研究支持先尝试回答能让随后的阅读更有效（预测试效应，Richland 等 2009），但托福实考是先读，所以默认不开。
- 阅读错题照旧自动带上题目和证据段落，现在进统一复习队列。

### 5.2 听力

按"先听、再验证、再精听"三段走，每段只出现这一段需要的东西：

1. **盲听**：只有播放器。可以重听，每放一遍调一次 `POST /api/listening/practice/{id}/play`，第一遍之后的都算重听。这一段不给文字。
2. **答题**：照托福/JLPT 的题型。交卷后先标错因（4.4），再看对错。
3. **精听**：逐句列表，每句可以单独重放、调速（0.75× / 1× / 1.25×）；默认文字是盖住的，点一句才显示这一句。系统挑 2–3 句（优先是答错题目的依据句）做**听写**：听这一句，打出来，`POST /api/listening/practice/{id}/dictation {line, text}` 按词比对，返回 `{words:[{text, status: ok|wrong|missing, typed?}], extra, correct, total, score}`，不调模型。日语先把原句分词，再按读音（假名）对齐，所以写成假名也算对——听写查的是听没听清，不是汉字会不会写。

   逐句的支撑：本机 Kokoro 合成时一句一句地合，按实际写出的样本数记下每句的起止秒（一段对白常有两三句）。`GET /api/listening/practice/{id}/lines` 给每段对白和它的句子 `sentences:[{sentence, text, start, end}]`，以及建议听写的 `dictation:[{line, sentence}]`；`GET /api/listening/practice/{id}/lines/{n}/audio?sentence=k` 把这一句切成单独的 WAV（不带 sentence 是整段对白）。听写请求 `{line, sentence, text}`，返回里带 `reference`。这几个都要交卷后才给；调速由播放器做。用兼容语音 API 合成的、或这次改动之前生成的练习只知道整段对白的位置，那时一段就算一句。

   听写挑句子：先从答错题的依据句里挑，长度以听一遍能记住为准（英语约 12 个词、日语约 25 个字），太短的回应（"No, not at all."）不挑。听写是纠正"没听清"最有效的练习（Vandergrift & Goh 2012 的元认知听力教学里的"验证"环节）。

"随心记"保留，任何阶段都能打字记东西。听力错题进统一复习队列，复习时重放的是原音频片段。

### 5.3 单词本

列表还在，但默认入口变成"复习"——到期几张、开始。词条详情里能看到它所有的语境、遇见次数、下次复习日期、记忆稳定性（用"大约能记 N 天"表示）。

### 5.4 错题本

按语言、技能、题型筛选的列表保留，用于回看。"开始复习"进的是统一队列。

### 5.5 课程

课程有自己的一份规格：`COURSE-KERNEL.md`。和这份文档有关的几条：

- **学会的标准**：同一个知识点在两个不同情境里自己做到，算学会；之后到期回头再用、又做到两次，算记牢。
- **证据不只来自聊天**：上课时的回答、阅读题和听力题里标了知识点的题、口语课，都记进同一本账（`course_events`）。阅读题、听力题答对答错是客观证据，不用模型判。
- **按天复习**：学会之后什么时候回头用，和卡片用同一套 FSRS（2.1）。选择题和闲聊里的证据，间隔增长打七折。
- **看得见依据**：每个知识点能点开看凭什么判你会了或还不会（哪天、在课上还是题里、你的原话）。`GET /api/teaching/evidence`。
- **课可以主动上**：课程页、"今天"和聊天菜单里都能开一课；她在聊天里带，材料显示在聊天上方。
- **进"今天"**：下一课和到期该回头用的知识点，出现在"今天"的输出那一步。

### 5.6 聊天里的教学

聊天是语言环境，不是课堂。它做三件事，都在后台：到期的生词由她在话题合适时自然用出来（事件规则"生词回炉"，改为从统一队列取）；课程每四轮里最多开口一轮，带不进去就不带；用户用对了课程目标或到期的词，记一次成功的相遇（给对应的卡记一次"记得"，但间隔增长打七折——不是在考试条件下想起来的，算较弱的证据）。

**闲聊只带闲聊带得动的。** 读一段材料再解释、听一段再判断的那类知识点不在闲聊里带（它们走上课、阅读题、听力题）；闲聊里只带表达类的（怎么说、怎么回应、用哪个句型）。正在上课时、小窗弹幕那一轮，都不带。

**同一个目标不缠着聊天。** 同时可提供的新知识点最多两个（来自不同单元），轮到课程开口的那一轮只给其中一个，两个轮流给——几个目标穿插出现比单一目标集中出现学得更好（交错练习，Rohrer & Taylor 2007），也不会让同一个词连着几轮冒出来。每个新知识点记"在聊天里被带过几次"：连续带满 4 次、用户一次都没用出来，就搁置 24 小时，换给下一个可学的点；回来后再给 4 次机会，仍然没有就搁置 72 小时，以后每次都是 72 小时。用户一用出来（哪怕有帮助），计数清零、立即解除搁置。理由：输入强化有用，但反复给同一个没被接住的目标，收益递减、还让人烦；隔一段时间再出现本身就是分散练习。到期该回头用的知识点不受这个上限影响。课程提示里也写明：目标表达在她最近几句里已经说过，这一轮就别再说，宁可什么都不带。

实现见 `COURSE-KERNEL.md` 第 3、5、8 节：带一次记一行 `offer`，搁置是从账本算出来的。

### 5.7 口语课

口语课是独立程序，这里不改它的教学。对接两处：它的错题账本条数和最近一课计入"今天"和统计；它记下的反复错误，她在聊天里照常留意（已有）。

## 六、事件

统一复习接进事件规则：新事件 `study.review_session_done`（带 `count`、`forgot`、`language`）；条件字段新增 `reviews_due`（现在到期几张）。自带规则"生词回炉"的 `{{due_vocab::N}}` 改为从 `review_cards` 取。

学习这一侧提供的函数（都收一个打开的连接，不提交）：`learning.due_vocab(conn, language, n, near_text)`、`learning.reviews_due(conn, language)`、`learning.chat_success(conn, language, lemmas)`（用了到期的词：给卡记一次弱的"记得"，取代原来把 vocab_entries.due_at 推后一天）、`learning.end_session(conn, language)`（发 `study.review_session_done`）。

## 七、界面上的规矩

- 不写解释性的小字。状态用图形和数字表达；非写不可的字，口气要像人说话。
- 一屏只做一件事：复习时只有一张卡；盲听时只有播放器。
- 评分按钮上直接写下次什么时候再见（"10 分钟""3 天""9 天""21 天"），不写"困难/良好"这类需要解释的词。
- 键盘能做完整个复习：空格翻面，1–4 评分。
