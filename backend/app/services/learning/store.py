"""Tables, settings and the one-way sync that turns saved items into review cards.

`sync(conn)` is idempotent and cheap: it creates a card for every saved word, pattern,
reading mistake and listening mistake that has none, carries over the old scheduling
fields the first time, copies old review attempts into review_log, gives every word
its first context sentence, adds `vocab_produce` cards for words that are already
stable, and drops cards whose source row is gone. Old tables are never deleted.
"""
import json

from .. import clock
from . import fsrs

KINDS = ("vocab", "vocab_produce", "pattern", "reading_q", "listening_q")
OBJECTIVE = ("reading_q", "listening_q", "vocab_produce")
PRODUCE_AFTER_DAYS = 7
LEGACY_INTERVALS = [1, 3, 7, 14, 30]   # services/review.py stages

SETTINGS = {
    # key: (default, parser)
    "review_target_retention": (0.90, lambda v: min(0.95, max(0.80, float(v)))),
    "review_new_per_day": (12, lambda v: min(50, max(0, int(float(v))))),
    "review_mix": (True, lambda v: str(v).strip().lower() not in ("0", "false", "off", "no")),
    "reading_questions_first": (False, lambda v: str(v).strip().lower() in ("1", "true", "on", "yes")),
}


def setting(conn, key):
    default, parse = SETTINGS[key]
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None or row[0] in (None, ""):
        return default
    try:
        return parse(row[0])
    except (TypeError, ValueError):
        return default


def settings(conn) -> dict:
    return {key: setting(conn, key) for key in SETTINGS}


def migrate(conn) -> None:
    """Columns the schema file cannot add to an existing table, then the first sync."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(vocab_entries)")}
    if "encounters" not in columns:
        conn.execute("ALTER TABLE vocab_entries ADD COLUMN encounters INTEGER NOT NULL DEFAULT 0")
    sync(conn)


def record_event(conn, kind: str, language: str | None, ref: str | None = None, data: dict | None = None,
                 at: str | None = None) -> int:
    """One row in study_events. All statistics are computed from these rows and review_log."""
    return conn.execute(
        "INSERT INTO study_events (at, language, kind, ref, data_json) VALUES (?, ?, ?, ?, ?)",
        (at or clock.stamp(), language, kind, ref, json.dumps(data or {}, ensure_ascii=False))).lastrowid


def _legacy_review(row) -> dict:
    """Scheduling fields from the old two-field SRS (vocab/pattern) or error review states."""
    if row["reps"]:
        stability = max(1.0, float(row["interval_days"] or 1))
        due = clock.parse(row["due_at"])
        return {"state": "review", "stability": stability, "difficulty": fsrs.W[4],
                "due_at": clock.stamp(due) if due else clock.stamp(), "reps": row["reps"]}
    return {"state": "new", "stability": None, "difficulty": None, "due_at": None, "reps": 0}


def _insert_card(conn, kind, language, ref_table, ref_id, fields) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO review_cards
           (kind, language, ref_table, ref_id, state, stability, difficulty, due_at, last_review_at, reps)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (kind, language, ref_table, ref_id, fields["state"], fields["stability"], fields["difficulty"],
         fields["due_at"], fields.get("last_review_at"), fields.get("reps", 0)))


def _missing(conn, kind, ref_table, select):
    return conn.execute(
        f"""SELECT * FROM ({select}) src WHERE NOT EXISTS (
              SELECT 1 FROM review_cards c WHERE c.kind = ? AND c.ref_table = ? AND c.ref_id = src.ref_id)""",
        (kind, ref_table)).fetchall()


def sync(conn) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(vocab_entries)")}
    if "encounters" not in columns:
        conn.execute("ALTER TABLE vocab_entries ADD COLUMN encounters INTEGER NOT NULL DEFAULT 0")
    for kind, table in (("vocab", "vocab_entries"), ("pattern", "pattern_entries")):
        for row in _missing(conn, kind, table,
                            f"SELECT CAST(id AS TEXT) AS ref_id, language, due_at, interval_days, reps FROM {table}"):
            _insert_card(conn, kind, row["language"], table, row["ref_id"], _legacy_review(row))
    legacy = {}
    for row in conn.execute("SELECT * FROM review_states"):
        legacy[(row["kind"], row["item_id"], row["item_index"])] = row
    for kind, table, select in (
        ("reading_q", "reading_errors",
         """SELECT e.exercise_id || ':' || e.item_index AS ref_id, e.exercise_id AS item_id, e.item_index, s.language
            FROM reading_errors e JOIN reading_exercises s ON s.id = e.exercise_id"""),
        ("listening_q", "listening_errors",
         """SELECT e.practice_id || ':' || e.item_index AS ref_id, e.practice_id AS item_id, e.item_index, s.language
            FROM listening_errors e JOIN listening_error_sets s ON s.id = e.practice_id"""),
    ):
        old_kind = kind.split("_")[0]
        for row in _missing(conn, kind, table, select):
            state = legacy.get((old_kind, row["item_id"], row["item_index"]))
            fields = {"state": "new", "stability": None, "difficulty": None, "due_at": None, "reps": 0}
            if state is not None and state["attempt_count"]:
                stage = state["stage"]
                due, last = clock.parse(state["due_at"]), clock.parse(state["last_attempt_at"])
                fields = {"state": "review" if stage else "relearning",
                          "stability": float(LEGACY_INTERVALS[stage - 1]) if stage else fsrs.W[0],
                          "difficulty": fsrs.W[4], "due_at": clock.stamp(due) if due else clock.stamp(),
                          "last_review_at": clock.stamp(last) if last else None, "reps": state["attempt_count"]}
            _insert_card(conn, kind, row["language"], table, row["ref_id"], fields)
    # Old error-review attempts join the one log (request_id = attempt_id keeps this idempotent).
    for row in conn.execute(
            """SELECT a.* FROM review_attempts a WHERE NOT EXISTS
               (SELECT 1 FROM review_log l WHERE l.request_id = a.attempt_id)""").fetchall():
        card = conn.execute("SELECT id FROM review_cards WHERE kind = ? AND ref_id = ?",
                            (row["kind"] + "_q", f"{row['item_id']}:{row['item_index']}")).fetchone()
        if card is None:
            continue
        try:
            outcome = json.loads(row["result_json"]).get("outcome")
        except (TypeError, ValueError):
            outcome = None
        at = clock.parse(row["created_at"])
        conn.execute(
            """INSERT OR IGNORE INTO review_log (card_id, at, rating, peeked, request_id, was_due)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (card["id"], clock.stamp(at) if at else clock.stamp(), 3 if outcome == "correct" else 1,
             int(outcome == "revealed"), row["attempt_id"]))
    # First context of every word is the sentence it was saved with.
    conn.execute(
        """INSERT OR IGNORE INTO vocab_contexts (vocab_id, sentence, source_kind, source_ref, created_at)
           SELECT id, context_sentence, CASE WHEN source_message_id IS NULL THEN 'unknown' ELSE 'chat' END,
                  CAST(source_message_id AS TEXT), created_at
           FROM vocab_entries v WHERE context_sentence IS NOT NULL AND trim(context_sentence) <> ''
             AND NOT EXISTS (SELECT 1 FROM vocab_contexts c WHERE c.vocab_id = v.id)""")
    # Recognise first, then produce: a produce card once the word is stable for a week.
    conn.execute(
        """INSERT OR IGNORE INTO review_cards (kind, language, ref_table, ref_id, state)
           SELECT 'vocab_produce', language, ref_table, ref_id, 'new' FROM review_cards
           WHERE kind = 'vocab' AND state = 'review' AND stability > ?""", (PRODUCE_AFTER_DAYS,))
    # Cards whose source is gone.
    for kind, table, expr in (("vocab", "vocab_entries", "CAST(id AS TEXT)"),
                              ("vocab_produce", "vocab_entries", "CAST(id AS TEXT)"),
                              ("pattern", "pattern_entries", "CAST(id AS TEXT)"),
                              ("reading_q", "reading_errors", "exercise_id || ':' || item_index"),
                              ("listening_q", "listening_errors", "practice_id || ':' || item_index")):
        conn.execute(f"""DELETE FROM review_cards WHERE kind = ? AND ref_id NOT IN (SELECT {expr} FROM {table})""",
                     (kind,))
