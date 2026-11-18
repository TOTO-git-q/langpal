"""宏：世界书正文、hook 的 inject 文本、say 指令里都能用。认不出的宏原样保留，不报错。

{{user}} {{char}} {{time}} {{date}} {{weekday}} {{idle_days}} {{getvar::名字}} {{event.键}}
{{random::甲::乙}} {{roll::6}} {{due_vocab::2}}
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import clock
from .situation import Situation, read_var

logger = logging.getLogger(__name__)

_MACRO = re.compile(r"\{\{\s*([^{}]{1,200}?)\s*\}\}")
DUE_VOCAB_MAX = 10

CATALOG = [
    {"name": "{{user}}", "label": "用户的称呼（设置里的 user_name，没设就是“对方”）"},
    {"name": "{{char}}", "label": "联系人的名字"},
    {"name": "{{time}}", "label": "现在的时间 HH:MM"},
    {"name": "{{date}}", "label": "今天的日期 YYYY-MM-DD"},
    {"name": "{{weekday}}", "label": "星期几（周一…周日）"},
    {"name": "{{idle_days}}", "label": "距上次和这个联系人说话几天"},
    {"name": "{{getvar::名字}}", "label": "变量的值（先找这个联系人的，再找全局的）"},
    {"name": "{{event.键}}", "label": "事件带的数据"},
    {"name": "{{random::甲::乙::丙}}", "label": "随机挑一个"},
    {"name": "{{roll::6}}", "label": "1 到 N 的随机整数"},
    {"name": "{{due_vocab::2}}", "label": "到期该复习的生词挑 N 个，写成「词（读音）：意思」；一个都没有时整个动作作废"},
]


@dataclass
class Expansion:
    text: str
    ok: bool = True  # False = 用到了 {{due_vocab}} 但一个词都没有
    vocab_ids: list[int] = field(default_factory=list)


def _user_name(conn) -> str:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'user_name'").fetchone()
    except Exception:
        row = None
    value = (row[0] if row else "") or ""
    return value.strip()[:40] or "对方"


def pick_due_vocab(conn, language: str, count: int, query_text: str = "") -> list[dict]:
    """到期该复习的生词挑 count 个（排期以复习卡为准，见 docs/LEARNING.md）：优先和 query_text 意思相近的，
    语义模型不可用时按到期时间。挑中不改排期；她真在回复里用到、这一轮完整发完时才算碰见一次（chat.py）。"""
    from . import learning
    return learning.due_vocab(conn, language, count, query_text)

def format_vocab(rows: list[dict]) -> str:
    parts = []
    for r in rows:
        reading = f"（{r['reading']}）" if r.get("reading") and r["reading"] != r["lemma"] else ""
        meaning = f"：{r['meaning']}" if r.get("meaning") else ""
        parts.append(f"{r['lemma']}{reading}{meaning}")
    return "、".join(parts)


def expand(text: str, situation: Situation, *, rng=None) -> Expansion:
    if not text or "{{" not in text:
        return Expansion(text or "")
    rng = rng or clock.rng
    result = Expansion("")
    conn = situation.conn

    def replace(match: re.Match) -> str:
        raw = match.group(0)
        name = match.group(1).strip()
        try:
            if name == "user":
                return _user_name(conn)
            if name == "char":
                return str(situation.persona.get("name") or "")
            if name == "time":
                return situation.moment.strftime("%H:%M")
            if name == "date":
                return situation.moment.strftime("%Y-%m-%d")
            if name == "weekday":
                return clock.WEEKDAYS[situation.moment.weekday()]
            if name == "idle_days":
                value = situation.get("idle_days")
                return "好几" if value is None else str(value)
            if name.startswith("event."):
                key = name[6:]
                return str(situation.event[key]) if key in situation.event else raw
            parts = [p.strip() for p in name.split("::")]
            head, args = parts[0], parts[1:]
            if head == "getvar" and len(args) == 1:
                value = read_var(conn, args[0], situation.persona.get("id"))
                return "" if value is None else str(value)
            if head == "random" and args:
                return rng.choice(args)
            if head == "roll" and len(args) == 1 and args[0].isdigit() and 1 <= int(args[0]) <= 1_000_000:
                return str(rng.randint(1, int(args[0])))
            if head == "due_vocab" and len(args) <= 1:
                count = int(args[0]) if args and args[0].isdigit() else 1
                count = max(1, min(DUE_VOCAB_MAX, count))
                rows = pick_due_vocab(conn, situation.language, count, situation.query_text)
                if not rows:
                    result.ok = False
                    return ""
                result.vocab_ids.extend(r["id"] for r in rows)
                return format_vocab(rows)
        except Exception:
            logger.debug("宏 %s 展开失败，原样保留", raw, exc_info=True)
        return raw

    result.text = _MACRO.sub(replace, text)
    return result
