# API v1.4 增量契约（嵌入式回忆 RAG + 引擎即时切换）——冻结版

> 在 v1.1（拆条/打断）+ v1.2（mood/贴纸）+ v1.3（引擎设置/Codex）之上叠加。WP-M（后端）。
> 聊天 SSE 事件契约完全不变——回忆 RAG 是生成前对 `user_text` 的一次内部改写，前端无感知；
> 引擎切换的可见变化只是"改了就立刻生效"，接口形状（`PUT /api/settings`）不变。

## 1. 新表：`message_embeddings`

```sql
CREATE TABLE message_embeddings (
    message_id  INTEGER PRIMARY KEY REFERENCES messages(id),
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL
);
```

- `vector`：float32 原始字节（`np.float32.tobytes()`），不做归一化存储，检索时现算 cosine。
- 每条 `messages` 行最多对应一条 `message_embeddings` 行（`message_id` 是主键，`INSERT OR
  IGNORE` 保证幂等）。
- **哨兵行**：贴纸气泡（`content` 以 `"[sticker:"` 开头）/ 空文本消息会写一行
  `model='skip', dim=0, vector=b''`——不是真的向量，只是让这条消息在 `LEFT JOIN` 意义上
  "已处理"，backfill 才能正确终止。`recall()` 检索时用 `dim > 0` 过滤掉这些哨兵行。
- 模型：`intfloat/multilingual-e5-large`（1024 维，fastembed/ONNX）。选型理由、缓存路径、
  Windows 已知噪音见 `backend/app/services/recall.py` 模块 docstring——**不要**照抄任务书草案
  里的 `multilingual-e5-small`，这版 fastembed 的支持列表里没有这个型号。

## 2. 后台钩子时序

| 时机 | 调用 | 失败语义 |
|---|---|---|
| 后端进程启动（`main.py` startup） | `asyncio.create_task` 跑 `recall.backfill_all()` | 不阻塞启动；模型不可用时自己提前退出，不重试到下次进程重启 |
| 每轮聊天投递完、`done` 事件之后（`chat.py` `_run_background_hooks`，与 `memoryx.maybe_extract`/`explain.pregen_for_message` 同级） | `recall.embed_new_messages(session_id)` | try/except+`logger.warning`，绝不影响主聊天链路 |
| 生成前，拿到 `gen_lock`、拼完 interrupt preface 之后（`chat.py` `_build_recall_block`） | `recall.recall(persona_id, joined_text, exclude, k=3)` | try/except+`logger.warning`，异常时当没有命中处理（返回空块） |

`embed_new_messages`/`backfill_all` 都是"只算缺的"（`LEFT JOIN message_embeddings ... WHERE
message_id IS NULL`），可以重复调用、可以中途重启，不会重算已存在的向量。

## 3. `recall()` 检索语义

`recall(persona_id, query_text, exclude_message_ids, k=3) -> list[{"text", "when",
"message_ids"}]`

- 搜索范围：**该 persona 名下所有会话**（跨会话，不限当前会话）。
- `exclude_message_ids`：调用方（`chat.py`）传当前会话最近 30 条消息 id，避免"回忆"到刚刚
  才说过的话。
- 阈值：cosine >= `RECALL_THRESHOLD`（当前 `0.80`，实测标定见 `recall.py` docstring——e5 系
  向量整体偏"挤"，不能照抄"0.5 附近"的经验值）。
- 命中做**邻域扩展**：同会话内按 id 升序排列后，取命中前后各 2 条（含命中自身）拼成片段；
  多个命中的邻域窗口有重叠/相邻时合并成一个片段，避免同一段旧对话被引用两次。
- 结果按合并后片段的最高分排序取前 `k` 个，再按时间先后重新排列后返回（呈现顺序，不是分数
  顺序）。
- 总预算 600 字符（所有片段的 `text` 加起来），超预算从后往前截断（末尾片段可能被截短并加
  `…`，超预算的片段整个丢弃）。
- `message_ids`：额外字段（不影响 `{text, when}` 这个核心形状），调用方只用它打日志
  （`recall: 注入 N 个片段，message_ids=[...]`），不把聊天内容写进日志。
- 模型不可用 / 没有候选 / 全部低于阈值 → 返回 `[]`，不是异常。

## 4. 生成前注入格式（`chat.py` `_build_recall_block`）

命中非空时，`user_text` 最前面（interrupt preface 之前）插入：

```
（这是系统提供的背景资料，不是对方现在说的话：下面是你们以前聊过、可能和这句话有关的旧
片段。你自然地记得这些事，回复时可以自然带到，但不要复读原文、不要提你在看记录。）
【旧对话片段·{when}】
{text}
---
【旧对话片段·{when}】
{text}
---
（以上是背景，下面才是对方现在的消息）
```

每个命中片段各占一个 `【旧对话片段·when】...---` 块；`when` 形如 `2026-08-20 下午`（日期
+ 粗粒度时段，跟 `build_context_card` 的"上次聊到"卡片同一套措辞习惯）。

## 5. 引擎即时切换（v1.3 语义变更）

**v1.3 原文**（`docs/API-v1.3-engines.md` §1）："以上所有键都只影响下一次新建的 provider
客户端……新开一个会话（`session_id` 传空）才会用到新配置"——**这条对 `chat_engine` 已经不
成立**，v1.4 起 `chat_engine` 改值立即生效。`chat_model_*`/`chat_reasoning_*` 等其它键仍然
维持 v1.3 的"只影响下一次新建客户端"语义不变（引擎切换会顺带让这些设置对同一个 session_key
的下一次连接生效，但单独改模型/推理档位、不改引擎，仍然要等这个 session_key 的常驻客户端
下次重新建立才生效——本项目没有专门为它们再加一个"立即生效"开关）。

- `PUT /api/settings` 收到的 patch 里如果 `chat_engine` 的值**真的变了**（跟改之前的库内值
  比较，不是"这个 key 出现在 patch 里"就算），触发
  `providers.registry.drop_all_live_sessions()`：
  - 清空 `session_key -> 引擎` 的全部粘性映射（不分 persona，整批清）。
  - 每个已经构造过的 provider 断开/忘掉自己缓存的"在飞常驻状态"（agent_sdk 的已 connect()
    客户端、codex 的线程内存映射、deepseek/custom 的内存历史）。
- 效果：**下一条消息**（不需要新会话）就会用新引擎——因为粘性映射被清空，
  `registry.get_provider()` 找不到这个 session_key 的记录，退回读 `settings.chat_engine`
  现场值。
- 上下文不丢：
  - claude/codex 各自有落库的 `claude_session_id`/`codex_thread_id`，断开内存客户端不影响
    下次 resume/thread-resume。
  - deepseek/custom 断开后下次这个 session_key 出现会重新 `_seed_history_from_db` 补种
    （原有机制，未改）。
  - **新增**：如果这个会话从没用过即将切入的这个引擎（没有可 resume 的状态，比如第一次切
    到 claude），真正 fresh connect / 新建线程时，`services.prompts.current_session_recap
    (session_key)` 会把**当前会话**自己的尾部（最多 12 条/800 字，选料逻辑与
    `build_context_card` 共享）拼进 `system_prompt`（agent_sdk）/`baseInstructions`
    （codex_appserver）末尾，避免"新引擎=瞬间失忆"。DeepSeek/Custom 不需要这个兜底——它们
    本来就是每次都从 DB 补种历史的无状态 REST 调用。
- 同值重复 `PUT`（比如前端 `change` 事件误触发同一个值）不会触发 `drop_all_live_sessions()`
  ——只在真的变了值时才断开所有在飞常驻客户端。
- **已知妥协（`claude → deepseek → claude` 这种在同一个会话里来回切换）**：8792 实测确认
  ——切到 deepseek 那一轮之后，再切回 claude 会走 `claude_session_id` 原生 resume，而
  resume 复活的是 **claude 自己那份 CLI 会话文件**里的历史，不包含"切到 deepseek 那段时间
  里说过的话"（那段对话只存在于 langpal 的 `messages` 表和 deepseek 当时的内存历史里，
  claude 的原生会话文件完全不知道）。实测现象：deepseek 那轮里告诉她"我叫花子"，切回
  claude 后问她"我叫什么"，她答不出来（但猫的名字这种早于切换、resume 范围内的事实她
  记得很清楚）。deepseek/custom 不受影响——它们每次都从 DB 重新 `_seed_history_from_db`，
  切过去从不丢东西。这是"resume 一份原生会话文件"这个机制本身的局限（没有 API 能往一个
  已存在的 resume 会话里"倒灌"另一个引擎说过的话），修复需要额外的"每个引擎在这个会话里
  的水位线"追踪机制，超出本次任务范围，先如实记录。日常使用里（选定一个引擎持续聊，偶尔
  永久换一个，而不是来回横跳）不会碰到这个缺口。
- `drop_all_live_sessions()` 内部各 provider 清理步骤都各自 try/except，一个引擎的清理失败
  不影响其它引擎、不影响 settings 本身已经落库成功（"设置保存成功但清理部分失败"的最坏情况
  退化成旧版"要开新会话才生效"，不会导致整个请求 500）。

## 6. 前端

`frontend/js/settings.js` 里"引擎选择"下面的提示文案从"改动保存后对新会话生效，正在聊的
会话继续用旧引擎"改成"改动保存后立即生效（下一条消息就用新引擎，聊天记忆不丢）"。除这一行
文案外前端无需任何改动（`PUT /api/settings` 接口形状不变）。
