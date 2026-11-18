"""One word, many contexts; encounters; dictation comparison. docs/LEARNING.md 2.3 and 5.2."""
import difflib
import re
import unicodedata

from .. import clock
from . import store

MAX_CONTEXTS = 30


def _fold(text):
    return unicodedata.normalize("NFKC", text or "").casefold().strip()


def save_vocab(conn, body: dict) -> tuple[dict, bool]:
    """Save a word; saving one that exists adds a context instead. Returns (entry, created)."""
    sentence = (body.get("context_sentence") or "").strip()
    created = conn.execute(
        """INSERT INTO vocab_entries (language, lemma, surface, reading, meaning, pos, context_sentence, source_message_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(language, lemma) DO NOTHING""",
        (body["language"], body["lemma"], body.get("surface"), body.get("reading"), body.get("meaning"),
         body.get("pos"), sentence, body.get("source_message_id"))).rowcount == 1
    row = conn.execute("SELECT * FROM vocab_entries WHERE language = ? AND lemma = ?",
                       (body["language"], body["lemma"])).fetchone()
    vocab_id = row["id"]
    if not created:
        # Fill blanks the first save left; never overwrite what the user already has.
        for field in ("surface", "reading", "meaning", "pos"):
            if body.get(field) and not row[field]:
                conn.execute(f"UPDATE vocab_entries SET {field} = ? WHERE id = ?", (body[field], vocab_id))
    if sentence:
        add_context(conn, vocab_id, sentence, body.get("source_kind") or ("chat" if body.get("source_message_id") else "unknown"),
                    body.get("source_ref") or (str(body["source_message_id"]) if body.get("source_message_id") else None))
    store.sync(conn)
    return entry(conn, vocab_id), created


def entry(conn, vocab_id: int) -> dict:
    row = conn.execute("SELECT * FROM vocab_entries WHERE id = ?", (vocab_id,)).fetchone()
    if row is None:
        raise LookupError("没有这个词")
    card = conn.execute("SELECT id, state, stability, due_at, suspended FROM review_cards WHERE kind = 'vocab' AND ref_id = ?",
                        (str(vocab_id),)).fetchone()
    contexts = contexts_of(conn, vocab_id)
    return {**dict(row), "contexts": contexts, "context_count": len(contexts),
            "card": dict(card) if card else None,
            # "about N days": stability is when recall falls to 90%.
            "remember_days": round(card["stability"]) if card and card["stability"] else None}


def contexts_of(conn, vocab_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, sentence, source_kind, source_ref, created_at FROM vocab_contexts WHERE vocab_id = ? ORDER BY id",
        (vocab_id,))]


def add_context(conn, vocab_id: int, sentence: str, source_kind="unknown", source_ref=None) -> dict | None:
    sentence = sentence.strip()[:600]
    if not sentence:
        raise ValueError("语境句不能为空")
    if conn.execute("SELECT 1 FROM vocab_entries WHERE id = ?", (vocab_id,)).fetchone() is None:
        raise LookupError("没有这个词")
    if conn.execute("SELECT count(*) FROM vocab_contexts WHERE vocab_id = ?", (vocab_id,)).fetchone()[0] >= MAX_CONTEXTS:
        return None
    conn.execute(
        """INSERT OR IGNORE INTO vocab_contexts (vocab_id, sentence, source_kind, source_ref, created_at)
           VALUES (?, ?, ?, ?, ?)""", (vocab_id, sentence, source_kind[:20], source_ref, clock.stamp()))
    row = conn.execute("SELECT * FROM vocab_contexts WHERE vocab_id = ? AND sentence = ?", (vocab_id, sentence)).fetchone()
    return dict(row)


def delete_context(conn, vocab_id: int, context_id: int) -> bool:
    if conn.execute("SELECT count(*) FROM vocab_contexts WHERE vocab_id = ?", (vocab_id,)).fetchone()[0] <= 1:
        raise ValueError("至少留一条语境")
    return bool(conn.execute("DELETE FROM vocab_contexts WHERE id = ? AND vocab_id = ?", (context_id, vocab_id)).rowcount)


def _appears(word: str, text: str, language: str) -> bool:
    if not word:
        return False
    if language.startswith("ja") or not word.isascii():
        return word in text
    return re.search(rf"(?<![\w'-]){re.escape(word)}(?![\w'-])", text, re.IGNORECASE) is not None


def encounter(conn, language: str, text: str, ref: str | None = None, source: str = "reading") -> list[int]:
    """Count one encounter for every saved word that appears in `text` (once per ref)."""
    if ref and conn.execute("SELECT 1 FROM study_events WHERE kind = 'encounter' AND ref = ? AND language = ?",
                            (ref, language)).fetchone():
        return []
    hits = [row["id"] for row in conn.execute("SELECT id, lemma, surface FROM vocab_entries WHERE language = ?", (language,))
            if _appears(row["lemma"], text, language) or _appears(row["surface"] or "", text, language)]
    if hits:
        conn.executemany("UPDATE vocab_entries SET encounters = encounters + 1 WHERE id = ?", [(i,) for i in hits])
    store.record_event(conn, "encounter", language, ref, {"source": source, "words": len(hits)})
    return hits


def encounter_lemmas(conn, language: str, lemmas: list[str]) -> int:
    """For callers that already tokenized (chat): +1 for each saved lemma in the list."""
    folded = {_fold(l) for l in lemmas if l}
    ids = [row["id"] for row in conn.execute("SELECT id, lemma FROM vocab_entries WHERE language = ?", (language,))
           if _fold(row["lemma"]) in folded]
    conn.executemany("UPDATE vocab_entries SET encounters = encounters + 1 WHERE id = ?", [(i,) for i in ids])
    return len(ids)


# ---------------------------------------------------------------- dictation


def _words(text: str, language: str) -> list[dict]:
    return [{"text": w, "key": _fold(w).replace("’", "'"), "alt": ""}
            for w in re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE)]


def _compare_japanese(reference: str, typed: str) -> dict:
    """Japanese: tokenize the reference into words, then align both sides by reading (kana).

    Dictation checks hearing, not kanji choice, so 図書館 and としょかん both count; a word is
    ok when every kana of its reading is matched, missing when none is, wrong otherwise.
    """
    from ..tokenize import tokenize

    def kana(token):
        return _fold(token.get("reading") or token["surface"])
    ref = [t for t in tokenize(reference, "ja") if t.get("clickable")]
    spans, text = [], ""
    for token in ref:
        spans.append((len(text), len(text) + len(kana(token))))
        text += kana(token)
    typed_text = "".join(kana(t) for t in tokenize(typed, "ja") if t.get("clickable"))
    matched_ref, matched_typed = set(), set()
    for block in difflib.SequenceMatcher(a=text, b=typed_text, autojunk=False).get_matching_blocks():
        matched_ref.update(range(block.a, block.a + block.size))
        matched_typed.update(range(block.b, block.b + block.size))
    words = []
    for token, (start, end) in zip(ref, spans):
        hit = sum(1 for i in range(start, end) if i in matched_ref)
        status = "ok" if hit == end - start else "missing" if hit == 0 else "wrong"
        words.append({"text": token["surface"], "status": status})
    extra, run = [], ""
    for i, char in enumerate(typed_text):
        if i in matched_typed:
            if run:
                extra.append(run)
            run = ""
        else:
            run += char
    if run:
        extra.append(run)
    return words, extra


def compare(reference: str, typed: str, language: str) -> dict:
    """Word-by-word: each reference word is ok / wrong / missing; extra typed words are listed. No model."""
    if language.startswith("ja"):
        words, extra = _compare_japanese(reference, typed)
        correct = sum(1 for w in words if w["status"] == "ok")
        return {"words": words, "extra": extra, "correct": correct, "total": len(words),
                "score": round(correct / len(words), 3) if words else None}
    ref, got = _words(reference, language), _words(typed, language)
    keys_ref = [w["key"] for w in ref]
    keys_got = [g["key"] for g in got]
    words, extra = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=keys_ref, b=keys_got, autojunk=False).get_opcodes():
        if tag == "equal":
            words += [{"text": ref[i]["text"], "status": "ok"} for i in range(i1, i2)]
        elif tag == "replace":
            for k, i in enumerate(range(i1, i2)):
                typed_word = got[j1 + k]["text"] if j1 + k < j2 else None
                words.append({"text": ref[i]["text"], "status": "wrong" if typed_word else "missing", "typed": typed_word})
            extra += [got[j]["text"] for j in range(j1 + (i2 - i1), j2)]
        elif tag == "delete":
            words += [{"text": ref[i]["text"], "status": "missing"} for i in range(i1, i2)]
        else:
            extra += [got[j]["text"] for j in range(j1, j2)]
    correct = sum(1 for w in words if w["status"] == "ok")
    return {"words": words, "extra": extra, "correct": correct, "total": len(ref),
            "score": round(correct / len(ref), 3) if ref else None}
