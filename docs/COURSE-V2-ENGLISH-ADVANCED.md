# IELTS Academic / GRE General：完整教案 v2

核对与编排日期：2026-11-11。作者源是 `authoring/english_advanced.py`，输出仅为本目录两份预制课程和本文，不访问用户数据库、密钥、模型服务或运行时设置。

这两门课沿既有课程的全部 54 个单元 ID 重写，使用冻结的 `CourseV2`。IELTS 24 单元、48 知识点；GRE 30 单元、69 知识点，后者包含原有 9 个真实数量推理单元。合计 117 个逐点必需评价标准，每个标准四档，共 468 段行为描述；234 条原创目标语例子、108 个不同情境探测、378 段单元教学动作。课程不按日期或学习分钟数推进。

## 来源、任务与应用改编分开

- IELTS.org 的 Academic Reading、Listening、Writing、Speaking 页面提供任务边界，官方评分页面与写作/口语规格提供评价方向。这里的四档是“尚未达到／有帮助／独立／灵活迁移”的应用行为标准，不换算 Band，也不把本地打字或聊天当正式考试评分。
- Cambridge Complete IELTS 仅沿 `docs/CURRICULUM-SOURCES.md` 已有的公开可读目录记录提供八主题线索。**原站目录 PDF 抓取曾返回 503，本轮没有读取该 PDF 或教材课内活动**。保留目录链接用于核查，不声称复刻教材或读取其练习。具体知识、数值、短段、情境与七段动作由 JINE 原创改编，并非来源原句或原题。
- GRE 以 ETS 当前 Verbal 的阅读、Text Completion、Sentence Equivalence，以及当前 Analyze an Issue 写作要求为边界。论证分析仍作为阅读与写作能力，但不增加已经取消的独立 Analyze an Argument 考试任务。
- 9 个数量单元依 ETS Math Review 的算术、代数、几何与数据分析组织，实际教定义、公式、建模、运算及反例。它们不是“英语聊天话题”包装，也不穷尽 GRE 数学全部细节。标准差示例明确采用总体标准差定义；不引入推断统计成绩、微积分或正式证明任务。
- 全部例句、微型材料、答案、数值和探测为原创；公开来源用于概念核对与任务约束。短材料是拆解技能的起点，不冒充完整官方篇幅、难度、题库或整套试卷。模型扩展材料时仍须单独检查答案唯一性和信息充分性。

## 单元怎样提供可观察证据

每个单元有两个不同场景、2–3 个具体知识点，包含形式与适用条件、两条原创英语例子及中文释义、易混表达对照、可观察检查。七段动作分别处理接入、输入、注意差异、有支持使用、撤去帮助、迁移和提取；各单元材料、错误对照及独立任务不同。共享作者函数只展开 schema 结构，不把同一个空泛脚本换主题。

每个知识点独立拥有四档标准和必需标记，全部知识点均由探测覆盖；两个探测同时开放打字与口头解释通道。普通文字、转写可用于语义和推理评价，不能证明发音、停顿、语速或流利度。**听力必须先有实际音频输入，教师脚本不先展示；缺音频只能明确降为文字理解练习，不能记录听力掌握。** GRE 没有口试，数学、阅读和写作的口头说明只是交流迁移，不代替正式作答。

同一个答案可能有某点正确、某点仍依赖帮助；不能用一句“我懂了”、照抄示范或碰巧选对累加独立成功。默认帮助阶梯和复习间隔为可修改应用规则，不声称经过实验标定。复习以有效学习机会计数，默认 3/8/20，非日历时间；旧 v1 单元 ID 保留，但旧完成记录不直接授予新版知识点掌握。

## 重跑与扩展

```
python authoring/english_advanced.py --sample
python authoring/english_advanced.py
python authoring/english_advanced.py --check
python -m unittest discover -s tests -p test_course_v2_english_advanced.py -v
```

生产脚本先对两门课全部执行 `CourseV2.model_validate_json` 与冻结 JSON Schema 的 `Draft202012Validator`，通过后才写输出。`--check` 只验证及比较，不写文件。可修改作者记录中的情境、例子、知识形式、检查和步骤，不能删改 schema 来迁就数据。添加来源须先核对可读内容，再在具体单元 `source_refs` 记录章节、用途和改编范围。新增课应另定 ID；修改既有单元内容会产生新的证据指纹，不能覆盖用户历史。

测试另核全部旧 ID、情境/例子/七段输入的区分、知识—标准—探测覆盖、音频边界与数量单元范围。分数、平均速度、二次根、几何比例、总体标准差、抽球概率、计数、交集、加权与数量比较反例进行了独立计算，并核对输出 JSON 的答案片段。Schema 和算术检查通过不等于已测试外部 LLM 出题、语音合成或真实学习效果。

## 来源直达

- [Cambridge Complete IELTS 官方课程介绍](https://www.cambridge.es/en/catalogue/exams/courses/complete/complete-ielts)（`cambridge-course`）
- [Complete IELTS 6.5–7.5 目录链接（本轮未读取原PDF）](https://assets.cambridge.org/97811076/57601/toc/9781107657601_toc.pdf)（`cambridge-toc`）
- [IELTS Academic 官方阅读任务](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-reading)（`ielts-reading`）
- [IELTS Academic 官方听力任务](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-listening)（`ielts-listening`）
- [IELTS Academic 官方写作任务](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-writing)（`ielts-writing`）
- [IELTS Academic 官方口语任务](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-speaking)（`ielts-speaking`）
- [IELTS 官方评分维度与分数解释](https://ielts.org/take-a-test/your-results/ielts-scoring-in-detail)（`ielts-scoring`）
- [IELTS Academic 官方各题型样例入口](https://ielts.org/take-a-test/preparation-resources/sample-test-questions/academic-test)（`ielts-samples`）
- [ETS GRE General 当前考试内容](https://www.ets.org/gre/test-takers/general-test/prepare/content.html)（`gre-content`）
- [ETS GRE Verbal 题型与能力要求](https://www.ets.org/gre/test-takers/general-test/prepare/content/verbal-reasoning.html)（`gre-verbal`）
- [ETS GRE Analytical Writing 当前任务与要求](https://www.ets.org/gre/test-takers/general-test/prepare/content/analytical-writing.html)（`gre-writing`）
- [ETS GRE 官方准备建议](https://www.ets.org/gre/test-takers/general-test/prepare/strategies-tips.html)（`gre-strategies`）
- [ETS GRE Quantitative Reasoning 题型与范围](https://www.ets.org/gre/test-takers/general-test/prepare/content/quantitative-reasoning.html)（`gre-quant`）
- [ETS GRE Math Review：算术、代数、几何、数据分析](https://www.ets.org/pdfs/gre/gre-math-review.pdf)（`gre-math`）

## 逐单元改编记录

下表每行均对应输出中的真实 `source_refs`。教材/官方条目是依据；知识点、场景和步骤为应用编排。

### IELTS Academic

| 单元 ID | 可观察行动 | 知识点 | 直接依据与改编用途 |
| --- | --- | --- | --- |
| `speaking-familiar-answer` | 回答熟悉话题，并用一件小事说清理由 | 先给与问法对应的回答，再补原因；用具体例子和频率限制说明理由 | ielts-speaking：Speaking Part 1：熟悉主题的个人问答；本单元将直接作答和展开拆为两个可观察点。；ielts-scoring：Speaking：连贯、词汇使用和语法的官方评估方向；四档标准为应用内部行为描述，不换算Band。 |
| `listening-corrected-detail` | 听清更正，并把最后确认的信息填对 | 区分试探说法与最终更正；按字段和字数录入信息 | ielts-listening：Listening：form/note completion，按录音信息与题目词数限制完成；例句、情境与探测为原创改编。 |
| `reading-heading-or-detail` | 区分一段的主旨和可定位的细节 | 用核心关系概括段落；用同义表达核对具体信息 | ielts-reading：Reading：matching headings 与 matching information 的目标差异；例句、情境与探测为原创改编。 |
| `reading-contradicted-or-missing` | 把“与原文相反”和“原文没交代”分开 | 分清支持、矛盾和缺失；核对量词及比较范围 | ielts-reading：Reading：identifying information；False与Not given的官方区分；例句、情境与探测为原创改编。 |
| `writing-chart-overview` | 先概括图表的大趋势，再选择细节 | 概括总体趋势与组别差异；区分图表描述与原因推测 | ielts-writing：Academic Writing Task 1：选取主要特征与比较；overview为应用教学拆解；例句、情境与探测为原创改编。 |
| `ielts-chart-comparison` | 比较数值，并把百分点和百分比说清 | 明确倍数及近似比较；区分百分比增幅和百分点差 | ielts-writing：Academic Writing Task 1：准确选择、比较并描述数据；例句、情境与探测为原创改编。 |
| `ielts-health-distractors` | 听懂被否定的选项与最后决定 | 追踪提议、否定和接受；核对赞同的对象与条件 | ielts-listening：Listening multiple choice：理解观点、细节与选项干扰；例句、情境与探测为原创改编。 |
| `writing-argue-a-position` | 读清写作指令，用理由支持自己的立场 | 把指令拆成必须回应的内容；把理由解释到主张上 | ielts-writing：Academic Writing Task 2：按具体任务回应并展开论证；例句、情境与探测为原创改编。 |
| `speaking-tell-an-event` | 把一件事讲出起因、转折和意义 | 用过去时和过去完成时理清事件；用细节解释感受或意义 | ielts-speaking：Speaking Part 2 长回答及 Part 3 追问的组织训练；例句、情境与探测为原创改编。 |
| `ielts-art-opinion` | 分清作者的判断与引述的看法 | 给观点找到真正的持有者；判断作者是否持有题干观点 | ielts-reading：Reading：identifying writer views/claims；观点归属；例句、情境与探测为原创改编。 |
| `ielts-art-options` | 逐项验证选择题，不被半句正确带走 | 核对选项的每个组成条件；识别同义改写但守住含义边界 | ielts-reading：Reading multiple choice：详细意义与同义改写；例句、情境与探测为原创改编。 |
| `writing-process-sequence` | 讲清一个过程，同时保留条件和支路 | 把过程阶段作为句子主线；区分顺序、条件和循环 | ielts-writing：Academic Writing Task 1：diagram/process description；例句、情境与探测为原创改编。 |
| `ielts-history-map` | 跟随地图指路，并在转向后重定参照 | 沿行进方向理解转弯与经过；将路线上已否定的信息更新 | ielts-listening：Listening plan/map labelling：路线与参照信息；例句、情境与探测为原创改编。 |
| `ielts-history-structure` | 填摘要时保留原文的因果和转折 | 用句法检查摘要空格；在压缩时保留关系词含义 | ielts-reading：Reading summary completion：词形与逻辑关系；例句、情境与探测为原创改编。 |
| `ielts-history-review` | 把史实、解释和证据强弱分开 | 把发现与解释分开；说明替代解释与所需证据 | ielts-reading：Reading：区分信息与推断；主张需要文本依据；例句、情境与探测为原创改编。 |
| `listening-follow-signposts` | 听讲座时按结构记笔记 | 辨认路标的篇章作用；保留对象与关系的压缩笔记 | ielts-listening：Listening Part 4：单人学术讲话与note completion；例句、情境与探测为原创改编。 |
| `ielts-balanced-essay` | 回应反方理由，并说明自己的判断条件 | 承认有效顾虑，不歪曲反方；按同一标准权衡，而非数优缺点 | ielts-writing：Task 2：讨论不同观点并提出有根据的立场；例句、情境与探测为原创改编。 |
| `speaking-explain-a-tradeoff` | 从自己的经历谈到社会选择 | 从个人例子抽取可讨论的问题；在抽象讨论中保留条件与权衡 | ielts-speaking：Speaking Part 3：从个人话题延伸到抽象讨论；例句、情境与探测为原创改编。 |
| `ielts-nature-linking` | 追清指代与跨句关系 | 为代词或概括词找可成立的指代；区分承接、因果和反预期 | ielts-reading：Reading：句间关系、指代和理解连贯文本；例句、情境与探测为原创改编。 |
| `ielts-maps-change` | 比较前后布局，不把没画出的东西补进去 | 准确区分新增、替换和未变化；固定地图方位和参照物 | ielts-writing：Academic Writing Task 1：map/site changes；例句、情境与探测为原创改编。 |
| `ielts-language-review` | 把含混的表达改得准确又自然 | 用准确搭配表达具体变化或影响；用指代和逻辑连接代替机械连接词 | ielts-scoring：IELTS Writing/Speaking：词汇准确适切与连贯；应用内部编辑任务；例句、情境与探测为原创改编。 |
| `ielts-space-inference` | 给推断划界，并说清不确定来自哪里 | 保留可能性及证据强度；指出区分竞争解释的证据 | ielts-reading：Reading：推断和作者主张的限定；例句、情境与探测为原创改编。 |
| `ielts-space-listening` | 先辨题目要什么，再跨题型听同一段 | 区分问目的、例子还是细节；将理解转换为合规答案 | ielts-listening：Listening：matching、note completion 与multiple choice的任务要求；例句、情境与探测为原创改编。 |
| `ielts-checkpoint` | 换陌生材料验证四项技能，并选择下一步 | 将回答与材料依据对应；根据具体错误选择后续练习 | ielts-scoring：IELTS四科评估方向；多模式证据与下一步复习为应用设计；例句、情境与探测为原创改编。 |

### GRE General

| 单元 ID | 可观察行动 | 知识点 | 直接依据与改编用途 |
| --- | --- | --- | --- |
| `gre-reading-habit` | 读出短文在解决什么问题 | 区分讨论对象和关于它的主张；用待解决问题检验每句功能 | gre-verbal：Verbal Reading Comprehension：主旨、结构与作者目的；例句、情境与探测为原创改编。 |
| `gre-vocab-context` | 用语境给多义词定准含义 | 根据论证选择词义；区分中立、褒贬与强度 | gre-verbal：Verbal：词在上下文中的意义与概念关系；例句、情境与探测为原创改编。 |
| `gre-sentence-logic` | 拆开长句，保住限定与逻辑骨架 | 从插入信息中找主断言；核对否定究竟排除了什么 | gre-verbal：Verbal：句子组成与逻辑关系；例句、情境与探测为原创改编。 |
| `verbal-text-completion` | 填空前先预测句子需要什么含义 | 先用简单词预测语义；将候选代回整句检验 | gre-verbal：Text Completion：利用上下文线索并核查完整句义；例句、情境与探测为原创改编。 |
| `gre-tc-multiple` | 多空互相校验，不在第一个顺词处停下 | 逐空建立并联条件；检查词组间的关系方向 | gre-verbal：Text Completion：两至三空的局部与整体一致性；例句、情境与探测为原创改编。 |
| `gre-tc-reversal` | 多次转折后，读出最后到底肯定什么 | 区分让步中的让步与主结论；核对每个对照的具体对象 | gre-verbal：Text Completion：转折线索与整段意义；例句、情境与探测为原创改编。 |
| `gre-se-meaning` | 先读完整句义，再找两种可成立的改写 | 先确定完整句子要表达什么；两项都适配，并构成等价整句 | gre-verbal：Sentence Equivalence：两项构成意义相同的完成句；例句、情境与探测为原创改编。 |
| `verbal-sentence-equivalence` | 排除熟悉同义对，核对语境中的等价 | 排除整对不适配的同义项；比较语境里的程度与搭配 | gre-verbal：Sentence Equivalence：上下文、词义和完整句义共同约束；例句、情境与探测为原创改编。 |
| `reading-claim-example` | 区分主结论、支持理由和举例 | 找出作者要读者接受的主张；解释例子支持了什么而非只复述 | gre-verbal：Reading Comprehension：主要与次要观点、概括和证据关系；例句、情境与探测为原创改编。 |
| `gre-rc-function` | 判断一句话在论证里做什么 | 按与上下文关系判断句子作用；区分承认异议与接受对方结论 | gre-verbal：Reading Comprehension：部分与整体的结构关系；例句、情境与探测为原创改编。 |
| `gre-rc-detail` | 核对细节时守住对象、条件和范围 | 逐项核对谁对谁有什么关系；区分必要、充分与范围限制 | gre-verbal：Reading Comprehension：具体信息和句子含义；例句、情境与探测为原创改编。 |
| `reading-qualifier-inference` | 只推到证据允许的位置 | 在改述中保存模态与量词；区分必随材料成立与仅有可能 | gre-verbal：Reading Comprehension：信息推断与限定强度；例句、情境与探测为原创改编。 |
| `gre-rc-perspective` | 追踪多方立场与作者的距离 | 建立说话者与主张对应；读出怀疑、认可或保留 | gre-verbal：Reading Comprehension：作者视角及多方观点；例句、情境与探测为原创改编。 |
| `reading-support-or-weaken` | 说明新证据怎样改变论证 | 找从证据跨到结论缺的一步；逐条说明加强或削弱的方向 | gre-verbal：Reading Comprehension：支持、削弱及替代解释；例句、情境与探测为原创改编。 |
| `reading-evaluate-multiple` | 多选逐项验证，拒绝把一项的真扩散到另一项 | 每个选项建立独立支持链；对复合选项检查每个分句 | gre-verbal：Reading Comprehension：select multiple correct answers；例句、情境与探测为原创改编。 |
| `reading-select-evidence-sentence` | 按所问功能选整句，不只点到关键词 | 以任务要求决定整句选择；区分重述结论与给出支持 | gre-verbal：Reading Comprehension：select a sentence from a passage；例句、情境与探测为原创改编。 |
| `writing-analyze-an-issue` | 先回应Issue的具体指令，再界定立场 | 把题目指令转成论证义务；用可辩护的范围陈述主张 | gre-writing：Analyze an Issue：按具体指令分析复杂观点、以理由与例证展开；不设置已取消的独立Analyze an Argument考试任务；例句、情境与探测为原创改编。 |
| `gre-issue-evidence` | 让例子解释机制，而非堆名字 | 解释例子到结论的连接；区分真实事实、假设例子与普遍结论 | gre-writing：Analyze an Issue：按具体指令分析复杂观点、以理由与例证展开；不设置已取消的独立Analyze an Argument考试任务；例句、情境与探测为原创改编。 |
| `gre-issue-countercase` | 认真处理强反例，并调整主张范围 | 回应最相关的反方理由；让步后说明怎样影响结论 | gre-writing：Analyze an Issue：按具体指令分析复杂观点、以理由与例证展开；不设置已取消的独立Analyze an Argument考试任务；例句、情境与探测为原创改编。 |
| `gre-issue-revision` | 改整篇论证的结构与精确性 | 用每段功能检查全文路线；修正改变意义的范围与连接 | gre-writing：Analyze an Issue：按具体指令分析复杂观点、以理由与例证展开；不设置已取消的独立Analyze an Argument考试任务；例句、情境与探测为原创改编。 |
| `gre-quant-arithmetic` | 读懂数的限制，算对整数、分数和幂根 | 用整数除法与整除检验余数；按分母与符号计算有理数；区分指数规则与平方根的定义 | gre-math：Math Review：Arithmetic §§1.1–1.5，整数、分数、幂根、实数；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-quant-ratio` | 选对比例基准，算对连续变化与速率 | 将比转为等份而非误当占比；用变化乘数处理不同基数；把速度与单位统一后计算 | gre-math：Math Review：Arithmetic §§1.6–1.7；Algebra §2.7 applications，ratio、percent、rate；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-quant-algebra` | 把文字关系列成式子，并核对解的范围 | 准确转写比较与不等式；用等价变形求解并检查多解；简化前保留被排除的值 | gre-math：Math Review：Algebra §§2.1、2.3–2.5，表达式、方程、不等式；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-quant-functions` | 读函数与坐标图，说明输入怎样影响输出 | 将函数当作输入到输出的规则；用斜率和截距解释直线；据给定坐标核对交点和可行区间 | gre-math：Math Review：Algebra §§2.6、2.8–2.9，functions、coordinate geometry、graphs；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-quant-geometry` | 用已知几何条件计算，拒绝凭图猜相等 | 区分图上看来如此和明确条件；区分长度、面积和体积的缩放；用半径高度及单位求几何量 | gre-math：Math Review：Geometry §§3.1–3.6，角、三角形、相似、圆及立体；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-quant-data` | 解释图表分布，不把平均数当全部 | 区分平均数与中位数；用范围与标准差描述离散；读清坐标、样本量和组别 | gre-math：Math Review：Data Analysis §§4.1–4.2，图表、中心与离散；总体SD为本单元明确采用定义；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-quant-probability` | 先看样本空间与是否放回，再算概率 | 以等可能结果建立分母；区分独立与无放回的条件变化；区分有序安排与无序选择 | gre-math：Math Review：Data Analysis §§4.3–4.4，counting与probability；条件概率遵循官方Quant范围；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `quant-compare-conditions` | 用边界与反例判断两数量关系 | 先读取实数、整数、正数和端点限制；用反例检验关系是否固定；按GRE四种关系报告结论 | gre-math：Math Review：Algebra §§2.3–2.6；Quantitative Comparison的比较与条件应用；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `quant-weighted-data` | 合并数据前先找分母和权重 | 按观测数量加权而非直接平均；合并集合时扣除重复成员；解释总体比例为何取决于组构成 | gre-math：Math Review：Data Analysis §§4.2、4.3、4.6，weighted mean、sets与数据解释；比例另参照Arithmetic §1.7；例句、情境与探测为原创改编。；gre-quant：Quantitative Reasoning：建模、计算、数量比较和数据解释；本单元保留真实数量推理，不把口头解释当GRE考试题型。 |
| `gre-checkpoint` | 在新材料中解释答案，并定位下一项巩固目标 | 分别建立文本与数量答案依据；根据本次输出区分错误来源 | gre-content：GRE General当前Verbal、Analyze an Issue和Quantitative范围；综合检查与错误分类为应用安排；例句、情境与探测为原创改编。 |
