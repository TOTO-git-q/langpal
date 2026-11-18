"""Today, advice, statistics, encounters and learning settings. docs/LEARNING.md sections 3-4.

All read-only except POST /learning/encounters. Same-origin only.
"""
from contextlib import closing
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..db import get_conn
from ..security import same_origin
from ..services.languages import LanguageTag
from ..services.learning import insights, store, words

router = APIRouter(tags=["learning"], dependencies=[Depends(same_origin)])


@router.get("/today")
def today(language: LanguageTag):
    with closing(get_conn()) as conn, conn:
        return insights.today(conn, language)


@router.get("/learning/advice")
def advice(language: LanguageTag):
    with closing(get_conn()) as conn, conn:
        return insights.advice(conn, language)


@router.get("/learning/stats")
def stats(language: LanguageTag, days: int = Query(30, ge=1, le=365)):
    with closing(get_conn()) as conn, conn:
        return insights.stats(conn, language, days)


@router.get("/learning/settings")
def learning_settings():
    """Current values with defaults. Written through the general settings API (PUT /api/settings)."""
    with closing(get_conn()) as conn:
        return {**store.settings(conn), "types": insights.TYPES, "causes": insights.CAUSES}


class EncounterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: LanguageTag
    text: Annotated[str, StringConstraints(min_length=1, max_length=60000)]
    ref: Annotated[str, StringConstraints(min_length=1, max_length=800)]
    source: Literal["reading", "listening", "chat"] = "reading"


@router.post("/learning/encounters")
def encounters(body: EncounterIn):
    """Saved words that appear in an article or transcript: +1 encounter each, once per ref."""
    with closing(get_conn()) as conn, conn:
        hits = words.encounter(conn, body.language, body.text, body.ref, body.source)
    return {"words": len(hits), "vocab_ids": hits}
