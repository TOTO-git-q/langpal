# 听力练习

一组练习走「选题 → 听材料 → 答题 → 复盘」。音频播完才显示题目，交卷后才给答案、解释、文稿和每题的原文依据。

## 接口

全部要求同源请求（`app/security.py` 的 `same_origin`）。

| 接口 | 用途 |
| --- | --- |
| `GET /api/listening/options` | 各语言是否已配好声音、题型、难度、每门语言的听力安排。 |
| `POST /api/listening/practice` | 出题、合成、存库，存好才返回 id。响应里 `removed` 列出为腾地方自动删掉的旧练习。 |
| `GET /api/listening/practices?lang=&limit=` | 已存练习（含 `size_bytes`、`status`：`ready`/`graded`/`unreadable`），外加 `storage` 总占用。 |
| `GET /api/listening/practice/{id}` | 单组练习的元数据和首次交卷回执。 |
| `DELETE /api/listening/practice/{id}` | 删一组练习和它的音频、草稿；错题本里的错题不受影响。 |
| `GET /api/listening/practice/{id}/audio`、`/questions` | 音频（WAV）和题干。日语口播选项只显示编号。 |
| `POST /api/listening/practice/{id}/grade` | 交卷。第一次交卷的回执不可改，答错的题连同一份音频进错题本。 |
| `GET /api/listening/errors`、`GET /api/listening/errors/{id}/audio` | 错题本和错题音频。 |
| `DELETE /api/listening/errors/{id}` | 删一组练习的全部错题、错题音频和复习记录。 |
| `GET/PUT /api/listening/synthesis`、`POST /api/listening/plans/{lang}`、`GET/PUT /api/listening/coach` | 声音设置、听力安排、口语服务地址。 |

## 存储上限

按实际占用计：已存练习（音频＋文字）加错题本（它自己那份音频＋错题）。上限 200 组、256 MiB。新练习放不下时，先自动删最早的**已交卷**练习；没交卷的不动。实在腾不出来返回 507，提示去听力页删练习或错题。错题本的音频是另存的一份，删练习不影响错题回放。

## 出题与声音

出题用设置里给「听力」选的文字模型（`app/providers/registry.py` 的 `listening` 功能），难度选「跟随课程」时按当前语言的课程目标出题。声音由 `app/services/listening_tts.py` 合成：本机 Kokoro，或兼容 OpenAI `/audio/speech` 的服务，在设置页选。

两个说话人都是女声。本机 Kokoro 默认：英语 A `af_heart`、B `af_nicole`；日语 A、B 都是 `jf_alpha`，B 降 2.5 个半音（`pitch_b`）。`pitch_b` 是 B 的音高偏移，单位半音，范围 -6 到 6，没设或为 0 就不变；合成时先按比例改语速再重采样，所以时长和不移调时一样，逐句的时间位置按重采样后的样本算。它只对本机 Kokoro 起作用，兼容接口忽略。设置里存着旧默认男声（`am_michael`、`jm_kumo`）的，读取时自动换成上面这组。题干里提到说话人时用对话里听得出来的身份（学生、店员、教授），不用「男の人 / 女の人」。

`GET /practice/{id}/lines` 的每一行和 `GET /practice/{id}/shape` 的每一段带 `female`：这个说话人现在配的是不是女声。听力页在非女声的段落上给音频标 `data-voice-mute="1"`，角色窗口只跟女声对口型（见 docs/STAGE.md）。

题型参考 [ETS TOEFL iBT 听力](https://www.ets.org/toefl/test-takers/ibt/about/content/listening.html) 和 [JLPT N1 题型](https://www.jlpt.jp/e/guideline/pdf/n1_e_revised.pdf)，都是原创练习，不代表考试成绩。

## 配置本机 Kokoro

准备一个独立的 CPU Python 环境，装 Kokoro 0.9.4、Misaki 0.9.4、`espeakng-loader`、`en_core_web_sm`、`pyopenjtalk-plus`、`fugashi`、`unidic-lite`、`jaconv`、`mojimoji`。模型目录放 [Kokoro-82M 权重](https://huggingface.co/hexgrad/Kokoro-82M/tree/main)、所用音色（见 [音色表](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)）和 [Open JTalk 字典](https://github.com/r9y9/open_jtalk/releases/tag/v1.11.1)：

```text
listening-models/
  config.json
  kokoro-v1_0.pth
  voices/af_heart.pt  voices/af_nicole.pt  voices/jf_alpha.pt
  open_jtalk_dic_utf_8-1.11/…
```

现成的环境放在 `E:\tools\langpal-kokoro`（`runtime` 是 Python 3.12 的 venv，`models` 是权重、音色和 Open JTalk 词典；合成进程离线运行，不依赖别的缓存目录）。然后在服务环境里设：

```dotenv
LANGPAL_LISTENING_TTS_PYTHON=E:\tools\langpal-kokoro\runtime\Scripts\python.exe
LANGPAL_LISTENING_TTS_ASSETS=E:\tools\langpal-kokoro\models
```

合成进程拿不到任何 API 密钥。后端第一次要合成时拉起一个常驻的合成进程（出题时就开始加载模型），之后复用；一次只合成一组、其余排队；空闲 10 分钟或后端退出时关掉，崩了下次自动重起。没配声音时页面仍可浏览题型，但不能开始练习。
