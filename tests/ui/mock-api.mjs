// mock-api.mjs — 界面预览用的固定假数据。preview.mjs 用 page.route('**/api/**') 把所有接口请求交给 handle()。
// 每个接口的形状按前端代码的读取方式写；后端真实返回如果不同，以这里为对照表改前端或改假数据。
import fs from 'node:fs';
// 没登记的接口一律 404 + 记一笔（preview 结束时打印），方便发现漏掉的调用。

const today = new Date();
const iso = (daysAgo, hh = 10, mm = 0) => {
  const d = new Date(today);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hh, mm, 0, 0);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(hh)}:${pad(mm)}:00`;
};

// ---------- 人设 / 会话 / 消息 ----------
export const personas = [
  { id: 1, name: '糖糖（あめ）', language: 'ja', avatar_url: null, archived_at: null,
    profile: { relation: '对方是「P酱」——她的专属阿P', tone: '私下态为主：情绪浓度溢出、句子短断跳', keigo: '平辈',
      interests: ['配信', '唱歌', '观察P酱'], free_text: '原创网络角色超天酱＝糖糖＝あめ——是主播女孩重度依赖中的游戏主角。', world_book_ids: [],
      voice_samples: { ja: ['ねえ聞いて', 'もう無理なんだけど', 'Pちゃん今なにしてるの？', '配信の準備めんどくさ〜', 'え、それほんと？', 'あめちゃんえらい', 'ちょっとだけ寝る', '今日はがんばった', 'お腹すいた…', 'ふーん、そうなんだ'] } } },
  { id: 2, name: 'Emma', language: 'en', avatar_url: null, archived_at: null, profile: { relation: 'study buddy', tone: 'casual' } },
  { id: 3, name: 'Lena', language: 'de', avatar_url: null, archived_at: null, profile: {} },
];

// 主聊天是会话 30；11、12 是以前按联系人分开的旧对话（只读）
const MAIN_SESSION = 30;
const sessions = { 1: [{ id: 11, persona_id: 1, started_at: iso(9) }, { id: MAIN_SESSION, persona_id: 1, started_at: iso(2) }], 2: [{ id: 12, persona_id: 2, started_at: iso(8) }], 3: [] };
const stickerList = JSON.parse(fs.readFileSync(new URL('../../frontend/assets/stickers/manifest.json', import.meta.url), 'utf8'))
  .map((x) => ({ id: x.id, url: 'assets/stickers/' + x.file, meaning: x.desc }));

// 日语 token：带读音（注音用）和 clickable。
function jaTokens(parts) {
  return parts.map(([surface, reading, lemma, pos], i) => ({
    i, surface, reading: reading || '', lemma: lemma || surface, pos: pos || '',
    clickable: /\p{L}/u.test(surface) && pos !== '記号', space_after: false,
  }));
}
function enTokens(text) {
  return text.split(/(\s+)/).filter((t) => t.trim()).map((w, i, all) => ({
    i, surface: w, lemma: w.replace(/[^\p{L}']/gu, '').toLowerCase() || w, reading: '', pos: '',
    clickable: /\p{L}/u.test(w), space_after: i < all.length - 1,
  }));
}

const choLong = jaTokens([
  ['えっと', 'エット'], ['、', '', '', '記号'], ['何', 'ナニ'], ['言っ', 'イッ', '言う'], ['てる', 'テル'], ['の', 'ノ'], ['か', 'カ'],
  ['よく', 'ヨク'], ['わかん', 'ワカン', 'わかる'], ['ない', 'ナイ'], ['。', '', '', '記号'], ['あめ', 'アメ'], ['に', 'ニ'],
  ['お願い', 'オネガイ'], ['し', 'シ', 'する'], ['て', 'テ'], ['ほしい', 'ホシイ'], ['って', 'ッテ'], ['こと', 'コト'], ['？', '', '', '記号'],
  ['それとも', 'ソレトモ'], ['、', '', '', '記号'], ['あめ', 'アメ'], ['の', 'ノ'], ['方', 'ホウ'], ['から', 'カラ'],
  ['お願い', 'オネガイ'], ['します', 'シマス', 'する'], ['って', 'ッテ'], ['言っ', 'イッ', '言う'], ['て', 'テ'], ['ほしい', 'ホシイ'],
  ['って', 'ッテ'], ['こと', 'コト'], ['？', '', '', '記号'],
]);
const choShort = jaTokens([['ふふ', 'フフ'], ['、', '', '', '記号'], ['お願い', 'オネガイ'], ['します', 'シマス', 'する'], ['って', 'ッテ'], ['敬語', 'ケイゴ'], ['使っ', 'ツカッ', '使う'], ['て', 'テ'], ['き', 'キ', '来る'], ['た', 'タ'], ['。', '', '', '記号']]);
const choMorning = jaTokens([['おはよ', 'オハヨ'], ['！', '', '', '記号'], ['朝', 'アサ'], ['から', 'カラ'], ['元気', 'ゲンキ'], ['じゃん', 'ジャン'], ['。', '', '', '記号']]);
const joinTokens = (tokens) => tokens.map((t) => t.surface + (t.space_after ? ' ' : '')).join('');

const cho = { persona_id: 1, persona_name: '糖糖（あめ）', language: 'ja' };
const emma = { persona_id: 2, persona_name: 'Emma', language: 'en' };
const lena = { persona_id: 3, persona_name: 'Lena', language: 'de' };
const messages = {
  [MAIN_SESSION]: [
    { id: 101, role: 'user', content: 'おはよう！', created_at: iso(1, 9, 2), read: true, language: 'ja' },
    { id: 102, role: 'assistant', ...cho, content: joinTokens(choMorning), tokens: choMorning, created_at: iso(1, 9, 3) },
    { id: 103, role: 'assistant', ...cho, content: '[sticker:cho_peace]', sticker: 'cho_peace', tokens: null, created_at: iso(1, 9, 3) },
    { id: 104, role: 'user', content: 'おねがいします！！！ 雨ちゃん', created_at: iso(0, 20, 10), read: true, language: 'ja' },
    { id: 105, role: 'assistant', ...cho, content: joinTokens(choShort), tokens: choShort, created_at: iso(0, 20, 11) },
    { id: 106, role: 'assistant', ...cho, content: joinTokens(choLong), tokens: choLong, created_at: iso(0, 20, 11), guard_flag: false },
    { id: 107, role: 'user', content: '这张图里写的是什么？', image_url: 'assets/avatars/happy.png', created_at: iso(0, 20, 14), read: true, language: 'ja' },
    { id: 108, role: 'assistant', ...cho, content: 'ちゃんと言ってよ、変にドキドキさせないでよね……心臓うるさいんだけど', tokens: null, created_at: iso(0, 20, 15) },
    { id: 109, role: 'assistant', ...emma, content: 'Wait, is she always this dramatic?', tokens: enTokens('Wait, is she always this dramatic?'), created_at: iso(0, 20, 15) },
    { id: 110, role: 'system', kind: 'enter', persona_id: 3, persona_name: 'Lena', content: 'Lena 来了', created_at: iso(0, 21, 0) },
    { id: 111, role: 'user', content: 'Lena, wie war dein Tag?', created_at: iso(0, 21, 1), read: true, language: 'de' },
    { id: 112, role: 'assistant', ...lena, content: 'Ganz okay! Ich habe heute endlich mal wieder gekocht.', tokens: null, created_at: iso(0, 21, 2) },
  ],
  11: [
    { id: 51, role: 'user', content: 'はじめまして！', created_at: iso(9, 22, 1) },
    { id: 52, role: 'assistant', content: 'はじめまして〜！あめだよ', tokens: null, created_at: iso(9, 22, 2) },
  ],
  12: [
    { id: 201, role: 'user', content: 'Hi Emma, how was your weekend?', created_at: iso(1, 18) },
    { id: 202, role: 'assistant', content: 'Pretty chill, honestly. I finally finished that novel you recommended.', tokens: enTokens('Pretty chill, honestly. I finally finished that novel you recommended.'), created_at: iso(1, 18, 1) },
  ],
};

// ---------- 学习页 ----------
const readerItems = [
  { id: 'nasa-1', title: 'NASA Invites Media, Public to Join Voyager 1 One-Light Day Activities', source: 'NASA', date: iso(1), length: 515, lang: 'en', url: 'https://www.nasa.gov/',
    text: 'Launched nearly 50 years ago in 1977, NASA’s Voyager 1 on Wednesday, Nov. 18 will have traveled one light-day from Earth, which is more than 16 billion miles (25.9 billion kilometers). Voyager 1 is the most distant human-made object, and any light from Earth would take 24 hours to reach the spacecraft. The milestone is a reminder of how far the twin probes have come since they left Earth.', curation_status: 'pending', public: true },
  { id: 'nasa-2', title: 'NASA to Welcome Expedition 74 Astronauts Home After Long Mission', source: 'NASA', date: iso(1), length: 592, lang: 'en', url: 'https://www.nasa.gov/', text: 'Four crew members will return to Earth after six months aboard the International Space Station.' },
  { id: 'wiki-1', title: '1 Wall Street', source: 'Wikipedia', date: iso(2), length: 410, lang: 'en', url: 'https://en.wikipedia.org/', text: '1 Wall Street is a 50-story office building at the corner of Wall Street and Broadway in Manhattan.' },
  { id: 'wiki-2', title: '1 Line (Sound Transit)', source: 'Wikipedia', date: iso(2), length: 438, lang: 'en', url: 'https://en.wikipedia.org/', text: 'The 1 Line is a light rail line serving Seattle and its suburbs.' },
  { id: 'feed-1', title: 'Morning briefing: markets open higher', source: 'Example Feed', date: iso(0), lang: 'en', url: 'https://example.org/', text: 'A short summary only.', feedOnly: true },
];

const listeningOptions = {
  synthesis: { en: true, ja: false, de: false },
  // 题型：说话人数、题数、TOEFL 的英文原名（日语为 null）
  formats: [
    { id: 'en_response', language: 'en', label: '即时回应', speakers: 1, questions: 1, subtitle: 'Listen and Choose a Response' },
    { id: 'en_conversation', language: 'en', label: '校园对话', speakers: 2, questions: 2, subtitle: 'Listen to a Conversation' },
    { id: 'en_announcement', language: 'en', label: '校园公告', speakers: 1, questions: 2, subtitle: 'Listen to an Announcement' },
    { id: 'en_talk', language: 'en', label: '学术讲解', speakers: 1, questions: 3, subtitle: 'Listen to an Academic Talk' },
    { id: 'ja_task', language: 'ja', label: '課題理解', speakers: 2, questions: 1, subtitle: null },
    { id: 'ja_points', language: 'ja', label: 'ポイント理解', speakers: 2, questions: 1, subtitle: null },
    { id: 'ja_gist', language: 'ja', label: '概要理解', speakers: 1, questions: 1, subtitle: null },
    { id: 'ja_response', language: 'ja', label: '即時応答', speakers: 1, questions: 1, subtitle: null },
    { id: 'ja_integrated', language: 'ja', label: '統合理解', speakers: 2, questions: 2, subtitle: null },
  ],
  difficulties: [{ id: 'default', label: '跟随课程' }, { id: 'easy', label: '简单' }, { id: 'hard', label: '较难' }],
  capabilities: { practice_difficulty: true, listening_sessions: true },
  plans: { en: { format: 'en_talk', difficulty: 'default', topic: '' } },
};

// 错题：阅读用 question/options/selected/paragraph，听力用 prompt/choices/selection/evidence[]，都要 updated_at 排序。
const reviewItems = [
  { kind: 'reading', exercise_id: 'e1', item_index: 0, language: 'en', title: 'NASA Invites Media, Public to Join Voyager 1', question: 'According to the passage, why is the Nov. 18 milestone significant?',
    options: ['Voyager 1 will stop sending data', 'Voyager 1 will be one light-day from Earth', 'NASA will launch a new probe', 'Light from Voyager will reach Mars'],
    selected: 0, answer: 1, explanation: '第二句明确说 Voyager 1 届时距离地球一个光日。', paragraph: 'Launched nearly 50 years ago in 1977, NASA’s Voyager 1 on Wednesday, Nov. 18 will have traveled one light-day from Earth.', quote: 'will have traveled one light-day from Earth', skill: 'inference',
    source_url: 'https://www.nasa.gov/', updated_at: iso(1) },
  { kind: 'listening', practice_id: 'p1', item_index: 1, language: 'ja', title: '駅のアナウンス', prompt: '電車はなぜ遅れていますか。',
    choices: ['事故があったから', '雪が降っているから', '点検中だから', '乗客が多いから'], selection: 3, answer: 2, explanation: '广播里说「車両点検のため」。',
    evidence: [{ line: 3, speaker: 'A', text: 'ただいま車両点検のため、電車が遅れております。' }], clips: [{ start: 6, end: 9.4 }], skill: 'jlpt_task', updated_at: iso(2) },
];

// ---------- 设置 ----------
const lessonCourseUrl = new URL('../../backend/app/data/lessons/toefl-2026/', import.meta.url);
const lessonCourse = JSON.parse(fs.readFileSync(new URL('course.json', lessonCourseUrl), 'utf8'));
const courseLessons = new Map();
for (const section of lessonCourse.sections) {
  for (const id of section.lessons) {
    if (id !== 'writing-email') continue;
    const file = new URL(id + '.json', lessonCourseUrl);
    if (fs.existsSync(file)) courseLessons.set(id, JSON.parse(fs.readFileSync(file, 'utf8')));
  }
}
const lessonPreset = {...lessonCourse, units: [...courseLessons.values()].map(unit => ({id: unit.id, title: unit.title, can_do: unit.goal}))};
const teachingPresets = [lessonPreset];

const vocab = [
  { id: 1, language: 'ja', lemma: 'お願い', surface: 'お願い', reading: 'おねがい', meaning: '请求；拜托', context_sentence: 'ふふ、おねがいしますって敬語使ってきた。', source_message_id: 105, created_at: iso(0) },
  { id: 2, language: 'en', lemma: 'recommend', surface: 'recommended', reading: null, meaning: '推荐', context_sentence: 'I finally finished that novel you recommended.', source_message_id: 202, created_at: iso(1) },
  { id: 3, language: 'ja', lemma: '心臓', surface: '心臓', reading: 'しんぞう', meaning: '心脏', context_sentence: '心臓うるさいんだけど', source_message_id: 108, created_at: iso(0) },
];
const patterns = [
  { id: 1, language: 'ja', pattern_name: '〜って〜こと？', explanation: '确认对方意思：「你是说……吗？」', example_sentence: 'あめにお願いしてほしいってこと？', translation: '你是想让我拜托你？', source_message_id: 106, created_at: iso(0) },
];

const memory = [
  { id: 1, persona_id: 1, category: 'fact', content: 'P酱：24岁PhD，研究RNA编辑/自然免疫；周一至五出勤', active: true },
  { id: 2, persona_id: 1, category: 'preference', content: '喜欢被叫「P酱」，讨厌被说教', active: true },
  { id: 3, persona_id: 1, category: 'event', content: '11/10 一起熬夜看了配信回放', active: false },
];

// ---------- 世界书 / 事件 hook（docs/LORE-AND-HOOKS.md） ----------
const loreEntry = (uid, extra) => ({
  uid, title: '', content: '', enabled: true, constant: false, keys: [], secondary_keys: [], logic: 'and_any',
  case_sensitive: false, whole_words: false, lemma: null, semantic: false, semantic_threshold: 0.84, position: 'turn',
  order: 100, probability: 100, scan_depth: null, sticky: 0, cooldown: 0, delay: 0, group: '', group_weight: 100,
  group_override: false, exclude_recursion: false, prevent_recursion: false, delay_until_recursion: false,
  conditions: [], automation_id: '', extensions: {}, ...extra,
});
const initialBooks = () => [
  { id: 1, name: '糖糖的直播间', scope: 'attached', enabled: true, attached: [1], book: { version: 2,
    settings: { scan_depth: 4, budget_chars: 1600, recursion: true, max_recursion: 3, lemma_match: true },
    entries: [
      loreEntry(1, { title: '配信时间', content: '糖糖每晚 9 点开播，开播前会很紧张。', keys: ['配信', '直播'], position: 'turn' }),
      loreEntry(2, { title: 'P酱是谁', content: '{{user}} 是她的专属阿P，研究 RNA 编辑的博士生。', constant: true, position: 'after_persona' }),
      loreEntry(3, { title: '周四抗体到货', content: '今天是周四，P酱的抗体到货日。', conditions: [{ field: 'weekday', op: '==', value: 4 }] }),
      loreEntry(4, { title: '吃饭', content: '她总是忘记吃饭。', keys: ['食べる', '饭'], lemma: true, enabled: false }),
    ] } },
  { id: 2, name: '东京生活常识', scope: 'global', enabled: true, attached: [], book: { version: 2, settings: { scan_depth: 2, budget_chars: 800, recursion: false, max_recursion: 1, lemma_match: true },
    entries: [loreEntry(1, { title: '电车', content: '东京的电车末班车大约 0 点。', keys: ['終電', '电车'] })] } },
];
// 下面两份照真后端 GET /api/hooks/meta 和 GET /api/hooks/rules（自带的 7 条）原样抄来
const hooksMeta = {
  "events": [
    {
      "id": "chat.open",
      "label": "打开某个联系人的对话",
      "source": "frontend",
      "fields": [
        {
          "key": "first_today",
          "label": "今天第一次打开",
          "type": "bool"
        }
      ]
    },
    {
      "id": "chat.user_message",
      "label": "用户发了消息（生成之前）",
      "source": "backend",
      "fields": [
        {
          "key": "text",
          "label": "消息原文",
          "type": "text"
        },
        {
          "key": "length",
          "label": "字数",
          "type": "number"
        }
      ]
    },
    {
      "id": "chat.reply",
      "label": "对方回完一轮",
      "source": "backend",
      "fields": [
        {
          "key": "mood",
          "label": "情绪",
          "type": "text"
        },
        {
          "key": "bubbles",
          "label": "气泡数",
          "type": "number"
        },
        {
          "key": "fixes",
          "label": "这轮纠正了几处",
          "type": "number"
        },
        {
          "key": "proactive",
          "label": "是她主动发的",
          "type": "bool"
        }
      ]
    },
    {
      "id": "chat.idle",
      "label": "对话开着但 10 分钟没动静",
      "source": "frontend",
      "fields": [
        {
          "key": "minutes",
          "label": "多少分钟没动静",
          "type": "number"
        }
      ]
    },
    {
      "id": "study.vocab_saved",
      "label": "收藏了一个词",
      "source": "backend",
      "fields": [
        {
          "key": "lemma",
          "label": "词",
          "type": "text"
        },
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "study.pattern_saved",
      "label": "收藏了一个句型",
      "source": "backend",
      "fields": [
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "study.reading_finished",
      "label": "做完一篇阅读",
      "source": "backend",
      "fields": [
        {
          "key": "title",
          "label": "标题",
          "type": "text"
        },
        {
          "key": "correct",
          "label": "答对",
          "type": "number"
        },
        {
          "key": "total",
          "label": "总题数",
          "type": "number"
        },
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "study.listening_finished",
      "label": "做完一组听力",
      "source": "backend",
      "fields": [
        {
          "key": "correct",
          "label": "答对",
          "type": "number"
        },
        {
          "key": "total",
          "label": "总题数",
          "type": "number"
        },
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "study.review_done",
      "label": "复习了一道错题",
      "source": "backend",
      "fields": [
        {
          "key": "kind",
          "label": "题型（reading / listening）",
          "type": "text"
        },
        {
          "key": "correct",
          "label": "答对了",
          "type": "bool"
        },
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "study.lesson_finished",
      "label": "口语课刚下课",
      "source": "backend",
      "fields": [
        {
          "key": "lesson_id",
          "label": "课的 id",
          "type": "text"
        },
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "course.unit_completed",
      "label": "课程里一个单元达标",
      "source": "backend",
      "fields": [
        {
          "key": "unit_id",
          "label": "单元 id",
          "type": "text"
        },
        {
          "key": "title",
          "label": "单元名",
          "type": "text"
        },
        {
          "key": "language",
          "label": "语言",
          "type": "text"
        }
      ]
    },
    {
      "id": "lore.activated",
      "label": "带 automation_id 的世界书条目生效",
      "source": "backend",
      "fields": [
        {
          "key": "automation_id",
          "label": "automation_id",
          "type": "text"
        },
        {
          "key": "book_id",
          "label": "书 id",
          "type": "number"
        },
        {
          "key": "uid",
          "label": "条目 uid",
          "type": "number"
        }
      ]
    }
  ],
  "condition_fields": [
    {
      "key": "hour",
      "label": "现在几点（0–23）",
      "type": "number",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between"
      ]
    },
    {
      "key": "weekday",
      "label": "星期几（1=周一 … 7=周日）",
      "type": "number",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between"
      ]
    },
    {
      "key": "date",
      "label": "今天的日期（MM-DD）",
      "type": "text",
      "ops": [
        "==",
        "!=",
        "in",
        "contains",
        "between"
      ]
    },
    {
      "key": "idle_days",
      "label": "距上次和这个联系人说话过了几天",
      "type": "number",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between"
      ]
    },
    {
      "key": "turns",
      "label": "这段对话已有多少条消息",
      "type": "number",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between"
      ]
    },
    {
      "key": "vocab_due",
      "label": "这门语言到期该复习的生词数",
      "type": "number",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between"
      ]
    },
    {
      "key": "debts_open",
      "label": "口语课错题账本里还没改掉的条目数",
      "type": "number",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between"
      ]
    },
    {
      "key": "course_unit",
      "label": "当前课程单元的 id",
      "type": "text",
      "ops": [
        "==",
        "!=",
        "in",
        "contains",
        "between"
      ]
    },
    {
      "key": "last_mood",
      "label": "对方上一条回复的情绪",
      "type": "text",
      "ops": [
        "==",
        "!=",
        "in",
        "contains",
        "between"
      ]
    },
    {
      "key": "language",
      "label": "这个联系人的语言",
      "type": "text",
      "ops": [
        "==",
        "!=",
        "in",
        "contains",
        "between"
      ]
    },
    {
      "key": "var.*",
      "label": "hook 变量（var.名字）",
      "type": "any",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between",
        "contains"
      ]
    },
    {
      "key": "event.*",
      "label": "事件带的数据（event.键，只在 hook 里有）",
      "type": "any",
      "ops": [
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "between",
        "contains"
      ]
    }
  ],
  "actions": [
    {
      "type": "inject",
      "label": "接下来几轮把一段话放进背景",
      "fields": [
        {
          "key": "text",
          "label": "内容（支持宏）",
          "type": "textarea",
          "required": true
        },
        {
          "key": "turns",
          "label": "持续几轮",
          "type": "number",
          "default": 1,
          "min": 1,
          "max": 50
        }
      ]
    },
    {
      "type": "say",
      "label": "让对方主动发一条消息",
      "fields": [
        {
          "key": "directive",
          "label": "给她的念头（支持宏，不会被念出来）",
          "type": "textarea",
          "required": true
        }
      ]
    },
    {
      "type": "set_var",
      "label": "设变量",
      "fields": [
        {
          "key": "name",
          "label": "变量名",
          "type": "text",
          "required": true
        },
        {
          "key": "value",
          "label": "值（数字或文字）",
          "type": "text",
          "required": true
        },
        {
          "key": "scope",
          "label": "范围",
          "type": "select",
          "default": "persona",
          "options": [
            {
              "value": "persona",
              "label": "这个联系人"
            },
            {
              "value": "global",
              "label": "全局"
            }
          ]
        }
      ]
    },
    {
      "type": "inc_var",
      "label": "变量加减",
      "fields": [
        {
          "key": "name",
          "label": "变量名",
          "type": "text",
          "required": true
        },
        {
          "key": "by",
          "label": "加多少（负数就是减）",
          "type": "number",
          "default": 1
        },
        {
          "key": "scope",
          "label": "范围",
          "type": "select",
          "default": "persona",
          "options": [
            {
              "value": "persona",
              "label": "这个联系人"
            },
            {
              "value": "global",
              "label": "全局"
            }
          ]
        }
      ]
    },
    {
      "type": "activate_entry",
      "label": "强制一条世界书条目生效几轮",
      "fields": [
        {
          "key": "book_id",
          "label": "世界书",
          "type": "book",
          "required": true
        },
        {
          "key": "uid",
          "label": "条目",
          "type": "entry",
          "required": true
        },
        {
          "key": "turns",
          "label": "持续几轮",
          "type": "number",
          "default": 1,
          "min": 1,
          "max": 50
        }
      ]
    },
    {
      "type": "deactivate_entry",
      "label": "压住一条世界书条目几轮",
      "fields": [
        {
          "key": "book_id",
          "label": "世界书",
          "type": "book",
          "required": true
        },
        {
          "key": "uid",
          "label": "条目",
          "type": "entry",
          "required": true
        },
        {
          "key": "turns",
          "label": "持续几轮",
          "type": "number",
          "default": 1,
          "min": 1,
          "max": 50
        }
      ]
    },
    {
      "type": "remember",
      "label": "往这个联系人的长期记忆里写一条",
      "fields": [
        {
          "key": "content",
          "label": "内容（支持宏）",
          "type": "textarea",
          "required": true
        },
        {
          "key": "category",
          "label": "类别",
          "type": "select",
          "default": "event",
          "options": [
            {
              "value": "fact",
              "label": "事实"
            },
            {
              "value": "preference",
              "label": "喜好"
            },
            {
              "value": "event",
              "label": "事件"
            },
            {
              "value": "promise",
              "label": "约定"
            }
          ]
        }
      ]
    }
  ],
  "macros": [
    {
      "name": "{{user}}",
      "label": "用户的称呼（设置里的 user_name，没设就是“对方”）"
    },
    {
      "name": "{{char}}",
      "label": "联系人的名字"
    },
    {
      "name": "{{time}}",
      "label": "现在的时间 HH:MM"
    },
    {
      "name": "{{date}}",
      "label": "今天的日期 YYYY-MM-DD"
    },
    {
      "name": "{{weekday}}",
      "label": "星期几（周一…周日）"
    },
    {
      "name": "{{idle_days}}",
      "label": "距上次和这个联系人说话几天"
    },
    {
      "name": "{{getvar::名字}}",
      "label": "变量的值（先找这个联系人的，再找全局的）"
    },
    {
      "name": "{{event.键}}",
      "label": "事件带的数据"
    },
    {
      "name": "{{random::甲::乙::丙}}",
      "label": "随机挑一个"
    },
    {
      "name": "{{roll::6}}",
      "label": "1 到 N 的随机整数"
    },
    {
      "name": "{{due_vocab::2}}",
      "label": "到期该复习的生词挑 N 个，写成「词（读音）：意思」；一个都没有时整个动作作废"
    }
  ],
  "once_per": [
    {
      "value": "none",
      "label": "不限"
    },
    {
      "value": "session",
      "label": "每次启动应用一次"
    },
    {
      "value": "day",
      "label": "每天一次"
    }
  ],
  "limits": {
    "rules": 200,
    "conditions": 12,
    "actions": 10,
    "text": 2000
  }
};
const initialRules = () => [
  {
    "name": "久别重逢",
    "enabled": true,
    "persona_ids": null,
    "event": "chat.open",
    "conditions": [
      {
        "field": "idle_days",
        "op": ">=",
        "value": 2
      }
    ],
    "probability": 100,
    "cooldown_minutes": 0,
    "cooldown_turns": 0,
    "once_per": "day",
    "actions": [
      {
        "type": "say",
        "directive": "对方已经 {{idle_days}} 天没来找你了。按你的性格先开口。"
      }
    ],
    "id": 1,
    "builtin": "reunion"
  },
  {
    "name": "深夜",
    "enabled": true,
    "persona_ids": null,
    "event": "chat.user_message",
    "conditions": [
      {
        "field": "hour",
        "op": "between",
        "value": [
          1,
          4
        ]
      }
    ],
    "probability": 100,
    "cooldown_minutes": 0,
    "cooldown_turns": 0,
    "once_per": "day",
    "actions": [
      {
        "type": "inject",
        "text": "（现在是深夜 {{time}}。可以顺口提一句这么晚还没睡，别说教。）",
        "turns": 1
      }
    ],
    "id": 2,
    "builtin": "late_night"
  },
  {
    "name": "学完来找你（阅读）",
    "enabled": true,
    "persona_ids": null,
    "event": "study.reading_finished",
    "conditions": [],
    "probability": 100,
    "cooldown_minutes": 180,
    "cooldown_turns": 0,
    "once_per": "none",
    "actions": [
      {
        "type": "say",
        "directive": "对方刚做完一篇阅读《{{event.title}}》，答对 {{event.correct}}/{{event.total}}。按你的性格说两句。"
      }
    ],
    "id": 3,
    "builtin": "study_reading"
  },
  {
    "name": "学完来找你（听力）",
    "enabled": true,
    "persona_ids": null,
    "event": "study.listening_finished",
    "conditions": [],
    "probability": 100,
    "cooldown_minutes": 180,
    "cooldown_turns": 0,
    "once_per": "none",
    "actions": [
      {
        "type": "say",
        "directive": "对方刚做完一组听力，答对 {{event.correct}}/{{event.total}}。按你的性格说两句。"
      }
    ],
    "id": 4,
    "builtin": "study_listening"
  },
  {
    "name": "生词回炉",
    "enabled": true,
    "persona_ids": null,
    "event": "chat.user_message",
    "conditions": [
      {
        "field": "vocab_due",
        "op": ">=",
        "value": 1
      }
    ],
    "probability": 100,
    "cooldown_minutes": 0,
    "cooldown_turns": 6,
    "once_per": "none",
    "actions": [
      {
        "type": "inject",
        "text": "对方该复习这几个词了：{{due_vocab::2}}。话题合适就自然地用在回复里，不要解释、不要点名。",
        "turns": 1
      }
    ],
    "id": 5,
    "builtin": "vocab_review"
  },
  {
    "name": "下课了",
    "enabled": false,
    "persona_ids": null,
    "event": "study.lesson_finished",
    "conditions": [],
    "probability": 100,
    "cooldown_minutes": 0,
    "cooldown_turns": 0,
    "once_per": "none",
    "actions": [
      {
        "type": "say",
        "directive": "对方刚上完一节口语课。按你的性格问问上得怎么样，别像老师那样讲评。"
      }
    ],
    "id": 6,
    "builtin": "lesson_done"
  },
  {
    "name": "单元达标",
    "enabled": true,
    "persona_ids": null,
    "event": "course.unit_completed",
    "conditions": [],
    "probability": 100,
    "cooldown_minutes": 0,
    "cooldown_turns": 0,
    "once_per": "none",
    "actions": [
      {
        "type": "remember",
        "content": "{{date}} 对方在课程里学完了「{{event.title}}」这一单元",
        "category": "event"
      },
      {
        "type": "say",
        "directive": "对方刚在课程里学完「{{event.title}}」这个单元。按你的性格夸一句或聊两句，别像老师讲评。"
      }
    ],
    "id": 7,
    "builtin": "unit_done"
  },
  {
    "id": 8,
    "name": "熬夜计数",
    "enabled": true,
    "persona_ids": [
      1
    ],
    "event": "chat.user_message",
    "conditions": [
      {
        "field": "hour",
        "op": "between",
        "value": [
          23,
          4
        ]
      },
      {
        "field": "var.night_owl",
        "op": "<",
        "value": 5
      }
    ],
    "probability": 100,
    "cooldown_minutes": 120,
    "cooldown_turns": 0,
    "once_per": "day",
    "actions": [
      {
        "type": "inc_var",
        "name": "night_owl",
        "by": 1,
        "scope": "persona"
      },
      {
        "type": "activate_entry",
        "book_id": 1,
        "uid": 1,
        "turns": 2
      }
    ],
    "builtin": null
  }
];

function sseFrames({ lead = 1, proactive = false, chime = null, userIds = [], enter = null, actions = [], bubbleLimit } = {}) {
  const lines = {
    1: proactive
      ? [jaTokens([['ねえ', 'ネエ'], ['、', '', '', '記号'], ['二', 'フツ'], ['日', 'カ'], ['も', 'モ'], ['来', 'コ', '来る'], ['なかった', 'ナカッタ'], ['じゃん', 'ジャン'], ['。', '', '', '記号']]),
         jaTokens([['寂しかった', 'サビシカッタ', '寂しい'], ['んだけど', 'ンダケド'], ['？', '', '', '記号']])]
      : [jaTokens([['えー', 'エー'], ['、', '', '', '記号'], ['また', 'マタ'], ['それ', 'ソレ'], ['？', '', '', '記号']]),
         jaTokens([['仕方', 'シカタ'], ['ない', 'ナイ'], ['な', 'ナ'], ['あ', 'ア'], ['。', '', '', '記号'], ['今日', 'キョウ'], ['だけ', 'ダケ'], ['だから', 'ダカラ'], ['ね', 'ネ'], ['。', '', '', '記号']])],
    2: [enTokens('Ha, she says that every time.')],
    3: [enTokens('Na gut, dann eben nur heute.')],
  };
  const frames = [];
  const push = (event, data) => frames.push(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  const who = (id) => { const p = personas.find((x) => x.id === id); return { session_id: MAIN_SESSION, persona_id: id, persona_name: p?.name, language: p?.language, ...(proactive ? { proactive: true } : {}) }; };
  if (enter) push('system', { kind: 'enter', text: enter + ' 来了', message_id: 949, proactive: true });
  const ids = [];
  let next = proactive ? 950 : 900;
  const speak = (id, role) => {
    push('speaker', { ...who(id), role });
    if (role === 'lead' && userIds.length) push('read', { message_ids: userIds, ...who(lead) });
    if (role === 'lead') push('guard', { status: 'passed', retries: 0, mood: proactive ? 'pout' : 'happy', session_id: MAIN_SESSION, ...who(id) });
    lines[id].slice(0, bubbleLimit).forEach((tokens, i) => {
      const text = joinTokens(tokens);
      push('delta', { bubble: i, text: text.slice(0, Math.ceil(text.length / 2)), ...who(id) });
      push('delta', { bubble: i, text: text.slice(Math.ceil(text.length / 2)), ...who(id) });
      push('bubble_done', { bubble: i, message_id: next, text, tokens, sticker: null, ...who(id) });
      ids.push(next++);
    });
  };
  speak(lead, 'lead');
  for (const action of actions) push('action', { ...action, ...who(lead) });
  if (chime && chime !== lead) speak(chime, 'chime');
  push('done', { message_ids: ids, session_id: MAIN_SESSION, ...who(lead) });
  return frames.join('');
}

const json = (data, status = 200) => ({ status, json: data });
const sse = (text) => ({ status: 200, contentType: 'text/event-stream', body: text });

// 每个预览场景一份独立的假后端状态。opts:
//   degraded   模型与账号：主引擎出错，降级到 DeepSeek
//   proactive  糖糖有一条待发的主动消息（打开对话就冒出来）
//   solo       主聊天里只有主人设（没有副人设在场）
//   fun        趣味模式开着
export function createMock(opts = {}) {
  const books = initialBooks();
  let rules = initialRules();
  let nextRule = 20;
  // 后端：新条目不带 uid 时编号（书内最大 uid + 1）
  const numberEntries = (book) => {
    let max = Math.max(0, ...(book.entries || []).map((e) => Number(e.uid) || 0));
    book.entries = (book.entries || []).map((e) => (e.uid ? e : { ...e, uid: ++max }));
    return book;
  };
  const vars = [
    { name: 'night_owl', value: 2, scope: 'persona', persona_id: 1 },
    { name: 'streak_days', value: 5, scope: 'global', persona_id: null },
  ];
  const pending = new Map(opts.proactive ? [[1, 1]] : opts.proactiveGuest ? [[3, 1]] : []);
  let lesson = null, nextLessonId = 1;
  const courses = {ja: {mode: 'off'}, en: {mode: 'ambient', preset_id: lessonCourse.id}};
  const courseOverview = language => {
    const teaching = courses[language] || {mode: 'off'};
    const outline = teachingPresets.find(item => item.id === teaching.preset_id);
    if (outline?.version === 3) {
      const units = outline.units.map(unit => ({...unit, status: 'new', points: courseLessons.get(unit.id).points.map(point => ({
        id: point.id, label: point.label, status: 'new',
      }))}));
      const next = teaching.mode === 'ambient' ? units[0] : null;
      return {active: teaching.mode === 'ambient', course: {id: outline.id, title: outline.title, language},
        counts: {points: units.reduce((n, unit) => n + unit.points.length, 0), known: 0},
        units, next: next ? {unit_id: next.id, title: next.title} : null,
        lesson: lesson?.language === language && !lesson.ended ? lessonView() : null};
    }
    return {active: false, course: null, counts: {points: 0, known: 0}, units: [], next: null, lesson: null};
  };

  function lessonView() {
    if (!lesson) return null;
    const source = courseLessons.get(lesson.lesson_id);
    const cards = (lesson.practiceRun ? source.cards.slice(-1) : source.cards)
      .map(card => { const {tasks, ...visible} = structuredClone(card); return visible; });
    let task = null;
    if (cards.at(-1)?.type === 'write') {
      const selected = structuredClone(source.cards.find(card => card.type === 'write').tasks[0]);
      if (!lesson.ended) { delete selected.model; delete selected.must; }
      task = selected;
    }
    const {practiceRun, ...view} = structuredClone(lesson);
    return {...view, cards, task};
  }
  const chatMain = {
    primary_id: 1, primary_chime: 20, language: 'ja', fun: Boolean(opts.fun), fun_languages: ['ja', 'en', 'de'], session_id: MAIN_SESSION,
    guests: [
      { persona_id: 2, enabled: true, rule: { type: 'always' }, chime: 25 },
      { persona_id: 3, enabled: true, rule: { type: 'keyword', keywords: ['Lena', 'Deutsch'] }, chime: 10 },
    ],
  };
  const presentGuests = () => (opts.solo ? [] : chatMain.guests.filter((g) => g.enabled).map((g) => g.persona_id));
  const mainView = () => ({ ...chatMain, present_guest_ids: presentGuests(), languages: [{ tag: 'ja', label: '日本語' }, { tag: 'en', label: 'English' }, { tag: 'de', label: 'Deutsch' }],
    pending: [...pending.values()].reduce((a, b) => a + b, 0) });
  let nextUserId = 1001;
  // ---------- 学习（docs/LEARNING.md）：复习队列、今天、建议、统计 ----------
  const reviewCards = opts.emptyQueue ? [] : [
    { id: 1, kind: 'vocab', language: 'ja', state: 'review', vocab_id: 1, sentence: 'ふふ、____しますって敬語使ってきた。', hint: '请求', meaning: null,
      back: { lemma: 'お願い', surface: 'お願い', reading: 'おねがい', meaning: '请求；拜托', sentence: 'ふふ、おねがいしますって敬語使ってきた。', other_sentences: ['あめにお願いしてほしいってこと？'], encounters: 4 } },
    { id: 2, kind: 'reading_q', language: 'en', state: 'review', title: 'NASA Invites Media, Public to Join Voyager 1', question: 'Why is the Nov. 18 milestone significant?',
      options: ['Voyager 1 will stop sending data', 'Voyager 1 will be one light-day from Earth', 'NASA will launch a new probe', 'Light from Voyager will reach Mars'],
      paragraph: 'Launched nearly 50 years ago in 1977, NASA’s Voyager 1 on Wednesday, Nov. 18 will have traveled one light-day from Earth.', quote: 'will have traveled one light-day from Earth', skill: 'inference', skill: 'detail',
      back: { answer: 1, explanation: '第二句说它届时离地球一个光日。', quote: 'will have traveled one light-day from Earth' } },
    { id: 3, kind: 'vocab_produce', language: 'ja', state: 'review', vocab_id: 3, meaning: '心脏', sentence: '____うるさいんだけど',
      back: { lemma: '心臓', surface: '心臓', reading: 'しんぞう', meaning: '心脏', sentence: '心臓うるさいんだけど', other_sentences: [], encounters: 2 } },
    { id: 4, kind: 'listening_q', language: 'ja', state: 'review', title: '駅のアナウンス', question: '電車はなぜ遅れていますか。', options: ['事故があったから', '雪が降っているから', '点検中だから', '乗客が多いから'],
      audio: '/api/listening/errors/p1/audio', clips: [{ start: 0, end: 3.2 }], skill: 'detail',
      back: { answer: 2, explanation: '广播里说「車両点検のため」。', evidence: [{ speaker: 'A', text: 'ただいま車両点検のため、電車が遅れております。' }] } },
    { id: 5, kind: 'pattern', language: 'ja', state: 'new', sentence: 'あめに____ってこと？', translation: '你是想让我拜托你？',
      back: { pattern: '〜ってこと？', explanation: '确认对方的意思', example: 'あめにお願いしてほしいってこと？', translation: '你是想让我拜托你？' } },
  ];
  const revealed = new Map();
  const intervals = { 1: 0, 2: 1.4, 3: 3.8, 4: 9.2 };
  let graded = 0, forgotCount = 0;
  const frontOf = ({ back, ...card }) => card;
  const vocabContexts = [
    { id: 1, vocab_id: 1, sentence: 'ふふ、おねがいしますって敬語使ってきた。', source_kind: 'chat', created_at: iso(0) },
    { id: 2, vocab_id: 1, sentence: 'あめにお願いしてほしいってこと？', source_kind: 'chat', created_at: iso(0) },
    { id: 3, vocab_id: 1, sentence: '一つお願いがあるんだけど。', source_kind: 'reading', created_at: iso(2) },
  ];
  const lookups = [];
  const readerLookups = [
    { lemma: 'milestone', word: 'milestone', sentence: 'The milestone is a reminder of how far the twin probes have come.', saved: false },
    { lemma: 'probe', word: 'probes', sentence: 'The milestone is a reminder of how far the twin probes have come.', saved: true },
    { lemma: 'distant', word: 'distant', sentence: 'Voyager 1 is the most distant human-made object.', saved: false },
  ];
  let plays = 0;
  const listeningScript = [
    { speaker: 'A', text: 'Excuse me, is the library open this weekend?' },
    { speaker: 'B', text: 'The library closes early on Fridays. On Saturday it opens at ten.' },
    { speaker: 'A', text: 'What about Saturday?' },
    { speaker: 'B', text: 'Bring your student card. You need it at the gate.' },
  ];
  const gpt = { state: opts.gpt ? 'authorized' : 'required', model: opts.gpt ? 'gpt-5.5' : null, effort: opts.gpt ? 'medium' : null };
  const zotero = { port: 23119, library: 'users/0' };
  const builtinSource = (id, name, kind, lang, format = 'json') => ({ id, name, kind, lang, format, url: 'https://' + id + '.example', builtin: true, enabled: true, connector: kind === 'paper' ? 'papers' : 'feed', auth: { mode: 'none', configured: false, key_mask: '' }, fields: {}, params: {}, query_param: kind === 'paper' ? 'query' : '', allow_private: false });
  const readerSources = [
    builtinSource('nasa', 'NASA', 'article', 'en', 'rss'), builtinSource('wikipedia', 'Wikipedia', 'article', 'en'), builtinSource('nhk', 'NHK やさしいことば', 'article', 'ja'),
    { id: 'custom-1', name: '雨の本屋だより', kind: 'article', lang: 'ja', format: 'rss', url: 'https://ame-books.example/feed', builtin: false, enabled: true, connector: 'spec', auth: { mode: 'none', configured: false, key_mask: '' }, fields: {}, params: {}, query_param: '', allow_private: false },
    builtinSource('europe-pmc', 'Europe PMC', 'paper', null), builtinSource('arxiv', 'arXiv', 'paper', null, 'rss'),
  ];
  const settings = {
    chat_engine: 'claude', utility_engine: 'auto', chat_fallback: 'enabled', chat_model_claude: 'sonnet', chat_reasoning_claude: 'medium',
    vision_engine: 'claude', deepseek_model: 'deepseek-chat', deepseek_api_key: '····a1b2',
    custom_base_url: '', custom_model: '', custom_api_key: null, coach_bridge: true,
    hooks_enabled: true, hooks_say_daily_cap: 4, hooks_say_min_gap_minutes: 30,
  };
  const listenPlans = structuredClone(listeningOptions.plans);
  let practices = opts.listeningEmpty ? [] : [
    { id: 'p-3', language: 'en', format: '学术讲解', status: 'graded', count: 3, score: 2, marks: [true, false, true], created_at: iso(0, 9), size_bytes: 2400000 },
    { id: 'p-2', language: 'en', format: '校园对话', status: 'ready', count: 2, created_at: iso(1, 21), size_bytes: 1800000 },
    { id: 'p-6', language: 'en', format: '学术讲解', status: 'graded', count: 4, score: 1, marks: [false, true, false, false], created_at: iso(2, 20), size_bytes: 2100000 },
    { id: 'p-5', language: 'en', format: '校园公告', status: 'graded', count: 2, score: 2, marks: [true, true], created_at: iso(4, 19), size_bytes: 1500000 },
    { id: 'p-4', language: 'en', format: '校园对话', status: 'graded', count: 3, score: 1, marks: [false, false, true], created_at: iso(6, 22), size_bytes: 1700000 },
    { id: 'p-7', language: 'ja', format: '課題理解', status: 'graded', count: 1, score: 0, marks: [false], preview: '今後、何をすることになるか。', created_at: iso(8, 20), size_bytes: 1600000 },
    { id: 'p-8', language: 'ja', format: '概要理解', status: 'graded', count: 2, score: 2, marks: [true, true], created_at: iso(11, 21), size_bytes: 1600000 },
    { id: 'p-9', language: 'en', format: '学术讲解', status: 'graded', count: 4, score: 3, marks: [true, true, false, true], preview: 'Why do some desert plants open their pores only at night?', created_at: iso(15, 9), size_bytes: 2600000 },
    { id: 'p-1', status: 'unreadable', created_at: iso(3, 8), size_bytes: 950000 },
  ];
  const storage = () => ({ count: practices.length, max_count: 40, used_bytes: practices.reduce((n, p) => n + p.size_bytes, 0), max_bytes: 200 * 1024 * 1024 });
  const bookRow = (b) => ({ id: b.id, name: b.name, scope: b.scope, enabled: b.enabled, entry_count: b.book.entries.length, attached_persona_ids: b.scope === 'global' ? [] : b.attached });
  const pendingList = () => [...pending].map(([persona_id, count]) => ({ persona_id, count }));
  const log = [
    { at: '2026-11-12 09:12:40', rule_id: 1, rule_name: '久别重逢', event: 'chat.open', persona_id: 1, actions: ['say'], skipped_reason: null },
    { at: '2026-11-12 01:40:02', rule_id: 8, rule_name: '熬夜计数', event: 'chat.user_message', persona_id: 1, actions: ['inc_var:night_owl', 'activate_entry'], skipped_reason: null },
    { at: '2026-11-11 22:05:13', rule_id: 5, rule_name: '生词回炉', event: 'chat.user_message', persona_id: 2, actions: [], skipped_reason: 'no_due_vocab' },
    { at: '2026-11-11 20:31:55', rule_id: 3, rule_name: '学完来找你（阅读）', event: 'study.reading_finished', persona_id: 2, actions: [], skipped_reason: 'say_min_gap' },
  ];

  function handle(rawUrl, method = 'GET', body = null) {
    const url = new URL(rawUrl);
    const path = url.pathname.replace(/^\/api/, '');
    const q = url.searchParams;
    const m = (re) => path.match(re);
    const req = () => (body ? JSON.parse(body) : {});
    let hit;

    // 应用壳
    if (path === '/health') return json({ status: 'ok', mode: 'live', engine: opts.degraded ? 'deepseek' : 'claude', degraded: Boolean(opts.degraded) });
    if (path === '/usage') return json({ available: true, five_hour_pct: 37.2, five_hour_resets: iso(-1), seven_day_pct: 12.4, seven_day_resets: iso(-3) });
    if (path === '/languages') return json({ items: [{ tag: 'ja', label: '日本語' }, { tag: 'en', label: 'English' }, { tag: 'de', label: 'Deutsch' }] });
    if (path === '/personas' && method === 'GET') return json({ items: personas });

    // 聊天
    if (path === '/sessions') return json({ items: sessions[Number(q.get('persona_id'))] || [] });
    hit = m(/^\/sessions\/(\d+)\/messages$/);
    if (hit) return json({ items: messages[Number(hit[1])] || [] });
    hit = m(/^\/messages\/(\d+)\/location$/);
    if (hit) {
      const id = Number(hit[1]);
      const sid = Object.keys(messages).find((k) => messages[k].some((x) => x.id === id));
      return sid ? json({ session_id: Number(sid) }) : json({ detail: '没有这条消息' }, 404);
    }
    // 学习
    if (path === '/today') {
      const lang = q.get('language') || 'ja';
      return json({ language: lang, date: '2026-11-13', steps: [
        { kind: 'review', count: reviewCards.length - graded, done: false, reviewed_today: graded },
        { kind: 'listening', count: 0, done: false, week: 1, suggestion: '降一档会学得更快', basis: '最近 5 次平均答对 2.4/4' },
        { kind: 'reading', count: 1, done: true, week: 3, suggestion: '可以升一档', basis: '最近 5 篇平均答对 8.6/9，查词 1.2%' },
        { kind: 'output', done: false, target: { lesson: courseOverview(q.get('language') || 'ja').next, words: [{ lemma: 'お願い', meaning: '请求' }, { lemma: '心臓', meaning: '心脏' }], speaking_debts: 3, last_lesson: null } },
      ] });
    }
    if ((path === '/learning/advice' || path === '/learning/stats') && !q.get('language')) return json({ detail: 'language required' }, 422);
    if (path === '/learning/advice') return json({ language: q.get('language'),
      reading: { level: 'up', suggestion: '可以升一档', basis: '最近 5 篇平均答对 8.6/9，查词 1.2%', n: 5 },
      ...(opts.listeningEmpty ? {} : { listening: { level: 'down', suggestion: '降一档会学得更快', basis: '最近 5 次平均答对 2.4/4', n: 5 } }), weak_types: [] });
    if (path === '/learning/stats') return json(opts.noStats ? { reading: null, listening: null, review: null, words_encountered: null } : {
      language: q.get('language'), days: 30,
      reading: { count: 12, accuracy: 0.81, types: { detail: { n: 30, correct: 27, accuracy: 0.9, label: '事实细节' }, inference: { n: 22, correct: 14, accuracy: 0.636, label: '推断' }, vocabulary: { n: 18, correct: 16, accuracy: 0.889, label: '词义' } } },
      listening: opts.listeningEmpty ? { count: 0, accuracy: null, causes: {}, dictation: null, replays: null } : { count: 8, accuracy: 0.66, types: { gist: { n: 10, correct: 8, accuracy: 0.8, label: '主旨' }, detail: { n: 14, correct: 7, accuracy: 0.5, label: '细节' } }, causes: { not_heard: 6, not_understood: 3, misjudged: 2 }, dictation: 0.74, replays: 9 },
      review: { count: 132, forgot: 17, retention_7d: 0.88, retention_30d: 0.86 }, words_encountered: 214 });
    if (path === '/learning/settings') return json({ types: { reading: { detail: '事实细节', inference: '推断', jlpt_short: '内容理解（短文）' }, listening: { gist: '主旨', detail: '细节', jlpt_task: '课题理解' } }, causes: { not_heard: '没听清', not_understood: '听清了没听懂', misjudged: '听懂了答错' }, review_target_retention: settings.review_target_retention ?? 0.9, review_new_per_day: settings.review_new_per_day ?? 12, review_mix: settings.review_mix ?? true, reading_questions_first: settings.reading_questions_first ?? false });
    if (path === '/learning/encounters' && method === 'POST') return json({ words: 7 }, 201);
    if (path === '/review/queue') { const kinds = (q.get('kinds') || '').split(',').filter(Boolean); const cards = reviewCards.filter((c) => !kinds.length || kinds.includes(c.kind)).map(frontOf); return json({ cards, later: [], due_now: cards.length, new_left_today: 8 }); }
    hit = m(/^\/review\/cards\/(\d+)\/(reveal|grade)$/);
    if (hit) {
      const card = reviewCards.find((c) => c.id === Number(hit[1]));
      if (!card) return json({ detail: '没有这张卡' }, 404);
      const r = req();
      const objective = ['reading_q', 'listening_q', 'vocab_produce'].includes(card.kind);
      if (hit[2] === 'reveal') {
        const peeked = Boolean(r.gave_up) || (objective && r.answer == null);
        const correct = peeked || r.answer == null ? null : card.kind === 'vocab_produce' ? [card.back.lemma, card.back.reading].includes(String(r.answer).trim()) : r.answer === card.back.answer;
        revealed.set(card.id, { peeked, correct });
        return json({ id: card.id, kind: card.kind, back: card.back, peeked, correct, intervals });
      }
      const state = revealed.get(card.id) || {};
      const rating = state.peeked ? 1 : objective ? (state.correct ? 3 : 1) : r.rating;
      graded += 1; if (rating === 1) forgotCount += 1;
      return json({ next_due_at: iso(-Math.round(intervals[rating] || 0)), interval_days: intervals[rating], again_in_session: false, rating, peeked: Boolean(state.peeked), stability: 4.2 });
    }
    if (path === '/review/session/end') return json({ count: graded, forgot: forgotCount });
    if (path === '/review/summary') return json({ due_now: reviewCards.length - graded, new_available: 3, by_kind: {}, retention_7d: 0.88, retention_30d: 0.86, reviews_7d: 140,
      forecast: [0, 6, 4, 9, 2, 5, 3].map((due, i) => ({ date: iso(-i).slice(0, 10), due })) });
    hit = m(/^\/vocab\/(\d+)$/);
    if (hit && method === 'GET') {
      const v = vocab.find((x) => x.id === Number(hit[1]));
      if (!v) return json({ detail: '没有这个词' }, 404);
      return json({ ...v, encounters: 4, remember_days: 23.6, card: { due_at: iso(-5), stability: 23.6 },
        contexts: vocabContexts.filter((c) => c.vocab_id === v.id) });
    }
    hit = m(/^\/vocab\/(\d+)\/contexts$/);
    if (hit && method === 'DELETE') { const id = Number(q.get('context_id')); const i = vocabContexts.findIndex((c) => c.id === id); if (i >= 0) vocabContexts.splice(i, 1); return json({ ok: true }); }
    // 阅读：查过的词、读后两句
    if (path === '/reader/lookups' && method === 'POST') { const r = req(); lookups.push({ ...r, saved: false }); return json({ ok: true }, 201); }
    if (path === '/reader/lookups' && method === 'GET') return json({ items: [...new Map([...readerLookups, ...lookups].map((x) => [x.lemma, x])).values()] });
    if (path === '/reader/summary-feedback' && method === 'POST') return json({ points_right: ['Voyager 1 is about to reach one light-day from Earth.'],
      fixes: [{ original: 'is most far', better: 'is the most distant', why: '最高级用 the most + 形容词' }], missed: 'It is the most distant human-made object.' });
    // 听力：盲听计数、错因、精听逐句、听写
    hit = m(/^\/listening\/practice\/([\w-]+)\/(play|causes|lines|dictation)$/);
    if (hit) {
      if (hit[2] === 'play') { plays += 1; return json({ plays, replays: Math.max(0, plays - 1) }, 201); }
      if (hit[2] === 'causes') { const items = req().items.map((i) => ({ ...i, type: 'detail', next: { not_heard: 'dictation', not_understood: 'save_words', misjudged: 'evidence' }[i.cause] })); return json({ items }); }
      if (hit[2] === 'lines') return json({ lines: listeningScript.map((l, i) => {
        const parts = l.text.match(/[^.?!]+[.?!]+/g) || [l.text];
        const span = 2.8 / parts.length;
        return { line: i + 1, ...l, start: i * 3, end: i * 3 + 2.8, sentences: parts.map((t, k) => ({ sentence: k + 1, text: t.trim(), start: i * 3 + k * span, end: i * 3 + (k + 1) * span })) };
      }), dictation: [{ line: 2, sentence: 1 }, { line: 4, sentence: 2 }] });
      const r = req();
      const words = r.line === 2
        ? [{ text: 'The', status: 'ok' }, { text: 'library', status: 'ok' }, { text: 'closes', status: 'wrong', typed: 'close' }, { text: 'early', status: 'ok' }, { text: 'on', status: 'missing' }, { text: 'Fridays', status: 'ok' }]
        : [{ text: 'Bring', status: 'ok' }, { text: 'your', status: 'ok' }, { text: 'student', status: 'ok' }, { text: 'card', status: 'ok' }];
      const correct = words.filter((w) => w.status === 'ok').length;
      const ref = r.line === 2 ? 'The library closes early on Fridays.' : 'You need it at the gate.';
      return json({ line: r.line, sentence: r.sentence ?? null, reference: ref, words, extra: [], correct, total: words.length, score: correct / words.length });
    }
    hit = m(/^\/listening\/practice\/([\w-]+)\/lines\/(\d+)\/audio$/);
    if (hit) return { status: 200, contentType: 'audio/wav', body: '' };
    if (path === '/teaching/lesson' && method === 'GET') return json({lesson: lessonView()});
    if (path === '/teaching/lesson/start' && method === 'POST') {
      const body = req(), language = body.language || chatMain.language;
      const overview = courseOverview(language);
      if (!overview.active || overview.course?.id !== lessonCourse.id) return json({}, 422);
      const unit = courseLessons.get(body.lesson_id || overview.next?.unit_id);
      if (!unit) return body.lesson_id ? json({}, 404) : json({detail: '现在没有可上的课'}, 409);
      lesson = {id: nextLessonId++, language, course_id: lessonCourse.id, lesson_id: unit.id, title: unit.title,
        started_at: iso(0), ended: false, answers: {}, sheet: null, essay: '', set: null, result: null, practice: null, venue: 'page', practiceRun: Boolean(body.practice)};
      return json({lesson: lessonView()}, 201);
    }
    if (path === '/teaching/lesson/stop' && method === 'POST') { lesson = null; return json({lesson}); }
    if (path === '/teaching/lesson/answer' && method === 'POST') {
      const {card: cardId, item, text} = req(), card = lessonView()?.cards.find(card => card.id === cardId);
      if (!lesson || lesson.ended || card?.type !== 'drill') return json({}, 409);
      if (!Number.isInteger(item) || !card.items[item] || typeof text !== 'string') return json({}, 422);
      const ok = text.includes('right'), check = {ok, fix: ok ? '' : 'FIX ' + text, why: ok ? '对。' : '还差一点。'};
      (lesson.answers[card.id] ||= {})[String(item)] = {text, ...check};
      return json({lesson: lessonView(), check});
    }
    if (path === '/teaching/lesson/submit' && method === 'POST') {
      if (!lesson || lesson.ended || lessonView().cards.at(-1).type !== 'write') return json({}, 409);
      const {text, seconds} = req();
      if ((text?.trim().match(/\S+/g) || []).length < 10) return json({detail: '写得太少，没法批改'}, 422);
      const unit = courseLessons.get(lesson.lesson_id), example = structuredClone(unit.cards.find(card => card.type === 'marking').example);
      lesson.sheet = {
        coverage: example.coverage.map(({verdict, quote, note}) => ({verdict: ({'做到了': 'done', '做了但太薄': 'thin', '没做': 'missing'})[verdict], quote, note})),
        score: 3, reason: example.reason, fixes: example.fixes, upgrade: example.upgrade,
        points: unit.points.map(point => ({id: point.id, met: false, quote: '', why: example.reason})), next: '',
      };
      lesson.essay = text;
      lesson.seconds = seconds;
      lesson.ended = true;
      if (lesson.practice && lesson.venue === 'chat') pending.set(chatMain.primary_id, 1);   // 只有聊天里写的练习，她才接一句
      return json({lesson: lessonView()});
    }
    // 只给预览用：让她多一条待发（看图标栏红点）
    if (path === '/__mock/pending' && method === 'POST') { pending.set(1, 1); return json({ ok: true }); }
    // 主聊天（docs/MAIN-CHAT.md 第四节）
    if (path === '/chat/main/warm' && method === 'POST') return json({ ok: true });
    if (path === '/chat/speech/warm' && method === 'POST') return json({ ok: true }, 202);
    if (path === '/chat/main' && method === 'GET') return json(mainView());
    if (path === '/chat/main' && method === 'PUT') {
      const r = req();
      const known = ['primary_id', 'language', 'fun', 'fun_languages', 'guests', 'primary_chime'];
      if (Object.keys(r).some((k) => !known.includes(k))) return json({ detail: '不认识的设置项' }, 422);
      if (r.language && !mainView().languages.some((l) => l.tag === r.language)) return json({ detail: '这门语言还没添加' }, 422);
    }
    if (path === '/chat/main' && method === 'PUT') { Object.assign(chatMain, req()); return json(mainView()); }
    if (path === '/chat/main/messages') {
      const all = messages[MAIN_SESSION];
      const before = Number(q.get('before')) || Infinity;
      const limit = Number(q.get('limit')) || 50;
      return json({ session_id: MAIN_SESSION, items: all.filter((x) => x.id < before).slice(-limit) });
    }
    if (path === '/chat/archives') return json({ items: [
      { session_id: 11, persona_id: 1, persona_name: '糖糖（あめ）', language: 'ja', started_at: iso(9, 22, 1), last_at: iso(9, 22, 2), count: messages[11].length },
      { session_id: 12, persona_id: 2, persona_name: 'Emma', language: 'en', started_at: iso(8, 18, 0), last_at: iso(8, 18, 1), count: messages[12].length },
    ] });
    hit = m(/^\/chat\/archives\/(\d+)$/);
    if (hit) return messages[Number(hit[1])] && Number(hit[1]) !== MAIN_SESSION ? json({ session_id: Number(hit[1]), read_only: true, items: messages[Number(hit[1])] }) : json({ detail: '没有这段旧对话' }, 404);
    if (path === '/stickers') return json({ items: stickerList });
    if (path === '/chat' && method === 'POST') {
      const r = req();
      const present = presentGuests();
      const lead = r.to ?? (/lena/i.test(r.text || '') && present.includes(3) ? 3 : 1);
      const chime = lead === 1 && present.includes(2) ? 2 : null;
      return sse(sseFrames({ lead, chime, userIds: [nextUserId++], actions: opts.chatActions || [], bubbleLimit: opts.chatBubbleLimit }));
    }
    if (path === '/chat/proactive' && method === 'POST') {
      const personaId = req().persona_id ?? [...pending.keys()][0];
      if (!pending.get(personaId)) return sse(`event: done\ndata: ${JSON.stringify({ empty: true, proactive: true })}\n\n`);
      pending.delete(personaId);
      return sse(sseFrames({ lead: personaId, proactive: true, enter: opts.proactiveGuest ? personas.find((p) => p.id === personaId)?.name : null }));
    }
    if (path === '/uploads/image') return json({ url: 'assets/avatars/happy.png' });
    if (path === '/explain/words') {
      const r = req();
      // 整句预取的简释（点词秒出）：detail=brief 时词卡上有「用法与语法」按需展开
      const brief = (occurrence) => ({ surface: 'お願い', lemma: 'お願い', reading: 'おねがい', pos: '名词', meaning_zh: '请求；拜托', detail: 'brief', occurrence });
      return json({ words: String(r.sentence || '').includes('お願い') ? [brief(0), brief(1)] : [], sentence: r.sentence });
    }
    if (path === '/explain/word') {
      const r = req();
      return json({ surface: r.surface, lemma: r.lemma, reading: r.language === 'ja' ? 'おねがい' : null, pos: '名词', meaning_zh: '请求；拜托（客气地请别人做事）',
        usage_in_context: '这里是糖糖学你说敬语，带点调侃。', grammar_note: '「お＋动词连用形」构成谦让表达。', register_note: '礼貌', detail: 'brief' });
    }
    if (path === '/explain/sentence') {
      return json({ translation_zh: '嗯……你在说什么我不太明白。是想让我拜托你？还是想让我说「拜托了」？',
        chunks: [{ text: 'えっと', role: '感叹' }, { text: '何言ってるのか', role: '宾语从句' }, { text: 'よくわかんない', role: '谓语' }],
        grammar_points: [{ pattern: '〜てほしい', explanation_zh: '希望别人做某事。', example: '手伝ってほしい。' }, { pattern: '〜ってこと？', explanation_zh: '确认对方的意思。', example: 'つまり来ないってこと？' }] });
    }
    if (path === '/reader/furigana') return json({ tokens: [{ text: req().text || '' }] });

    // 事件 hook
    if (path === '/hooks/meta') return json(hooksMeta);
    if (path === '/hooks/pending') return json({ items: pendingList() });
    if (path === '/hooks/fire' && method === 'POST') {
      const r = req();
      if (!['chat.open', 'chat.idle'].includes(r.event)) return json({ detail: [{ msg: "Input should be 'chat.open' or 'chat.idle'" }] }, 422);
      return json({ fired: opts.proactive ? [1] : [], pending: pendingList() });
    }
    if (path === '/hooks/rules' && method === 'GET') return json({ items: rules });
    if (path === '/hooks/rules' && method === 'POST') { const rule = { ...req(), id: nextRule++, builtin: null }; rules.push(rule); return json(rule, 201); }
    hit = m(/^\/hooks\/rules\/(\d+)$/);
    if (hit && method === 'PUT') { const id = Number(hit[1]); rules = rules.map((r) => (r.id === id ? { ...r, ...req(), id } : r)); return json(rules.find((r) => r.id === id)); }
    if (hit && method === 'DELETE') {
      const rule = rules.find((r) => r.id === Number(hit[1]));
      if (rule?.builtin) return json({ detail: '自带规则不能删，只能关' }, 409);
      rules = rules.filter((r) => r !== rule); return json({ ok: true });
    }
    if (path === '/hooks/log') return json({ items: log.slice(0, Number(q.get('limit') || 50)) });
    if (path === '/hooks/vars' && method === 'GET') return json({ items: vars.filter((v) => !q.get('persona_id') || v.persona_id === Number(q.get('persona_id')) || v.scope === 'global') });
    if (path === '/hooks/vars' && method === 'PUT') {
      const r = req();
      const i = vars.findIndex((v) => v.name === r.name && v.scope === r.scope && (v.persona_id ?? null) === (r.persona_id ?? null));
      if (r.scope === 'persona' && !r.persona_id) return json({ detail: '联系人变量要带 persona_id' }, 422);
      if (r.value === null) { if (i >= 0) vars.splice(i, 1); } else if (i >= 0) vars[i].value = r.value; else vars.push({ ...r, persona_id: r.scope === 'global' ? null : r.persona_id });
      return json({ items: vars });
    }

    // 世界书
    if (path === '/lore/books' && method === 'GET') return json({ items: books.map(bookRow) });
    if (path === '/lore/books' && method === 'POST') {
      const r = req();
      const book = { id: Math.max(0, ...books.map((b) => b.id)) + 1, name: r.name, scope: r.scope || 'attached', enabled: true, attached: [], book: numberEntries(r.book || { version: 2, settings: {}, entries: [] }) };
      books.push(book);
      return json({ id: book.id, name: book.name, scope: book.scope, enabled: true, book: book.book }, 201);
    }
    hit = m(/^\/lore\/books\/(\d+)(\/export)?$/);
    if (hit) {
      const book = books.find((b) => b.id === Number(hit[1]));
      if (!book) return json({ detail: '没有这本书' }, 404);
      if (hit[2]) return { status: 200, contentType: 'application/json', body: JSON.stringify({ entries: {} }) };
      if (method === 'GET') return json({ id: book.id, name: book.name, scope: book.scope, enabled: book.enabled, book: book.book });
      if (method === 'PUT') { const r = req(); Object.assign(book, r); if (r.book) numberEntries(book.book); return json({ id: book.id, name: book.name, scope: book.scope, enabled: book.enabled, book: book.book }); }
      if (method === 'DELETE') { books.splice(books.indexOf(book), 1); return json({ ok: true }); }
    }
    if (path === '/lore/import') {
      if (String(body || '').includes('bad.json')) return json({ detail: '没认出这是酒馆世界书或角色卡' }, 422);
      const book = { id: Math.max(0, ...books.map((b) => b.id)) + 1, name: '酒馆导入 · 雨宫学园', scope: 'attached', enabled: true, attached: [],
        book: { version: 2, settings: { scan_depth: 4, budget_chars: 1600, recursion: true, max_recursion: 3, lemma_match: true },
          entries: [loreEntry(1, { title: '学生会', content: '学生会室在旧校舍三楼。', keys: ['学生会'] }), loreEntry(2, { title: '图书室', content: '放学后图书室只开到五点。', keys: ['图书室'] })] } };
      books.push(book);
      return json({ id: book.id, name: book.name, entry_count: 2, warnings: ['第 3 条的正则关键词写错了，已去掉：/学生(会/', '第 5 条正文超过 4000 字，已截断'] }, 201);
    }
    if (path === '/lore/test' && method === 'POST') {
      return json({
        activated: [
          { book_id: 1, book_name: '糖糖的直播间', uid: 2, title: 'P酱是谁', position: 'after_persona', reason: 'constant', injected: 'system' },
          { book_id: 1, book_name: '糖糖的直播间', uid: 1, title: '配信时间', position: 'turn', reason: 'key:配信', injected: 'turn' },
          { book_id: 2, book_name: '东京生活常识', uid: 1, title: '电车', position: 'turn', reason: 'lemma:終電', injected: 'turn' },
          { book_id: 1, book_name: '糖糖的直播间', uid: 5, title: '上周的约定', position: 'turn', reason: 'sticky', injected: null },
        ],
        // 真后端最多回 500 条；这里放一长串，看列表会不会撑爆
        skipped: [
          { book_id: 1, uid: 3, title: '周四抗体到货', why: 'conditions' },
          { book_id: 1, uid: 4, title: '吃饭', why: 'disabled' },
          ...Array.from({ length: 40 }, (_, i) => ({ book_id: 2, uid: 10 + i, title: '东京小知识 ' + (i + 1), why: ['no_match', 'cooldown', 'group', 'budget', 'probability'][i % 5] })),
        ],
        turn_preview: '［背景］\n糖糖每晚 9 点开播，开播前会很紧张。\n东京的电车末班车大约 0 点。',
        system_preview: 'P酱 是她的专属阿P，研究 RNA 编辑的博士生。',
      });
    }

    // 单词本 / 句型本
    if (path === '/vocab' && method === 'GET') return json({ items: vocab.filter((v) => !q.get('language') || v.language === q.get('language')) });
    if (path === '/patterns' && method === 'GET') return json({ items: patterns.filter((v) => !q.get('language') || v.language === q.get('language')) });
    if (path === '/vocab' && method === 'POST') {
      const r = req();
      const old = vocab.find((v) => v.language === r.language && v.lemma === r.lemma);
      if (old) { vocabContexts.push({ id: vocabContexts.length + 1, vocab_id: old.id, sentence: r.context_sentence || '', source_kind: r.source_kind || 'chat', created_at: iso(0) }); return json({ ...old, created: false, context_count: vocabContexts.filter((c) => c.vocab_id === old.id).length, contexts: vocabContexts.filter((c) => c.vocab_id === old.id) }); }
      return json({ id: 99, ...r, created: true, context_count: 1 });
    }
    if (/^\/(vocab|patterns)/.test(path)) return json({ ok: true, id: 99 });

    // 阅读
    if (path === '/reader/options') return json({ sources: [{ id: 'nasa', name: 'NASA', kind: 'article', lang: 'en', builtin: true, enabled: true }, { id: 'europepmc', name: 'Europe PMC', kind: 'paper', lang: null, builtin: true, enabled: true }],
      formats: [{ id: 'toefl', name: 'TOEFL', language: 'en', builtin: true }, { id: 'jlpt', name: 'JLPT N1', language: 'ja', builtin: true }], defaults: { paper: null, article_en: null } });
    if (path === '/reader/news') return json({ items: readerItems.filter((x) => x.lang === (q.get('lang') || 'en')), unavailable: [], has_candidates: false });
    if (path === '/reader/papers') return json({ items: [], unavailable: [] });
    if (path === '/reader/style') return json({ size: 17, line_height: 1.85, measure: 68, font: 'serif', theme: 'lilac' });
    // 阅读来源（内置 + 自己加的）；试连：地址带 feed 的按 RSS 抓得到，api.example 的 JSON 列表在 results、标题叫 headline、网址叫 link
    if (path === '/reader/sources' && method === 'GET') return json({ items: readerSources });
    if (path === '/reader/sources' && method === 'POST') { const r = req(); const row = { ...r, id: 'custom-' + (readerSources.length + 1), builtin: false, connector: 'spec', auth: { mode: r.auth?.mode || 'none', name: r.auth?.name || '', prefix: r.auth?.prefix || '', configured: Boolean(r.auth?.key), key_mask: r.auth?.key ? '••••' : '' } }; readerSources.push(row); return json(row, 201); }
    if (path === '/reader/sources/order' && method === 'PUT') { const ids = req().ids; readerSources.sort((x, y) => ids.indexOf(x.id) - ids.indexOf(y.id)); return json({ items: readerSources }); }
    if (path === '/reader/sources/test' && method === 'POST') {
      const src = req().source || {};
      const sample = (n) => Array.from({ length: n }, (_, i) => ({ title: ['Rainy-day bookshops are back', 'Why night owls learn differently', 'A tiny guide to Tokyo trains', 'The last tram of the night'][i % 4], url: 'https://example.org/' + i, text: 'A short summary of the article that came back from the source, long enough to show two lines in the preview card.', date: '2026-11-1' + i }));
      if (/feed|rss/.test(src.url)) return src.format === 'rss' ? json({ ok: true, count: 12, items: sample(12), message: '' }) : json({ ok: false, count: 0, items: [], message: '来源返回的格式与配置不符' });
      if (/api\.example/.test(src.url) && src.format === 'json') {
        if (src.fields?.items !== 'results') return json({ ok: false, count: 0, items: [], message: '结果列表字段没有指向数组' });
        if (src.fields?.title !== 'headline' || src.fields?.url !== 'link') return json({ ok: false, count: 0, items: [], message: '有返回记录，但没有读到标题或有效原文地址' });
        return json({ ok: true, count: 8, items: sample(8).map((x) => ({ ...x, text: src.fields?.text === 'abstract' ? x.text : '' })), message: '' });
      }
      return json({ ok: false, count: 0, items: [], message: '连接来源失败，请检查地址、网络或证书' });
    }
    hit = m(/^\/reader\/sources\/([\w-]+)\/test$/);
    if (hit) return json({ ok: true, count: 20, items: [], message: '' });
    hit = m(/^\/reader\/sources\/([\w-]+)$/);
    if (hit) {
      const row = readerSources.find((x) => x.id === hit[1]);
      if (!row) return json({ detail: '找不到该来源' }, 404);
      if (method === 'PATCH') { const r = req(); if (row.builtin && Object.keys(r).some((k) => k !== 'enabled')) return json({ detail: '内置来源只能开关' }, 422); Object.assign(row, r); return json(row); }
      if (method === 'DELETE') { readerSources.splice(readerSources.indexOf(row), 1); return json({ ok: true }); }
    }
    if (path === '/reader/zotero/connection' && method === 'GET') return json(zotero);
    if (path === '/reader/zotero/connection' && method === 'PUT') { Object.assign(zotero, req()); return json(zotero); }
    if (path === '/reader/zotero/connection/test') return json({ ok: true });
    if (path === '/reader/zotero/items') return json({ items: [{ zoteroKey: 'ABCD1234', title: 'Sleep and second-language vocabulary consolidation', authors: 'Kim, Lee', date: '2024', source: 'Zotero', access: 'pdf', text: 'Abstract…' }] });
    if (path === '/reader/errors') return json({ items: reviewItems.filter((x) => x.kind === 'reading') });
    if (path === '/reader/translations') return json({ translations: [] });

    // 听力
    // 听力安排：每个假后端自己一份，保存后刷新仍在
    if (path === '/listening/options') return json({ ...listeningOptions, plans: listenPlans, subscription: '' });
    hit = m(/^\/listening\/plans\/([\w-]+)$/);
    if (hit && method === 'POST') { const b = req(); listenPlans[hit[1]] = { ...(listenPlans[hit[1]] || {}), format: b.format, difficulty: b.difficulty, topic: b.topic || '' }; return json(listenPlans[hit[1]]); }
    if (path === '/listening/practices') return json({ items: practices, storage: storage() });
    // 一段新练习：出题 → 盲听 → 答题 → 交卷（错一题）
    if (path === '/listening/practice' && method === 'POST') { const item = { id: 'p-new', language: 'en', format: '校园对话', count: 2, status: 'ready', created_at: iso(0), size_bytes: 1000000 }; return json(item); }
    // 句子时间轴：批改前就有，不含文字
    hit = m(/^\/listening\/practice\/([\w-]+)\/shape$/);
    if (hit) {
      const lens = [3.2, 2.4, 3.1, 1.6, 3.6, 2.2, 1.9];
      let t = 0;
      const segments = lens.map((len, i) => { const seg = { start: +t.toFixed(2), end: +(t + len).toFixed(2), speaker: i % 2 ? 'B' : 'A' }; t += len + 0.3; return seg; });
      return json({ segments, duration: +t.toFixed(2) });
    }
    hit = m(/^\/listening\/practice\/([\w-]+)\/(audio|questions|grade)$/);
    if (hit) {
      if (hit[2] === 'audio') return { status: 200, contentType: 'audio/wav', body: '' };
      if (hit[2] === 'questions') return json({ questions: [{ prompt: 'Why does the student ask about the library?', choices: ['To return a book', 'To check opening hours', 'To find a friend', 'To print a paper'] }, { prompt: 'What should he bring?', choices: ['A pen', 'Money', 'His student card', 'A laptop'] }] });
      const picks = req().selections || [];
      const results = [
        { prompt: 'Why does the student ask about the library?', choices: ['To return a book', 'To check opening hours', 'To find a friend', 'To print a paper'], answer: 1, correct: picks[0] === 1, explanation: 'He asks whether it is open this weekend.', evidence: [{ speaker: 'A', text: 'Excuse me, is the library open this weekend?', line: 1 }], skill: 'gist' },
        { prompt: 'What should he bring?', choices: ['A pen', 'Money', 'His student card', 'A laptop'], answer: 2, correct: picks[1] === 2, explanation: 'The librarian says to bring the student card.', evidence: [{ speaker: 'B', text: 'Bring your student card.', line: 4 }], skill: 'detail' },
      ];
      const score = results.filter((r) => r.correct).length;
      return json({ title: 'Library hours', score, count: 2, results, script: listeningScript, clips: listeningScript.map((_, i) => ({ start: i * 3, end: i * 3 + 2.8 })), saved_errors: 2 - score });
    }
    hit = m(/^\/listening\/practice\/([\w-]+)$/);
    if (hit && method === 'DELETE') { practices = practices.filter((p) => p.id !== hit[1]); return json({ deleted: hit[1], storage: storage() }); }
    if (hit) {
      const p = practices.find((x) => x.id === hit[1]) || {};
      if (p.status !== 'graded') return json(p);
      // 已交卷：带收据和每道错题已标的错因（没标的是 null）
      const results = [
        { prompt: 'Why does the student ask about the library?', choices: ['To return a book', 'To check opening hours', 'To find a friend', 'To print a paper'], answer: 1, correct: false, selection: 0, explanation: 'He asks whether it is open this weekend.', evidence: [{ speaker: 'A', text: 'Excuse me, is the library open this weekend?', line: 1 }], skill: 'gist' },
        { prompt: 'What should he bring?', choices: ['A pen', 'Money', 'His student card', 'A laptop'], answer: 2, correct: false, selection: 0, explanation: 'The librarian says to bring the student card.', evidence: [{ speaker: 'B', text: 'Bring your student card.', line: 4 }], skill: 'detail' },
      ];
      return json({ ...p, receipt: { title: 'Library hours', score: 0, count: 2, results, script: listeningScript, clips: listeningScript.map((_, i) => ({ start: i * 3, end: i * 3 + 2.8 })), saved_errors: 2 },
        causes: { items: [{ index: 0, cause: 'not_heard', type: '主旨', next: 'dictation' }, { index: 1, cause: null, type: '细节', next: null }] } });
    }
    if (path === '/listening/errors') return json({ items: reviewItems.filter((x) => x.kind === 'listening') });
    if (m(/^\/listening\/errors\/[\w-]+$/) && method === 'DELETE') return json({ deleted: 1 });
    if (path === '/listening/coach') return json({ ok: false, url: 'http://127.0.0.1:65531/', desktop_managed: false, languages: ['en', 'ja'] });
    if (path === '/listening/synthesis') return json({ provider: 'kokoro', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini-tts', api_key_configured: false,
      kokoro_en: { a: 'af_heart', b: 'am_michael', speed: 1 }, kokoro_ja: { a: 'jf_alpha', b: 'jm_kumo', speed: 1 },
      api_en: { a: 'alloy', b: 'verse', speed: 1 }, api_ja: { a: 'alloy', b: 'verse', speed: 1 }, api_languages: {},
      kokoro_voices: { en: ['af_heart', 'am_michael'], ja: ['jf_alpha', 'jm_kumo'] }, pause_ms: 300, volume: 1 });

    // 口语
    if (path === '/speaking/settings') return json({ voicePresets: [{id:'sweet',label:'甜'},{id:'salt',label:'盐'},{id:'onee',label:'御'},{id:'yami',label:'病'},{id:'plain',label:'标准'}], settings: { models: { realtime: 'gpt-realtime', grading: 'gpt-4o', lessonCard: 'gpt-4o-mini', tts: 'gpt-4o-mini-tts' }, voice: 'alloy', ttsVoice: 'alloy', voicePreset: 'yami', voices: ['alloy', 'verse'] } });
    if (path === '/speaking/connection') return json({ provider: 'openai', baseUrl: 'https://api.openai.com/v1', keyConfigured: true, textProvider: 'jine',
      realtime: { speed: 1, vad: 'semantic_vad', eagerness: 'auto', threshold: 0.5, silenceMs: 500, prefixMs: 300, noiseReduction: 'near_field', interrupt: true, maxOutputTokens: null, transcriptionModel: 'gpt-4o-transcribe' } });
    if (path.startsWith('/speaking/lessons')) return json([]);

    // 复习
    if (path === '/review/capabilities') return json({ version: 1, persisted_attempts: true });
    if (path === '/review/state') return json({ items: [] });

    // 学习存储（书架里有两份导入的文档）
    if (path === '/study-storage/capabilities') return json({ version: 1, writable: true });
    if (path === '/study-storage/documents') return json({ documents: [
      { metadata: { id: 'doc-a', title: '細胞の老化と免疫', lang: 'ja', source: '本地文件', scope: '本地文件', libraryOrigin: 'import', text: '細胞は分裂を重ねるうちに…', openedAt: Date.now() - 3600e3 }, revision: 2, hasFile: false },
      { metadata: { id: 'doc-b', title: 'Lecture notes: RNA editing', lang: 'en', source: '本地文件', scope: '用户粘贴正文', libraryOrigin: 'import', text: 'ADAR enzymes convert adenosine to inosine…', openedAt: Date.now() - 86400e3 }, revision: 1, hasFile: false },
    ] });
    if (path === '/study-storage/listening-notes') return json({ text: '', revision: 0 });
    if (path === '/study-storage/listening-draft') { if (method === 'GET') return json({ id: q.get('id'), draft: null, revision: 0 }); if (method === 'PUT') { const r = req(); return json({ id: r.id, draft: r.draft, revision: (r.revision || 0) + 1 }); } return json({ ok: true }); }
    if (path === '/study-storage/annotations') return json({ annotations: [] });
    if (path === '/study-storage/document' && method === 'DELETE') return json({ id: q.get('id'), deleted: true, annotations: 0 });
    if (path === '/study-storage/document' && method === 'GET') return json({ detail: '没有' }, 404);
    if (path === '/study-storage/document') return json({ metadata: { id: q.get('id') || 'doc' }, revision: 1, hasFile: false });

    // 课程 / 记忆 / 设置
    if (path === '/teaching/presets') return json({ items: teachingPresets });
    hit = m(/^\/teaching\/settings\/(.+)$/);
    if (hit) {
      const lang = decodeURIComponent(hit[1]);
      if (method === 'PUT') { const body = req(); courses[lang] = {...body, ...(body.preset ? {preset_id: body.preset} : {})}; }
      return json({language: lang, teaching: courses[lang] || {mode: 'off'}, progress: courseOverview(lang)});
    }
    if (path === '/memory' && method === 'GET') return json({ items: memory.filter((x) => !q.get('persona_id') || x.persona_id === Number(q.get('persona_id'))) });
    if (path === '/settings' && method === 'GET') return json(settings);
    if (path === '/settings' && method === 'PUT') { Object.assign(settings, req()); return json(settings); }
    if (path === '/engines/status') return json({
      claude: { available: !opts.claudeOut, detail: '已登录（订阅）', model: settings.chat_model_claude, reasoning: settings.chat_reasoning_claude },
      deepseek: { configured: true, model: settings.deepseek_model }, custom: { configured: false, model: null },
      chatgpt: { configured: gpt.state === 'authorized', authorized: gpt.state === 'authorized', authorization_state: gpt.state, model: gpt.model, reasoning: gpt.effort },
      chat_engine: settings.chat_engine, utility_engine: settings.utility_engine, utility_effective: settings.utility_engine === 'auto' ? 'claude' : settings.utility_engine,
      chat_fallback: settings.chat_fallback, current_engine: opts.degraded ? 'deepseek' : settings.chat_engine, degraded: Boolean(opts.degraded),
    });
    // 模型目录：读到什么显示什么；DeepSeek 的档位接口没声明（source=default），Claude 带 off
    hit = m(/^\/engines\/(\w+)\/models$/);
    if (hit) {
      const level = (ids) => ids.map((id) => ({ id, label: { off: '关闭', minimal: '最少', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' }[id] || id }));
      if (hit[1] === 'claude') return json({ models: [
        { id: 'sonnet', label: 'Claude Sonnet', reasoning: { levels: level(['off', 'low', 'medium', 'high', 'max']), default: 'off', source: 'api', selected: settings.chat_reasoning_claude } },
        { id: 'opus', label: 'Claude Opus', reasoning: { levels: level(['off', 'low', 'medium', 'high', 'xhigh', 'max']), default: 'off', source: 'api', selected: null } },
        { id: 'haiku', label: 'Claude Haiku', reasoning: { levels: level(['off']), default: 'off', source: 'api', selected: null } }] });
      if (hit[1] === 'deepseek') return json({ models: [
        { id: 'deepseek-chat', label: 'deepseek-chat', reasoning: { levels: level(['low', 'medium', 'high']), default: 'medium', source: 'default', selected: null } },
        { id: 'deepseek-reasoner', label: 'deepseek-reasoner', reasoning: { levels: level(['low', 'medium', 'high']), default: 'medium', source: 'default', selected: null } }] });
      if (hit[1] === 'chatgpt') {
        if (gpt.state !== 'authorized') return json({ detail: '请先连接 ChatGPT。' }, 502);
        return json({ models: [
          { id: 'gpt-5.5', label: 'GPT-5.5', reasoning: { levels: level(['minimal', 'low', 'medium', 'high']), default: 'medium', source: 'api', selected: gpt.effort } },
          { id: 'gpt-5.5-mini', label: 'GPT-5.5 mini', reasoning: { levels: level(['low', 'medium']), default: 'low', source: 'api', selected: null } }] });
      }
      return json({ detail: '请先保存这个服务的连接信息。' }, 502);
    }
    hit = m(/^\/engines\/(\w+)\/reasoning$/);
    if (hit && method === 'POST') {
      const r = req();
      if (hit[1] === 'claude') { settings.chat_model_claude = r.model; settings.chat_reasoning_claude = r.effort || 'off'; }
      if (hit[1] === 'chatgpt') { if (gpt.state !== 'authorized') return json({ detail: '请先连接 ChatGPT。' }, 409); gpt.model = r.model; gpt.effort = r.effort; }
      return json({ model: r.model, effort: r.effort });
    }
    // ChatGPT 账号（SIWC）
    if (path === '/workspace-agent/siwc/status') return json({ configured: gpt.state === 'authorized', authorization_state: gpt.state, selected_model: gpt.model, account_label: gpt.state === 'authorized' ? 'p-chan@example.com' : null, live_enabled: true });
    if (path === '/workspace-agent/siwc/login' && method === 'POST') { gpt.state = 'pending'; return json({ browser_url: 'http://127.0.0.1:45123/begin?ticket=' + 'a'.repeat(43), expires_in: 300 }); }
    if (path === '/workspace-agent/siwc/cancel') { gpt.state = 'required'; return json({ cancelled: true }); }
    if (path === '/workspace-agent/siwc/logout') { gpt.state = 'required'; gpt.model = null; return json({ signed_out: true }); }
    if (path === '/workspace-agent/siwc/test') return json({ ok: true, model: gpt.model, reply: 'OK' });

    // 课程管家：Claude / DeepSeek / ChatGPT 三家，默认跟主引擎
    if (path === '/workspace-agent/capabilities') return json({ version: 1, conversations: true, attachments: true, images: true, proposals: true, max_attachments: 4,
      providers: [
        { id: 'claude', label: 'Claude', configured: !opts.claudeOut, vision: true, model: settings.chat_model_claude, configuration_state: opts.claudeOut ? 'missing' : 'configured', availability_note: opts.claudeOut ? 'Claude 未登录：在终端运行 claude login' : '' },
        { id: 'deepseek', label: 'DeepSeek', configured: true, vision: false, model: settings.deepseek_model, configuration_state: 'configured', availability_note: '' },
        { id: 'chatgpt', label: 'ChatGPT', configured: gpt.state === 'authorized', vision: true, model: gpt.model, configuration_state: gpt.state === 'authorized' ? 'configured' : 'missing', availability_note: gpt.state === 'authorized' ? '' : '先在设置 › 模型与账号里登录 ChatGPT' },
      ],
      main_engine: settings.chat_engine, default_provider: settings.chat_engine === 'custom' ? null : settings.chat_engine,
      default_note: settings.chat_engine === 'custom' ? '主引擎是自定义端点，课程管家用不了，换一家' : '', available: !opts.claudeOut, image_input: true });
    if (path === '/workspace-agent/conversations' && method === 'POST') return json({ id: 'c2', title: '新对话' });
    if (path === '/workspace-agent/plan' && method === 'POST') return json({ reply: '好，我看看。', route: [], proposal: null, test_source: null });
    if (path === '/workspace-agent/conversations' && method === 'GET') return json({ conversations: [{ id: 'c1', title: '日语课程调整', updated_at: iso(1) }] });
    if (path === '/workspace-agent/proposals') return json({ proposals: [] });
    if (m(/^\/workspace-agent\/conversations\/[\w-]+$/)) return json({ messages: [], attachments: [] });
    if (path === '/workspace-agent/catalog') return json({ tools: [] });
    if (path === '/workspace-agent/inspect') return json({});

    if (method !== 'GET') return json({ ok: true });
    return null;
  }

  return { handle };
}

// 兼容旧用法：一份共用状态
export const handle = createMock().handle;
