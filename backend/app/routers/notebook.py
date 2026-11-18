"""收藏路由：单词本 / 句型本。

一个词一条词条、可挂多条语境：再次收藏同一个词 = 加一条语境（docs/LEARNING.md 2.3）。
收藏的词和句型会自动生成统一复习队列里的卡（services/learning）。
"""
from contextlib import closing
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from ..db import get_conn
from ..security import same_origin
from ..services import hooks
from ..services.languages import LanguageTag
from ..services.learning import store, words

router = APIRouter(tags=["notebook"], dependencies=[Depends(same_origin)])

SourceKind = Literal["chat", "reading", "listening", "manual"]


class VocabIn(BaseModel):
    language: LanguageTag
    lemma: str
    surface: str | None = None
    reading: str | None = None
    meaning: str | None = None
    pos: str | None = None
    context_sentence: str
    source_message_id: int | None = None
    source_kind: SourceKind | None = None
    source_ref: str | None = None


class PatternIn(BaseModel):
    language: LanguageTag
    pattern_name: str
    explanation: str | None = None
    example_sentence: str | None = None
    translation: str | None = None
    source_message_id: int | None = None


@router.get("/vocab")
def list_vocab(language: str | None = None):
    with closing(get_conn()) as conn:
        if language is None:
            rows = conn.execute("SELECT * FROM vocab_entries").fetchall()
        else:
            rows = conn.execute("SELECT * FROM vocab_entries WHERE language = ?", (language,)).fetchall()
        return {"items": [dict(row) for row in rows]}


@router.post("/vocab")
def add_vocab(body: VocabIn):
    """Saving a word that is already saved adds this sentence as one more context."""
    with closing(get_conn()) as conn, conn:
        entry, created = words.save_vocab(conn, body.model_dump())
    if created:
        hooks.emit_soon("study.vocab_saved", None, {"lemma": body.lemma, "language": body.language})
    return {**entry, "created": created}


@router.get("/vocab/{entry_id}")
def vocab_detail(entry_id: int):
    """All contexts, encounters, the review card and "about N days" of memory."""
    try:
        with closing(get_conn()) as conn:
            return words.entry(conn, entry_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None


@router.delete("/vocab/{entry_id}")
def delete_vocab(entry_id: int):
    with closing(get_conn()) as conn, conn:
        conn.execute("DELETE FROM vocab_contexts WHERE vocab_id = ?", (entry_id,))
        if conn.execute("DELETE FROM vocab_entries WHERE id = ?", (entry_id,)).rowcount == 0:
            raise HTTPException(404, "not found")
        conn.execute("DELETE FROM review_cards WHERE kind IN ('vocab','vocab_produce') AND ref_id = ?", (str(entry_id),))
    return {"ok": True}


class ContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentence: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    source_kind: SourceKind = "manual"
    source_ref: Annotated[str, StringConstraints(max_length=300)] | None = None


class MeaningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meaning: Annotated[str, StringConstraints(min_length=1, max_length=300)]


@router.put("/notebook/{entry_id}")
def update_vocab(entry_id: int, body: MeaningIn):
    with closing(get_conn()) as conn, conn:
        if not conn.execute("UPDATE vocab_entries SET meaning = ? WHERE id = ?", (body.meaning, entry_id)).rowcount:
            raise HTTPException(404, "not found")
        return words.entry(conn, entry_id)


@router.get("/vocab/{entry_id}/contexts")
def list_contexts(entry_id: int):
    with closing(get_conn()) as conn:
        if conn.execute("SELECT 1 FROM vocab_entries WHERE id = ?", (entry_id,)).fetchone() is None:
            raise HTTPException(404, "not found")
        return {"items": words.contexts_of(conn, entry_id)}


@router.post("/vocab/{entry_id}/contexts", status_code=201)
def add_context(entry_id: int, body: ContextIn):
    try:
        with closing(get_conn()) as conn, conn:
            row = words.add_context(conn, entry_id, body.sentence, body.source_kind, body.source_ref)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    if row is None:
        raise HTTPException(409, "这个词的语境已经够多了")
    return row


@router.delete("/vocab/{entry_id}/contexts")
def delete_context(entry_id: int, context_id: int):
    try:
        with closing(get_conn()) as conn, conn:
            if not words.delete_context(conn, entry_id, context_id):
                raise HTTPException(404, "没有这条语境")
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return {"ok": True}


@router.get("/patterns")
def list_patterns(language: str | None = None):
    with closing(get_conn()) as conn:
        if language is None:
            rows = conn.execute("SELECT * FROM pattern_entries").fetchall()
        else:
            rows = conn.execute("SELECT * FROM pattern_entries WHERE language = ?", (language,)).fetchall()
        return {"items": [dict(row) for row in rows]}


@router.post("/patterns")
def add_pattern(body: PatternIn):
    with closing(get_conn()) as conn, conn:
        new_id = conn.execute(
            """INSERT INTO pattern_entries
               (language, pattern_name, explanation, example_sentence, translation, source_message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.language, body.pattern_name, body.explanation, body.example_sentence, body.translation,
             body.source_message_id)).lastrowid
        store.sync(conn)
        entry = dict(conn.execute("SELECT * FROM pattern_entries WHERE id = ?", (new_id,)).fetchone())
    hooks.emit_soon("study.pattern_saved", None, {"language": body.language})
    return entry


@router.delete("/patterns/{entry_id}")
def delete_pattern(entry_id: int):
    with closing(get_conn()) as conn, conn:
        if conn.execute("DELETE FROM pattern_entries WHERE id = ?", (entry_id,)).rowcount == 0:
            raise HTTPException(404, "not found")
        conn.execute("DELETE FROM review_cards WHERE kind = 'pattern' AND ref_id = ?", (str(entry_id),))
    return {"ok": True}
