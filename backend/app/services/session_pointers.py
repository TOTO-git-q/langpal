"""每个人设在一段对话里的原生会话指针（Claude 的会话 id 等），存在 session_pointers 表。

主聊天里几个人设共用一段对话（同一个 session_id），但各有各的常驻会话，key 是 `p{人设}s{会话}`。
以前指针存在 sessions.claude_session_id（一段对话只有一个），主聊天里副人设会和主人设撞上；
现在按 (session_id, persona_id, engine) 各存一份。

    get(session_key, engine="claude") -> str | None
    set(session_key, pointer, engine="claude")      pointer 为 None / "" = 清掉
    clear(session_key=..., persona_id=..., session_id=..., engine=None)

迁移 migrate(conn)：sessions.claude_session_id 里原有的指针按会话的主人（sessions.persona_id）搬过来，幂等。

## 轮换（docs/MAIN-CHAT.md 1.3）

主聊天是永久的一条线，原生会话只增不减：resume 越来越慢，迟早撞上下文上限。所以每把指针记下
created_at（这段原生会话开始的时间）和 turns（上面完整跑过几轮；chat.py 每完整一轮调 count_turn）。
同一段原生会话里 CLI 换了新 id（resume 后会轮换）只更新 pointer，created_at / turns 不变；指针被清掉
（坏 id、换引擎、轮换）后下一把从头算。due_for_rotation：turns >= 60 或用满 7 天，并且这条时间线
最后一条消息已经过去 3 小时以上（安静的时候才换，用户察觉不到）。"""
from __future__ import annotations

import re
from contextlib import closing
from datetime import timedelta

from .. import db
from . import clock

ROTATE_TURNS = 60
ROTATE_AGE = timedelta(days=7)
ROTATE_QUIET = timedelta(hours=3)

_KEY = re.compile(r"^p(\d+)s(\d+)$")


def parse(session_key: str) -> tuple[int, int] | None:
    """`p5s19` -> (persona_id 5, session_id 19)；不是这种形状返回 None。"""
    match = _KEY.match(session_key or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def get(session_key: str, engine: str = "claude") -> str | None:
    parts = parse(session_key)
    if parts is None:
        return None
    persona_id, session_id = parts
    with closing(db.get_conn()) as conn:
        row = conn.execute("SELECT pointer FROM session_pointers WHERE session_id = ? AND persona_id = ? AND engine = ?",
                           (session_id, persona_id, engine)).fetchone()
    return row[0] if row else None


def set(session_key: str, pointer: str | None, engine: str = "claude") -> None:  # noqa: A001 - 约定的接口名
    parts = parse(session_key)
    if parts is None:
        return
    persona_id, session_id = parts
    with closing(db.get_conn()) as conn:
        if pointer:
            # 同一段原生会话里换了 id：只更新 pointer，开始时间和轮数照旧
            conn.execute("""INSERT INTO session_pointers (session_id, persona_id, engine, pointer, created_at, turns)
                            VALUES (?, ?, ?, ?, ?, 0) ON CONFLICT(session_id, persona_id, engine)
                            DO UPDATE SET pointer = excluded.pointer""",
                         (session_id, persona_id, engine, str(pointer), clock.stamp()))
        else:
            conn.execute("DELETE FROM session_pointers WHERE session_id = ? AND persona_id = ? AND engine = ?",
                         (session_id, persona_id, engine))
        conn.commit()


def clear(session_key: str | None = None, *, persona_id: int | None = None, session_id: int | None = None,
          engine: str | None = None) -> int:
    """按 key、或按人设、或按会话清指针（可再限定引擎）；什么都不给 = 清全部。返回清掉几条。"""
    where, args = [], []
    if session_key is not None:
        parts = parse(session_key)
        if parts is None:
            return 0
        persona_id, session_id = parts
    if persona_id is not None:
        where.append("persona_id = ?")
        args.append(persona_id)
    if session_id is not None:
        where.append("session_id = ?")
        args.append(session_id)
    if engine is not None:
        where.append("engine = ?")
        args.append(engine)
    sql = "DELETE FROM session_pointers" + (" WHERE " + " AND ".join(where) if where else "")
    with closing(db.get_conn()) as conn:
        count = conn.execute(sql, args).rowcount
        conn.commit()
    return count


def info(session_key: str, engine: str = "claude") -> dict | None:
    parts = parse(session_key)
    if parts is None:
        return None
    persona_id, session_id = parts
    with closing(db.get_conn()) as conn:
        row = conn.execute("SELECT pointer, created_at, turns FROM session_pointers WHERE session_id = ? "
                           "AND persona_id = ? AND engine = ?", (session_id, persona_id, engine)).fetchone()
    return {"pointer": row[0], "created_at": row[1], "turns": row[2]} if row else None


def count_turn(session_key: str, engine: str = "claude") -> None:
    """这把原生会话上完整跑完了一轮（没有指针就什么都不做）。"""
    parts = parse(session_key)
    if parts is None:
        return
    persona_id, session_id = parts
    with closing(db.get_conn()) as conn:
        conn.execute("UPDATE session_pointers SET turns = turns + 1 WHERE session_id = ? AND persona_id = ? "
                     "AND engine = ?", (session_id, persona_id, engine))
        conn.commit()


def due_for_rotation(session_key: str, engine: str = "claude", *, before_message_id: int | None = None) -> dict | None:
    """该换一段新的原生会话了吗？是 → 返回指针信息（附 age_days），否 → None。
    before_message_id：算"最后一条消息"时不看这条及以后的（这一轮刚发来的那批不算打破安静）。"""
    current = info(session_key, engine)
    if current is None:
        return None
    now = clock.now()
    started = clock.parse(current["created_at"]) or now
    if current["turns"] < ROTATE_TURNS and now - started < ROTATE_AGE:
        return None
    _, session_id = parse(session_key)
    with closing(db.get_conn()) as conn:
        row = conn.execute("SELECT max(created_at) FROM messages WHERE session_id = ? AND (? IS NULL OR id < ?)",
                           (session_id, before_message_id, before_message_id)).fetchone()
    last = clock.parse(row[0]) if row else None
    if last is not None and now - last < ROTATE_QUIET:
        return None
    return {**current, "age_days": round((now - started).total_seconds() / 86400, 1)}


def migrate(conn) -> None:
    """sessions.claude_session_id → session_pointers（按会话的主人算），已有的不覆盖；没有开始时间的旧行记成现在。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "claude_session_id" in cols:
        conn.execute("""INSERT OR IGNORE INTO session_pointers (session_id, persona_id, engine, pointer, created_at, turns)
                        SELECT id, persona_id, 'claude', claude_session_id, ?, 0 FROM sessions
                        WHERE claude_session_id IS NOT NULL AND claude_session_id != ''""", (clock.stamp(),))
    conn.execute("UPDATE session_pointers SET created_at = ? WHERE created_at IS NULL", (clock.stamp(),))
