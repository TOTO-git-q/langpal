# 日语教案 v2：作者说明与来源映射

核对与制作日期：2026-11-11。适用文件：`backend/app/data/teaching/jlpt-n1.json` 至 `jlpt-n5.json`。

## 交付范围

五份教案共 113 单元、229 个单元内知识点、458 条例句实例、462 条行为标准。课程和全部 113 个原单元 ID 保留，内容指纹随教案变化重新计算。没有迁移、删除或覆盖用户学习证据；没有修改公共 schema、运行时、UI、用户数据库或密钥。

| 课程 | 单元 | 知识点 | 行为标准 | 情境探测 |
| --- | ---: | ---: | ---: | ---: |
| JLPT N5 | 20 | 40 | 81 | 40 |
| JLPT N4 | 21 | 42 | 84 | 42 |
| JLPT N3 | 22 | 44 | 89 | 44 |
| JLPT N2 | 25 | 50 | 101 | 50 |
| JLPT N1 | 25 | 53 | 107 | 50 |

## 教学设计

单元标题和 Can-do 描述用户能完成的行动：澄清、点单、解释改动、转告消息、比较条件、向同伴说明论证等。各单元有两份明确不同的情境材料、2–3 个具体知识点、使用条件、两条例句、与相近表达的区别，以及逐点语义/适用性两类必需标准。例句、案例、活动与评价文本均为本项目原创改编，不是教材引文或官方原题。

作者库有 98 份具体语言知识记录，在不同单元中按新材料再次使用；重复某项词句知识是螺旋练习，不把它冒充新增语法。每次复用保留相同含义边界，而单元任务、人物、资料和迁移约束不同。知识点证据仍按单元与模式记录。

七段流程包括自然接入、真实输入、注意差异、按需支架、独立任务、不同场景迁移和提取。读解、叙事、听解、任务协商、角色互动与语言组织使用不同流程配方；每份配方都填入本单元具体材料、对比与行动要求。点单核对、授受视点、邮件回复、人物叙事重释、资料交接另有逐段人工专写流程。表达类任务允许用户自主选择真实经历、安排和观点，不能由教师替用户写好内容再把复读记成掌握。

N1 保留高级理解：社论中的设问—表面回答—反例—修正结论，抽象定义、比喻边界、作者与引用立场，留有歧义的叙事，三段长文的跨段结构，多人和两种信息的听力整合。口头转述是理解之后的交流迁移；不把日常口语或术语命中替代 JLPT N1 阅读/听力要求。

打字与口语任务共享知识，但处理方式不同：打字可以保留原文并组织消息；听力先隐藏脚本再听，口语还需回应追问。只有文本时，只能练习脚本理解，不能标作听懂了录音。发音知识的形式运用标准须有原音；文字可支持词义关系判断，不能推断音拍、发音、停顿或流利度。

## 评价与推进边界

每个知识点有语义与适用性两条必需四档标准。档位描述保留具体检查项或表达区别，不用出现某个词就判对；合理等义表达可以达标。两个不同场景的探测覆盖所有知识点和 typed/spoken。没有实际产出或没有必要音频时保持未评价，不能把缺证据当失败。教师例句、提示后答案、照抄和即时复述不作独立成功。

当前课程策略使用应用默认值：独立成功至少 2，场景至少 2，保持表现至少 2；有效机会间隔 3、复习间隔 3/8/20。这些数字仅存于可编辑 teaching_policy，活动文本按当前策略安排，不把次数当作学会的充分证明，不宣称经过教育测量校准。各知识点还须满足本次实际语义、条件、独立性与证据标准。先修采用同课程有向无环的技能顺序，不用上课日历。

## 来源与归级边界

- JLPT 官方规定能力范围和试题形式，不发布 2010 年之后的封闭词汇、汉字、语法清单。本项目不宣称收集了官方穷尽考点；具体表达的教学编排不等于官方唯一归级。
- Irodori Starter 为 A1、Elementary 1/2 为 A2。这里只参考可核对的生活任务与课序，不宣布 A1=N5 或 A2=N4。
- N3–N1 参考新完全マスター出版社公开目录中的语法功能组、语篇训练顺序和听解题型。没有访问或复制完整受版权保护的教材章节，也不冒称例句或活动来自其正文。source_refs 中的定位是公开目录的章节/任务位置，不能当成所有句型均在该章原文出现的证明。
- 日本基金 MY Can-do/任务型课堂文章用于具体交际对象、情境、行动和任务迁移的设计框架。文章重点为 Marugoto B1，不将其活动难度直接当作 N1 或其它 JLPT 等级的测量依据。
- JLPT 不设口语或作文考试；课程内的口头说明、邮件回复和自主表达服务于学习迁移，而非新增官方题型。
- 情境中的调查、制度、人物与机构均为虚构教学材料；不能作为现实事实或专业建议。生成音频、自动评价是否准确、课程是否改善真实成绩，还需另行运行验证和学习者证据，本次数据校验不证明这些效果。

## 核对的直接来源

- [JLPT 官方等级能力说明](https://www.jlpt.jp/e/about/levelsummary.html)
- [JLPT 官方试题构成](https://www.jlpt.jp/e/guideline/testsections.html)
- [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)
- [日本基金 MY Can-do 与任务型课堂设计](https://www.jpf.go.jp/e/project/japanese/teach/tsushin/news/202309.html)
- [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)
- [日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)
- [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)
- [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)
- [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)
- [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)
- [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)
- [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)
- [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)
- [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)
- [JLPT 官方 FAQ：不发布封闭内容清单、无会话作文考试](https://www.jlpt.jp/e/faq/)

## 再生产与审查

1. `authoring/japanese_seed.json` 只保留旧课程/单元 ID 和已核对的来源定位，不含 v1 六字段教学正文。
2. `authoring/japanese_materials.py` 是可编辑语言记录、逐单元情境配方和专写活动；每个知识点有真实形式、两个原创例句、使用条件、区别与观察点。
3. `authoring/japanese.py` 将作者记录组装为冻结 v2；每份输出前都运行实际 `CourseV2.model_validate_json` 和 `Draft202012Validator`，不接触数据库或网络。
4. 如改知识点或场景，先核对形式、意义、区别与任务是否匹配；再看两场景是否真的需要重新组织，最后修改标准与探测。
5. 项目 venv 运行 `python authoring/japanese.py` 可重生全部五份；`--course jlpt-n1` 可只生成一份。测试 `python -m unittest discover -s tests -p test_course_v2_japanese.py -v`；设置 `PYTHONPATH=backend`。测试禁止打开任何 SQLite 数据库。

## 逐单元行动、语言点与来源

### JLPT N5（20 单元）

| ID | 用户行动 | 具体形式/策略 | 来源定位 |
| --- | --- | --- | --- |
| `n5-sounds` | 听清名字并按时间打招呼 | おばさん／おばあさん、きて／きって、四時／七時；おはようございます／こんにちは／よろしくお願いします | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 课堂用语、第 1–2 课；JLPT N5 熟悉主题的基础听读。 |
| `n5-repair` | 没听清时请对方重说再确认 | もう一度お願いします／ゆっくりお願いします；〜ですか／〜ですね／〜じゃありません | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 课堂用语、第 1–2 课；JLPT N5 熟悉主题的基础听读。 |
| `first-introduction` | 介绍自己并问一项对方信息 | 〜は〜です／〜も〜です／〜ですか；何／どこ／いつ／どんな | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 3–4 课：自我介绍、住所与家人。 |
| `n5-home` | 说清住处与家人的所在 | 場所に住んでいます／人は場所にいます；一つ・二つ／一人・二人／一冊・二冊／一枚・二枚 | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 3–4 课：自我介绍、住所与家人。 |
| `n5-food` | 听懂食物喜好并说自己的选择 | 〜が好きです／あまり〜好きじゃありません；何／どこ／いつ／どんな | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 5–6 课：饮食喜好、简单点单。 |
| `cafe-order` | 看菜单点出商品和数量 | 名詞を数量ください／〜をお願いします；一つ・二つ／一人・二人／一冊・二冊／一枚・二枚 | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 5–6 课：饮食喜好、简单点单。 |
| `n5-room` | 根据描述判断哪里有人或有物 | 場所に人・動物がいます／物があります；〜の上・下・前・後ろ・隣・中 | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 7–8 课：房屋、职场与位置。 |
| `where-things-are` | 用参照物告诉对方东西在哪 | 〜の上・下・前・後ろ・隣・中；〜ですか／〜ですね／〜じゃありません | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 7–8 课：房屋、职场与位置。 |
| `daily-clock` | 把两件日常动作和时刻对上 | 〜時に〜ます／何時に；〜から〜まで／〜曜日は休みです | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 9–10 课：日程与日常请求。 |
| `n5-request` | 请对方借物或做一个明确动作 | 〜てください／〜を貸してください；これ・それ・あれ／この・その・あの＋名詞 | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 9–10 课：日程与日常请求。 |
| `ask-for-permission` | 先问能否做，再按规则行动 | 〜てもいいですか／はい、どうぞ；〜てはいけません／〜はだめです | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：JLPT 基础日常理解；由 Starter 请求主题延展的许可迁移，不宣称官方句型归级。 |
| `opening-hours` | 看告示判断什么时候能去 | 〜から〜まで／〜曜日は休みです；〜時に〜ます／何時に | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：JLPT 基础阅读与信息检索；整合 Starter 日程、购物主题，任务由 JINE 改编。 |
| `n5-interests` | 围绕同一爱好问一项细节 | よく／時々／あまり〜ません／いつも；何／どこ／いつ／どんな | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 11–12 课：爱好、邀请。 |
| `simple-invitation` | 接受或婉拒邀请并定个时间地点 | 〜ませんか／いいですね／〜はちょっと；〜時に〜ます／何時に | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 11–12 课：爱好、邀请。 |
| `destination-by-train` | 确认目的地与交通方式 | 場所に・へ行きます／乗り物で行きます；〜ですか／〜ですね／〜じゃありません | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 13–14 课：交通与城镇描述。 |
| `n5-description` | 按两个特征让对方认出目标 | い形容詞＋名詞／な形容詞＋な＋名詞；これ・それ・あれ／この・その・あの＋名詞 | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 13–14 课：交通与城镇描述。 |
| `n5-shopping` | 问清单价再买对数量 | いくらですか／〜円／一つで〜円；名詞を数量ください／〜をお願いします | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 15–16 课：购物与价钱。 |
| `yesterday-update` | 说清昨天做过和没做过的事 | 〜ました／〜ませんでした／〜かったです；それから／でも／先に | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：Irodori Starter 第 17–18 课：假日经历。 |
| `short-message-details` | 按最新消息确认见面安排 | 〜ですか／〜ですね／〜じゃありません；それから／でも／先に | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：JLPT 基础阅读与信息检索；整合 Starter 日程、购物主题，任务由 JINE 改编。 |
| `n5-checkpoint` | 读听新安排后提出可行回应 | 〜から〜まで／〜曜日は休みです；〜ませんか／いいですね／〜はちょっと | [日本基金 Irodori 入门课程目录](https://www.irodori.jpf.go.jp/en/starter/pdf.html)：以上基础听读、语言知识与生活主题的陌生材料迁移检查。 |

### JLPT N4（21 单元）

| ID | 用户行动 | 具体形式/策略 | 来源定位 |
| --- | --- | --- | --- |
| `n4-current-self` | 说清最近变化和现在的生活 | 〜ています／〜てきました／先月から；〜ので／〜から／〜んです | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 1–2 课：近况与兴趣。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 1–2 课：近况与兴趣。 |
| `n4-hobby-detail` | 介绍爱好并说一个具体限制 | 動詞辞書形＋のが好き／得意・苦手；よく／時々／あまり〜ません／いつも | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 1–2 课：近况与兴趣。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 1–2 课：近况与兴趣。 |
| `n4-season` | 用前后对比说明季节变化 | い形容詞〜くなる／な形容詞〜になる；い形容詞＋名詞／な形容詞＋な＋名詞 | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 3–4 课：季节与天气经历。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 3–4 课：季节与天气经历。 |
| `n4-weather-past` | 解释天气怎样改变了计划 | 〜ので／〜から／〜んです；〜ました／〜ませんでした／〜かったです | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 3–4 课：季节与天气经历。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 3–4 课：季节与天气经历。 |
| `preference-with-reason` | 按需求比较两个住处或地点 | AよりBのほうが〜／〜けれど／どちら；動詞ます形＋やすい・にくい | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 5–6 课：城镇评价与路线。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 5–6 课：城镇评价与路线。 |
| `steps-in-order` | 按参照物和步骤给出路线 | 〜てから／〜前に／〜たあとで；〜の上・下・前・後ろ・隣・中 | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 5–6 课：城镇评价与路线。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 5–6 课：城镇评价与路线。 |
| `explain-a-delay` | 说明迟到原因并给预计到达 | 〜てしまいました／〜ちゃった；〜と思います／〜ぐらい／たぶん | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 7–8 课：迟到、经验。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 7–8 课：迟到、经验。 |
| `firsthand-experience` | 讲一次实际经历而不混入计划 | 〜たことがある／〜たことがない；〜ました／〜ませんでした／〜かったです | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 7–8 课：迟到、经验。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 7–8 课：迟到、经验。 |
| `listen-ask-back` | 问清一个汉字或填写方法 | 何と読みますか／どういう意味ですか／〜ばいいですか；〜ですか／〜ですね／〜じゃありません | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 9–10 课：汉字读音与学习；Elementary 2 第 17–18 课：能力与将来。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 9–10 课：汉字读音与学习；Elementary 2 第 17–18 课：能力与将来。 |
| `n4-learning-plan` | 说清想做、打算做和下一步 | 〜たい／〜つもり／〜予定；〜てから／〜前に／〜たあとで | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 9–10 课：汉字读音与学习；Elementary 2 第 17–18 课：能力与将来。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 9–10 课：汉字读音与学习；Elementary 2 第 17–18 课：能力与将来。 |
| `n4-preparation` | 按清单分出已备妥和待准备 | 〜ておく／〜てある；もう〜た／まだ〜ていない／〜ている | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 11–12 课：饮食准备；Elementary 2 第 15 课：留下的状态。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 11–12 课：饮食准备；Elementary 2 第 15 课：留下的状态。 |
| `n4-food-conditions` | 说明饮食限制并核对替代菜 | 〜が入っている／〜ので食べられません；形容詞語幹＋そう／〜そうに見える | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 12 课；Elementary 2 第 3–4 课：饮食限制与吃法。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 12 课；Elementary 2 第 3–4 课：饮食限制与吃法。 |
| `ongoing-or-done` | 报告已经完成与仍未确定的进度 | もう〜た／まだ〜ていない／〜ている；〜と思います／〜ぐらい／たぶん | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 13–14 课：预计完成、请假与请求。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 13–14 课：预计完成、请假与请求。 |
| `favor-and-alternative` | 带理由请求许可并给替代办法 | 〜てもいいですか／はい、どうぞ；〜ので／〜から／〜んです | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 13–14 课：预计完成、请假与请求。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 13–14 课：预计完成、请假与请求。 |
| `n4-health` | 描述不舒服并回应生活建议 | 〜ので／〜から／〜んです；〜たほうがいい／〜ないほうがいい | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 15–16 课：身体情况、生活习惯。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 15–16 课：身体情况、生活习惯。 |
| `n4-giving` | 感谢一次帮助并说清谁做了什么 | 〜てくれる／〜てもらう／〜てあげる；〜が〜を／〜は〜に／〜てくる・いく | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 1 第 17–18 课：个人关系与礼物。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 1 第 17–18 课：个人关系与礼物。 |
| `contingency-plan` | 按条件变化商量备选安排 | 〜たら／〜なら／〜ても；〜たい／〜つもり／〜予定 | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 2 第 7–8 课：条件变化与活动信息；后者为消息转述迁移。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 2 第 7–8 课：条件变化与活动信息；后者为消息转述迁移。 |
| `relay-a-changed-plan` | 带来源把最新改动转告给朋友 | 〜と言っていました／〜そうです；もう〜た／まだ〜ていない／〜ている | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 2 第 7–8 课：条件变化与活动信息；后者为消息转述迁移。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 2 第 7–8 课：条件变化与活动信息；后者为消息转述迁移。 |
| `find-the-right-option` | 按使用目的挑一项商品或服务 | 動詞ます形＋やすい・にくい；AよりBのほうが〜／〜けれど／どちら | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：Irodori Elementary 2 第 11–14 课：商品比较与服务请求。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：Irodori Elementary 2 第 11–14 课：商品比较与服务请求。 |
| `n4-task-listening` | 听完纠正后说出先做什么 | 〜てから／〜前に／〜たあとで；〜たら／〜なら／〜ても | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：JLPT N4 基础日常阅读、稍慢听力与任务理解；整合两册生活主题。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：JLPT N4 基础日常阅读、稍慢听力与任务理解；整合两册生活主题。 |
| `n4-checkpoint` | 读听新通知后作出相关安排 | 〜たら／〜なら／〜ても；〜と言っていました／〜そうです | [日本基金 Irodori 初级 1 课程目录](https://www.irodori.jpf.go.jp/en/elementary01/pdf.html)：JLPT N4 基础日常阅读、稍慢听力与任务理解；整合两册生活主题。；[日本基金 Irodori 初级 2 课程目录](https://www.irodori.jpf.go.jp/en/elementary02/pdf.html)：JLPT N4 基础日常阅读、稍慢听力与任务理解；整合两册生活主题。 |

### JLPT N3（22 单元）

| ID | 用户行动 | 具体形式/策略 | 来源定位 |
| --- | --- | --- | --- |
| `paraphrase-from-context` | 把短通知改成朋友听得懂的话 | 〜を希望する方／〜までに／なお；普通体／丁寧体／書面語→自然な会話 | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部「読むための基礎トレーニング」：书面语、和语与汉语词、语法性表达。标题任务为说明文主题迁移。 |
| `n3-word-families` | 按搭配解释一个汉字词的意思 | 道具を使う／施設を利用する／内容を確認する；つまり／言い換えると／抽象語と具体例 | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部「読むための基礎トレーニング」：书面语、和语与汉语词、语法性表达。标题任务为说明文主题迁移。 |
| `headline-to-chat` | 用正文修正对标题的第一理解 | 見出しの省略／対象・時点・条件を本文で確認；〜を希望する方／〜までに／なお | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部「読むための基礎トレーニング」：书面语、和语与汉语词、语法性表达。标题任务为说明文主题迁移。 |
| `repair-the-misunderstanding` | 把尚未确定与不能做的误解改清 | 〜という意味ではなく／〜ということですね；〜ですか／〜ですね／〜じゃありません | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：语法组合、主题、主语、长句。修复对话为同一解析能力的迁移。 |
| `n3-grammar-chunks` | 读出长修饰里谁做了什么 | 名詞を修飾する節／格助詞／主述対応；〜は／〜が／文脈による主語省略 | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：语法组合、主题、主语、长句。修复对话为同一解析能力的迁移。 |
| `n3-topic-subject` | 跨句补出被省略的人物 | 〜は／〜が／文脈による主語省略；〜が〜を／〜は〜に／〜てくる・いく | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：语法组合、主题、主语、长句。修复对话为同一解析能力的迁移。 |
| `follow-a-turning-point` | 根据转折更新对故事的理解 | しかし／そのため／例えば／〜はずだったが；〜と感じた／〜と思った／初めは〜が | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：预测后文、指示、段落结构、作者感受。 |
| `n3-reference` | 把そのため换成完整事件 | それ／そのため／そのこと／前文の出来事；〜てから／〜前に／〜たあとで | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：预测后文、指示、段落结构、作者感受。 |
| `n3-paragraph` | 用一句话概括再给一条依据 | 中心の考え／理由／具体例；しかし／そのため／例えば／〜はずだったが | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：预测后文、指示、段落结构、作者感受。 |
| `compare-personal-reviews` | 分开两份评论里的事实与感受 | 〜と感じた／〜と思った／初めは〜が；AよりBのほうが〜／〜けれど／どちら | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 1 部：预测后文、指示、段落结构、作者感受。 |
| `n3-mail` | 读懂改约邮件并给完整回应 | 〜ので／〜てもらえませんか／変更・確認の依頼；〜と言っていました／〜そうです | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 2 部：邮件、便条、说明、意见文、解说文与随笔。 |
| `rule-versus-decision` | 分清通知规定与个人选择 | 〜ことになっている／〜ことにした／〜必要がある；〜てから／〜前に／〜たあとで | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 2 部：邮件、便条、说明、意见文、解说文与随笔。 |
| `n3-opinion` | 准确转述一条观点及其理由 | 中心の考え／理由／具体例；〜ので／〜から／〜んです | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 2 部：邮件、便条、说明、意见文、解说文与随笔。 |
| `conditions-in-a-notice` | 根据两项条件找到可选项目 | 〜ことになっている／〜ことにした／〜必要がある；質問の対象→該当箇所→否定・比較・範囲の照合 | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：3A N3 读解第 3 部：广告、募集、通知、说明、图表与业务邮件。 |
| `n3-sound` | 在相近音和数字中确认关键信息 | おばさん／おばあさん、きて／きって、四時／七時；〜ておく→〜とく／〜のでは→〜んじゃ／音拍と句末 | [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)：3A N3 听解实力养成 I：相似音、数字、重音语调与音变。 |
| `n3-situation` | 按场景区分求助、许可和主动帮助 | 〜ましょうか／〜てもらえますか／〜てもいいですか；〜てもいいですか／はい、どうぞ | [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)：3A N3 听解实力养成 II：场景、许可请求、问题与帮助的表达。 |
| `hear-a-soft-refusal` | 听懂间接拒绝并商量另一种办法 | 〜たいのですが／〜はちょっと／〜なら；〜ましょうか／〜てもらえますか／〜てもいいですか | [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)：3A N3 听解实力养成 III：动作主体、敬语、惯用回应与间接回应。 |
| `group-task-handoff` | 听完任务后确认谁先做哪一步 | 〜てから／〜前に／〜たあとで；〜は／〜が／文脈による主語省略 | [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)：3A N3 听解实力养成 IV：要做什么、先做什么。 |
| `n3-listening-point` | 结合转折和追加听出最终评价 | 〜けれど／それより／実は／最終評価；しかし／そのため／例えば／〜はずだったが | [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)：3A N3 听解实力养成 V：肯否、改写与追加信息。 |
| `pass-along-a-voice-update` | 把语音里的主旨和必要信息转成消息 | 中心の考え／理由／具体例；〜と言っていました／〜そうです | [3A 新完全マスター N3 听解目录](https://www.3anet.co.jp/np/books/3644/)：3A N3 听解实力养成 VI：话题、意图和整体意见；口头转述为迁移。 |
| `n3-text-grammar` | 把一段经历连成时态和视点一致的消息 | それ／そのため／そのこと／前文の出来事；〜ています／〜てきました／先月から | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：JLPT N3 句子语法、文章语法与综合读听任务；3A 读解第 4 部题型练习与两册复习。 |
| `n3-checkpoint` | 用新材料修正规则与决定的误解 | 〜ことになっている／〜ことにした／〜必要がある；〜という意味ではなく／〜ということですね | [3A 新完全マスター N3 读解目录](https://www.3anet.co.jp/np/books/3614/)：JLPT N3 句子语法、文章语法与综合读听任务；3A 读解第 4 部题型练习与两册复习。 |

### JLPT N2（25 单元）

| ID | 用户行动 | 具体形式/策略 | 来源定位 |
| --- | --- | --- | --- |
| `n2-lexical-reading` | 按语境解释延期与取消的区别 | 見直す／再検討する／撤回する；つまり／言い換えると／抽象語と具体例 | [JLPT 官方等级能力说明](https://www.jlpt.jp/e/about/levelsummary.html)：JLPT 语言知识：汉字读音、构词、语境义、近义改写与用法；不作为封闭词表。 |
| `n2-time-aspect` | 说清插入事件时原动作进行到哪里 | 〜たとたん／〜最中に；〜つつある／〜て以来 | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 1 部第 1–3 课：时间节点、进行与完成后的关系。 |
| `n2-scope` | 按限定词判断谁能参加 | 〜に限らず／〜のみならず；〜に限り／〜限りでは | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 1 部第 4–7 课：范围、限定、追加与对象。 |
| `n2-basis` | 解释按什么材料和条件作决定 | 〜に基づいて／〜に沿って；〜に応じて／〜につれて | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 1 部第 8–10 课：依据、相关变化与例示。 |
| `qualified-agreement` | 承认优点后说清适用边界 | 〜わけではない／〜からといって；〜とはいえ／〜といえども | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 1 部第 11–17 课：否定、让步、条件和原因。 |
| `n2-assembly` | 把语块连成关系明确的句子 | 名詞を修飾する節／格助詞／主述対応；〜が〜を／〜は〜に／〜てくる・いく | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 2 部：句子组装。 |
| `n2-discourse` | 跨句追踪谁把资料交给谁 | 〜が〜を／〜は〜に／〜てくる・いく；その判断／こうした事態／省略内容の復元 | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 3 部：时态、视点、指示、连接、语体；转述来源为视点迁移。 |
| `attribute-what-you-heard` | 转述时分开确认消息与个人推测 | 〜そうだ／〜ようだ／〜とのことだ；〜とは限らない／〜可能性がある／〜に違いない | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A N2 文法第 3 部：时态、视点、指示、连接、语体；转述来源为视点迁移。 |
| `resolve-a-source-mismatch` | 找出两份通知冲突在哪里 | 共通結論／異なる根拠／評価基準；原則／ただし／〜に限って／適用対象照合 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 3 部：中篇、长篇主张、整合理解、信息检索；冲突核对为整合阅读迁移。 |
| `n2-contrast` | 按同一维度说明两方差异 | 一方／これに対して／対比軸をそろえる；質問の対象→該当箇所→否定・比較・範囲の照合 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 1 部：对比、改写、比喻、设问、明确主张及局部问题。 |
| `n2-paraphrase` | 把抽象说明换成不走样的日常话 | つまり／言い換えると／抽象語と具体例；その判断／こうした事態／省略内容の復元 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 1 部：对比、改写、比喻、设问、明确主张及局部问题。 |
| `separate-example-and-scope` | 说清比喻或例子能支持哪一点 | 比喩の対応／本体と喩体／適用限界；明示／支持される推論／未記載／反証 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 1 部：对比、改写、比喻、设问、明确主张及局部问题。 |
| `recover-the-main-claim` | 从设问和例子找到作者主张 | 問い→仮の答え→反例→修正された主張；具体例→共通項→話の構造→主張 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 1 部：对比、改写、比喻、设问、明确主张及局部问题。 |
| `n2-local-evidence` | 用完整事件解释画线部分 | その判断／こうした事態／省略内容の復元；質問の対象→該当箇所→否定・比較・範囲の照合 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 1 部：对比、改写、比喻、设问、明确主张及局部问题。 |
| `extract-exact-eligibility` | 按两项条件挑出可报名的活动 | 原則／ただし／〜に限って／適用対象照合；〜に限り／〜限りでは | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 2 部：先确认实用文本目的，再检索广告、通知、说明和表格。 |
| `compare-two-articles` | 分别还原两篇文章的赞同点和理由 | 共通結論／異なる根拠／評価基準；つまり／言い換えると／抽象語と具体例 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 3 部：中篇、长篇主张、整合理解、信息检索；冲突核对为整合阅读迁移。 |
| `n2-long-reading` | 按段落说明长文怎样得出结论 | 具体例→共通項→話の構造→主張；明示／支持される推論／未記載／反証 | [3A 新完全マスター N2 读解目录](https://www.3anet.co.jp/np/books/3612/)：3A N2 读解第 3 部：中篇、长篇主张、整合理解、信息检索；冲突核对为整合阅读迁移。 |
| `n2-sound` | 听出缩略表达中的改口和否定 | 〜ておく→〜とく／〜のでは→〜んじゃ／音拍と句末；〜ではなく／というより／つまり／言い換え | [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)：3A N2 听解实力养成 I：相似音、音变、缩略。 |
| `read-the-implied-request` | 听出婉拒后提出可行替代 | 〜たいのですが／〜はちょっと／〜なら；〜というわけには／〜ていただけると／文脈と語調 | [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)：3A N2 听解实力养成 II：即时回应，动作主体、语调、间接回答。 |
| `n2-task` | 听完变更确认第一步 | まず／後回しでよい／〜より先に／訂正；質問の対象→該当箇所→否定・比較・範囲の照合 | [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)：3A N2 听解实力养成 III：任务、第一步和条件。 |
| `n2-point` | 在同义改写中找到真正理由 | 〜ではなく／というより／つまり／言い換え；質問の対象→該当箇所→否定・比較・範囲の照合 | [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)：3A N2 听解实力养成 IV：相关信息、改写与要点。 |
| `summarize-an-interview` | 把访谈的主题与主张分开概括 | 具体例→共通項→話の構造→主張；〜とされる／しかし／評価語・引用の距離 | [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)：3A N2 听解实力养成 V：例子与概括、主旨、意图；访谈概括为迁移。 |
| `n2-integrated-listening` | 把三个人的限制合成一个安排 | 話者別の希望・制約／共通部分／最終合意；まず／後回しでよい／〜より先に／訂正 | [3A 新完全マスター N2 听解目录](https://www.3anet.co.jp/np/books/3642/)：3A N2 听解实力养成 VI：多人、两种话语的整合。 |
| `switch-register` | 把公告改成给朋友或同事的消息 | 普通体／丁寧体／書面語→自然な会話；〜そうだ／〜ようだ／〜とのことだ | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A 文法语体一致性及读听综合；转成自然对话是应用迁移，不是 JLPT 口试。 |
| `n2-checkpoint` | 在新主题中依据材料作判断并回应 | 明示／支持される推論／未記載／反証；〜という理解でよいか／〜場合はどうか | [3A 新完全マスター N2 文法目录](https://www.3anet.co.jp/np/books/3602/)：3A 文法语体一致性及读听综合；转成自然对话是应用迁移，不是 JLPT 口试。 |

### JLPT N1（25 单元）

| ID | 用户行动 | 具体形式/策略 | 来源定位 |
| --- | --- | --- | --- |
| `n1-lexical-precision` | 解释为什么是重新审视而非取消 | 見直す／再検討する／撤回する；〜とは限らない／〜可能性がある／〜に違いない | [JLPT 官方等级能力说明](https://www.jlpt.jp/e/about/levelsummary.html)：JLPT N1 语言知识题型；官方高级词义、读音、改写、用法能力边界，不是官方封闭清单。 |
| `n1-time-boundary` | 还原一段事件的起止与反复 | 〜が早いか／〜そばから；〜を皮切りに／〜に至るまで／〜をもって | [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)：3A N1 文法第 1 部第 1–2 课：时间与范围边界。 |
| `keep-the-strength-of-a-claim` | 转述结论而不扩大力度 | 〜にとどまらず／〜ならでは；〜とは限らない／〜可能性がある／〜に違いない | [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)：3A N1 文法第 1 部第 3–4 课及主观判断章节：限定、追加、例示与强度。 |
| `n1-relation` | 按条件是否有效解释两条规则 | 〜いかんにかかわらず／〜いかんで；〜以上／〜からには／〜なくしては | [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)：3A N1 文法第 1 部第 5–7 课：相关、无关、样态、伴随。 |
| `n1-concession` | 解释作者承认什么、保留什么 | 〜とはいえ／〜といえども；明示／支持される推論／未記載／反証 | [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)：3A N1 文法第 1 部第 8–12 课：逆接、条件、目的手段、原因理由。 |
| `n1-means-cause` | 读出理由中的强调与必要条件 | 〜ばこそ／〜ゆえに／〜なしに；〜以上／〜からには／〜なくしては | [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)：3A N1 文法第 1 部第 8–12 课：逆接、条件、目的手段、原因理由。 |
| `n1-sentence-discourse` | 把打乱的论述还原成有边界的结论 | 〜以上／〜からには／〜なくしては；その判断／こうした事態／省略内容の復元 | [3A 新完全マスター N1 文法目录](https://www.3anet.co.jp/np/books/3600/)：3A N1 文法第 2–3 部：组装、时态、条件、视点、指示、连接和语体。 |
| `n1-contrast` | 沿同一尺度比较两种选择 | 一方／これに対して／対比軸をそろえる；共通結論／異なる根拠／評価基準 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 1 部：对比、换言、比喻、设问与指代、意义、理由、例子。 |
| `unpack-an-abstract-distinction` | 用新例子说明抽象概念的边界 | ここでいう〜とは／言い換えれば／具体例→概念；明示／支持される推論／未記載／反証 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 1 部：对比、换言、比喻、设问与指代、意义、理由、例子。 |
| `n1-metaphor` | 解释比喻怎样支撑论点 | 比喩の対応／本体と喩体／適用限界；問い→仮の答え→反例→修正された主張 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 1 部：对比、换言、比喻、设问与指代、意义、理由、例子。 |
| `map-an-editorial-argument` | 从社论设问还原作者的条件结论 | 問い→仮の答え→反例→修正された主張；一方／これに対して／対比軸をそろえる；明示／支持される推論／未記載／反証 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 1 部：对比、换言、比喻、设问与指代、意义、理由、例子。 |
| `n1-local-reading` | 把画线短语还原成完整意思 | その判断／こうした事態／省略内容の復元；〜とされる／しかし／評価語・引用の距離 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 1 部：对比、换言、比喻、设问与指代、意义、理由、例子。 |
| `read-the-unspoken-stance` | 指出作者与引用观点之间的距离 | 〜とされる／しかし／評価語・引用の距離；〜とはいえ／〜といえども | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：JLPT N1 官方能力：抽象复杂评论、深层叙事与语境意图；3A 读解主张理解。追问为沟通迁移。 |
| `track-a-narrative-reversal` | 用结尾线索重新解释人物行为 | 語り手の視点／回想／結末による再解釈；明示／支持される推論／未記載／反証 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：JLPT N1 官方能力：抽象复杂评论、深层叙事与语境意图；3A 读解主张理解。追问为沟通迁移。 |
| `ask-without-flattening-nuance` | 准确复述后追问一个边界 | 〜という理解でよいか／〜場合はどうか；ここでいう〜とは／言い換えれば／具体例→概念 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：JLPT N1 官方能力：抽象复杂评论、深层叙事与语境意图；3A 读解主张理解。追问为沟通迁移。 |
| `n1-practical-search` | 按身份和例外选出有效办理条件 | 原則／ただし／〜に限って／適用対象照合；その判断／こうした事態／省略内容の復元 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 2 部：实用文本目的与广告、通知、说明、表格的信息检索。 |
| `compare-competing-frames` | 比较两篇文章的共同点与依据 | 共通結論／異なる根拠／評価基準；一方／これに対して／対比軸をそろえる | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 3 部：中长篇、作者主张、两文整合理解。 |
| `n1-long-argument` | 跨段还原长文的论证骨架 | 問い→仮の答え→反例→修正された主張；具体例→共通項→話の構造→主張；明示／支持される推論／未記載／反証 | [3A 新完全マスター N1 读解目录](https://www.3anet.co.jp/np/books/3610/)：3A N1 读解第 3 部：中长篇、作者主张、两文整合理解。 |
| `n1-sound` | 在自然语流中听出否定与疑虑 | 〜ておく→〜とく／〜のでは→〜んじゃ／音拍と句末；〜というわけには／〜ていただけると／文脈と語調 | [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)：3A N1 听解实力养成 I：相似音与缩略。 |
| `n1-response` | 按委婉回应继续商量 | 〜というわけには／〜ていただけると／文脈と語調；〜という理解でよいか／〜場合はどうか | [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)：3A N1 听解实力养成 II：动作主体、态度、已然未然、语调、惯用回应。 |
| `n1-priority` | 在变更后确认谁先做什么 | まず／後回しでよい／〜より先に／訂正；〜ではなく／というより／つまり／言い換え | [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)：3A N1 听解实力养成 III：任务、优先、条件整理。 |
| `n1-listening-point` | 用语义改写匹配真正决定因素 | 〜ではなく／というより／つまり／言い換え；明示／支持される推論／未記載／反証 | [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)：3A N1 听解实力养成 IV：相关性、改写、多信息筛选。 |
| `hear-a-lecture-structure` | 把讲座中的三个例子归回主张 | 具体例→共通項→話の構造→主張；〜とされる／しかし／評価語・引用の距離 | [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)：3A N1 听解实力养成 V：例子与概括、结构、主张与意图。 |
| `identify-speaker-alignments` | 整合多人意见后说明真正共识 | 話者別の希望・制約／共通部分／最終合意；まず／後回しでよい／〜より先に／訂正 | [3A 新完全マスター N1 听解目录](https://www.3anet.co.jp/np/books/3640/)：3A N1 听解实力养成 VI：多人及两种话语整合。 |
| `brief-from-mixed-sources` | 综合文字与录音给出带来源的摘要 | 共通結論／異なる根拠／評価基準；話者別の希望・制約／共通部分／最終合意；明示／支持される推論／未記載／反証 | [JLPT 官方等级能力说明](https://www.jlpt.jp/e/about/levelsummary.html)：以上读听综合迁移；书面概括与自然聊天是 JINE 运用任务，不是 JLPT 新增考试项目。 |

