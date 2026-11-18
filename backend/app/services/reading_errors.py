"""Persist delivered reading sets and grade against server-owned answer keys."""
import json
import re
from contextlib import closing

from ..db import get_conn


JAPANESE = re.compile(r"[\u3040-\u30ff]")
JA_PARAGRAPH_LIMIT = 400


def _japanese_paragraph(text, quote):
    """Japanese pages mark paragraphs with a line break or a full-width-space indent, rarely a blank line.
    Use the paragraph holding the quote; when it is long, the quoted sentences plus one on each side."""
    paragraphs = [p.strip() for p in re.split(r"\n+|(?=\u3000)", text) if p.strip()]
    start = text.find(quote)
    paragraph = next((p for p in paragraphs if quote in p), None)
    if paragraph is None:  # the quote crosses a paragraph break: take the paragraphs it touches
        paragraph = text[max(0, text.rfind("\n", 0, start) + 1):text.find("\n", start + len(quote)) % (len(text) + 1)].strip()
    if len(paragraph) <= JA_PARAGRAPH_LIMIT:
        return paragraph
    sentences = [s for s in re.split(r"(?<=[。！？])", paragraph) if s]
    offsets, position = [], 0
    for sentence in sentences:
        offsets.append((position, position + len(sentence)))
        position += len(sentence)
    begin = paragraph.find(quote)
    stop = begin + len(quote)
    hit = [i for i, (a, b) in enumerate(offsets) if a < stop and b > begin]
    first, last = max(0, hit[0] - 1), min(len(sentences) - 1, hit[-1] + 1)
    return ("…" if first else "") + "".join(sentences[first:last + 1]).strip() + ("…" if last < len(sentences) - 1 else "")


def evidence_paragraph(text, quote):
    """The part of the article a question's quote comes from (stored with the question, shown with the mistake)."""
    if not quote or quote not in text:
        return text.strip()[:2200]
    if JAPANESE.search(quote):
        return _japanese_paragraph(text, quote)
    paragraphs = re.split(r"\n[ \t]*\n", text)
    paragraph = next((p for p in paragraphs if quote in p), text)
    if len(paragraph) > 700:
        # Pages whose paragraphs are separated by single line breaks (Wikipedia text, feeds):
        # use the line that holds the quote, with the line before it for context when short.
        lines = paragraph.split("\n")
        hit = next((i for i, line in enumerate(lines) if quote in line), None)
        if hit is not None:
            chosen = lines[hit]
            if len(chosen) < 250 and hit > 0:
                chosen = lines[hit - 1] + "\n" + chosen
            paragraph = chosen
    if len(paragraph) <= 2200:
        return paragraph.strip()
    center = paragraph.index(quote)
    start = max(0, center - 900)
    end = min(len(paragraph), center + len(quote) + 900)
    return ("…" if start else "") + paragraph[start:end].strip() + ("…" if end < len(paragraph) else "")


def item_with_evidence(item):
    """Older Japanese sets stored the whole article as the paragraph; cut it down when read."""
    if item.get("quote") and item.get("paragraph"):
        return {**item, "paragraph": evidence_paragraph(item["paragraph"], item["quote"])}
    return item


def load_set(ident):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT payload_json FROM reading_exercises WHERE id = ?", (ident,)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def save_set(ident, body, data):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO reading_exercises VALUES (?, ?, ?, ?, ?)",
            (ident, body.language, body.title, body.url, json.dumps(data, ensure_ascii=False)),
        )
        row = conn.execute("SELECT payload_json FROM reading_exercises WHERE id = ?", (ident,)).fetchone()
        return json.loads(row["payload_json"])


def submit(ident, choices):
    with closing(get_conn()) as conn, conn:
        row = conn.execute("SELECT payload_json FROM reading_exercises WHERE id = ?", (ident,)).fetchone()
        if row is None:
            raise LookupError("阅读题不存在")
        items = json.loads(row["payload_json"])["items"]
        if (not isinstance(choices, list) or len(choices) != len(items)
                or any(type(picked) is not int or not 0 <= picked < len(item["options"])
                       for picked, item in zip(choices, items))):
            raise ValueError("请完成每一道题")
        errors = [(ident, index, picked) for index, (picked, item) in enumerate(zip(choices, items)) if picked != item["answer"]]
        conn.executemany(
            """INSERT INTO reading_errors (exercise_id, item_index, selected) VALUES (?, ?, ?)
               ON CONFLICT(exercise_id, item_index) DO UPDATE SET selected = excluded.selected, updated_at = datetime('now')
               WHERE reading_errors.selected <> excluded.selected""",
            errors,
        )
        return {"correct": len(items) - len(errors), "items": items, "saved_errors": len(errors)}


def entries(language):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT e.exercise_id, e.item_index, e.selected, e.updated_at,
                      s.title, s.language, s.source_url, s.payload_json
               FROM reading_errors e JOIN reading_exercises s ON s.id = e.exercise_id
               WHERE (? IS NULL OR s.language = ?)
               ORDER BY e.updated_at DESC, e.exercise_id, e.item_index LIMIT 150""",
            (language, language),
        ).fetchall()
    return [
        {**{key: row[key] for key in ("exercise_id", "item_index", "selected", "updated_at", "title", "language", "source_url")},
         **item_with_evidence(json.loads(row["payload_json"])["items"][row["item_index"]])}
        for row in rows
    ]


def delete_error(exercise_id, item_index):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("DELETE FROM reading_errors WHERE exercise_id = ? AND item_index = ?",
                            (exercise_id, item_index)).rowcount:
            return False
        conn.execute("DELETE FROM review_cards WHERE kind = 'reading_q' AND ref_table = 'reading_errors' AND ref_id = ?",
                     (f"{exercise_id}:{item_index}",))
        for table in ("review_states", "review_attempts"):
            conn.execute(f"DELETE FROM {table} WHERE kind = 'reading' AND item_id = ? AND item_index = ?",
                         (exercise_id, item_index))
    return True
