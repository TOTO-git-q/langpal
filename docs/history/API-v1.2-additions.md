# API v1.2 增量契约（mood + 贴纸）——冻结版

> 在 v1.1（拆条/打断，见 API.md SSE 节）之上叠加。WP-G（后端）与 WP-H（前端）共同遵守。
> 前端必须优雅降级：mood 缺失/为 null → 默认头像；没有 sticker 气泡 → 纯文本流程不变。

## 1. mood（每轮一个，驱动头像与桌宠）

- `guard` 事件增加字段：`{"status": ..., "retries": ..., "mood": "<mood>|null"}`
- mood 词表（冻结，10 个）：
  `normal / happy / excited / shy / smug / pout / sad / tired / surprised / thinking`
  - smug=得意，pout=嘟嘴装凶（糖糖高频），thinking=思考/欲言又止
- 后端实现：system prompt 要求模型在回复最末尾单独一行输出 `⟦mood:xxx⟧` 标记，
  后端剥离该行（绝不进气泡文本、不进分词、不落库正文），非法值→null。
- 前端用途：JINE 联系人头像随 mood 换图；桌宠触发对应动作。

## 2. 贴纸气泡

- 模型可在回复中单独占一行输出 `⟦sticker:<id>⟧`（提示词注入可用贴纸清单：id+一句话描述，
  最多 30 个常用的），后端把它拆成独立气泡：
- `bubble_done` 形状扩展：`{"bubble": i, "message_id": ..., "tokens": [], "sticker": "<id>|null"}`
  - sticker 气泡：tokens 恒为 []，DB content 存 `[sticker:<id>]`
  - 文本气泡：sticker 为 null，其余照旧
- 贴纸清单唯一真相：`frontend/assets/stickers/manifest.json`
  （形状：`[{"id": "...", "file": "...", "desc": "一句话中文描述"}]`），
  后端启动时读同一份文件注入提示词；文件不存在→整个贴纸功能静默关闭。
- 频率约束写进提示词：贴纸是点缀，多数回复没有；一轮最多一张。

## 3. 历史消息

- `GET /sessions/{id}/messages`：sticker 气泡的行 content=`[sticker:<id>]`、tokens=null，
  前端渲染时自行识别 `[sticker:...]` 前缀。
