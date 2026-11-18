"""Shared target-language registry for study tools and chat sessions."""
import json
import re
from contextlib import closing
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from ..db import get_conn

_TAG = re.compile(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{4})?(?:-[a-zA-Z]{2}|-[0-9]{3})?")
REGISTRY_KEY = "study_languages"
BUILTINS = {"ja": "日本語", "en": "English", "de": "Deutsch"}


def canonical(tag: str) -> str:
    tag = tag.strip()
    if not _TAG.fullmatch(tag):
        raise ValueError("请使用语言代码，例如 fr、pt-BR 或 zh-Hant")
    root, *parts = tag.split("-")
    return "-".join([root.lower(), *(part.title() if len(part) == 4 else part.upper() for part in parts)])


LanguageTag = Annotated[str, AfterValidator(canonical)]


class LanguageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tag: LanguageTag
    label: Annotated[str, StringConstraints(min_length=1, max_length=50)]


def base(tag: str) -> str:
    return tag.split("-", 1)[0]


def registered(conn) -> dict[str, str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (REGISTRY_KEY,)).fetchone()
    try:
        stored = json.loads(row[0]) if row else {}
    except (ValueError, TypeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {**{tag: label for tag, label in stored.items() if isinstance(label, str)}, **BUILTINS}


def catalog() -> dict[str, str]:
    with closing(get_conn()) as conn:
        return registered(conn)


def add(body: LanguageInput) -> dict:
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        items = registered(conn)
        if body.tag in items:
            raise ValueError("此语言已存在")
        if len(items) >= 30:
            raise ValueError("最多可添加 30 种语言")
        items[body.tag] = body.label
        custom = {tag: label for tag, label in items.items() if tag not in BUILTINS}
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (REGISTRY_KEY, json.dumps(custom, ensure_ascii=False)))
    return {"tag": body.tag, "label": body.label}


def display(tag: str) -> str:
    # Always include the exact tag. A custom label is display data.
    try:
        label = catalog().get(tag)
    except Exception:
        label = BUILTINS.get(tag)
    return f"{label} ({tag})" if label else tag
