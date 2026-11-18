"""Persist user-defined reading formats and defaults in the existing settings table."""
import hashlib
import json
import re
import secrets
from contextlib import closing

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..db import get_conn
from . import languages, reading_formats

FORMAT_PREFIX = "reader-format:"
DEFAULTS_KEY = "reader-defaults-v1"
CUSTOM_LIMITS = {"en": (15, 1400), "ja": (40, 3200)}
BUILTINS = (
    {"id": "toefl", "name": "TOEFL", "language": "en", "builtin": True},
    {"id": "gre", "name": "GRE", "language": "en", "builtin": True},
    {"id": "jlpt", "name": "JLPT N1", "language": "ja", "builtin": True},
)


class FormatInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    language: languages.LanguageTag
    min_length: int = Field(strict=True, ge=1, le=3200)
    max_length: int = Field(strict=True, ge=1, le=3200)
    target_length: int = Field(strict=True, ge=1, le=3200)
    question_count: int = Field(strict=True, ge=1, le=8)
    skills: str = Field(min_length=5, max_length=600)

    @model_validator(mode="after")
    def validate_lengths(self):
        lower, upper = reading_formats.limits(self.language, custom=True)
        if not lower <= self.min_length <= self.target_length <= self.max_length <= upper:
            raise ValueError(f"长度须在 {lower}–{upper} 内，且最短 ≤ 默认 ≤ 最长")
        return self


class DefaultsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper: str | None = Field(default=None, max_length=80)
    article_en: str | None = Field(default=None, max_length=80)
    article_ja: str | None = Field(default=None, max_length=80)
    format_en: str | None = Field(default=None, max_length=80)
    format_ja: str | None = Field(default=None, max_length=80)
    article_by_language: dict[languages.LanguageTag, str] = Field(default_factory=dict, max_length=30)
    format_by_language: dict[languages.LanguageTag, str] = Field(default_factory=dict, max_length=30)


def _key(ident):
    if not re.fullmatch(r"reading-[a-f0-9]{16}", ident):
        raise LookupError("没有找到这个阅读格式")
    return FORMAT_PREFIX + ident


def _custom_record(row):
    if row is None:
        return None
    return {
        **json.loads(row["value"]),
        "id": row["key"].removeprefix(FORMAT_PREFIX),
        "builtin": False,
    }


def list_formats():
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY rowid",
            (FORMAT_PREFIX + "%",),
        ).fetchall()
        tags = languages.registered(conn)
    generic = [{"id": "general", "name": "通用阅读", "language": tag, "builtin": True}
               for tag in tags if tag not in {"en", "ja"}]
    return [*BUILTINS, *generic, *map(_custom_record, rows)]


def custom_format(ident):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT key, value FROM settings WHERE key = ?", (_key(ident),)).fetchone()
    if row is None:
        raise LookupError("这个阅读格式已删除")
    return _custom_record(row)


def save_format(body, ident=None):
    new = ident is None
    ident = ident or "reading-" + secrets.token_hex(8)
    encoded = body.model_dump_json()
    with closing(get_conn()) as conn, conn:
        if new:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (_key(ident), encoded))
        else:
            result = conn.execute("UPDATE settings SET value = ? WHERE key = ?", (encoded, _key(ident)))
            if not result.rowcount:
                raise LookupError("这个阅读格式已删除")
    return {"id": ident, "builtin": False, **body.model_dump()}


def delete_format(ident):
    with closing(get_conn()) as conn, conn:
        result = conn.execute("DELETE FROM settings WHERE key = ?", (_key(ident),))
        if not result.rowcount:
            raise LookupError("这个阅读格式已删除")


def defaults():
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (DEFAULTS_KEY,)).fetchone()
    return (DefaultsInput.model_validate_json(row["value"]) if row else DefaultsInput()).model_dump()


def save_defaults(body):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (DEFAULTS_KEY, body.model_dump_json()),
        )


def revision(custom):
    if not custom:
        return ""
    return hashlib.sha256(json.dumps(custom, sort_keys=True).encode()).hexdigest()
