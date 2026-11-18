"""Lesson identifiers, drill checks and writing mark sheets."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Slug = Annotated[str, StringConstraints(pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')]


class DrillCheck(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ok: bool
    fix: str
    why: str


class SheetCoverage(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    verdict: Literal['done', 'thin', 'missing']
    quote: str
    note: str


class SheetFix(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    from_: str = Field(alias='from')
    to: str
    rule: str


class SheetUpgrade(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    from_: str = Field(alias='from')
    to: str
    why: str


class SheetPoint(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    met: bool
    quote: str
    why: str


class Sheet(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    coverage: list[SheetCoverage]
    score: int = Field(ge=0, le=5)
    reason: str
    fixes: list[SheetFix]
    upgrade: SheetUpgrade | None
    points: list[SheetPoint]
    next: str

