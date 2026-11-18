"""Review original mistakes without rewriting their historical answers.

Scheduling is a transparent practice aid, not an estimate of mastery. UTC days
and server time govern advancement. Revealing an answer never counts as success.
"""
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

from ..db import get_conn

INTERVALS = [1, 3, 7, 14, 30]


class ConflictError(ValueError):
    pass


class CapacityError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def original(conn, kind, item_id, item_index):
    if kind == "reading":
        row = conn.execute("""SELECT s.payload_json FROM reading_errors e
            JOIN reading_exercises s ON s.id=e.exercise_id
            WHERE e.exercise_id=? AND e.item_index=?""", (item_id, item_index)).fetchone()
    else:
        row = conn.execute("""SELECT e.payload_json FROM listening_errors e
            JOIN listening_error_sets s ON s.id=e.practice_id
            WHERE e.practice_id=? AND e.item_index=?""", (item_id, item_index)).fetchone()
    if not row:
        raise LookupError("Original mistake was not found")
    try:
        item = json.loads(row["payload_json"])
        if kind == "reading":
            item = item["items"][item_index]
        answer = item["answer"]
        options = item["options" if kind == "reading" else "choices"]
        if (not isinstance(options, list) or not 2 <= len(options) <= 5
                or type(answer) is not int or not 0 <= answer < len(options)):
            raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError("Original question is not gradeable") from None
    return answer, len(options)


def initial(kind, item_id, item_index):
    return dict(kind=kind, item_id=item_id, item_index=item_index, attempt_count=0,
                independent_correct_count=0, stage=0, due_at=None,
                last_outcome=None, last_attempt_at=None)


def states(language=None, limit=300):
    # Match the exact source windows exposed by the two original error APIs.
    # This prevents old state rows displacing states needed by the current UI.
    with closing(get_conn()) as conn:
        rows = conn.execute("""WITH reading_window AS (
            SELECT 'reading' AS kind, e.exercise_id AS item_id, e.item_index
            FROM reading_errors e JOIN reading_exercises s ON s.id=e.exercise_id
            WHERE (? IS NULL OR s.language=?)
            ORDER BY e.updated_at DESC,e.exercise_id,e.item_index LIMIT 150
        ), listening_window AS (
            SELECT 'listening' AS kind, e.practice_id AS item_id, e.item_index
            FROM listening_errors e JOIN listening_error_sets s ON s.id=e.practice_id
            WHERE (? IS NULL OR s.language=?)
            ORDER BY e.updated_at DESC,e.practice_id,e.item_index LIMIT 150
        ), originals AS (SELECT * FROM reading_window UNION ALL SELECT * FROM listening_window)
        SELECT r.* FROM review_states r JOIN originals o
        ON r.kind=o.kind AND r.item_id=o.item_id AND r.item_index=o.item_index
        ORDER BY r.kind,r.item_id,r.item_index LIMIT ?""",
        (language, language, language, language, limit + 1)).fetchall()
    return {"items": [public_state(dict(row)) for row in rows[:limit]], "limit": limit,
            "truncated": len(rows) > limit, "scope": "latest_150_per_kind", "timezone": "UTC"}


def public_state(state):
    return {key: value for key, value in state.items() if key != "last_exposure_day"}


def is_recorded(attempt_id) -> bool:
    with closing(get_conn()) as conn:
        return conn.execute("SELECT 1 FROM review_attempts WHERE attempt_id=?", (str(attempt_id),)).fetchone() is not None


def attempt(body):
    data = body.model_dump(mode="json")
    fingerprint = json.dumps(data, sort_keys=True, separators=(",", ":"))
    key = (body.kind, body.item_id, body.item_index)
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        saved = conn.execute("SELECT request_json,result_json FROM review_attempts WHERE attempt_id=?",
                             (str(body.attempt_id),)).fetchone()
        if saved:
            if saved["request_json"] != fingerprint:
                raise ConflictError("Attempt ID already belongs to a different submission")
            return json.loads(saved["result_json"])
        answer, count = original(conn, *key)
        if body.selection is not None and not 0 <= body.selection < count:
            raise ValueError("Selection is outside this question's choices")
        now = utcnow()
        day = now.date().isoformat()
        now_text = stamp(now)
        daily = conn.execute("""SELECT COUNT(*) FROM review_attempts
            WHERE kind=? AND item_id=? AND item_index=? AND created_at>=?""",
            (*key, day + "T00:00:00Z")).fetchone()[0]
        if daily >= 200:
            raise CapacityError("Daily review limit reached for this question")
        row = conn.execute("SELECT * FROM review_states WHERE kind=? AND item_id=? AND item_index=?", key).fetchone()
        state = dict(row) if row else {**initial(*key), "last_exposure_day": None}
        outcome = "revealed" if body.mode == "revealed" else ("correct" if body.selection == answer else "wrong")
        state["attempt_count"] += 1
        if outcome == "correct":
            # Only the first exposure of a UTC day can supply independent
            # correct evidence, even when several clients submit fresh UUIDs.
            if state["last_exposure_day"] != day:
                state["independent_correct_count"] += 1
            # Every answer exposure (including failure/reveal) prevents another
            # interval promotion today. Early practice cannot postpone a due item.
            if state["last_exposure_day"] != day and (not state["due_at"] or state["due_at"] <= now_text):
                state["stage"] = min(len(INTERVALS), state["stage"] + 1)
                state["due_at"] = stamp(now + timedelta(days=INTERVALS[state["stage"] - 1]))
        else:
            state["stage"] = 0
            state["due_at"] = stamp(now + timedelta(minutes=10))
        state.update(last_outcome=outcome, last_attempt_at=now_text, last_exposure_day=day)
        conn.execute("""INSERT INTO review_states
            (kind,item_id,item_index,attempt_count,independent_correct_count,stage,due_at,last_outcome,last_attempt_at,last_exposure_day)
            VALUES (:kind,:item_id,:item_index,:attempt_count,:independent_correct_count,:stage,:due_at,:last_outcome,:last_attempt_at,:last_exposure_day)
            ON CONFLICT(kind,item_id,item_index) DO UPDATE SET
            attempt_count=excluded.attempt_count,independent_correct_count=excluded.independent_correct_count,
            stage=excluded.stage,due_at=excluded.due_at,last_outcome=excluded.last_outcome,
            last_attempt_at=excluded.last_attempt_at,last_exposure_day=excluded.last_exposure_day""", state)
        result = dict(attempt_id=str(body.attempt_id), outcome=outcome,
                      correct=None if outcome == "revealed" else outcome == "correct",
                      answer=answer, state=public_state(state))
        conn.execute("""INSERT INTO review_attempts
            (attempt_id,kind,item_id,item_index,request_json,result_json,created_at) VALUES (?,?,?,?,?,?,?)""",
            (str(body.attempt_id), *key, fingerprint, json.dumps(result), now_text))
        return result
