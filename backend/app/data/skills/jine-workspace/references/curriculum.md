# 课程、人设和世界书

- “默认课程”指某门学习语言使用的课程，不是管家自己的课程。明确要求后用 course.set，选择真实 preset，并开启 ambient。
- 备考课用 `course.build` 做。四级、六级、雅思学术类、高考英语（新课标卷）、JLPT N1 的课表已经对着官方资料核过，报考试的名字就行；别的考试按用户这一轮附的资料排课表，资料里没有的事实会在课里标成「没有官方资料核对」。做好的课在课程目录里（id 以 my- 开头），要设为默认时用 `course.set` 的 preset。
- 每个角色只说自己的语言、维持自己的说话方式。
- `world.save` 管共享世界书（version 2：条目有 `keys`、`constant`、`position`、`conditions` 等字段，只写和默认值不同的；旧的 version 1 形状也收），`persona.edit` 用 `world_book_ids` 引用已有世界书。关键词只触发当前语境需要的条目；常驻条目会进系统提示词，少用。把可验证项目设定、角色说话方式、当前学什么放在各自位置。现有世界书的部分编辑需要原本的完整内容，缺失时请从专用设置读取或让用户说明范围。
- 主聊天只有一条时间线：一个主人设加若干副人设。`chat.room` 改它的设置（只传要改的字段）：`primary_id` 换主人设（时间线不换）、`language` 语言拨片、`fun` 趣味模式开关和 `fun_languages` 语言池、`primary_chime` 副人设主讲时主人设插一句的概率（0–100）、`guests` 副人设整张表（每项 `persona_id`、`enabled`、`rule` 出现时机：`always` / `time` 带 `start`、`end`（可跨零点）/ `keyword` 带 `keywords`、`chime` 插话概率 0–100）。改 guests 时把没让改的副人设原样带上。`inspect.chat_main` 是现在的设置和人设名字。
- `persona.edit` 的 `voice_samples` 是口吻样本 `{语言: [句子…]}`：只替换提到的那门语言，每句 2–60 字、每门最多 600 句，重复和空行会被去掉。`inspect.personas[].voice_sample_counts` 只给句数，要改某门语言就把那门整份重写；不要把剧情经历写成样本。
- 事件规则（hook，比如她主动发消息的时机）目前没有管家工具，只能在设置页编辑；用户问到时说明在哪改，不要提出操作。
- 仓库入口 `backend/app/services/course/`、`backend/app/routers/teaching.py` 和 `frontend/js/settings-teaching.js`。验证不同角色调用同一语言课程并保留各自共享世界书引用。
