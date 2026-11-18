# API v1.3 增量契约（引擎设置 + Codex 引擎 + 人设删除）——冻结版

> 在 v1.1（拆条/打断，见 API.md）+ v1.2（mood/贴纸，见 API-v1.2-additions.md）之上叠加。
> WP-K（后端）与 WP-L（前端）共同遵守。聊天 SSE 事件契约（queued/guard/delta/bubble_done/
> done/interrupted/error）完全不变，引擎只是 `services/chat.py` 内部换了一个 provider，
> 前端无感知。

## 1. settings 新键

全部走现有通用 `GET /api/settings`（返回全量 key-value）、`PUT /api/settings`
（收 `{key: value, ...}` patch，任意 key 都会 `INSERT OR REPLACE`，未列出的 key 不受影响）。
布尔字段（`degraded`/`websearch_enabled`）已有的 0/1↔bool 转换逻辑不变，本次新增的键都是纯字符串
（枚举值或密钥），不需要类型转换特判——除了密钥类的**掩码**规则（见 §2）。

| key | 取值 | 默认 | 说明 |
|---|---|---|---|
| `chat_engine` | `claude` \| `codex` \| `deepseek` \| `custom` | `claude` | 新会话选主引擎用；已在飞的 session 粘住上次选定的引擎，改这个键不影响正在进行的会话 |
| `chat_model_claude` | `sonnet` \| `opus` \| `haiku` | `sonnet` | 传给 Agent SDK 的 `model` |
| `chat_reasoning_claude` | `off` \| `low` \| `high` | `off` | 映射 Agent SDK `max_thinking_tokens`：`off→0` `low→4096` `high→16384` |
| `chat_model_codex` | 任意字符串（如 `sol`/`terra`/`luna`，用户自己配的档位名） | 空串 = 用 codex 自己的默认 | 传给 `thread/start` 的 `model` 字段；空串则不传该字段 |
| `chat_reasoning_codex` | `none` \| `minimal` \| `low` \| `medium` \| `high` \| `xhigh` | `medium` | 传给 `turn/start` 的 `effort` 字段 |
| `deepseek_model` | `deepseek-chat` \| `deepseek-reasoner` | `deepseek-chat` | OpenAICompatProvider(DeepSeek 实例) 的 model |
| `custom_base_url` | 字符串（OpenAI 兼容 base_url，如 `https://api.example.com`） | 空串 | 为空视为"未配置" |
| `custom_model` | 字符串 | 空串 | 为空视为"未配置" |
| `deepseek_api_key` | 密钥，见 §2 | — | 优先于 `.env` 的 `DEEPSEEK_API_KEY` |
| `custom_api_key` | 密钥，见 §2 | — | Custom 引擎的 key，无 .env 兜底 |

**生效时机语义（前端要知道）**：以上所有键都只影响**下一次新建的 provider 客户端**——
`chat_engine`/`chat_model_*`/`chat_reasoning_*` 改了不会迁移正在进行中的 session（同一个
session_key 复用已 connect 的常驻客户端，这是 v1.1 就有的"人设/系统提示词冻结"语义的自然延伸）；
新开一个会话（`session_id` 传空）才会用到新配置。前端在设置页改完引擎/模型后，如果想立刻看到效果，
应该引导用户开新会话，而不是承诺"当前会话立刻切换"。

## 2. 密钥掩码规则（`deepseek_api_key` / `custom_api_key`）

- **`GET /api/settings`**：这两个 key 永远不会返回明文。
  - 未设置（settings 表没有这一行，或 `.env` 里也没配）→ 该 key 返回 `null`。
  - 已设置 → 返回 `"····" + 明文尾 4 位`（比如明文 `sk-abcd1234wxyz`，返回 `"····wxyz"`）。
    不足 4 位的极短 key，尾部有多少给多少（比如 3 位明文 `abc` → `"····abc"`），不报错。
  - `deepseek_api_key` 若 settings 表未设置但 `.env` 里有 `DEEPSEEK_API_KEY`，同样按"已设置"
    掩码返回（前端看到的是"有没有配置"的观感，不关心来源是库还是 .env）。
- **`PUT /api/settings`**：
  - 收到非空明文（不以 `"····"` 开头）→ 存库（明文），覆盖旧值。
  - 收到空串 `""` → 删除 settings 表里这一行（`DELETE FROM settings WHERE key=...`），
    `deepseek_api_key` 删除后会退回 `.env` 兜底（`.env` 本身不会被清空/改动）。
  - 收到以 `"····"` 开头的值（前端把 GET 返回的掩码串原样回传，比如用户没碰这个输入框就提交了
    整个表单）→ **整个忽略这个 key 的 patch**（既不存库也不删除，维持原值），不报错、
    不出现在返回的 patch 结果里的"变更"部分（但 GET 意义上的返回值不变）。
  - 密钥明文任何情况下不写日志（`logger.*` 里不得出现这两个 key 的值）。

前端实现提示：设置页密钥输入框默认展示 GET 回来的掩码串（或留空占位符，视 UI 而定）；用户没有
主动修改这个字段就直接提交整份表单是完全安全的（会被后端识别并跳过）。

## 3. `DELETE /api/personas/{id}`

- 无此人设 → `404`。
- 级联删除（同一个事务/连续执行，不做部分回滚保护——本项目单用户本机场景足够）：
  - 该人设名下所有 `sessions`
  - 这些 session 名下所有 `messages`
  - 该人设名下所有 `memory_items`
  - `settings` 表里这些 session 对应的 `memx_watermark_session_{sid}` 水位键
  - `personas` 行本身
- 尽力清理内存态：provider/registry 里如果这个人设的某个 session_key 还挂着常驻客户端
  （Claude Agent SDK 的 `_clients[session_key]`、DeepSeek/Custom 的 `_histories[session_key]`、
  Codex 的线程映射），尽力断开清理；registry 目前没有暴露"按 persona 批量清理"的接口，
  **这次新增了 `registry.drop_persona_sessions(persona_id, session_ids)`** 供这个路由调用，
  没有对应机制的引擎（比如某 provider 压根不维护会话态）静默跳过，不报错。
- 成功 → `{"ok": true}`。

## 4. `GET /api/engines/status`

轻量、**不做网络调用**，只做本地文件存在性探测 + settings 表读取：

```json
{
  "claude": {"available": true, "detail": "已登录（订阅）"},
  "codex": {"available": true, "detail": "已登录（订阅）"},
  "deepseek": {"configured": true},
  "custom": {"configured": false}
}
```

- `claude.available`：`%USERPROFILE%\.claude\.credentials.json` 是否存在。
  - 存在 → `detail = "已登录（订阅）"`；不存在 → `detail = "未登录：在终端运行 claude login"`。
- `codex.available`：`%USERPROFILE%\.codex\auth.json` 是否存在（只判断存在性，不读内容/不解析）。
  - 存在 → `detail = "已登录（订阅）"`；不存在 → `detail = "未登录：在终端运行 codex login"`。
- `deepseek.configured`：`deepseek_api_key`（settings 或 `.env`）是否非空。
- `custom.configured`：`custom_base_url` 与 `custom_api_key` 是否都非空。

## 5. Codex 引擎实现备忘（供前端理解行为边界，非前端要改的东西）

- Codex 走用户本机 `codex-cli` 的 ChatGPT 订阅 OAuth（`codex app-server` 子进程 + JSON-RPC），
  纯聊天场景：只读沙盒、关审批、cwd 指向 `backend/db/codex-workdir` 空目录——它不会执行命令、
  不会读写项目文件。
- `generate_json`（词卡/句解析等杂活）**不支持**，`get_utility_provider()` 永远不会选中它
  （杂活只在 claude/deepseek 之间选）；如果不小心调用会 `NotImplementedError`。
- 会话记忆：`sessions` 表新增 `codex_thread_id` 列，新会话第一次用 codex 引擎时
  `thread/start` 建线程并落库；同一会话后续消息、或后端重启后同一会话再来消息，都用
  `thread/resume` 复活对应 thread id（实测跨进程存活，见 worklog）。
- system prompt（人设 profile 编译出来的那段）通过 `thread/start` 的 `baseInstructions`
  参数一次性注入，线程级冻结，不需要每轮重复传——和 Claude/DeepSeek 的"系统提示词只在
  会话第一次生效"语义完全对齐。
