"""Course selection and lesson content fingerprints."""
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from .. import languages
from . import lessons

SETTINGS_PREFIX = "teaching_language:"
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Teaching(StrictModel):
    mode: Literal["off", "ambient"] = "off"
    preset: Slug | None = Field(default=None, validation_alias=AliasChoices("preset", "preset_id"))

    @model_validator(mode="after")
    def selected_course(self):
        if self.mode == "ambient" and not self.preset:
            raise ValueError("请先选一份教学大纲")
        return self

@lru_cache(maxsize=1)
def presets() -> dict[str, lessons.Course]:
    return lessons.courses()


def resolve(settings: Teaching, language: str) -> lessons.Course | None:
    outline = presets().get(settings.preset) if settings.preset else None
    if settings.preset and outline is None:
        raise ValueError("找不到这份预制大纲")
    if outline and outline.language != language:
        raise ValueError("大纲语言需要与所选学习语言一致")
    return outline


def validate_profile(profile: dict, language: str, conn=None) -> dict:
    result = profile.copy()
    # 世界书相关的两个键（world_book / world_book_ids）由世界书模块校验
    from .. import lore
    return lore.validate_profile(result, conn)

def language_settings(conn, language: str) -> Teaching:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTINGS_PREFIX + language,)).fetchone()
    if row:
        try:
            settings = Teaching.model_validate_json(row[0])
            resolve(settings, language)
            return settings
        except ValueError:
            pass
    return Teaching()

def save_language_settings(conn, language: str, teaching: Teaching) -> None:
    if language not in languages.registered(conn):
        raise ValueError("请先添加这门语言")
    resolve(teaching, language)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 (SETTINGS_PREFIX + language, teaching.model_dump_json(exclude_none=True)))

def point_key(outline, unit_id, point_id):
    return hashlib.sha256(f'{outline.id}/{unit_id}/{point_id}'.encode()).hexdigest()


@dataclass(frozen=True)
class PointView:
    id: str
    label: str
    key: str


@dataclass(frozen=True)
class UnitView:
    id: str
    title: str
    can_do: str
    points: tuple


@dataclass(frozen=True)
class CourseView:
    units: tuple


def view(course):
    return CourseView(tuple(UnitView(item.id, item.title, item.goal, tuple(
        PointView(p.id, p.label, point_key(course, item.id, p.id))
        for p in item.points)) for _, item in lessons.available(course)))
