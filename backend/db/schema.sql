-- LangPal SQLite schema (v1 建表即含 v2 字段，避免迁移)
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS personas (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    language    TEXT NOT NULL CHECK (language IN ('ja', 'en', 'de')),
    profile_json TEXT NOT NULL DEFAULT '{}',
    avatar      TEXT,   -- 自定义头像文件名（data/avatars/ 下）；NULL = 用首字母/情绪头像
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    persona_id  INTEGER NOT NULL REFERENCES personas(id),
    language    TEXT,
    started_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ended_at    TEXT,
    summary     TEXT,
    codex_thread_id TEXT,   -- codex 引擎的 app-server 线程 id（跨进程重启靠它 thread/resume）
    claude_session_id TEXT  -- Claude Agent SDK 的 CLI 会话 id（跨进程重启靠它 resume）
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    persona_id  INTEGER REFERENCES personas(id),
    language    TEXT,
    content     TEXT NOT NULL,
    tokens_json TEXT,               -- 分词结果，前端渲染依据；user 消息为 NULL
    guard_flag  INTEGER NOT NULL DEFAULT 0,  -- 语言守门二次失败标记
    image_path  TEXT,               -- WP-N：用户发的图片文件名（data/uploads/ 下）；NULL=纯文字
    read_at     TEXT,               -- 主聊天：用户消息被读到（她开始生成）的时间
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

-- 世界书（docs/LORE-AND-HOOKS.md）。book_json 是 version 2；scope = global（对所有联系人生效）
-- / attached（挂在人设资料 world_book_ids 上才生效）。老库的这两列由 db._migrate 补。
CREATE TABLE IF NOT EXISTS world_books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    book_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'attached',
    enabled INTEGER NOT NULL DEFAULT 1
);

-- 世界书条目的粘性/冷却，按（对话, 人设）记轮数：主聊天里每个人设各有一份。
CREATE TABLE IF NOT EXISTS lore_state (
    session_id     INTEGER NOT NULL,
    persona_id     INTEGER NOT NULL DEFAULT 0,
    book_id        INTEGER NOT NULL,
    uid            INTEGER NOT NULL,
    sticky_until   INTEGER NOT NULL DEFAULT -1,
    cooldown_until INTEGER NOT NULL DEFAULT -1,
    activations    INTEGER NOT NULL DEFAULT 0,
    last_turn      INTEGER NOT NULL DEFAULT -1,
    PRIMARY KEY (session_id, persona_id, book_id, uid)
);

-- 每个人设在一段对话里生成了第几轮（用户消息、她主动发、插话都算一轮）+ 她上一条回复的情绪。
CREATE TABLE IF NOT EXISTS chat_turns (
    session_id INTEGER NOT NULL,
    persona_id INTEGER NOT NULL DEFAULT 0,
    turn       INTEGER NOT NULL DEFAULT 0,
    last_mood  TEXT,
    PRIMARY KEY (session_id, persona_id)
);

-- 主聊天（docs/MAIN-CHAT.md）：每个人设各自的原生会话指针（Claude 的会话 id 等）。
CREATE TABLE IF NOT EXISTS session_pointers (
    session_id INTEGER NOT NULL,
    persona_id INTEGER NOT NULL,
    engine     TEXT NOT NULL,
    pointer    TEXT NOT NULL,
    created_at TEXT,                       -- 这把原生会话开始的时间（轮换用）
    turns      INTEGER NOT NULL DEFAULT 0, -- 这把原生会话上完整跑过几轮（轮换用）
    PRIMARY KEY (session_id, persona_id, engine)
);

-- 主聊天：这个人设看到哪条消息了（算每轮开头的补课块）。
CREATE TABLE IF NOT EXISTS chat_seen (
    session_id      INTEGER NOT NULL,
    persona_id      INTEGER NOT NULL,
    last_message_id INTEGER NOT NULL,
    PRIMARY KEY (session_id, persona_id)
);

-- 只跑一次的数据迁移的记号（比如往糖糖的人设卡里写口吻样本种子）。
CREATE TABLE IF NOT EXISTS chat_migrations (
    name    TEXT PRIMARY KEY,
    done_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 语义触发用的向量缓存（世界书条目、生词），按 (模型, 文本) 哈希。
CREATE TABLE IF NOT EXISTS lore_vectors (
    hash TEXT PRIMARY KEY,
    dim  INTEGER NOT NULL,
    vec  BLOB NOT NULL
);

-- 事件 hook。rule_json 是整条规则；builtin 是自带规则的键（用户规则为 NULL）。
CREATE TABLE IF NOT EXISTS hook_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    rule_json  TEXT NOT NULL,
    builtin    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hook_rules_builtin ON hook_rules(builtin) WHERE builtin IS NOT NULL;

CREATE TABLE IF NOT EXISTS hook_vars (
    scope      TEXT NOT NULL CHECK (scope IN ('persona', 'global')),
    persona_id INTEGER NOT NULL DEFAULT 0,
    name       TEXT NOT NULL,
    value      TEXT NOT NULL,
    PRIMARY KEY (scope, persona_id, name)
);

-- 待发的 say，和还没用完的 inject / activate_entry / deactivate_entry。
CREATE TABLE IF NOT EXISTS hook_queue (
    id           INTEGER PRIMARY KEY,
    persona_id   INTEGER NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('say', 'inject', 'activate_entry', 'deactivate_entry')),
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    consumed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_hook_queue_pending ON hook_queue(persona_id, kind, consumed_at);

-- 触发日志，只留最近 500 条。
CREATE TABLE IF NOT EXISTS hook_log (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    rule_id     INTEGER,
    event       TEXT NOT NULL,
    persona_id  INTEGER,
    detail_json TEXT NOT NULL
);

-- 每条规则在每个联系人上最近一次生效的时间/轮数/日期/启动批次（冷却和 once_per 用）。
CREATE TABLE IF NOT EXISTS hook_rule_state (
    rule_id      INTEGER NOT NULL,
    persona_id   INTEGER NOT NULL,
    last_at      TEXT,
    last_turn    INTEGER,
    last_day     TEXT,
    last_session TEXT,
    PRIMARY KEY (rule_id, persona_id)
);

CREATE TABLE IF NOT EXISTS teaching_evidence (
    persona_id INTEGER NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    outline_key TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    PRIMARY KEY (persona_id, outline_key, unit_id, evidence_key),
    UNIQUE (persona_id, outline_key, user_id)
);

CREATE TABLE IF NOT EXISTS memory_items (
    id          INTEGER PRIMARY KEY,
    persona_id  INTEGER REFERENCES personas(id),
    category    TEXT NOT NULL DEFAULT 'fact',   -- fact / preference / event / promise
    content     TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    source_session_id INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS vocab_entries (
    id          INTEGER PRIMARY KEY,
    language    TEXT NOT NULL,
    lemma       TEXT NOT NULL,
    surface     TEXT,
    reading     TEXT,               -- 仅日语（假名）；英/德为 NULL
    meaning     TEXT,
    pos         TEXT,
    context_sentence TEXT,          -- 收藏时原句，必存
    source_message_id INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    -- SRS（M6 启用）
    due_at      TEXT,
    interval_days REAL NOT NULL DEFAULT 0,
    ease        REAL NOT NULL DEFAULT 2.5,
    reps        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (language, lemma)
);
CREATE INDEX IF NOT EXISTS idx_vocab_lang ON vocab_entries(language);

CREATE TABLE IF NOT EXISTS pattern_entries (
    id          INTEGER PRIMARY KEY,
    language    TEXT NOT NULL,
    pattern_name TEXT NOT NULL,
    explanation TEXT,
    example_sentence TEXT,
    translation TEXT,
    source_message_id INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    -- SRS（M6 启用）
    due_at      TEXT,
    interval_days REAL NOT NULL DEFAULT 0,
    ease        REAL NOT NULL DEFAULT 2.5,
    reps        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pattern_lang ON pattern_entries(language);

CREATE TABLE IF NOT EXISTS explain_cache (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('word', 'sentence')),
    cache_key   TEXT NOT NULL UNIQUE,   -- word: lemma + 句子hash；sentence: 句子hash
    payload_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS reading_exercises (
    id           TEXT PRIMARY KEY,
    language     TEXT NOT NULL,
    title        TEXT NOT NULL,
    source_url   TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reading_errors (
    exercise_id TEXT NOT NULL REFERENCES reading_exercises(id),
    item_index  INTEGER NOT NULL,
    selected    INTEGER NOT NULL CHECK (selected BETWEEN 0 AND 4),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (exercise_id, item_index)
);

CREATE TABLE IF NOT EXISTS listening_error_sets (
    id       TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    title    TEXT NOT NULL,
    audio    BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS listening_errors (
    practice_id  TEXT NOT NULL REFERENCES listening_error_sets(id),
    item_index   INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (practice_id, item_index)
);

-- WP-M：消息级嵌入向量缓存（回忆 RAG 用）。model/dim 如实记录当次写入时用的模型
-- （切换模型后旧向量维度不同，recall() 靠 dim>0 过滤、不校验 model 是否一致——本项目
-- 单模型场景下不值得做多模型并存的复杂度；vector 是 float32 的原始字节，dim=0/model='skip'
-- 是"这条消息不需要嵌入"（贴纸/空文本）的哨兵行，用来让 backfill 幂等终止，不是真的向量。
CREATE TABLE IF NOT EXISTS message_embeddings (
    message_id  INTEGER PRIMARY KEY REFERENCES messages(id),
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY,
    persona_id  INTEGER REFERENCES personas(id),
    due_at      TEXT NOT NULL,
    what        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('explain_language', 'zh'),
    ('engine', 'agent_sdk'),
    ('degraded', '0'),
    ('websearch_enabled', '0'),
    -- v1.3 引擎设置（见 docs/API-v1.3-engines.md）。密钥类（deepseek_api_key/
    -- custom_api_key）不在这里预置——不存在即"未设置"，GET /api/settings 返回 null。
    ('chat_engine', 'claude'),
    ('chat_model_claude', 'sonnet'),
    ('chat_reasoning_claude', 'off'),
    ('chat_model_codex', ''),
    ('chat_reasoning_codex', 'medium'),
    ('deepseek_model', 'deepseek-chat'),
    ('custom_base_url', ''),
    ('custom_model', '');

-- 预置三个人设（日英德各一）。
-- 只在"库里一个人设都没有"（= 全新的库）时种。这个文件每次服务启动都会被 executescript
-- 跑一遍，原先写的是 INSERT OR IGNORE —— 那样用户在界面里删掉某个预置人设之后，下一次
-- 重启又会把 TA 原样种回来（删除看起来"没生效"）。用 WHERE NOT EXISTS 包住整批，既保证
-- 首次建库有内容，又不会复活用户主动删掉的人。
INSERT INTO personas (id, name, language, profile_json)
SELECT * FROM (
    SELECT 1 AS id, '雪菜' AS name, 'ja' AS language,
           '{"relation":"朋友","tone":"轻松","keigo":"平辈","interests":["读书","散步","美食"],"free_text":"大学时代认识的好友，说话直接但温柔，喜欢分享日常。"}' AS profile_json
    UNION ALL SELECT 2, 'Emma', 'en',
           '{"relation":"friend","tone":"casual","interests":["movies","travel"],"free_text":"An easygoing friend who loves small talk and asks good questions."}'
    UNION ALL SELECT 3, 'Lena', 'de',
           '{"relation":"Freundin","tone":"locker","interests":["Musik","Kochen"],"free_text":"Eine entspannte Freundin, die gern ueber Alltag und Kultur plaudert."}'
)
WHERE NOT EXISTS (SELECT 1 FROM personas);

-- Review attempts are separate from original mistakes; no mastery claims.
CREATE TABLE IF NOT EXISTS review_states (
    kind TEXT NOT NULL CHECK (kind IN ('reading','listening')),
    item_id TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    independent_correct_count INTEGER NOT NULL DEFAULT 0,
    stage INTEGER NOT NULL DEFAULT 0 CHECK (stage BETWEEN 0 AND 5),
    due_at TEXT,
    last_outcome TEXT,
    last_attempt_at TEXT,
    last_exposure_day TEXT,
    PRIMARY KEY (kind,item_id,item_index)
);
CREATE TABLE IF NOT EXISTS review_attempts (
    attempt_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_attempt_item_day
ON review_attempts(kind,item_id,item_index,created_at);

-- Versioned generated listening snapshots, retained until explicit user management.
-- First submission is a practice receipt, never a proficiency/mastery assessment.
CREATE TABLE IF NOT EXISTS listening_sessions (
    id TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    version INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    audio BLOB NOT NULL,
    reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes >= 0),
    created_at TEXT NOT NULL,
    graded_at TEXT,
    receipt_json TEXT,
    CHECK ((graded_at IS NULL) = (receipt_json IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_listening_sessions_recent ON listening_sessions(language, created_at DESC);
CREATE TRIGGER IF NOT EXISTS listening_first_receipt_immutable
BEFORE UPDATE OF receipt_json, graded_at ON listening_sessions
WHEN OLD.receipt_json IS NOT NULL AND
     (NEW.receipt_json IS NOT OLD.receipt_json OR NEW.graded_at IS NOT OLD.graded_at)
BEGIN
    SELECT RAISE(ABORT, 'First listening submission is immutable');
END;

-- Canonical study workspace; PDF bytes travel with SQLite backups.
CREATE TABLE IF NOT EXISTS study_documents (
    id TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,
    file BLOB,
    revision INTEGER NOT NULL CHECK (revision > 0)
);
CREATE TABLE IF NOT EXISTS study_annotations (
    document_id TEXT NOT NULL REFERENCES study_documents(id),
    id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0,1)),
    PRIMARY KEY (document_id, id)
);
CREATE TABLE IF NOT EXISTS study_state (
    kind TEXT NOT NULL CHECK (kind IN ('listening-notes','listening-draft')),
    id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    PRIMARY KEY (kind, id)
);

-- Local Agent history. Attachment bytes/text live only in study_documents.
CREATE TABLE IF NOT EXISTS workspace_conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES workspace_conversations(id),
    request_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','succeeded','failed')),
    attachment_ids_json TEXT NOT NULL,
    result_json TEXT,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (conversation_id,request_id,role)
);
CREATE INDEX IF NOT EXISTS idx_workspace_messages_conversation ON workspace_messages(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS workspace_attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES workspace_conversations(id),
    document_id TEXT NOT NULL REFERENCES study_documents(id),
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    provenance TEXT NOT NULL,
    text_chars INTEGER NOT NULL,
    truncated INTEGER NOT NULL CHECK (truncated IN (0,1)),
    no_text INTEGER NOT NULL CHECK (no_text IN (0,1)),
    document_digest TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Image attachments are not PDF study files; full SQLite backups include these bytes.
CREATE TABLE IF NOT EXISTS workspace_attachment_images (
    attachment_id TEXT PRIMARY KEY REFERENCES workspace_attachments(id),
    data BLOB NOT NULL,
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    sha256 TEXT NOT NULL
);

-- Durable reviewed changes. Executable code is never serialized.
CREATE TABLE IF NOT EXISTS workspace_proposals (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('pending','applied','undone','expired')),
    last_status TEXT,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_proposals_recent ON workspace_proposals(created_at DESC);

-- New rubric evidence never replaces legacy course records.
CREATE TABLE IF NOT EXISTS teaching_observations (
    id TEXT PRIMARY KEY, outline_key TEXT NOT NULL, course_key TEXT NOT NULL, language TEXT NOT NULL,
    modality TEXT NOT NULL CHECK (modality IN ('typed','spoken')),
    source TEXT NOT NULL CHECK (source IN ('chat','speaking')),
    assessable INTEGER NOT NULL CHECK (assessable IN (0,1)),
    observation_json TEXT NOT NULL, evaluation_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_teaching_observations_course ON teaching_observations(course_key,modality,assessable);
CREATE TABLE IF NOT EXISTS teaching_mastery (
    course_key TEXT NOT NULL, unit_id TEXT NOT NULL, knowledge_id TEXT NOT NULL, point_key TEXT NOT NULL,
    modality TEXT NOT NULL CHECK (modality IN ('typed','spoken')),
    state_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (course_key,unit_id,knowledge_id,modality,point_key)
);

-- 学习这一侧（docs/LEARNING.md 第二、四节）。所有卡一个队列，统计只从记录算。
CREATE TABLE IF NOT EXISTS review_cards (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('vocab','vocab_produce','pattern','reading_q','listening_q')),
    language TEXT NOT NULL,
    ref_table TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'new' CHECK (state IN ('new','learning','review','relearning')),
    stability REAL,
    difficulty REAL,
    due_at TEXT,
    last_review_at TEXT,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    suspended INTEGER NOT NULL DEFAULT 0 CHECK (suspended IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    revealed_at TEXT,
    reveal_peeked INTEGER NOT NULL DEFAULT 0,
    reveal_answer TEXT,
    UNIQUE (kind, ref_table, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_review_cards_due ON review_cards(language, suspended, due_at);
CREATE TABLE IF NOT EXISTS review_log (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES review_cards(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    elapsed_days REAL,
    stability_before REAL,
    stability_after REAL,
    retrievability REAL,
    answer_ms INTEGER,
    peeked INTEGER NOT NULL DEFAULT 0,
    request_id TEXT UNIQUE,
    was_due INTEGER NOT NULL DEFAULT 0,   -- 1 = 到期后的复习（算保持率用）
    weak INTEGER NOT NULL DEFAULT 0       -- 1 = 聊天里用对，算较弱的证据
);
CREATE INDEX IF NOT EXISTS idx_review_log_card ON review_log(card_id, at);
CREATE TABLE IF NOT EXISTS vocab_contexts (
    id INTEGER PRIMARY KEY,
    vocab_id INTEGER NOT NULL REFERENCES vocab_entries(id) ON DELETE CASCADE,
    sentence TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'chat',
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (vocab_id, sentence)
);
CREATE TABLE IF NOT EXISTS study_events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    language TEXT,
    kind TEXT NOT NULL,
    ref TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_study_events ON study_events(language, kind, at);

CREATE TABLE IF NOT EXISTS course_events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    language TEXT NOT NULL,
    course_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    point_id TEXT NOT NULL,
    point_key TEXT NOT NULL,
    channel TEXT NOT NULL,
    ref TEXT NOT NULL,
    result TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (language, course_id, channel, ref, unit_id, point_id)
);
CREATE TABLE IF NOT EXISTS course_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    course_id TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    card INTEGER NOT NULL DEFAULT 0,
    log_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT
);
CREATE TABLE IF NOT EXISTS course_generated (
    id INTEGER PRIMARY KEY,
    language TEXT NOT NULL, course_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    topic TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE (language, course_id, lesson_id, item_id)
);
