"""SQLite 访问层。全项目唯一的连接入口。"""
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "langpal.db"
# 人设自定义头像的落地目录。放 data/ 下（和库同级）而不是 frontend/assets/：data/ 不进 git，
# 部署时解包代码不会覆盖/清空它，头像跟着数据走。
AVATAR_DIR = DATA_DIR / "avatars"
# 聊天图片消息的落地目录。同样放 data/ 下（不进 git，部署解包不会覆盖/清空它），
# 见 docs/history/API-v1.5-images.md。
UPLOAD_DIR = DATA_DIR / "uploads"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


def _migrate(conn: sqlite3.Connection) -> None:
    """`CREATE TABLE IF NOT EXISTS` 对已存在的表不会补列，新增字段走这里的幂等 ALTER TABLE
    （PRAGMA table_info 判断后再加，重复跑不出错）。"""
    persona_cols = {row[1] for row in conn.execute("PRAGMA table_info(personas)").fetchall()}
    if "avatar" not in persona_cols:
        # 自定义头像的文件名（存在 data/avatars/ 下；NULL = 没设过，前端回退首字母/情绪头像）
        conn.execute("ALTER TABLE personas ADD COLUMN avatar TEXT")
        conn.commit()
    if "archived_at" not in persona_cols:
        conn.execute("ALTER TABLE personas ADD COLUMN archived_at TEXT")
        conn.commit()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "language" not in cols:
        with conn:
            conn.execute("ALTER TABLE sessions ADD COLUMN language TEXT")
            conn.execute("UPDATE sessions SET language = (SELECT language FROM personas WHERE id = sessions.persona_id)")
    if "codex_thread_id" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN codex_thread_id TEXT")
        conn.commit()
    if "claude_session_id" not in cols:
        # Claude Agent SDK 的 CLI 会话 id：落库后跨后端重启用 options.resume 续接（对齐 codex 线程）
        conn.execute("ALTER TABLE sessions ADD COLUMN claude_session_id TEXT")
        conn.commit()
    # WP-M：message_embeddings 是全新表，schema.sql 的 CREATE TABLE IF NOT EXISTS 本身对老库
    # 已经幂等生效，这里再加一道双保险（照 codex_thread_id 的做法，统一走 _migrate 兜底）。
    conn.execute(
        "CREATE TABLE IF NOT EXISTS message_embeddings ("
        "message_id INTEGER PRIMARY KEY REFERENCES messages(id), "
        "model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL)"
    )
    conn.commit()
    msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "image_path" not in msg_cols:
        # WP-N：用户发的图片消息，文件名（存在 data/uploads/ 下）；NULL = 纯文字消息。
        conn.execute("ALTER TABLE messages ADD COLUMN image_path TEXT")
        conn.commit()
    with conn:
        if "persona_id" not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN persona_id INTEGER REFERENCES personas(id)")
        if "language" not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN language TEXT")
        if "read_at" not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN read_at TEXT")
    # 原生会话指针的轮换（docs/MAIN-CHAT.md 1.3）：记下每把指针的开始时间和跑过的轮数
    pointer_cols = {row[1] for row in conn.execute("PRAGMA table_info(session_pointers)").fetchall()}
    if pointer_cols:
        with conn:
            if "created_at" not in pointer_cols:
                conn.execute("ALTER TABLE session_pointers ADD COLUMN created_at TEXT")
            if "turns" not in pointer_cols:
                conn.execute("ALTER TABLE session_pointers ADD COLUMN turns INTEGER NOT NULL DEFAULT 0")
    # 主聊天：世界书状态和轮数改成按（对话, 人设）记。这两张表只存短期状态（粘性、冷却、轮数），
    # 旧形状直接重建，丢了只是当作新对话重新数。
    for table in ("lore_state", "chat_turns"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if cols and "persona_id" not in cols:
            with conn:
                conn.execute(f"DROP TABLE {table}")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
    book_cols = {row[1] for row in conn.execute("PRAGMA table_info(world_books)").fetchall()}
    with conn:
        if "scope" not in book_cols:
            conn.execute("ALTER TABLE world_books ADD COLUMN scope TEXT NOT NULL DEFAULT 'attached'")
        if "enabled" not in book_cols:
            conn.execute("ALTER TABLE world_books ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    reading_table = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reading_errors'"
    ).fetchone()
    if reading_table and "BETWEEN 0 AND 3" in reading_table[0]:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """CREATE TABLE reading_errors_v2 (
                    exercise_id TEXT NOT NULL REFERENCES reading_exercises(id),
                    item_index INTEGER NOT NULL,
                    selected INTEGER NOT NULL CHECK (selected BETWEEN 0 AND 4),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (exercise_id, item_index)
                )"""
            )
            conn.execute("INSERT INTO reading_errors_v2 SELECT exercise_id, item_index, selected, updated_at FROM reading_errors")
            conn.execute("DROP TABLE reading_errors")
            conn.execute("ALTER TABLE reading_errors_v2 RENAME TO reading_errors")
    _migrate_study_languages(conn)


def _migrate_study_languages(conn: sqlite3.Connection) -> None:
    """Remove the old two-language CHECK while keeping exercise IDs and child rows."""
    old_check = " CHECK (language IN ('en', 'ja'))"
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            for name in ("reading_exercises", "listening_error_sets"):
                sql, = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
                if old_check not in sql:
                    continue
                temporary = name + "_languages"
                conn.execute(sql.replace(name, temporary, 1).replace(old_check, "", 1))
                conn.execute(f"INSERT INTO {temporary} SELECT * FROM {name}")
                conn.execute(f"DROP TABLE {name}")
                conn.execute(f"ALTER TABLE {temporary} RENAME TO {name}")
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise sqlite3.IntegrityError("Study language migration failed foreign key verification")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    """建库建表，幂等。服务启动时调用。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        _migrate(conn)
        conn.row_factory = sqlite3.Row
        from .services import hooks, lore
        from .services import course

        with conn:
            conn.execute("BEGIN IMMEDIATE")
            course.ledger.ensure(conn)
            course.lesson.migrate(conn)
            # 人设里内嵌的旧世界书拆成共享书；version 1 的书原地升级成 version 2（都幂等）
            lore.migrate_legacy(conn)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            hooks.ensure_builtins(conn)
        from .services import chat_room

        with conn:
            conn.execute("BEGIN IMMEDIATE")
            # 主聊天：会话指针搬进 session_pointers、钉住主聊天会话、糖糖的口吻样本种子（都幂等）
            chat_room.migrate(conn)
        from .services.learning import store as learning_store

        with conn:
            conn.execute("BEGIN IMMEDIATE")
            # 统一复习：补 encounters 列，单词/句型/错题和旧复习记录迁成卡（幂等，不删旧表）
            learning_store.migrate(conn)
    finally:
        conn.close()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
