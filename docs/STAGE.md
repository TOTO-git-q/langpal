# 角色窗口（Stage）

主聊天对象在一扇自己的小窗里陪着用户：切到阅读、听力、口语时她还在。现在只有糖糖；这份文档写清楚
以后谁想加角色、加窗口该动哪里。

## 结构

| 部分 | 文件 | 做什么 |
|---|---|---|
| 主窗口这一半 | `frontend/js/stage.js` | 开关角色窗口；把聊天里发生的事广播出去（`BroadcastChannel('langpal-stage')`） |
| 角色窗口 | `frontend/stage.html`、`css/stage.css`、`js/stage-window.js` | 加载 Live2D 模型，按收到的事件驱动参数。不发任何后端请求 |
| 角色清单 | `frontend/assets/live2d/characters.json` | 每个角色的模型、取景、表情、手势、反应规则 |
| 桌面壳 | `desktop/main.js`（`openStage`）、`preload.js`（`langpalDesktop.stage`） | 把角色窗口开成主窗口的子窗口，记住位置大小，每 60ms 送一次鼠标位置 |

浏览器里没有桌面壳：标题栏的头像按钮用 `window.open` 开一个弹出窗口，其余完全一样。

## 事件

聊天页（`jine.js`）只在说话的人设有对应角色时（`LP.stage.reactsTo(persona)`）发事件：

| 事件 | 什么时候 | 糖糖的反应 |
|---|---|---|
| `typing` | 她开始回复 | 拿起手机低头打字，标题栏亮三颗小点 |
| `mood` `{mood}` | 后端给出这条回复的心情（十词表） | 记下，等气泡出来时亮出来 |
| `bubble` `{mood, sticker}` | 一条气泡落地 | 按一下发送，抬眼看这边，做这条的表情；是贴图就照着贴图比一下（`stickers`），比完再拿起手机 |
| `idle` | 这一轮说完 | 收起手机，按心情摆一个手势（`moodPose`；最后一条是贴图就接着摆贴图那个）。这轮的心情淡淡留在脸上几分钟（`linger`），开始等你回 |
| `interrupted` | 被新消息打断 | 吓一跳 |
| `read` / `sent` `{sticker}` / `user_typing` | 已读 / 用户发出 / 用户在输入 | 看向聊天、看向输入框；你发的是贴图，她看到时脸上先有反应（`stickers.*.seen`） |
| `other` | 别的角色（插话、来客）的气泡落地 | 转过去看一眼 |
| `tab` `{tab}` | 用户切了页面 | 发呆时看的方向跟着变（`tabs`） |
| `voice` `{level, tone}` | 主窗口在放声音，每秒约 30 次（见下「对口型」） | 张嘴跟着响度走，看着你说 |

没事发生时她自己会动：隔一阵做个小动作（`cues.fidget`，刚聊完时多挑合心情的 `fidgetMood`）、更短的间隔里点头、歪头、
瞟一眼、换重心、慢眨眼、叹气（`micro`，按留下来的心情挑）。她说完了你一直没回，`waitCheck` 秒后拿起手机看一眼
（`cues.waiting`），看了两回还没有就有点不高兴；你回了她就高兴一下。

角色窗口发回 `hello`（加载好了）、`dismissed`（用户点了它的关闭）、`closed`。

## 直播间：在她的窗口里跟她说话

角色窗口最底下是一条弹幕框。你在阅读、听力、口语页时不用切回聊天，打一句、回车就行：

1. 角色窗口（`js/stage-chat.js`）只把这句话交给主窗口：`{from:'stage', type:'say', data:{text}}`。它自己不发后端请求。
2. 主窗口（`stage.js` → `LP.jine.say(text, {via:'stage'})`）把它发进**同一条主聊天**，请求里多带两样：
   `via: "stage"` 和 `scene`（你现在在哪一页、那一页的语言、屏幕上看得见的字，由 `js/scene.js` 的 `LP.scene.get()` 取）。
3. 后端（docs/MAIN-CHAT.md 1.4）把页面内容放进这一轮的背景，这一轮用那一页的语言回答（那一页没有语言就用聊天拨片上的，
   也就是上一次用的），并告诉她这是一条弹幕：回一两条短的、能说出口的话。
4. 她的每条气泡照常进聊天记录；主窗口同时把它广播给角色窗口，气泡冒在她头顶。开着声音时主窗口把这条念出来
   （`POST /api/chat/messages/{id}/speech`，一条一条排队），她对口型。

你发的话从窗口左下往上冒，几秒后淡掉；她替你做了什么也在那儿冒一条深色的小条。

主窗口发给角色窗口的事件，在上面那张表之外多了这些：

| 事件 | 什么时候 | 角色窗口怎么用 |
|---|---|---|
| `bubble` `{mood, sticker, text, message_id, language, show, speak}` | 一条气泡落地 | `show` 为真才在头顶冒气泡：这一轮是从弹幕框发的，或者你此刻不在聊天页。`speak` = 这条会被念出来 |
| `speech` `{message_id, state}` | 这条开始念（`start`）、念完（`end`）、念不了（`error`） | 气泡留到念完 |
| `acted` `{label, ok}` | 她替你动了一下软件 | 左下冒一条小条，`ok` 为假时是锈红色 |
| `fail` `{text}` | 你从弹幕框发的那句没发出去 | 那条弹幕划掉 |

声音开关是弹幕框左边的 ♪，存在 `localStorage['lp.stage.voice']`（`'1'` 开、`'0'` 关，没存过算开），两扇窗共用；她自己也能开关
（`[do:voice on]`）。打开角色窗口时如果声音开着，主窗口先让后端把声音模型加载起来（`POST /api/chat/speech/warm`），免得第一句等太久。
你发新的一句时，正在念的那条会停，排着的也清掉。

头顶的气泡最多露三行；再长就一行一行往上卷。

## 对口型

主窗口（`stage.js`）量正在放的声音，把响度广播成 `voice` 事件：响度是 (dBFS + 60) / 60，`tone` 是频谱重心（0→1 对应 0→3 kHz，
i/e 高、o/u 低，用来定嘴形）。角色窗口里张嘴跟响度，「在不在说话」用快起慢落的包络加一高一低两道门槛判断，
词和词之间的空当不会让她一下停一下说。实测嘴比声音晚约 30 毫秒。

- 页面上的 `<audio>`（听力、复习里的片段）一播放就自动接上；不在页面上的调 `LP.stage.voice(audio)`。
  `audio.dataset.voice = 'off'` 的不接。只接同源和 `blob:` 的音频：跨域又没开 CORS 的接上会变静音。
- 聊天里每条角色消息有「朗读」：`POST /api/chat/messages/{id}/speech` 用设置里给这门语言配的听力声音（Kokoro 或兼容接口）
  念出来，返回 wav，最近 24 条缓存在内存里。鼠标移到按钮上时 `.../speech/warm` 先把本机声音模型加载起来（冷启动要二三十秒）。
  只有她自己的消息她才对口型，别的角色的朗读不接。
- 口语页的实时语音在口语课服务的 iframe 里（跨域），那边在被嵌入时每 33 毫秒 `postMessage`
  `{type: 'langpal:voice', level, tone}` 给外层（speaking-coach 的 `web/src/hostVoice.ts`），`stage.js` 只认 `iframe.coach-frame` 发来的。

## 加一个角色

1. 把模型放到 `frontend/assets/live2d/<Id>/`（Cubism 3+ 的 `*.model3.json`）。
2. 在 `characters.json` 里加一项。必填：`match`（人设名字的开头，用来对上人设）、`model`。其余都有默认：
   - `frame`：`width` 取景宽度占模型宽度的比例，`top` 头顶留白，`minHeight` 矮窗口里至少露出多高。
   - `moods`：十种心情各自的表情目标。键：`eye` 睁眼、`smile` 笑眼、`brow` 眉、`form` 嘴角、`open` 张嘴、
     `ax/ay/az` 头的偏转（度）、`gx/gy` 视线偏移、`bounce` 身体一弹。
   - `poses`：手势名 → 模型里的部件：`part` 部件 id、`arms` 它换掉模型自己的哪只手臂（R = 她的右手，画面左边）、
     `sleeves` 它自带哪只袖子（这时模型自己的那只袖子也淡出）。`poseFade` 淡入淡出用几秒。
     `gestures`：到位后手上的小动作（`freq` 频率、`amp` 幅度、`hold` 持续秒数、`beat` 心跳式、
     `bodyY/sway/tilt` 带动身体和头；`calm` 手贴着脸的手势让头少动到几成；`face` 手势到位后盖在心情上的表情；
     `arrive` 淡入时从多低的地方弹上来）；`cues`、`moodPose`：什么时候用哪个手势。
     `cues.fidget` 是没人理她时隔半分钟左右自己做的小动作，`cues.waiting` 是等你回消息时看手机用的手势。
   - `stickers`：贴图 id → `pose` 她发这张时比的手势、`mood` 表情、`seen` 你发这张她看到时的表情（不写就用 `mood`）、
     `wink` 眨一只眼、`hold` 比多久。
   - `voice`：她的消息朗读时的音色（只改声音质感，不改念法和语速；后端 `services/voice_timbre.py`）：
     `pitch` 音高抬几个半音（连共鸣一起抬，声音更小更轻）、`breath` 气声比人声低几 dB、`nasal` 鼻音抬几 dB、
     `close` 贴麦感抬几 dB。糖糖现在是 `1.8 / -22 / 3 / 2.5`；英文另用 af_nicole 当底子（它本身低、慢，
     所以 `rate 1.34`、`pitch 5.5`，气声等减轻）。可以按语言另写一项盖在上面（`"en": {...}`），
     里面还能写 `base`（用本机哪个 Kokoro 音色当底子，例如 `af_nicole`；本机没有这个文件就照设置里的）和
     `rate`（语速倍数：换的底子本身念得慢时用它拉回原来的语速）。
   - `linger`：一轮说完心情留在脸上的比例（`weight`，按心情）和淡掉要几秒（`seconds`）。`fidgetMood`：心情还在时挑哪些小动作。
   - `micro`：发呆时的小动作，`every` 间隔秒数范围，`weights` 各动作的分量（`nod tilt glance shift slowblink sigh peek`），
     `byMood` 心情还在时改哪些分量，`waiting` 等你回时改哪些。`waitCheck`：说完多少秒后第一次看手机。
   - `tabs`：用户在各页面时她发呆看的方向。
3. 模型用到的参数是标准的 `ParamAngleX/Y/Z`、`ParamBodyAngleX/Y/Z`、`ParamEyeLOpen/ROpen`、`ParamEyeLSmile/RSmile`、
   `ParamEyeBallX/Y`、`ParamBrowLY/RY`、`ParamMouthForm`、`ParamMouthOpenY`、`ParamBreath`，外加可选的
   `ParamPoseBob`（手势淡入时的弹起）、`ParamPoseWiggle`（到位后的小动作）。手势本身不是参数，是部件（见下）。
   模型里没有的参数和部件会被忽略。模型自带的物理（`*.physics3.json`）由角色窗口在设完这些参数以后再算
   （框架默认在设参数之前算，读不到真正的转头），所以头发、蝴蝶结跟着她实际的动作甩。
   鼠标位置（桌面壳每 60 毫秒送一次）先平滑再给眼睛，换视线时眼珠约 70 毫秒扫过去，不会一格一格地跳。

## 加一种窗口

角色窗口只认网址 `stage.html?c=<角色 id>` 和广播频道，所以别的宿主（桌面挂件、网页里的浮层、OBS 浏览器源）
直接加载这个网址就行；想给它发事件，往 `BroadcastChannel('langpal-stage')` 发
`{from: 'app', character: '<id>', type: '<事件>', data: {...}}`。

## 糖糖的模型

制作流程和源文件不在这个仓库里（`E:\cxref\ame-l2d`）。更新模型 = 把那边的 `v4\out\Ame` 整个目录拷到
`frontend/assets/live2d/Ame/` 再提交。

手势一共 12 个：胸前和身侧的 7 个（手机、抱胸、比耶、握拳、挥手、比心、交握）和 5 个手碰到脸的
（`bite` 咬指甲、`chin` 手指点下巴、`giggle` 捂嘴、`cheeks` 捧脸、`sleepy` 揉眼睛）。每个手势是模型里的一个部件
（`PartPose_<名>`），模型自己垂着的手臂和袖子也是部件（`PartArmR/L`、`PartSleeveR/L`）；换手势就是这些部件的
淡入淡出，没有中间动作（画过渡帧、让手臂按关节转上去都试过，效果不如直接淡入淡出，已放弃）。
模型带 `pose3.json`，别的查看器不驱动部件时只显示垂着的手臂。
碰脸的这 5 个在模型里还做了「手那一端跟着头走」：转头、点头、歪头时手不会在脸上滑；抬起的手臂带着自己那只被撑起来的袖子。
