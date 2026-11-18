"""Missed listening questions and their own copy of the audio, in the local database.

Rows are written by listening_sessions.save_first_grade together with the receipt.
"""
import json
from contextlib import closing

from ..db import get_conn


def entries(language):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT e.practice_id, e.item_index, e.updated_at, e.payload_json, s.title, s.language
               FROM listening_errors e JOIN listening_error_sets s ON s.id = e.practice_id
               WHERE (? IS NULL OR s.language = ?)
               ORDER BY e.updated_at DESC, e.practice_id, e.item_index LIMIT 150""",
            (language, language),
        ).fetchall()
    return [
        {**json.loads(row["payload_json"]),
         **{key: row[key] for key in ("practice_id", "item_index", "updated_at", "title", "language")}}
        for row in rows
    ]


def audio_for(practice_id):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT audio FROM listening_error_sets WHERE id = ?", (practice_id,)).fetchone()
    return row["audio"] if row else None


def delete_set(practice_id):
    """Remove one practice's missed questions, their audio and their review history."""
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM listening_errors WHERE practice_id = ?", (practice_id,))
        conn.execute("DELETE FROM review_states WHERE kind = 'listening' AND item_id = ?", (practice_id,))
        conn.execute("DELETE FROM review_attempts WHERE kind = 'listening' AND item_id = ?", (practice_id,))
        return bool(conn.execute("DELETE FROM listening_error_sets WHERE id = ?", (practice_id,)).rowcount)
