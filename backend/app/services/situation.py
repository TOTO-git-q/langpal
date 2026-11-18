"""「现在是什么情况」：世界书的条件触发和 hook 规则的条件共用这一份。

条件写法 `{"field": ..., "op": ..., "value": ...}`，字段见 FIELDS；另外 `var.<名字>` 读 hook 变量
（先找这个联系人的，没有再找全局的），`event.<键>` 读触发这次求值的事件数据。
字段值按需现算、算过就缓存，一次求值里不会重复查库。任何一项算不出来（库忙、口语课没装）
都当"没有值"：除了 `!=` 以外的比较一律不成立。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import clock

logger = logging.getLogger(__name__)

# key -> (给人看的名字, 类型)
FIELDS: dict[str, tuple[str, str]] = {
    "hour": ("现在几点（0–23）", "number"),
    "weekday": ("星期几（1=周一 … 7=周日）", "number"),
    "date": ("今天的日期（MM-DD）", "text"),
    "idle_days": ("距上次聊天过了几天", "number"),
    "turns": ("这段对话已有多少条消息", "number"),
    "vocab_due": ("这门语言到期该复习的生词数", "number"),
    "reviews_due": ("这门语言到期该复习的卡片数（生词、句型、错题都算）", "number"),
    "debts_open": ("口语课错题账本里还没改掉的条目数", "number"),
    "course_unit": ("当前课程单元的 id", "text"),
    "last_mood": ("对方上一条回复的情绪", "text"),
    "language": ("这一轮的语言（事件里没有时是她的母语）", "text"),
}
OPS = ("==", "!=", ">", ">=", "<", "<=", "in", "between", "contains")
OPS_BY_TYPE = {
    "number": ["==", "!=", ">", ">=", "<", "<=", "in", "between"],
    "text": ["==", "!=", "in", "contains", "between"],
    "any": list(OPS),
}
_DYNAMIC = re.compile(r"^(var|event)\.[\w.\-]{1,40}$")
VAR_NAME = r"^[\w\-.]{1,40}$"

Scalar = str | int | float | bool | None


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    field: str = Field(min_length=1, max_length=48)
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "between", "contains"]
    value: Scalar | list[Scalar] = None

    @field_validator("field")
    @classmethod
    def known_field(cls, value):
        if value not in FIELDS and not _DYNAMIC.match(value):
            raise ValueError(f"不认识的条件字段：{value}")
        return value

    @field_validator("value")
    @classmethod
    def bounded(cls, value):
        items = value if isinstance(value, list) else [value]
        if len(items) > 30 or any(isinstance(v, str) and len(v) > 200 for v in items):
            raise ValueError("条件的值太长")
        return value

    @model_validator(mode="after")
    def shape(self):
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("in 的值要写成列表")
        if self.op == "between" and not (isinstance(self.value, list) and len(self.value) == 2):
            raise ValueError("between 的值要写成 [下限, 上限]")
        return self


def _number(value) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _equal(left, right) -> bool:
    a, b = _number(left), _number(right)
    if a is not None and b is not None:
        return a == b
    return str(left).strip().casefold() == str(right).strip().casefold()


def _between(value, low, high, field: str) -> bool:
    x, a, b = _number(value), _number(low), _number(high)
    if x is None or a is None or b is None:
        x, a, b = str(value), str(low), str(high)
    if a <= b:
        return a <= x <= b
    # 下限比上限大时按"跨过零点"算，比如 hour between [22, 3]
    return x >= a or x <= b


def compare(value, op: str, target, field: str = "") -> bool:
    if value is None:
        return op == "!="
    try:
        if op == "==":
            return _equal(value, target)
        if op == "!=":
            return not _equal(value, target)
        if op in (">", ">=", "<", "<="):
            x, y = _number(value), _number(target)
            if x is None or y is None:
                return False
            return {">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y}[op]
        if op == "in":
            return any(_equal(value, item) for item in (target or []))
        if op == "between":
            return _between(value, target[0], target[1], field)
        if op == "contains":
            if isinstance(value, list):
                return any(_equal(item, target) for item in value)
            return str(target).casefold() in str(value).casefold()
    except Exception:
        return False
    return False


class Situation:
    """一次求值用的上下文。persona 是 personas 表一行的 dict；session_id 是这段对话；
    before_message_id：算「距上次说话」时只看这条消息之前的（不把刚发的这批算进去）。"""

    def __init__(self, conn, persona: dict | None, session_id: int | None = None, *,
                 event: dict | None = None, before_message_id: int | None = None, query_text: str = ""):
        self.conn = conn
        self.persona = persona or {}
        self.session_id = session_id
        self.event = event or {}
        self.before_message_id = before_message_id
        self.query_text = query_text or ""
        self.moment = clock.now()
        self._cache: dict[str, Any] = {}

    @property
    def language(self) -> str:
        return self.persona.get("language") or ""

    def get(self, field: str):
        if field in self._cache:
            return self._cache[field]
        try:
            value = self._compute(field)
        except Exception:
            logger.debug("条件字段 %s 算不出来，当作没有值", field, exc_info=True)
            value = None
        self._cache[field] = value
        return value

    def _compute(self, field: str):
        if field == "hour":
            return self.moment.hour
        if field == "weekday":
            return self.moment.isoweekday()
        if field == "date":
            return self.moment.strftime("%m-%d")
        if field == "language":
            return self.language or None
        if field.startswith("event."):
            return self.event.get(field[6:])
        if field.startswith("var."):
            return read_var(self.conn, field[4:], self.persona.get("id"))
        if field == "idle_days":
            return self._idle_days()
        if field == "turns":
            if self.session_id is None:
                return 0
            return self.conn.execute("SELECT count(*) FROM messages WHERE session_id = ?",
                                     (self.session_id,)).fetchone()[0]
        if field == "vocab_due":  # 排期以复习卡（review_cards）为准，见 docs/LEARNING.md
            return self.conn.execute(
                """SELECT count(*) FROM review_cards WHERE kind = 'vocab' AND language = ? AND suspended = 0
                   AND state <> 'new' AND due_at <= ?""", (self.language, clock.stamp(self.moment))).fetchone()[0]
        if field == "reviews_due":
            from . import learning
            return learning.reviews_due(self.conn, self.language)
        if field == "debts_open":
            from . import coach_bridge
            return coach_bridge.open_debts(self.conn, self.language)
        if field == "course_unit":
            from . import course
            unit = course.planner.next_lesson(self.conn, self.language, clock.now())
            return unit["unit_id"] if unit else ""
        if field == "last_mood":
            row = self.conn.execute(
                """SELECT last_mood FROM chat_turns WHERE persona_id = ? AND (? IS NULL OR session_id = ?)
                   AND last_mood IS NOT NULL ORDER BY session_id DESC LIMIT 1""",
                (self.persona.get("id"), self.session_id, self.session_id)).fetchone()
            return row[0] if row else None
        return None

    def _idle_days(self):
        # 主聊天：这段对话里上一条消息（不算刚发的这一批）；没有对话时看这个人设自己的旧对话
        if self.session_id is not None:
            row = self.conn.execute(
                """SELECT created_at FROM messages WHERE session_id = ? AND (? IS NULL OR id < ?)
                   ORDER BY id DESC LIMIT 1""",
                (self.session_id, self.before_message_id, self.before_message_id)).fetchone()
        else:
            row = self.conn.execute(
                """SELECT m.created_at FROM messages m JOIN sessions s ON s.id = m.session_id
                   WHERE s.persona_id = ? AND (? IS NULL OR m.id < ?) ORDER BY m.id DESC LIMIT 1""",
                (self.persona.get("id"), self.before_message_id, self.before_message_id)).fetchone()
        last = clock.parse(row[0]) if row else None
        if last is None:
            return None
        return max(0, int((self.moment - last).total_seconds() // 86400))


def check(conditions, situation: Situation) -> bool:
    for condition in conditions or ():
        field, op, value = (condition.field, condition.op, condition.value) if hasattr(condition, "field") \
            else (condition["field"], condition["op"], condition.get("value"))
        if not compare(situation.get(field), op, value, field):
            return False
    return True


def read_var(conn, name: str, persona_id: int | None):
    rows = conn.execute(
        """SELECT scope, value FROM hook_vars WHERE name = ? AND
           ((scope = 'persona' AND persona_id = ?) OR scope = 'global')""",
        (name, persona_id or 0)).fetchall()
    by_scope = {row[0]: row[1] for row in rows}
    raw = by_scope.get("persona", by_scope.get("global"))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def meta() -> list[dict]:
    fields = [{"key": key, "label": label, "type": kind, "ops": OPS_BY_TYPE[kind]}
              for key, (label, kind) in FIELDS.items()]
    fields.append({"key": "var.*", "label": "hook 变量（var.名字）", "type": "any", "ops": OPS_BY_TYPE["any"]})
    fields.append({"key": "event.*", "label": "事件带的数据（event.键，只在 hook 里有）", "type": "any",
                   "ops": OPS_BY_TYPE["any"]})
    return fields
