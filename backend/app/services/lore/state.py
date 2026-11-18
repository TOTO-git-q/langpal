"""按（对话, 人设）记的轮数和条目状态（粘性、冷却、上次激活在第几轮）。

主聊天里几个人设共用一段对话，但各有各的常驻会话，所以轮数和世界书状态各记各的。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EntryState:
    sticky_until: int = -1
    cooldown_until: int = -1
    activations: int = 0
    last_turn: int = -1


def current_turn(conn, session_id: int | None, persona_id: int = 0) -> int:
    if session_id is None:
        return 0
    row = conn.execute("SELECT turn FROM chat_turns WHERE session_id = ? AND persona_id = ?",
                       (session_id, persona_id)).fetchone()
    return row[0] if row else 0


def next_turn(conn, session_id: int, persona_id: int = 0) -> int:
    conn.execute("INSERT INTO chat_turns (session_id, persona_id, turn) VALUES (?, ?, 1) "
                 "ON CONFLICT(session_id, persona_id) DO UPDATE SET turn = turn + 1", (session_id, persona_id))
    return current_turn(conn, session_id, persona_id)


def set_mood(conn, session_id: int, persona_id: int, mood: str | None) -> None:
    conn.execute("INSERT INTO chat_turns (session_id, persona_id, turn, last_mood) VALUES (?, ?, 0, ?) "
                 "ON CONFLICT(session_id, persona_id) DO UPDATE SET last_mood = excluded.last_mood",
                 (session_id, persona_id, mood))


def load(conn, session_id: int | None, persona_id: int = 0) -> dict[tuple[int, int], EntryState]:
    if session_id is None:
        return {}
    return {(row[0], row[1]): EntryState(row[2], row[3], row[4], row[5]) for row in conn.execute(
        "SELECT book_id, uid, sticky_until, cooldown_until, activations, last_turn FROM lore_state "
        "WHERE session_id = ? AND persona_id = ?", (session_id, persona_id))}


def save(conn, session_id: int, persona_id: int, updates: dict[tuple[int, int], EntryState]) -> None:
    conn.executemany(
        """INSERT INTO lore_state (session_id, persona_id, book_id, uid, sticky_until, cooldown_until, activations,
                                   last_turn)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id, persona_id, book_id, uid) DO UPDATE SET sticky_until = excluded.sticky_until,
             cooldown_until = excluded.cooldown_until, activations = excluded.activations,
             last_turn = excluded.last_turn""",
        [(session_id, persona_id, book_id, uid, s.sticky_until, s.cooldown_until, s.activations, s.last_turn)
         for (book_id, uid), s in updates.items()])
