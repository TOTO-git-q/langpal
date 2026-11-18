"""Bounded reader typography shared by settings and the workspace Agent."""
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..db import get_conn

STYLE_KEY = "reader_style"


class Style(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int = Field(17, ge=14, le=26)
    line_height: float = Field(1.85, ge=1.35, le=2.25)
    measure: int = Field(75, ge=44, le=90)
    font: Literal["serif", "sans"] = "serif"
    theme: Literal["lilac", "paper", "night"] = "lilac"


def get() -> Style:
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (STYLE_KEY,)).fetchone()
    return Style.model_validate_json(row[0]) if row else Style()


def save(body: Style) -> Style:
    with closing(get_conn()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (STYLE_KEY, body.model_dump_json()))
    return body
