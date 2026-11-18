"""Saved listening practice and immutable first-submission receipts.

Storage is counted by what is actually on disk: every saved practice (audio and
JSON) plus the mistake notebook (its own copy of the audio and the missed items).
When a new practice would not fit, the oldest graded practices are removed first.
Ungraded practice is never removed automatically, and the notebook keeps its own
audio copy, so removing a practice never breaks a saved mistake.
"""
import json
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone

from ..db import get_conn
from .listening_formats import Exercise, Format

MAX_SESSIONS = 200
MAX_STORAGE_BYTES = 256 * 1024 * 1024
MAX_SESSION_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
GRADE_RESERVE = 2 * MAX_JSON_BYTES
SNAPSHOT_VERSION = 1
CLEANUP_HINT = ("听力存储已满，已保存的练习没有改动。请在听力页的练习记录里删除不需要的练习，"
                "或在错题本里删除旧错题后再试。")

_SESSION_BYTES = ("length(audio) + length(CAST(payload_json AS BLOB)) + length(CAST(metadata_json AS BLOB))"
                  " + COALESCE(length(CAST(receipt_json AS BLOB)), 0)")


class CapacityError(ValueError):
    pass


class SnapshotError(ValueError):
    pass


def _json(value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise CapacityError("Practice text exceeds the storage limit")
    return encoded


def _usage(conn):
    count, sessions = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM({_SESSION_BYTES}), 0) FROM listening_sessions").fetchone()
    notebook = conn.execute(
        "SELECT COALESCE(SUM(length(audio)), 0) FROM listening_error_sets").fetchone()[0]
    notebook += conn.execute(
        "SELECT COALESCE(SUM(length(CAST(payload_json AS BLOB))), 0) FROM listening_errors").fetchone()[0]
    return count, sessions + notebook


def _evictable(conn):
    """Graded practice, oldest first. Ungraded practice may still be in progress."""
    return conn.execute(
        f"""SELECT id, {_SESSION_BYTES} AS size FROM listening_sessions
            WHERE receipt_json IS NOT NULL ORDER BY created_at, rowid""").fetchall()


def _delete(conn, practice_id):
    removed = conn.execute("DELETE FROM listening_sessions WHERE id = ?", (practice_id,)).rowcount
    conn.execute("DELETE FROM study_state WHERE kind = 'listening-draft' AND id = ?", (practice_id,))
    return bool(removed)


def _make_room(conn, needed):
    """Remove the oldest graded practice until `needed` bytes and one more row fit."""
    count, used = _usage(conn)
    evicted = []
    candidates = iter(_evictable(conn))
    while count >= MAX_SESSIONS or used + needed > MAX_STORAGE_BYTES:
        row = next(candidates, None)
        if row is None:
            raise CapacityError(CLEANUP_HINT)
        _delete(conn, row["id"])
        evicted.append(row["id"])
        count -= 1
        used -= row["size"]
    return evicted


def check_capacity():
    """Cheap preflight before generation: could room be made without deleting ungraded work?"""
    with closing(get_conn()) as conn:
        count, used = _usage(conn)
        rows = _evictable(conn)
    if count - len(rows) >= MAX_SESSIONS or used - sum(row["size"] for row in rows) + GRADE_RESERVE > MAX_STORAGE_BYTES:
        raise CapacityError(CLEANUP_HINT)


def create(practice_id, exercise, profile, audio, timings, metadata):
    """Save a practice; returns the IDs of old graded practice removed to make room."""
    payload = _json({"exercise": exercise.model_dump(), "profile": asdict(profile), "timings": timings})
    meta = _json(metadata)
    size = len(audio) + len(payload.encode("utf-8")) + len(meta.encode("utf-8"))
    if size > MAX_SESSION_BYTES:
        raise CapacityError("Generated practice exceeds the 16 MiB session limit")
    # Room for this row, the receipt, and the notebook's audio copy if anything is missed.
    needed = size + len(audio) + GRADE_RESERVE
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        evicted = _make_room(conn, needed)
        conn.execute(
            """INSERT INTO listening_sessions
               (id, language, version, metadata_json, payload_json, audio, reserved_bytes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (practice_id, profile.language, SNAPSHOT_VERSION, meta, payload, audio, size, now),
        )
    return evicted


def delete(practice_id):
    """Remove one saved practice and its draft. Saved mistakes keep their own audio."""
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        return _delete(conn, practice_id)


def usage():
    with closing(get_conn()) as conn:
        count, used = _usage(conn)
    return {"count": count, "max_count": MAX_SESSIONS, "used_bytes": used, "max_bytes": MAX_STORAGE_BYTES}


def _metadata(row, include_receipt=False):
    if row["version"] != SNAPSHOT_VERSION:
        raise SnapshotError("This saved practice needs a compatible application version")
    try:
        result = json.loads(row["metadata_json"])
        receipt = json.loads(row["receipt_json"]) if row["receipt_json"] else None
        result.update(created_at=row["created_at"], graded_at=row["graded_at"],
                      status="graded" if receipt else "ready", size_bytes=row["size"])
        if receipt:
            result["score"] = receipt["score"]
            result["marks"] = [bool(item.get("correct")) for item in receipt.get("results") or []]
        if include_receipt:
            result["receipt"] = receipt
        return result
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise SnapshotError("Saved practice metadata cannot be read; it has not been changed") from error


def _brief(row):
    """List view: one unreadable record must not hide the rest or block deleting it."""
    try:
        return _metadata(row)
    except SnapshotError:
        return {"id": row["id"], "status": "unreadable", "created_at": row["created_at"],
                "graded_at": row["graded_at"], "size_bytes": row["size"]}


def recent(language=None, limit=20):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"""SELECT id, version, metadata_json, receipt_json, created_at, graded_at, {_SESSION_BYTES} AS size
               FROM listening_sessions WHERE (? IS NULL OR language = ?)
               ORDER BY created_at DESC, rowid DESC LIMIT ?""", (language, language, limit),
        ).fetchall()
    return [_brief(row) for row in rows]


def metadata(practice_id):
    with closing(get_conn()) as conn:
        row = conn.execute(
            f"""SELECT id, version, metadata_json, receipt_json, created_at, graded_at, {_SESSION_BYTES} AS size
               FROM listening_sessions WHERE id = ?""", (practice_id,),
        ).fetchone()
    return _metadata(row, include_receipt=True) if row else None


def load(practice_id):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT * FROM listening_sessions WHERE id = ?", (practice_id,)).fetchone()
    if row is None:
        return None
    if row["version"] != SNAPSHOT_VERSION:
        raise SnapshotError("This saved practice needs a compatible application version")
    try:
        payload = json.loads(row["payload_json"])
        return (Exercise.model_validate(payload["exercise"]), Format(**payload["profile"]),
                row["audio"], payload["timings"])
    except (ValueError, KeyError, TypeError) as error:
        raise SnapshotError("Saved practice cannot be read; it has not been changed") from error


def save_first_grade(practice_id, receipt):
    """Serialize submissions; notebook rows and the first receipt commit together.

    Grading is never refused for space: room for it was set aside when the practice was saved.
    """
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM listening_sessions WHERE id = ?", (practice_id,)).fetchone()
        if row is None:
            raise SnapshotError("Practice was not saved; prepare a new session")
        if row["receipt_json"]:
            return json.loads(row["receipt_json"])
        errors = [(practice_id, index, _json(result))
                  for index, result in enumerate(receipt["results"]) if not result["correct"]]
        if sum(len(item[2].encode("utf-8")) for item in errors) > MAX_JSON_BYTES:
            raise CapacityError("Grade exceeds the storage limit")
        saved = {**receipt, "saved_errors": len(errors), "graded_at":
                 datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                 "receipt_kind": "first_submission"}
        receipt_json = _json(saved)
        if errors:
            conn.execute(
                "INSERT OR IGNORE INTO listening_error_sets(id, language, title, audio) VALUES (?, ?, ?, ?)",
                (practice_id, row["language"], receipt["title"], row["audio"]),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO listening_errors(practice_id, item_index, payload_json) VALUES (?, ?, ?)",
                errors,
            )
        conn.execute("UPDATE listening_sessions SET receipt_json = ?, graded_at = ? WHERE id = ?",
                     (receipt_json, saved["graded_at"], practice_id))
    return saved
