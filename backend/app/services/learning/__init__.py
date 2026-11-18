"""Learning side: one review queue (FSRS), study records, advice and "today". Spec: docs/LEARNING.md.

fsrs      pure scheduling formulas
store     tables, settings, sync from saved items into cards, record_event
cards     queue / reveal / grade / summary, and helpers for chat and hooks
words     one word with many contexts, encounters, dictation comparison
insights  today, advice, question-type diagnosis, stats

Functions other modules call (they all take an open connection and do not commit):
- due_vocab(conn, language, n, near_text="")   for {{due_vocab::N}}
- reviews_due(conn, language)                   for the condition field `reviews_due`
- chat_success(conn, language, lemmas)          the user used due words right in chat (weak "good")
- encounter_lemmas(conn, language, lemmas)      saved words seen in chat (+1 encounter)
- record_event(conn, kind, language, ref, data) one study_events row (e.g. kind="chat", data={"turns", "fixes"})
- end_session(conn, language)                   close a review session: record it and emit
                                                study.review_session_done {count, forgot, language}
"""
from datetime import timedelta

from .. import clock
from .cards import chat_success, due_vocab, reviews_due
from .store import record_event
from .words import encounter, encounter_lemmas


def _last_session_end(conn, language) -> str:
    row = conn.execute("SELECT max(at) FROM study_events WHERE kind = 'review' AND language = ?", (language,)).fetchone()
    # A session never reaches back more than 12 hours (and never into migrated history).
    return max(row[0] or "0000", clock.stamp(clock.now() - timedelta(hours=12)))


def end_session(conn, language: str) -> dict | None:
    """Everything graded since the last session end counts as one session. No-op when nothing was graded."""
    since = _last_session_end(conn, language)
    count, forgot = conn.execute(
        """SELECT count(*), coalesce(sum(l.rating = 1 OR l.peeked = 1), 0) FROM review_log l
           JOIN review_cards c ON c.id = l.card_id
           WHERE c.language = ? AND l.at > ? AND l.weak = 0""",
        (language, since)).fetchone()
    if not count:
        return None
    payload = {"count": count, "forgot": forgot, "language": language}
    record_event(conn, "review", language, None, {"count": count, "forgot": forgot})
    _emit("study.review_session_done", payload)
    return payload


def _emit(event: str, payload: dict) -> None:
    """Hand the event to the hook engine in the background. Until hooks lists the event name, no rule matches it."""
    try:
        from .. import hooks
        hooks.emit_soon(event, None, payload)
    except Exception:
        pass


__all__ = ["chat_success", "due_vocab", "encounter", "encounter_lemmas", "end_session",
           "record_event", "reviews_due"]
