"""hook_queue：待发的 say，和还没用完的 inject / activate_entry / deactivate_entry。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

from .. import clock
from .model import QUEUE_HOURS


def enqueue(conn, persona_id: int, kind: str, payload: dict) -> int:
    now = clock.now()
    return conn.execute(
        "INSERT INTO hook_queue (persona_id, kind, payload_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (persona_id, kind, json.dumps(payload, ensure_ascii=False), clock.stamp(now),
         clock.stamp(now + timedelta(hours=QUEUE_HOURS)))).lastrowid


def pending(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT q.persona_id, count(*) FROM hook_queue q JOIN personas p ON p.id = q.persona_id
           WHERE q.kind = 'say' AND q.consumed_at IS NULL AND q.expires_at > ? AND p.archived_at IS NULL
           GROUP BY q.persona_id ORDER BY q.persona_id""", (clock.stamp(),)).fetchall()
    return [{"persona_id": row[0], "count": row[1]} for row in rows]


def says_today(conn, persona_id: int) -> tuple[int, str | None]:
    """(今天已经排过几条 say, 最近一条的时间)。"""
    row = conn.execute("""SELECT count(*) FROM hook_queue WHERE persona_id = ? AND kind = 'say' AND created_at >= ?
                          AND COALESCE(json_extract(payload_json, '$.course_lesson'), 0) = 0""",
                       (persona_id, clock.today() + " 00:00:00")).fetchone()
    last = conn.execute("""SELECT max(created_at) FROM hook_queue WHERE persona_id = ? AND kind = 'say'
                           AND COALESCE(json_extract(payload_json, '$.course_lesson'), 0) = 0""",
                        (persona_id,)).fetchone()
    return row[0], last[0]


def claim_say(conn, persona_id: int | None = None) -> tuple[int, str, int] | None:
    """取最早的一条待发 say（给了 persona_id 就只看她的），标记为已用；返回 (id, 指令, 人设 id)，没有返回 None。"""
    row = conn.execute(
        """SELECT q.id, q.payload_json, q.persona_id FROM hook_queue q JOIN personas p ON p.id = q.persona_id
           WHERE (? IS NULL OR q.persona_id = ?) AND q.kind = 'say' AND q.consumed_at IS NULL
           AND q.expires_at > ? AND p.archived_at IS NULL ORDER BY q.id LIMIT 1""",
        (persona_id, persona_id, clock.stamp())).fetchone()
    if row is None:
        return None
    if not conn.execute("UPDATE hook_queue SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
                        (clock.stamp(), row[0])).rowcount:
        return None
    try:
        directive = str(json.loads(row[1]).get("directive") or "")
    except (TypeError, ValueError, AttributeError):
        directive = ""
    return row[0], directive, row[2]

def unclaim(conn, item_id: int) -> None:
    conn.execute("UPDATE hook_queue SET consumed_at = NULL WHERE id = ?", (item_id,))


@dataclass
class TurnEffects:
    injects: list[str] = field(default_factory=list)
    forced: set = field(default_factory=set)
    suppressed: set = field(default_factory=set)
    rows: list[tuple[int, dict]] = field(default_factory=list)


def turn_effects(conn, persona_id: int) -> TurnEffects:
    effects = TurnEffects()
    for row in conn.execute(
            """SELECT id, kind, payload_json FROM hook_queue WHERE persona_id = ? AND consumed_at IS NULL
               AND kind IN ('inject', 'activate_entry', 'deactivate_entry') AND expires_at > ? ORDER BY id""",
            (persona_id, clock.stamp())):
        try:
            payload = json.loads(row[2])
        except (TypeError, ValueError):
            continue
        if row[1] == "inject":
            effects.injects.append(str(payload.get("text") or ""))
        elif row[1] == "activate_entry":
            effects.forced.add((payload.get("book_id"), payload.get("uid")))
        else:
            effects.suppressed.add((payload.get("book_id"), payload.get("uid")))
        effects.rows.append((row[0], payload))
    return effects


def consume_turn(conn, effects: TurnEffects) -> None:
    """一轮用掉一次：剩余轮数减一，到 0 就标记已用。"""
    stamp = clock.stamp()
    for item_id, payload in effects.rows:
        left = int(payload.get("turns_left") or 1) - 1
        if left <= 0:
            conn.execute("UPDATE hook_queue SET consumed_at = ? WHERE id = ?", (stamp, item_id))
        else:
            conn.execute("UPDATE hook_queue SET payload_json = ? WHERE id = ?",
                         (json.dumps({**payload, "turns_left": left}, ensure_ascii=False), item_id))


def cleanup(conn) -> None:
    """一周前用掉或过期的行删掉。"""
    cutoff = clock.stamp(clock.now() - timedelta(days=7))
    conn.execute("DELETE FROM hook_queue WHERE (consumed_at IS NOT NULL AND consumed_at < ?) OR expires_at < ?",
                 (cutoff, cutoff))
