# API v1.5 增量契约（聊天图片消息）——冻结版

> 在 v1.1（拆条/打断）+ v1.2（mood/贴纸）+ v1.3（引擎设置/Codex）+ v1.4（回忆 RAG/引擎即时
> 切换）之上叠加。WP-N。聊天 SSE 事件契约**完全不变**——图片只是 `POST /api/chat` 请求体、
> `messages` 落库、`GET /sessions/{id}/messages` 返回体这三处的增量字段，前端消费 SSE 的代码
> 不用改。

## 1. 上传接口：`POST /api/uploads/image`

Multipart，字段名 `file`。

- 魔数嗅探真实类型（不信任文件名/Content-Type）：只认 PNG / JPEG / GIF / WebP，其它一律
  `415`。
- 大小上限 **8MB**（头像上传走 `config.py` 独立的 3MB 上限，两个场景分开配）。
- 落盘 `data/uploads/{uuid4hex}.{ext}`（`data/` 下，不进 git，部署解包不会覆盖/清空它）。
- 返回：
  ```json
  {"url": "/uploads/3f9a1c2b8e7d4a5f9c0b1e2d3a4f5b6c.png", "width": 1024, "height": 768}
  ```
  `width`/`height` 是不依赖 Pillow 手写解析出来的（PNG 读 IHDR、JPEG 扫 SOF、GIF 读逻辑屏幕
  描述符、WebP 认 VP8/VP8L/VP8X 三种子格式，见 `backend/app/image_utils.py`）；解析不出（截断
  文件/冷门变体）就是 `null`，**不会**因为宽高解析失败而让整个上传报错——图片本身已经存盘
  成功。

## 2. `POST /api/chat` 请求体新增字段

```jsonc
{
  "persona_id": 1,
  "session_id": 3,          // 空 = 新开会话
  "text": "",               // 带图消息允许配文为空串（原来就没有非空校验，pydantic str 本来
                             // 就接受空串；这次只是显式给了默认值 ""，旧调用方零影响）
  "image_url": "/uploads/3f9a1c2b8e7d4a5f9c0b1e2d3a4f5b6c.png"  // 可选，也接受裸文件名
}
```

SSE 事件契约不变：`queued | guard -> (delta -> bubble_done)×N -> done | interrupted | error`。

## 3. 落库与查询

- `messages` 表新增列 `image_path TEXT`（幂等迁移，见 `db.py` `_migrate()` + `schema.sql` 双写）。
  一条带图消息 = 一行 `messages`：`content` 存配文（可为空串），`image_path` 存上传接口返回的
  文件名（不含目录）。
- `GET /sessions/{id}/messages` 每条消息新增 `image_url` 字段（`/uploads/xxx.png` 或 `null`），
  其余字段（`tokens`/`guard_flag`/...）不变。

## 4. 三引擎视觉能力矩阵

先做的能力探测（读 SDK/CLI 源码 + `codex app-server generate-json-schema` 反推协议），再动
的实现——过程和结论见 `docs/worklogs/WP-N.md`。

| 引擎 | `supports_vision()` | 怎么发图片 | 验证状态 |
|---|---|---|---|
| **claude**（`agent_sdk.py`） | `True` | `ClaudeSDKClient.query()` 除了吃字符串，也吃 `AsyncIterable[dict]`——非字符串分支把 dict 原样写进 CLI stdin，不做任何校验/转换。自己拼一条 `{"type":"user","message":{"role":"user","content":[{"type":"text",...},{"type":"image","source":{"type":"base64","media_type":...,"data":...}}]}}`，content 字段就是 Anthropic Messages API 原生的多模态形状。不用开 Read 工具、不用 CLI 的 `@路径` 语法。 | 8793 实例实测通过（见 worklog ②） |
| **codex**（`codex_appserver.py`） | `True` | `turn/start` 的 `input` 是 `UserInput` 数组，其中一个变体是 `{"type":"localImage","path":<本机绝对路径>}`（`generate-json-schema` 反推出的官方字段，不需要 base64）。 | 8793 实例实测通过（见 worklog ②），推荐作为识图验证的首选引擎 |
| **deepseek**（`DeepSeekProvider`） | `False` | 不发——`deepseek-chat` 是纯文本模型，官方不支持图片输入，不伪造。 | 按设计直接走兜底，已验证兜底文案不出戏 |
| **custom**（`CustomProvider`，用户自配 OpenAI 兼容端点） | `True` | 标准 `{"type":"image_url","image_url":{"url":"data:<mime>;base64,..."}}` content block，和 OpenAI 官方多模态格式一致。 | **未实测**（没有真实可用的自定义端点可测） |

### 兜底路径（`services/chat.py` `_build_vision_note`）

当前引擎 `supports_vision()` 为 `False` 时：

1. `registry.get_vision_describer()` 挑一个当前健康的视觉引擎（**codex 优先，claude 次之**）。
2. 用它跑一次性调用（一次性 `imgdesc-<uuid>` session_key，独立于任何真实聊天会话，用完就
   `forget_session` 清掉）描述图片，得到一段中文描述文字。
3. 描述文字拼成 `（对方发来一张图片，内容是：……）` 塞进 `user_text` 最前面，交给当前引擎
   继续正常聊天。
4. 两个视觉引擎都不健康（比如都没登录），或描述过程本身出岔子 → 退化成
   `（对方发来一张图片，但你现在看不到图片内容——可以自然地问ta图里是什么，不要说"我是AI
   看不了图"这种出戏的话）`。

**这条路径保证聊天不会因为图片而报错**——任何环节的异常都被 catch，最终落到第 4 步的文案，
不是抛异常让整轮请求 500。

### 已知妥协

- 主引擎在"直接把图片发给它"这条路径上调用失败、触发降级到 deepseek 时，本轮不会重新走
  一次"先描述再拼文字"的兜底——降级引擎只会收到纯文字（图片描述信息丢失），但**不会报错**。
  这是极少发生的双重失败场景（主引擎既支持视觉又恰好这次调用失败），暂不处理。
- custom 引擎的视觉支持代码已实现但未接过真实端点测试。

## 5. 存储与清理

- `data/uploads/`（`db.py` `UPLOAD_DIR`），由 `init_db()` 建目录。
- 删除人设时级联删除：该人设名下所有会话的 `messages.image_path` 文件连同头像文件一起从
  磁盘删除（`routers/config.py` `delete_persona`）。当前项目没有独立的"删单个会话"接口，
  图片清理只发生在人设删除这条路径上。
- 魔数嗅探/宽高解析/文件删除三个工具函数集中在 `backend/app/image_utils.py`，人设头像上传
  （`config.py`）和聊天图片上传（`chat.py`）共用同一份，不各自维护一份魔数表。
