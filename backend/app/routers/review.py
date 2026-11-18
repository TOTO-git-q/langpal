"""Review API. `/queue`, `/cards/*`, `/summary`, `/session/end` are the unified FSRS queue
(docs/LEARNING.md 2.5); `/state` and `/attempt` are the older mistake-only API, kept for the
current front end. An old-style attempt also grades the matching unified card."""
import logging
from contextlib import closing
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..db import get_conn
from ..security import same_origin
from ..services import learning, review
from ..services.languages import LanguageTag
from ..services.learning import cards

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(same_origin)])
_log = logging.getLogger(__name__)



class ReviewAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["reading", "listening"]
    item_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
    item_index: Annotated[StrictInt, Field(ge=0, le=99)]
    selection: Annotated[StrictInt, Field(ge=0, le=4)] | None = None
    mode: Literal["independent", "revealed"]
    attempt_id: UUID

    @model_validator(mode="after")
    def require_selection(self):
        if self.mode == "independent" and self.selection is None:
            raise ValueError("Independent practice requires a selection")
        return self


@router.get("/capabilities")
def capabilities():
    return dict(version=1, persisted_attempts=True, interval_days=review.INTERVALS, timezone="UTC")


@router.get("/state")
def state(lang: LanguageTag | None = None):
    return review.states(lang)


@router.post("/attempt")
def attempt(body: ReviewAttempt):
    try:
        replay = review.is_recorded(body.attempt_id)
        result = review.attempt(body)
        if not replay:  # 同一个 attempt_id 重发只算一次
            _done(body.kind, body.item_id, result.get("correct"))
            try:
                with closing(get_conn()) as conn, conn:
                    cards.grade_legacy(conn, body.kind, body.item_id, body.item_index, result["outcome"],
                                       str(body.attempt_id))
            except Exception:
                _log.warning("统一复习卡没跟上旧错题复习，下次同步时补", exc_info=True)
        return result
    except review.ConflictError as error:
        raise HTTPException(409, str(error)) from None
    except review.CapacityError as error:
        raise HTTPException(429, str(error)) from None
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def _done(kind: str, item_id: str, correct) -> None:
    """hook 事件 study.review_done：后台发，复习本身不等它。语言从原题所在的那组查。"""
    from ..services import hooks

    def meta(conn):
        table = "reading_exercises" if kind == "reading" else "listening_error_sets"
        row = conn.execute(f"SELECT language FROM {table} WHERE id = ?", (item_id,)).fetchone()
        return {"language": row[0]} if row else {}

    hooks.emit_soon("study.review_done", None, {"kind": kind, "correct": correct}, resolve=meta)


# ---------------------------------------------------------------- unified queue


def _run(action, *args, **kwargs):
    try:
        with closing(get_conn()) as conn, conn:
            return action(conn, *args, **kwargs)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/queue")
def queue(language: LanguageTag, kinds: str = Query("", max_length=200), limit: int = Query(50, ge=1, le=200)):
    return _run(cards.queue, language, [k for k in kinds.split(",") if k], limit)


class Reveal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Annotated[StrictInt, Field(ge=0, le=4)] | Annotated[str, Field(max_length=200)] | None = None
    gave_up: bool = False


@router.post("/cards/{card_id}/reveal")
def reveal(card_id: int, body: Reveal | None = None):
    body = body or Reveal()
    return _run(cards.reveal, card_id, body.answer, body.gave_up)


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Annotated[StrictInt, Field(ge=1, le=4)] | None = None
    answer: Annotated[StrictInt, Field(ge=0, le=4)] | Annotated[str, Field(max_length=200)] | None = None
    answer_ms: Annotated[StrictInt, Field(ge=0, le=3_600_000)] | None = None
    request_id: Annotated[str, Field(min_length=8, max_length=80)]


def _grade(conn, card_id, body: Grade):
    result = cards.grade(conn, card_id, body.rating, body.answer, body.answer_ms, body.request_id)
    card = conn.execute("SELECT language FROM review_cards WHERE id = ?", (card_id,)).fetchone()
    # The queue for this language just emptied: that closes the session.
    if not result.get("replayed") and card and cards.due_count(conn, card["language"]) == 0 and not conn.execute(
            """SELECT 1 FROM review_cards WHERE language = ? AND suspended = 0 AND state IN ('learning','relearning')""",
            (card["language"],)).fetchone():
        result["session"] = learning.end_session(conn, card["language"])
    return result


@router.post("/cards/{card_id}/grade")
def grade(card_id: int, body: Grade):
    return _run(_grade, card_id, body)


class CardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suspended: bool


@router.put("/cards/{card_id}")
def update_card(card_id: int, body: CardUpdate):
    return _run(cards.set_suspended, card_id, body.suspended)


@router.get("/summary")
def summary(language: LanguageTag):
    return _run(cards.summary, language)


class SessionEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: LanguageTag


@router.post("/session/end")
def end_session(body: SessionEnd):
    """The user left the review screen. Records the session (if anything was graded) and fires the event."""
    return {"session": _run(lambda conn: learning.end_session(conn, body.language))}
