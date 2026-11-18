"""世界书 version 2 的数据模型（字段、默认值、上限）。version 1 的旧书在校验时自动升级。"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ..situation import Condition

POSITIONS = ("before_persona", "after_persona", "turn")
LOGICS = ("and_any", "and_all", "not_any", "not_all")
Position = Literal["before_persona", "after_persona", "turn"]

MAX_BOOKS = 200
MAX_ENTRIES = 500
MAX_CONTENT = 4000
MAX_KEYS = 40
MAX_BOOK_CHARS = 400_000
MAX_EXTENSIONS = 20_000

_REGEX_KEY = re.compile(r"^/(.+)/([a-z]*)$", re.S)
Key = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def parse_regex(key: str):
    """'/pattern/flags' -> 编译好的正则；不是这种写法返回 None；写错了抛 ValueError。"""
    match = _REGEX_KEY.match(key)
    if not match:
        return None
    flags = 0
    for flag in match.group(2):
        if flag == "i":
            flags |= re.IGNORECASE
        elif flag == "m":
            flags |= re.MULTILINE
        elif flag == "s":
            flags |= re.DOTALL
        elif flag in "guy":
            continue
        else:
            raise ValueError(f"正则关键词 {key} 的标志 {flag} 不认识")
    try:
        return re.compile(match.group(1), flags)
    except re.error as error:
        raise ValueError(f"正则关键词 {key} 写错了：{error}") from None


def _check_keys(keys: list[str]) -> list[str]:
    cleaned = []
    for key in keys:
        key = key.strip()
        if not key:
            continue
        parse_regex(key)
        cleaned.append(key)
    return cleaned


class Entry(Strict):
    uid: int = Field(0, ge=0, le=10**9)
    title: str = Field("", max_length=200)
    content: str = Field("", max_length=MAX_CONTENT)
    enabled: bool = True
    constant: bool = False
    keys: list[Key] = Field(default_factory=list, max_length=MAX_KEYS)
    secondary_keys: list[Key] = Field(default_factory=list, max_length=MAX_KEYS)
    logic: Literal["and_any", "and_all", "not_any", "not_all"] = "and_any"
    case_sensitive: bool = False
    whole_words: bool = False
    lemma: bool | None = None
    semantic: bool = False
    semantic_threshold: float = Field(0.84, ge=0.5, le=1.0)
    position: Position = "turn"
    order: int = Field(100, ge=-100000, le=100000)
    probability: int = Field(100, ge=0, le=100)
    scan_depth: int | None = Field(None, ge=0, le=100)
    sticky: int = Field(0, ge=0, le=1000)
    cooldown: int = Field(0, ge=0, le=1000)
    delay: int = Field(0, ge=0, le=1_000_000)
    group: str = Field("", max_length=200)
    group_weight: int = Field(100, ge=1, le=100000)
    group_override: bool = False
    exclude_recursion: bool = False
    prevent_recursion: bool = False
    delay_until_recursion: bool = False
    conditions: list[Condition] = Field(default_factory=list, max_length=12)
    automation_id: str = Field("", max_length=120)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def default_position(cls, data):
        if isinstance(data, dict) and data.get("position") in (None, ""):
            data = {**data, "position": "after_persona" if data.get("constant") else "turn"}
        return data

    @field_validator("keys", "secondary_keys")
    @classmethod
    def valid_keys(cls, value):
        return _check_keys(value)

    @field_validator("title", "group", "automation_id")
    @classmethod
    def strip(cls, value):
        return value.strip()

    @field_validator("extensions")
    @classmethod
    def small_extensions(cls, value):
        if len(json.dumps(value, ensure_ascii=False, default=str)) > MAX_EXTENSIONS:
            raise ValueError("条目的 extensions 太大")
        return value

    def groups(self) -> list[str]:
        return [g.strip() for g in self.group.split(",") if g.strip()]


class BookSettings(Strict):
    scan_depth: int = Field(4, ge=0, le=100)
    budget_chars: int = Field(1600, ge=0, le=50000)
    recursion: bool = True
    max_recursion: int = Field(3, ge=0, le=10)
    lemma_match: bool = True


def upgrade_v1(data: dict) -> dict:
    """version 1（title/keywords/content/enabled）→ version 2。没有关键词的旧条目当常驻。"""
    entries = []
    for item in data.get("entries") or []:
        if not isinstance(item, dict):
            entries.append(item)
            continue
        keywords = [k for k in item.get("keywords") or [] if isinstance(k, str)]
        entries.append({
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "enabled": item.get("enabled", True),
            "keys": keywords,
            "constant": not keywords,
        })
    return {"version": 2, "entries": entries}


def is_v1(data) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("version") == 1:
        return True
    if "version" in data or "settings" in data:
        return False
    return any(isinstance(e, dict) and "keywords" in e for e in data.get("entries") or [])


class Book(Strict):
    version: Literal[2] = 2
    settings: BookSettings = Field(default_factory=BookSettings)
    entries: list[Entry] = Field(default_factory=list, max_length=MAX_ENTRIES)

    @model_validator(mode="before")
    @classmethod
    def upgrade(cls, data):
        if is_v1(data):
            return upgrade_v1(data)
        return data

    @model_validator(mode="after")
    def assign_uids(self):
        if sum(len(e.content) for e in self.entries) > MAX_BOOK_CHARS:
            raise ValueError("这本世界书的正文总量太大")
        seen: set[int] = set()
        top = max((e.uid for e in self.entries), default=0)
        for entry in self.entries:
            if entry.uid <= 0 or entry.uid in seen:
                top += 1
                entry.uid = top
            seen.add(entry.uid)
        return self


Scope = Literal["global", "attached"]


def compact(book: Book) -> dict:
    """只留和默认值不一样的字段（给课程管家看，省上下文）；version 总是带上。"""
    data = book.model_dump(exclude_defaults=True)
    entries = []
    for entry in book.entries:
        item = entry.model_dump(exclude_defaults=True)
        item["uid"] = entry.uid
        default_position = "after_persona" if entry.constant else "turn"
        if entry.position != default_position:
            item["position"] = entry.position
        else:
            item.pop("position", None)
        entries.append(item)
    data["entries"] = entries
    return {"version": 2, **{k: v for k, v in data.items() if k != "version"}}
