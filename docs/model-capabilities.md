# 模型与思考档位

四个聊天引擎：Claude（本机 claude CLI 的订阅登录）、DeepSeek（官方 API 直连）、自定义 OpenAI 兼容端点、
ChatGPT 账号（SIWC 登录，官方 openai SDK）。原则是**连上之后接口给什么就显示什么**，不在代码里写死模型和档位。

## 模型列表

`GET /api/engines/{claude|deepseek|custom|chatgpt}/models`（只读）：

| 引擎 | 模型来源 | 档位来源 |
| --- | --- | --- |
| Claude | Agent SDK 初始化返回的模型表 | 同一份里的 `supportedEffortLevels` |
| DeepSeek | `https://api.deepseek.com/models` | `/models` 里的 `effort.supported_levels` / `supported_reasoning_levels`（有才用） |
| 自定义端点 | `<custom_base_url>/models` | 同上 |
| ChatGPT | 账号模型目录（`visibility=list` 的条目） | 条目里的 `supported_reasoning_levels` / `default_reasoning_level` |

每个模型返回 `reasoning: {levels:[{id,label}], default, source, selected}`：
- `source: "api"` —— 档位来自接口；
- `source: "default"` —— 接口没声明，给的是保守默认列表 `low / medium / high`，界面要提示"接口没声明，这是默认列表"。
- `selected` —— 当前对这个连接 + 模型保存的选择；Claude 里 `"off"` 表示关扩展思考。

## 保存选择

`POST /api/engines/{engine}/reasoning`，body `{model, effort}`。后端先重新读一次接口，只接受这个模型读到的档位
（读不到时是默认列表）；`effort: null` 表示交给服务默认（Claude 是关扩展思考）。

| 引擎 | 存在哪 | 生效 |
| --- | --- | --- |
| Claude | `chat_model_claude` + `chat_reasoning_claude` | 断开常驻客户端，下一条消息用新选项重连并 resume 原会话（不清 `claude_session_id`） |
| DeepSeek / 自定义端点 | `model_reasoning_<engine>`（绑定连接地址和模型，换地址或换模型自动失效） | 下一次请求带 `reasoning_effort`；没选就不带 |
| ChatGPT | 账号授权记录（DPAPI），同 `POST /api/workspace-agent/siwc/model` | 下一次请求带 `reasoning.effort` |

`chat_model_claude` / `chat_reasoning_claude` 也仍可以走通用 `PUT /api/settings`（档位须是 off、常见值或最近一次从接口读到的值）。
`deepseek_model` / `custom_model` 照旧走 `PUT /api/settings`。

## 其它

- 杂活（词卡、句解析、记忆抽取）：`utility_engine` = `auto`（默认：有 DeepSeek key 走 DeepSeek，否则 Claude Haiku）/
  `claude` / `deepseek` / `custom` / `chatgpt`。杂活不带主聊天的思考档位。
- 课程管家：Claude（Agent SDK）、DeepSeek（DSH harness，只给课程管家用）、ChatGPT 三选一，默认跟随主聊天引擎，可每轮单独选。
- 库里遗留的 `chat_engine=codex` 启动时写回 `claude`。

## 会话与指针（主聊天里多个人设）

- 每个人设在每段对话里有自己的常驻会话，key 是 `p{人设}s{会话}`。Claude 的原生会话指针存在
  `session_pointers(session_id, persona_id, engine)`（services/session_pointers.py），按整把 key 读写和作废；
  旧列 `sessions.claude_session_id` 不再读写。坏指针只清自己那把 key；离开引擎只作废那把 key；改模型/思考档位不清指针。
- DeepSeek / 自定义端点 / ChatGPT 首次出现时用 `chat_room.seed_history(key)` 补种：只有这个人设自己说的算 assistant，
  别人的话带名字算 user。
- 归档人设：清掉她名下的会话和主聊天里她那把 key 的内存态与指针；最后一张人设卡不能归档。
- 补种取的是最近的（尾部优先，最多 30 条 / 6000 字），时间线再长也不会补到最早的那些。
- **原生会话轮换**：每把指针记 `created_at` 和完整跑过的轮数 `turns`（CLI 在同一段会话里换 id 只更新指针，这两项不变；指针被清掉后从头算）。跑满 60 轮或用满 7 天、并且这条时间线最后一条消息已过去 3 小时以上（这一轮刚发来的不算），就在预热或这一轮开始连接之前作废指针，下一次连接开一段新的，系统提示词里自带「当前会话回顾」（最近 24 条 / 2000 字，区分说话人）。回复进行中绝不轮换。轮换记一行 INFO 日志。长期记忆、语义回忆、世界书状态、记忆抽取水位都按对话和人设记，不受轮换影响。
