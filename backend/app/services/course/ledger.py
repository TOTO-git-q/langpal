"""The lesson progress event table."""
import json

from .. import clock
from . import content, state


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS course_events (
        id INTEGER PRIMARY KEY, at TEXT NOT NULL, language TEXT NOT NULL,
        course_id TEXT NOT NULL, unit_id TEXT NOT NULL, point_id TEXT NOT NULL,
        point_key TEXT NOT NULL, channel TEXT NOT NULL, ref TEXT NOT NULL,
        result TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', quote TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE (language, course_id, channel, ref, unit_id, point_id))""")


def read(conn, outline):
    ensure(conn)
    cursor = conn.execute("SELECT * FROM course_events WHERE language=? AND course_id=? AND channel='lesson' ORDER BY at,id",
                          (outline.language, outline.id))
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def write(conn, outline, events, *, now=None):
    """Write lesson results in the caller's transaction."""
    now = now or clock.now()
    before = state.fold(read(conn, outline), outline, now)
    inserted = 0
    for event in events:
        pair = event['unit_id'], event['point_id']
        if pair not in before['points']:
            continue
        values = (event.get('at') or clock.stamp(now), outline.language, outline.id, *pair,
                  content.point_key(outline, *pair), 'lesson', event['ref'], event['result'],
                  event.get('context', ''), event.get('quote', ''),
                  json.dumps(event.get('detail', {}), ensure_ascii=False))
        inserted += conn.execute("""INSERT INTO course_events
            (at,language,course_id,unit_id,point_id,point_key,channel,ref,result,context,quote,detail_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(language,course_id,channel,ref,unit_id,point_id) DO NOTHING""", values).rowcount
    after = state.fold(read(conn, outline), outline, now)
    for unit in content.view(outline).units:
        if after['units'][unit.id] == 'known' and before['units'][unit.id] != 'known':
            try:
                from .. import hooks
                hooks.emit_soon('course.unit_completed', None,
                                {'unit_id': unit.id, 'title': unit.title, 'language': outline.language})
            except Exception:
                pass
    return inserted
