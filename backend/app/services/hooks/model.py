"""hook 规则的数据模型：事件表、七种动作、规则本身。编辑界面照 meta() 画。"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..situation import VAR_NAME, Condition

MAX_RULES = 200
QUEUE_HOURS = 6  # 排队超过这么久没用上的 say / inject / 强制条目作废

# id -> (给人看的名字, [(键, 名字, 类型)], 谁发)
EVENTS: dict[str, tuple[str, list[tuple[str, str, str]], str]] = {
    "chat.open": ("打开某个联系人的对话", [("first_today", "今天第一次打开", "bool")], "frontend"),
    "chat.user_message": ("用户发了消息（生成之前）", [("text", "消息原文", "text"), ("length", "字数", "number")],
                          "backend"),
    "chat.reply": ("对方回完一轮", [("mood", "情绪", "text"), ("bubbles", "气泡数", "number"),
                                   ("fixes", "这轮纠正了几处", "number"), ("proactive", "是她主动发的", "bool")],
                   "backend"),
    "chat.idle": ("对话开着但 10 分钟没动静", [("minutes", "多少分钟没动静", "number")], "frontend"),
    "study.vocab_saved": ("收藏了一个词", [("lemma", "词", "text"), ("language", "语言", "text")], "backend"),
    "study.pattern_saved": ("收藏了一个句型", [("language", "语言", "text")], "backend"),
    "study.reading_finished": ("做完一篇阅读", [("title", "标题", "text"), ("correct", "答对", "number"),
                                              ("total", "总题数", "number"), ("language", "语言", "text")],
                               "backend"),
    "study.listening_finished": ("做完一组听力", [("correct", "答对", "number"), ("total", "总题数", "number"),
                                                ("language", "语言", "text")], "backend"),
    "study.review_done": ("复习了一道错题", [("kind", "题型（reading / listening）", "text"),
                                           ("correct", "答对了", "bool"), ("language", "语言", "text")],
                          "backend"),
    "study.review_session_done": ("做完一次复习", [("count", "这次复习了几张卡", "number"),
                                                    ("forgot", "其中忘了几张", "number"),
                                                    ("language", "语言", "text")], "backend"),
    "study.lesson_finished": ("口语课刚下课", [("lesson_id", "课的 id", "text"), ("language", "语言", "text")],
                              "backend"),
    "course.unit_completed": ("课程里一个单元达标", [("unit_id", "单元 id", "text"), ("title", "单元名", "text"),
                                                   ("language", "语言", "text")], "backend"),
    "course.lesson_finished": ("上完一节课", [("unit_id", "单元 id", "text"), ("title", "单元名", "text"),
                                              ("language", "语言", "text"),
                                              ("passed", "做到的知识点数", "number")], "backend"),
    "lore.activated": ("带 automation_id 的世界书条目生效", [("automation_id", "automation_id", "text"),
                                                         ("book_id", "书 id", "number"), ("uid", "条目 uid", "number")],
                       "backend"),
}
FRONTEND_EVENTS = ("chat.open", "chat.idle")
# 不属于某一个联系人的事件：规则没限定联系人时落到这门语言最近聊过的那个联系人
LANGUAGE_EVENTS = tuple(e for e in EVENTS if e.startswith(("study.", "course.")))

EventName = Literal[tuple(EVENTS)]  # type: ignore[valid-type]
VarName = Annotated[str, StringConstraints(pattern=VAR_NAME)]
VarValue = Union[Annotated[str, StringConstraints(max_length=500)], int, float, bool]
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
Category = Literal["fact", "preference", "event", "promise"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Inject(Strict):
    type: Literal["inject"]
    text: Text
    turns: int = Field(1, ge=1, le=50)


class Say(Strict):
    type: Literal["say"]
    directive: Text


class SetVar(Strict):
    type: Literal["set_var"]
    name: VarName
    value: VarValue
    scope: Literal["persona", "global"] = "persona"


class IncVar(Strict):
    type: Literal["inc_var"]
    name: VarName
    by: float = Field(1, ge=-1_000_000, le=1_000_000)
    scope: Literal["persona", "global"] = "persona"


class ActivateEntry(Strict):
    type: Literal["activate_entry"]
    book_id: int = Field(ge=1)
    uid: int = Field(ge=1)
    turns: int = Field(1, ge=1, le=50)


class DeactivateEntry(Strict):
    type: Literal["deactivate_entry"]
    book_id: int = Field(ge=1)
    uid: int = Field(ge=1)
    turns: int = Field(1, ge=1, le=50)


class Remember(Strict):
    type: Literal["remember"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    category: Category = "event"


Action = Annotated[Union[Inject, Say, SetVar, IncVar, ActivateEntry, DeactivateEntry, Remember],
                   Field(discriminator="type")]


class RuleBody(Strict):
    """新建/修改时客户端发来的部分（id、builtin 由服务端管）。"""
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    enabled: bool = True
    persona_ids: list[Annotated[int, Field(ge=1)]] | None = Field(None, max_length=50)
    event: EventName
    conditions: list[Condition] = Field(default_factory=list, max_length=12)
    probability: int = Field(100, ge=0, le=100)
    cooldown_minutes: int = Field(0, ge=0, le=525_600)
    cooldown_turns: int = Field(0, ge=0, le=10_000)
    once_per: Literal["none", "session", "day"] = "none"
    actions: list[Action] = Field(min_length=1, max_length=10)


class Rule(RuleBody):
    id: int
    builtin: str | None = None


ACTIONS_META = [
    {"type": "inject", "label": "接下来几轮把一段话放进背景", "fields": [
        {"key": "text", "label": "内容（支持宏）", "type": "textarea", "required": True},
        {"key": "turns", "label": "持续几轮", "type": "number", "default": 1, "min": 1, "max": 50}]},
    {"type": "say", "label": "让对方主动发一条消息", "fields": [
        {"key": "directive", "label": "给她的念头（支持宏，不会被念出来）", "type": "textarea", "required": True}]},
    {"type": "set_var", "label": "设变量", "fields": [
        {"key": "name", "label": "变量名", "type": "text", "required": True},
        {"key": "value", "label": "值（数字或文字）", "type": "text", "required": True},
        {"key": "scope", "label": "范围", "type": "select", "default": "persona",
         "options": [{"value": "persona", "label": "这个联系人"}, {"value": "global", "label": "全局"}]}]},
    {"type": "inc_var", "label": "变量加减", "fields": [
        {"key": "name", "label": "变量名", "type": "text", "required": True},
        {"key": "by", "label": "加多少（负数就是减）", "type": "number", "default": 1},
        {"key": "scope", "label": "范围", "type": "select", "default": "persona",
         "options": [{"value": "persona", "label": "这个联系人"}, {"value": "global", "label": "全局"}]}]},
    {"type": "activate_entry", "label": "强制一条世界书条目生效几轮", "fields": [
        {"key": "book_id", "label": "世界书", "type": "book", "required": True},
        {"key": "uid", "label": "条目", "type": "entry", "required": True},
        {"key": "turns", "label": "持续几轮", "type": "number", "default": 1, "min": 1, "max": 50}]},
    {"type": "deactivate_entry", "label": "压住一条世界书条目几轮", "fields": [
        {"key": "book_id", "label": "世界书", "type": "book", "required": True},
        {"key": "uid", "label": "条目", "type": "entry", "required": True},
        {"key": "turns", "label": "持续几轮", "type": "number", "default": 1, "min": 1, "max": 50}]},
    {"type": "remember", "label": "往这个联系人的长期记忆里写一条", "fields": [
        {"key": "content", "label": "内容（支持宏）", "type": "textarea", "required": True},
        {"key": "category", "label": "类别", "type": "select", "default": "event",
         "options": [{"value": v, "label": l} for v, l in (("fact", "事实"), ("preference", "喜好"),
                                                            ("event", "事件"), ("promise", "约定"))]}]},
]
