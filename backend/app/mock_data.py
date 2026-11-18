"""M0 罐头数据。所有形状与 docs/history/API.md 契约一致，M1 起被真实服务逐步替换。"""

PERSONAS = [
    {
        "id": 1, "name": "雪菜", "language": "ja",
        "profile": {
            "relation": "朋友", "tone": "轻松", "keigo": "平辈",
            "interests": ["读书", "散步", "美食"],
            "free_text": "大学时代认识的好友，说话直接但温柔，喜欢分享日常。",
        },
    },
    {
        "id": 2, "name": "Emma", "language": "en",
        "profile": {
            "relation": "friend", "tone": "casual",
            "interests": ["movies", "travel"],
            "free_text": "An easygoing friend who loves small talk and asks good questions.",
        },
    },
    {
        "id": 3, "name": "Lena", "language": "de",
        "profile": {
            "relation": "Freundin", "tone": "locker",
            "interests": ["Musik", "Kochen"],
            "free_text": "Eine entspannte Freundin, die gern über Alltag und Kultur plaudert.",
        },
    },
]

# 罐头回复（日语），SSE 分片下发
MOCK_REPLY = "おかえり！今日はどんな一日だった？最近読んだ本の話、聞かせてよ。"

# 手工分词结果——真实实现由 SudachiPy 产出同形状数据
# collected=True 的 token 前端渲染为「已收藏」淡色高亮
MOCK_TOKENS = [
    {"i": 0,  "surface": "おかえり", "lemma": "お帰り",  "reading": "おかえり", "pos": "感動詞", "clickable": True,  "collected": False},
    {"i": 1,  "surface": "！",       "lemma": "！",      "reading": "",         "pos": "補助記号", "clickable": False, "collected": False},
    {"i": 2,  "surface": "今日",     "lemma": "今日",    "reading": "きょう",   "pos": "名詞",   "clickable": True,  "collected": False},
    {"i": 3,  "surface": "は",       "lemma": "は",      "reading": "は",       "pos": "助詞",   "clickable": True,  "collected": False},
    {"i": 4,  "surface": "どんな",   "lemma": "どんな",  "reading": "どんな",   "pos": "連体詞", "clickable": True,  "collected": False},
    {"i": 5,  "surface": "一日",     "lemma": "一日",    "reading": "いちにち", "pos": "名詞",   "clickable": True,  "collected": True},
    {"i": 6,  "surface": "だっ",     "lemma": "だ",      "reading": "だっ",     "pos": "助動詞", "clickable": True,  "collected": False},
    {"i": 7,  "surface": "た",       "lemma": "た",      "reading": "た",       "pos": "助動詞", "clickable": True,  "collected": False},
    {"i": 8,  "surface": "？",       "lemma": "？",      "reading": "",         "pos": "補助記号", "clickable": False, "collected": False},
    {"i": 9,  "surface": "最近",     "lemma": "最近",    "reading": "さいきん", "pos": "名詞",   "clickable": True,  "collected": False},
    {"i": 10, "surface": "読ん",     "lemma": "読む",    "reading": "よん",     "pos": "動詞",   "clickable": True,  "collected": False},
    {"i": 11, "surface": "だ",       "lemma": "だ",      "reading": "だ",       "pos": "助動詞", "clickable": True,  "collected": False},
    {"i": 12, "surface": "本",       "lemma": "本",      "reading": "ほん",     "pos": "名詞",   "clickable": True,  "collected": False},
    {"i": 13, "surface": "の",       "lemma": "の",      "reading": "の",       "pos": "助詞",   "clickable": True,  "collected": False},
    {"i": 14, "surface": "話",       "lemma": "話",      "reading": "はなし",   "pos": "名詞",   "clickable": True,  "collected": False},
    {"i": 15, "surface": "、",       "lemma": "、",      "reading": "",         "pos": "補助記号", "clickable": False, "collected": False},
    {"i": 16, "surface": "聞か",     "lemma": "聞く",    "reading": "きか",     "pos": "動詞",   "clickable": True,  "collected": False},
    {"i": 17, "surface": "せ",       "lemma": "せる",    "reading": "せ",       "pos": "助動詞", "clickable": True,  "collected": False},
    {"i": 18, "surface": "て",       "lemma": "て",      "reading": "て",       "pos": "助詞",   "clickable": True,  "collected": False},
    {"i": 19, "surface": "よ",       "lemma": "よ",      "reading": "よ",       "pos": "助詞",   "clickable": True,  "collected": False},
    {"i": 20, "surface": "。",       "lemma": "。",      "reading": "",         "pos": "補助記号", "clickable": False, "collected": False},
]

MOCK_WORD_CARD = {
    "lemma": "一日",
    "surface": "一日",
    "reading": "いちにち",
    "pos": "名詞",
    "meaning_zh": "一天；一整天",
    "usage_in_context": "「どんな一日だった？」问的是「今天过得怎么样」，指从早到晚这一整天的经历。",
    "register_note": "通用，口语书面均可",
    "grammar_note": "读音随语境变化：ついたち＝每月 1 号；いちにち＝一天的时间长度",
    "cached": True,
}

MOCK_SENTENCE_ANALYSIS = {
    "translation_zh": "欢迎回来！今天过得怎么样？最近读的书，说给我听听吧。",
    "chunks": [
        {"text": "おかえり！", "role": "感叹句", "note": "「お帰りなさい」的省略形，对回家的人打招呼"},
        {"text": "今日は", "role": "主题", "note": "「は」标记谈论主题"},
        {"text": "どんな一日だった？", "role": "谓语（疑问）", "note": "「だった」是「だ」的过去形"},
        {"text": "最近読んだ本の", "role": "连体修饰", "note": "动词过去形直接修饰名词「本」"},
        {"text": "話、", "role": "宾语", "note": "口语中省略了助词「を」"},
        {"text": "聞かせてよ", "role": "谓语（请求）", "note": "使役＋て形表请求"},
    ],
    "grammar_points": [
        {
            "pattern": "〜（さ）せて（ください/よ）",
            "explanation_zh": "使役形＋て形，表示「让我……吧」的请求。「聞かせて」＝说给我听（让我听）。",
            "example": "その話、聞かせてよ。",
        },
        {
            "pattern": "连体修饰（动词短语修饰名词）",
            "explanation_zh": "动词普通形（含过去形）可直接放在名词前作定语，无需关系代词。",
            "example": "最近読んだ本",
        },
    ],
    "cached": False,
}

MOCK_VOCAB = [
    {
        "id": 1, "language": "ja", "lemma": "一日", "surface": "一日",
        "reading": "いちにち", "meaning": "一天；一整天", "pos": "名詞",
        "context_sentence": "今日はどんな一日だった？",
        "source_message_id": 2, "created_at": "2026-08-24 10:00:00",
    },
    {
        "id": 2, "language": "en", "lemma": "serendipity", "surface": "serendipity",
        "reading": None, "meaning": "机缘巧合；意外发现珍宝的运气", "pos": "noun",
        "context_sentence": "Finding that café was pure serendipity.",
        "source_message_id": 5, "created_at": "2026-08-23 21:12:00",
    },
    {
        "id": 3, "language": "de", "lemma": "Feierabend", "surface": "Feierabend",
        "reading": None, "meaning": "下班后的闲暇时光", "pos": "Substantiv (der, -e)",
        "context_sentence": "Was machst du heute nach Feierabend?",
        "source_message_id": 8, "created_at": "2026-08-23 19:30:00",
    },
]

MOCK_PATTERNS = [
    {
        "id": 1, "language": "ja", "pattern_name": "〜（さ）せて（ください/よ）",
        "explanation": "使役形＋て形，表示「让我……吧」的请求。",
        "example_sentence": "その話、聞かせてよ。",
        "translation": "那件事，说给我听听吧。",
        "source_message_id": 2, "created_at": "2026-08-24 10:01:00",
    },
]

MOCK_MEMORY = [
    {"id": 1, "persona_id": 1, "category": "fact", "content": "在大阪读书，研究方向和医学统计相关", "active": True, "created_at": "2026-08-20 22:00:00"},
    {"id": 2, "persona_id": 1, "category": "preference", "content": "喜欢在晚上聊天，话题偏日常与读书", "active": True, "created_at": "2026-08-21 23:10:00"},
    {"id": 3, "persona_id": 1, "category": "promise", "content": "答应过下次聊《雪国》的读后感", "active": True, "created_at": "2026-08-23 22:40:00"},
]

MOCK_SESSIONS = [
    {"id": 1, "persona_id": 1, "started_at": "2026-08-24 09:58:00", "ended_at": None, "summary": None},
]

MOCK_MESSAGES = [
    {"id": 1, "session_id": 1, "role": "user", "content": "ただいま！", "tokens": None, "guard_flag": False, "created_at": "2026-08-24 09:59:00"},
    {"id": 2, "session_id": 1, "role": "assistant", "content": MOCK_REPLY, "tokens": MOCK_TOKENS, "guard_flag": False, "created_at": "2026-08-24 09:59:05"},
]

MOCK_SETTINGS = {
    "explain_language": "zh",
    "engine": "agent_sdk",
    "degraded": False,
    "websearch_enabled": False,
}
