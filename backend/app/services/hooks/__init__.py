"""声明式事件 hook。规格见 docs/LORE-AND-HOOKS.md 第二、三节。

model    事件表、七种动作、规则
builtin  自带规则
store    规则 / 变量 / 日志 / 冷却状态
queue    待发的 say 和还没用完的 inject、强制条目
engine   发事件、求值、执行动作
"""
from . import queue
from .engine import (BOOT, check_lessons, claim_say, emit, emit_soon, enabled, ensure_builtins, fire, flush,
                     lesson_key_prefix, pending, persona_for_language, run_soon, unclaim)
from .model import ACTIONS_META, EVENTS, FRONTEND_EVENTS, MAX_RULES, Rule, RuleBody


def meta() -> dict:
    from .. import macros, situation
    return {
        "events": [{"id": key, "label": label, "source": source,
                    "fields": [{"key": k, "label": l, "type": t} for k, l, t in fields]}
                   for key, (label, fields, source) in EVENTS.items()],
        "condition_fields": situation.meta(),
        "actions": ACTIONS_META,
        "macros": macros.CATALOG,
        "once_per": [{"value": "none", "label": "不限"}, {"value": "session", "label": "每次启动应用一次"},
                     {"value": "day", "label": "每天一次"}],
        "limits": {"rules": MAX_RULES, "conditions": 12, "actions": 10, "text": 2000},
    }


__all__ = ["ACTIONS_META", "BOOT", "EVENTS", "FRONTEND_EVENTS", "Rule", "RuleBody", "check_lessons", "claim_say",
           "emit", "emit_soon", "enabled", "ensure_builtins", "fire", "flush", "lesson_key_prefix", "meta",
           "pending", "persona_for_language", "queue", "run_soon", "unclaim"]
