"""Shared listening plans, edited by the concierge and consumed by practice."""
import json
from contextlib import closing
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..db import get_conn
from . import languages
from .listening_formats import profiles_for

PREFIX = 'listening_plan:'


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    format: str = Field(default='auto', min_length=1, max_length=32)
    difficulty: Literal['default', 'foundation', 'intermediate', 'challenge'] = 'default'
    topic: str = Field(default='', max_length=120)


def read(conn, language):
    row = conn.execute('SELECT value FROM settings WHERE key=?', (PREFIX + language,)).fetchone()
    try:
        plan = Plan.model_validate_json(row[0]) if row else Plan()
        validate(language, plan)
        return plan
    except ValueError:
        return Plan()


def validate(language, plan):
    if plan.format != 'auto' and plan.format not in profiles_for(language):
        raise ValueError('请选择这门语言可用的听力题型。')


def save(conn, language, plan):
    if language not in languages.registered(conn):
        raise ValueError('请先添加这门学习语言。')
    validate(language, plan)
    conn.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (PREFIX + language, plan.model_dump_json()))


def catalog():
    with closing(get_conn()) as conn:
        return {tag: read(conn, tag).model_dump() for tag in languages.registered(conn)}

