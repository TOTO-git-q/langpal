# JINE 教案 v2：冻结合同

实现源：`backend/app/services/teaching_schema.py`。机器校验：`CourseV2`；兼容读取：`Outline`。生成的完整 JSON Schema 位于 `docs/schemas/course-v2.schema.json`。本合同先于批量教案重写冻结，作者不得各自增删公共字段。

## 课程

- `version: 2`, `id`, `title`, `language`：语言使用已有 BCP47 注册，不把语言列表限制为英语日语。
- `sources[]`：每条含唯一 `id/title/url`，只引用实际核对的教材公开目录、官方教学活动、官方考试要求；教材章节和本应用的改编分开说明。
- `design`：`purpose/entry_requirements[]/outcomes[]/coverage_note`。明确这门课的能力范围；N1 不冒充口试，考试等级不直接换算为交流能力认证。
- `teaching_policy`：单轮新知识和复习上限、帮助阶梯、纠错策略、暂停引导的情境、掌握与复习政策。默认值是可调整的应用规则，不声称是经过实验标定的教育测量阈值。
- `units[]`：有先修关系的完整单元。保留现有课程 ID 和单元 ID，不靠课程天数推进。
- `extensions`：命名空间 JSON，例如 `school.custom`，作为数据保存；不把它作为可执行指令或自动执行插件。

## 每个单元

- `id/title/can_do`：标题是用户能完成的表达或理解行动；目标能从真实表现核对。
- `prerequisites[]`：引用同课程单元，不能自指或循环。
- `situations[]`：至少两个不同场景，各含 `id/context/purpose/complication`。
- `knowledge[]`：2–6 个具体知识点。每点含 `id/kind/label/form/use_when`、至少两条原创 `examples{text,meaning,note}`、`contrasts{alternative,distinction}` 和可观察的 `checks[]`。不得只把主题换成另一个主题；需要真正的词汇、搭配、句法、篇章策略或语用知识。
- `practice`：`entry/input/noticing/supported/independent/transfer/retrieval` 七段。写明教师如何接入、提供材料、让用户注意差异、提供帮助、逐步撤去帮助、迁移和复习。它们是后台可选择的策略，不要求每次闲聊机械走完整流程。
- `modalities.typed/spoken`：分别写 `task/focus[]`。共享知识点，分别核对打字和口语表现；语音转写不能提供发音、停顿、语速或流利度的证据。
- `assessment.criteria[]`：每条含 `id/dimension/knowledge_ids/required` 和四档行为描述 `not_yet/supported/independent/flexible`，可标 `requires_audio`。每个知识点必须有必需标准，允许合理的不同表达，不用关键字命中代替语义判断。
- `assessment.probes[]`：至少两个不同情境，含 `id/context/prompt/expected/knowledge_ids/modalities`。所有知识点与两种表达模式必须有探测入口。
- `assessment.pitfalls[]`：识别典型误解、假进步、照抄和语气不合适的情况。
- `source_refs[]`：`source/locator/use`，逐单元记录它怎样参照来源。例句和活动均为应用改编，不能假称来源原文。

## 内部评价与推进

`Observation` 保存本次真实用户表达、此前老师提供的帮助、必要上下文、来源和模式；`Evaluation` 返回可否评价、理由，以及知识点的逐标准评分与用户原句证据。

1. 四档 0/1/2/3 表示尚未达到、有帮助才能达到、独立达到、灵活迁移；缺少证据为 `null`，不得当作 0。
2. 模型只评价，不决定写数据库或直接晋级。应用校验知识点/标准引用、原话证据、音频条件、帮助等级、复述/照抄与重复事件，再计算状态。
3. 原句必须能定位到本次用户表达；老师示例、引用、重复粘贴、没有实际输出的“我懂了”不累加独立成功。
4. 每个知识点分别记录 `typed/spoken`；不会用文字转写推断发音掌握。尚未提供音频的标准保持未评价。
5. 独立掌握需要多次成功、不同场景和分开的学习机会，默认分别至少 2 次、2 场景、间隔 3 个相关有效机会。次数是证据门槛，不是仅凭次数判对。
6. 复习采用有效练习机会间隔，默认 3/8/20，不用上课日历。达到独立标准后仍有提取、换情境复习；明显错误回到需要巩固，单次不确定判断不抹掉既有能力。
7. 新知识与复习共同进入候选队列，优先处理需要巩固或到期的内容。先修默认表示当前可评价的语言知识已具备学习准备；发音待原音核对不占用文字新点预算，也不封锁后续语言知识。`extensions["jine.prerequisites"]="all_points"`可显式选择全部点门槛，音频点仍不自动算掌握。用户当前话题、情绪和意愿优先，允许不教学。
8. “练过”“能独立用”“多次复习仍会”分别显示；进度反映有证据的学习状态，不转换成官方分数或声称正式通过考试。

## 兼容、作者流程与验收

v1 六字段自定义大纲仍能读取、保存、导出，旧证据保留。预制课程全部升级到 v2，旧知识分类需要重组为交际目标并带明确语言材料。既有单元 ID 保留用于追踪。全课修订指纹用于拦截异步评价期间的课程变更；掌握状态另按稳定课程身份、单元、知识点、模式及知识/标准指纹绑定。改标题、标签或其它单元不会清空未变化知识点；实际改动知识内容或评价标准才让对应点重新取证。v1旧证据不自动变成v2知识点已掌握。

课程管家与导入/工作台使用同一 schema；手工编辑与模型生成不能绕过验证。schema 定义、课程数据和运行时学习证据各自保存。评价标准、示例、练习与来源属于可编辑课程数据；API/语音模型和账号属于独立配置。

作者提交前必须：用 `CourseV2.model_validate_json` 校验每份文件，检查全部旧 ID、每单元来源映射、两种模式和知识点覆盖；人工复读目标语例句与教学步骤；不把同一个通用脚本套到所有单元。保留 `authoring/*.py` 生产脚本以及来源映射，以便之后复查、修改与继续生产。

## 已实现接口与生产线

- `GET /api/teaching/schema`：完整课程、兼容旧课程、观察与评价结构。
- `GET /api/teaching/plan/{language}?modality=typed|spoken`：当前新学与复习候选。
- `GET /api/teaching/lesson/{language}/{unit_id}`：完整单元及来源、修订指纹。
- `POST /api/teaching/workshop/lesson`：按现有来源与用户材料生成一个完整候选教案，不自动应用。
- `POST /api/teaching/observe`：真实表达评价。目标可用targets指定，并用outline_key绑定所学修订；该入口只处理文字/转写，不允许调用者声称已经分析原音。
- 课程管家 `course.lesson`：只修改已经载入的一个单元，保留其它内容，经预览应用；可撤销。

源教案生产脚本在 `authoring/`。课程 JSON、手工预览编辑和课程管家采用同一校验。
主聊天评价在完整回复送达后后台执行，失败保留原进度。口语课生成卡片和阶段引导读取相同目标；真实用户转写回传，跟读阶段不记独立表现。服务缺少评价能力时保持未知，不伪造通过。

这套评价是应用内部的形成性学习记录，不是标准化考试评分。结构和来源校验通过，不等同于已证明真实学习效果。
