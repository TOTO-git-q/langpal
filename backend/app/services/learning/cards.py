"""The one review queue: fronts, reveal, grading, summary. docs/LEARNING.md section 2."""
import json
import re
import unicodedata
from datetime import timedelta

from .. import clock
from . import fsrs, store

FAST_PRODUCE_MS = 5000
SESSION_GAP_MINUTES = fsrs.RELEARN_MINUTES
RETENTION_MIN_SAMPLES = 20
BLANK = "____"


class CardError(ValueError):
    pass


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold().strip()


def _token_ends(sentence: str, language: str) -> list[int] | None:
    try:
        from ..tokenize import tokenize
        ends, position = [], 0
        for token in tokenize(sentence, language):
            position += len(token["surface"])
            ends.append(position)
        return ends if position == len(sentence) else None
    except Exception:
        return None


def cloze(sentence: str, words: list[str], language: str) -> str | None:
    """Blank the word out of its sentence; None if it cannot be found (then the front asks by meaning).

    Japanese: find the word or its stem (食べる → 食べ), then widen the blank to the end of the
    dictionary word it falls in (食べ|た → ____た, 見直|し|が → ____が), never across particles.
    English: the word or its stem plus any ending (decide → decided).
    """
    if not sentence:
        return None
    for word in [w for w in words if w]:
        if language.startswith("ja") or not word.isascii():
            candidates = [word]
            if len(word) >= 2 and re.search(r"[ぁ-ん]$", word):
                candidates.append(word[:-1])
            if len(word) >= 3 and word.endswith("する"):
                candidates.append(word[:-2])  # 撤回する → 撤回(した)
            for candidate in candidates:
                index = sentence.find(candidate)
                if index < 0:
                    continue
                end = index + len(candidate)
                ends = _token_ends(sentence, language) if language.startswith("ja") else None
                if ends:
                    end = next(e for e in ends if e >= end)
                return sentence[:index] + BLANK + sentence[end:]
            continue
        stem = re.escape(word[:-1] if len(word) > 4 and word[-1] in "eyEY" else word)
        match = re.search(rf"(?<![\w'-]){stem}\w*", sentence, re.IGNORECASE)
        if match:
            return sentence[:match.start()] + BLANK + sentence[match.end():]
    return None


def hint_for(meaning: str, word_forms: list[str]) -> str | None:
    """First two characters of the meaning, unless they give the answer away (撤回 → 撤回)."""
    hint = (meaning or "")[:2]
    forms = "".join(w for w in word_forms if w).casefold()
    if not hint or any(char.casefold() in forms for char in hint if not char.isascii() or char.isalpha()):
        return None
    return hint


# ---------------------------------------------------------------- loading


def _card(conn, card_id: int):
    row = conn.execute("SELECT * FROM review_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("没有这张卡")
    return row


def _contexts(conn, vocab_id) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, sentence, source_kind, source_ref, created_at FROM vocab_contexts WHERE vocab_id = ? ORDER BY id",
        (vocab_id,))]


def _source(conn, card) -> dict | None:
    kind, ref = card["kind"], card["ref_id"]
    if kind in ("vocab", "vocab_produce"):
        row = conn.execute("SELECT * FROM vocab_entries WHERE id = ?", (int(ref),)).fetchone()
        return dict(row) if row else None
    if kind == "pattern":
        row = conn.execute("SELECT * FROM pattern_entries WHERE id = ?", (int(ref),)).fetchone()
        return dict(row) if row else None
    item_id, _, index = ref.rpartition(":")
    index = int(index)
    if kind == "reading_q":
        row = conn.execute("SELECT title, payload_json FROM reading_exercises WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        items = json.loads(row["payload_json"]).get("items") or []
        if index >= len(items):
            return None
        from ..reading_errors import item_with_evidence
        return {**item_with_evidence(items[index]), "title": row["title"], "item_id": item_id, "item_index": index}
    row = conn.execute(
        """SELECT e.payload_json, s.title FROM listening_errors e JOIN listening_error_sets s ON s.id = e.practice_id
           WHERE e.practice_id = ? AND e.item_index = ?""", (item_id, index)).fetchone()
    if row is None:
        return None
    return {**json.loads(row["payload_json"]), "title": row["title"], "item_id": item_id, "item_index": index}


def _context_for(card, contexts):
    """Rotate through the contexts so the word, not one sentence, is learned."""
    return contexts[card["reps"] % len(contexts)] if contexts else None


def front(conn, card) -> dict | None:
    src = _source(conn, card)
    if src is None:
        return None
    base = {"id": card["id"], "kind": card["kind"], "language": card["language"], "state": card["state"],
            "due_at": card["due_at"]}
    kind = card["kind"]
    if kind in ("vocab", "vocab_produce"):
        contexts = _contexts(conn, src["id"])
        context = _context_for(card, contexts)
        sentence = cloze(context["sentence"], [src.get("surface"), src["lemma"]], card["language"]) if context else None
        meaning = src.get("meaning") or ""
        if kind == "vocab":
            return {**base, "vocab_id": src["id"], "sentence": sentence,
                    "hint": hint_for(meaning, [src.get("surface"), src["lemma"], src.get("reading")]),
                    "meaning": None if sentence else meaning}
        return {**base, "vocab_id": src["id"], "meaning": meaning, "sentence": sentence}
    if kind == "pattern":
        name = re.sub(r"^[〜~～]+|[〜~～]+$", "", src["pattern_name"] or "")
        sentence = cloze(src.get("example_sentence") or "", [name], card["language"])
        return {**base, "sentence": sentence, "translation": src.get("translation"),
                "explanation": None if sentence else src.get("explanation")}
    if kind == "reading_q":
        return {**base, "title": src["title"], "question": src["question"], "options": src["options"],
                "paragraph": src.get("paragraph"), "skill": src.get("skill")}
    return {**base, "title": src["title"], "question": src["prompt"], "options": src["choices"],
            "audio": f"/api/listening/errors/{src['item_id']}/audio", "clips": src.get("clips") or [],
            "skill": src.get("skill")}


def back(conn, card) -> dict:
    src = _source(conn, card)
    if src is None:
        raise LookupError("这张卡的原始内容已删除")
    kind = card["kind"]
    if kind in ("vocab", "vocab_produce"):
        contexts = _contexts(conn, src["id"])
        used = _context_for(card, contexts)
        return {"lemma": src["lemma"], "surface": src.get("surface"), "reading": src.get("reading"),
                "meaning": src.get("meaning"), "sentence": used["sentence"] if used else None,
                "other_sentences": [c["sentence"] for c in contexts if not used or c["id"] != used["id"]],
                "encounters": src.get("encounters", 0)}
    if kind == "pattern":
        return {"pattern": src["pattern_name"], "explanation": src.get("explanation"),
                "example": src.get("example_sentence"), "translation": src.get("translation")}
    if kind == "reading_q":
        return {"answer": src["answer"], "explanation": src.get("explanation"), "quote": src.get("quote")}
    return {"answer": src["answer"], "explanation": src.get("explanation"), "evidence": src.get("evidence") or []}


# ---------------------------------------------------------------- queue


def _new_today(conn, language) -> int:
    return conn.execute(
        """SELECT count(DISTINCT l.card_id) FROM review_log l JOIN review_cards c ON c.id = l.card_id
           WHERE c.language = ? AND l.stability_before IS NULL AND l.at >= ? AND l.weak = 0""",
        (language, clock.today() + " 00:00:00")).fetchone()[0]


def _mix(cards: list) -> list:
    groups: dict[str, list] = {}
    for card in cards:
        groups.setdefault(card["kind"], []).append(card)
    mixed, lists = [], list(groups.values())
    while any(lists):
        for group in lists:
            if group:
                mixed.append(group.pop(0))
    return mixed


def _kinds_filter(kinds):
    kinds = [k for k in (kinds or []) if k in store.KINDS] or list(store.KINDS)
    return kinds, ",".join("?" * len(kinds))


def queue(conn, language: str, kinds=None, limit: int = 50) -> dict:
    store.sync(conn)
    now = clock.stamp()
    kinds, marks = _kinds_filter(kinds)
    due = conn.execute(
        f"""SELECT * FROM review_cards WHERE language = ? AND suspended = 0 AND state <> 'new'
            AND due_at <= ? AND kind IN ({marks}) ORDER BY due_at, id""", (language, now, *kinds)).fetchall()
    room = max(0, store.setting(conn, "review_new_per_day") - _new_today(conn, language))
    fresh = conn.execute(
        f"""SELECT * FROM review_cards WHERE language = ? AND suspended = 0 AND state = 'new'
            AND kind IN ({marks}) ORDER BY created_at, id""", (language, *kinds)).fetchall()
    if store.setting(conn, "review_mix"):
        due, fresh = _mix(due), _mix(fresh)
    fresh = fresh[:room]
    soon = clock.stamp(clock.now() + timedelta(minutes=SESSION_GAP_MINUTES))
    later = conn.execute(
        f"""SELECT id, due_at FROM review_cards WHERE language = ? AND suspended = 0
            AND state IN ('learning','relearning') AND due_at > ? AND due_at <= ? AND kind IN ({marks})
            ORDER BY due_at""", (language, now, soon, *kinds)).fetchall()
    cards = [f for f in (front(conn, c) for c in [*due, *fresh][:limit]) if f]
    return {"cards": cards, "later": [{"id": r["id"], "due_at": r["due_at"],
                                       "in_seconds": max(0, int((clock.parse(r["due_at"]) - clock.now()).total_seconds()))}
                                      for r in later],
            "due_now": len(due), "new_left_today": room}


# ---------------------------------------------------------------- reveal and grade


def _state(card) -> dict:
    return {"state": card["state"], "stability": card["stability"], "difficulty": card["difficulty"],
            "last_review_at": clock.parse(card["last_review_at"])}


def _correct(conn, card, answer) -> bool | None:
    if answer is None:
        return None
    src = _source(conn, card)
    if src is None:
        raise LookupError("这张卡的原始内容已删除")
    if card["kind"] == "vocab_produce":
        typed = _fold(str(answer))
        return bool(typed) and typed in {_fold(src.get("lemma")), _fold(src.get("surface")), _fold(src.get("reading"))}
    if type(answer) is not int:
        raise CardError("请选择一个选项")
    return answer == src["answer"]


def reveal(conn, card_id: int, answer=None, gave_up: bool = False) -> dict:
    """The back of the card. Revealing an objective card without an answer is a peek: it grades as forgot."""
    card = _card(conn, card_id)
    peeked = bool(gave_up) or (card["kind"] in store.OBJECTIVE and answer is None)
    correct = _correct(conn, card, answer) if not peeked else None
    conn.execute("UPDATE review_cards SET revealed_at = ?, reveal_peeked = ?, reveal_answer = ? WHERE id = ?",
                 (clock.stamp(), int(peeked), json.dumps(answer, ensure_ascii=False) if answer is not None else None,
                  card_id))
    retention = store.setting(conn, "review_target_retention")
    return {"id": card_id, "kind": card["kind"], "back": back(conn, card), "peeked": peeked, "correct": correct,
            "intervals": {str(k): v for k, v in fsrs.preview(_state(card), clock.now(), retention).items()}}


def _rating(conn, card, rating, answer, answer_ms) -> tuple[int, bool]:
    peeked = bool(card["reveal_peeked"])
    if peeked:
        return 1, True
    if card["kind"] in store.OBJECTIVE:
        if answer is None and card["reveal_answer"] is not None:
            answer = json.loads(card["reveal_answer"])
        correct = _correct(conn, card, answer)
        if correct is None:
            raise CardError("这张卡要先作答")
        if not correct:
            return 1, False
        fast = card["kind"] == "vocab_produce" and answer_ms is not None and answer_ms < FAST_PRODUCE_MS
        return (4 if fast else 3), False
    if rating not in (1, 2, 3, 4):
        raise CardError("评分只能是 1–4")
    return rating, False


def apply(conn, card, rating: int, *, peeked=False, answer_ms=None, request_id=None, weight=1.0) -> dict:
    now = clock.now()
    retention = store.setting(conn, "review_target_retention")
    before = _state(card)
    outcome = fsrs.review(before, rating, now, retention, weight)
    was_due = int(card["state"] != "new" and card["due_at"] is not None and card["due_at"] <= clock.stamp(now)
                  and card["state"] == "review")
    conn.execute(
        """INSERT INTO review_log (card_id, at, rating, elapsed_days, stability_before, stability_after,
               retrievability, answer_ms, peeked, request_id, was_due, weak)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (card["id"], clock.stamp(now), rating, outcome.elapsed_days, card["stability"], outcome.stability,
         outcome.retrievability, answer_ms, int(peeked), request_id, was_due, int(weight < 1)))
    conn.execute(
        """UPDATE review_cards SET state = ?, stability = ?, difficulty = ?, due_at = ?, last_review_at = ?,
               reps = reps + 1, lapses = lapses + ?, revealed_at = NULL, reveal_peeked = 0, reveal_answer = NULL
           WHERE id = ?""",
        (outcome.state, outcome.stability, outcome.difficulty, clock.stamp(outcome.due_at), clock.stamp(now),
         int(rating == 1 and card["state"] == "review"), card["id"]))
    if card["kind"] == "vocab" and outcome.stability > store.PRODUCE_AFTER_DAYS:
        conn.execute("""INSERT OR IGNORE INTO review_cards (kind, language, ref_table, ref_id, state)
                        VALUES ('vocab_produce', ?, ?, ?, 'new')""", (card["language"], card["ref_table"], card["ref_id"]))
    return {"id": card["id"], "rating": rating, "peeked": peeked, "next_due_at": clock.stamp(outcome.due_at),
            "interval_days": outcome.interval_days, "again_in_session": outcome.again_in_session,
            "stability": round(outcome.stability, 2)}


def grade(conn, card_id: int, rating=None, answer=None, answer_ms=None, request_id=None) -> dict:
    if request_id:
        logged = conn.execute("SELECT * FROM review_log WHERE request_id = ?", (request_id,)).fetchone()
        if logged is not None:
            if logged["card_id"] != card_id:
                raise CardError("这个 request_id 已用于另一张卡")
            card = _card(conn, card_id)
            return {"id": card_id, "rating": logged["rating"], "peeked": bool(logged["peeked"]),
                    "next_due_at": card["due_at"], "interval_days": fsrs.interval(logged["stability_after"])
                    if logged["rating"] > 1 and logged["stability_after"] else 0,
                    "again_in_session": logged["rating"] == 1, "stability": logged["stability_after"],
                    "replayed": True}
    card = _card(conn, card_id)
    if card["suspended"]:
        raise CardError("这张卡已暂停")
    value, peeked = _rating(conn, card, rating, answer, answer_ms)
    result = apply(conn, card, value, peeked=peeked, answer_ms=answer_ms, request_id=request_id)
    if card["kind"] in store.OBJECTIVE:
        result["correct"] = value > 1 and not peeked
    return result


def grade_legacy(conn, kind: str, item_id: str, item_index: int, outcome: str, attempt_id: str) -> None:
    """The old /review/attempt also moves the unified card (same attempt id, so never twice)."""
    store.sync(conn)
    card = conn.execute("SELECT * FROM review_cards WHERE kind = ? AND ref_id = ?",
                        (kind + "_q", f"{item_id}:{item_index}")).fetchone()
    if card is None or conn.execute("SELECT 1 FROM review_log WHERE request_id = ?", (attempt_id,)).fetchone():
        return
    apply(conn, card, 3 if outcome == "correct" else 1, peeked=outcome == "revealed", request_id=attempt_id)


def set_suspended(conn, card_id: int, suspended: bool) -> dict:
    _card(conn, card_id)
    conn.execute("UPDATE review_cards SET suspended = ? WHERE id = ?", (int(suspended), card_id))
    return {"id": card_id, "suspended": bool(suspended)}


# ---------------------------------------------------------------- summary and helpers for others


def due_count(conn, language: str) -> int:
    return conn.execute(
        """SELECT count(*) FROM review_cards WHERE language = ? AND suspended = 0 AND state <> 'new' AND due_at <= ?""",
        (language, clock.stamp())).fetchone()[0]


def retention(conn, language: str, days: int):
    since = clock.stamp(clock.now() - timedelta(days=days))
    rows = conn.execute(
        """SELECT l.rating, l.peeked FROM review_log l JOIN review_cards c ON c.id = l.card_id
           WHERE c.language = ? AND l.was_due = 1 AND l.weak = 0 AND l.at >= ?""", (language, since)).fetchall()
    if len(rows) < RETENTION_MIN_SAMPLES:
        return None
    return round(sum(1 for r in rows if r["rating"] > 1 and not r["peeked"]) / len(rows), 3)


def summary(conn, language: str) -> dict:
    store.sync(conn)
    now = clock.now()
    by_kind = {kind: 0 for kind in store.KINDS}
    for row in conn.execute(
            """SELECT kind, count(*) FROM review_cards WHERE language = ? AND suspended = 0 AND state <> 'new'
               AND due_at <= ? GROUP BY kind""", (language, clock.stamp(now))):
        by_kind[row[0]] = row[1]
    new_total = conn.execute("SELECT count(*) FROM review_cards WHERE language = ? AND suspended = 0 AND state = 'new'",
                             (language,)).fetchone()[0]
    room = max(0, store.setting(conn, "review_new_per_day") - _new_today(conn, language))
    forecast = []
    for offset in range(7):
        day = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
        if offset == 0:
            count = conn.execute(
                """SELECT count(*) FROM review_cards WHERE language = ? AND suspended = 0 AND state <> 'new'
                   AND due_at < ?""", (language, day + " 99")).fetchone()[0]
        else:
            count = conn.execute(
                """SELECT count(*) FROM review_cards WHERE language = ? AND suspended = 0 AND state <> 'new'
                   AND substr(due_at, 1, 10) = ?""", (language, day)).fetchone()[0]
        forecast.append({"date": day, "due": count})
    reviews_7d = conn.execute(
        """SELECT count(*) FROM review_log l JOIN review_cards c ON c.id = l.card_id
           WHERE c.language = ? AND l.at >= ? AND l.weak = 0""",
        (language, clock.stamp(now - timedelta(days=7)))).fetchone()[0]
    return {"language": language, "due_now": sum(by_kind.values()), "new_available": min(room, new_total),
            "by_kind": by_kind, "retention_7d": retention(conn, language, 7),
            "retention_30d": retention(conn, language, 30), "reviews_7d": reviews_7d, "forecast": forecast}


def due_vocab(conn, language: str, n: int = 2, near_text: str = "") -> list[dict]:
    """Due words for the chat rule "生词回炉" ({{due_vocab::N}}): [{id, lemma, reading, meaning, card_id}].

    Ordered by how overdue they are; when near_text is given and the semantic model is up,
    words close to the conversation come first.
    """
    store.sync(conn)
    rows = [dict(r) for r in conn.execute(
        """SELECT v.id, v.lemma, v.reading, v.meaning, c.id AS card_id FROM review_cards c
           JOIN vocab_entries v ON c.kind = 'vocab' AND c.ref_id = CAST(v.id AS TEXT)
           WHERE c.language = ? AND c.suspended = 0 AND c.state <> 'new' AND c.due_at <= ?
           ORDER BY c.due_at, c.id LIMIT 200""", (language, clock.stamp())).fetchall()]
    if near_text.strip() and len(rows) > n:
        try:
            from .. import semantic
            scores = semantic.similarities(near_text, [f"{r['lemma']} {r['meaning'] or ''}" for r in rows], timeout=0.5)
        except Exception:
            scores = None
        if scores is not None:
            rows = [rows[i] for i in sorted(range(len(rows)), key=lambda i: -scores[i])]
    return rows[:max(0, n)]


def reviews_due(conn, language: str) -> int:
    """Condition field `reviews_due`: cards due right now (all kinds)."""
    return due_count(conn, language)


def chat_success(conn, language: str, lemmas: list[str]) -> list[int]:
    """The user used a due word correctly in chat: weak evidence, a "good" with 70% of the growth."""
    store.sync(conn)
    folded = {_fold(lemma) for lemma in lemmas if lemma}
    graded = []
    for card in conn.execute(
            """SELECT c.*, v.lemma FROM review_cards c JOIN vocab_entries v ON c.ref_id = CAST(v.id AS TEXT)
               WHERE c.kind = 'vocab' AND c.language = ? AND c.suspended = 0 AND c.state <> 'new'
               AND c.due_at <= ?""", (language, clock.stamp())).fetchall():
        if _fold(card["lemma"]) in folded:
            apply(conn, card, 3, weight=0.7)
            graded.append(card["id"])
    return graded
