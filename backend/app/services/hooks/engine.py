"""发事件 → 找规则 → 判条件/冷却/概率 → 执行动作 → 记日志。

两种发法：
- `emit`：当场同步求值，返回生效的规则 id。用在 chat.user_message（这一轮的 inject 要马上用上）
  和前端的 /api/hooks/fire。只读库、算条件、往队列里写几行，毫秒级；库忙最多等 1 秒。
- `emit_soon`：丢给一个后台线程，调用方立刻返回。学习类、课程类、chat.reply、lore.activated 都走这条，
  判分/收藏/聊天本身完全不等它。

任何异常都只记日志，绝不抛给调用方。
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta

from ... import db
from .. import clock, macros
from ..lore import state as lore_state
from ..situation import Situation, check
from . import queue, store
from .model import FRONTEND_EVENTS, LANGUAGE_EVENTS, Rule

logger = logging.getLogger(__name__)

BOOT = uuid.uuid4().hex  # once_per = session：本次启动应用期间算一次
SAY_DAILY_CAP_DEFAULT = 4
SAY_MIN_GAP_DEFAULT = 30
_LESSON_KEY = "hooks_lesson_seen:"

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hooks")
_seeded: set[str] = set()


class _Skip(Exception):
    pass


def connect():
    conn = db.get_conn()
    conn.execute("PRAGMA busy_timeout = 1000")
    return conn


def _setting(conn, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def enabled(conn) -> bool:
    return _setting(conn, "hooks_enabled", "1") not in ("0", "false", "False", "")


def _int_setting(conn, key: str, default: int) -> int:
    try:
        return int(float(_setting(conn, key, str(default))))
    except ValueError:
        return default


def ensure_builtins(conn) -> None:
    store.ensure_builtins(conn)
    _seeded.add(str(db.DB_PATH))


def ensure_seeded(conn) -> None:
    """这个库还没写过自带规则就写一次（测试库、或启动时没跑到 init_db 的情况）。"""
    _ensure(conn)


def _ensure(conn) -> None:
    if str(db.DB_PATH) not in _seeded:
        store.ensure_builtins(conn)
        conn.commit()
        _seeded.add(str(db.DB_PATH))


def _persona(conn, persona_id) -> dict | None:
    row = conn.execute("SELECT * FROM personas WHERE id = ? AND archived_at IS NULL", (persona_id,)).fetchone()
    return dict(row) if row else None


def _main(conn):
    from .. import chat_room
    return chat_room.settings(conn)


def primary_persona(conn) -> dict | None:
    config = _main(conn)
    return _persona(conn, config.primary_id) if config.primary_id else None


def persona_for_language(conn, language: str) -> dict | None:
    """学习类事件落到谁头上：这门语言是主人设的母语 → 主人设；否则是哪个副人设的母语 → 她；否则主人设。"""
    config = _main(conn)
    primary = _persona(conn, config.primary_id) if config.primary_id else None
    if primary and primary["language"] == language:
        return primary
    for guest in config.guests:
        person = _persona(conn, guest.persona_id) if guest.enabled else None
        if person and person["language"] == language:
            return person
    return primary


def latest_session(conn, persona_id: int | None = None) -> int | None:
    """求值用的对话：主聊天那一段（每个人设在里面各有自己的轮数）。"""
    from .. import chat_room
    return chat_room.main_session_id(conn)


# 主聊天里的事件：规则限定了人设就落到那些人设头上（她不在场也算，say 会让她进场说一句）；
# 没限定就落到事件本身的人设（打开/闲置 = 主人设，用户消息 = 这一轮的主讲，回完 = 刚说完的人）。
_MAIN_CHAT_EVENTS = ("chat.open", "chat.idle", "chat.user_message", "chat.reply")


def _recipients(conn, rule: Rule, event: str, persona_id, payload: dict) -> list[dict]:
    if event in LANGUAGE_EVENTS:
        language = payload.get("language")
        if rule.persona_ids:
            people = [p for p in (_persona(conn, i) for i in rule.persona_ids) if p]
            return [p for p in people if not language or p["language"] == language]
        person = persona_for_language(conn, language) if language else primary_persona(conn)
        if person is None:
            store.log(conn, event, rule.id, None, {"rule_name": rule.name, "actions": [],
                                                   "skipped_reason": "no_persona"})
            return []
        return [person]
    if event in _MAIN_CHAT_EVENTS and rule.persona_ids:
        return [p for p in (_persona(conn, i) for i in rule.persona_ids) if p]
    if persona_id is None or (rule.persona_ids and persona_id not in rule.persona_ids):
        return []
    person = _persona(conn, persona_id)
    if person and event in _MAIN_CHAT_EVENTS and payload.get("language") and persona_id == payload.get("persona_id",
                                                                                                   persona_id):
        person = {**person, "language": payload["language"]}  # 条件和 {{due_vocab}} 按这一轮的语言算
    return [person] if person else []

def _act(conn, action, persona: dict, sit: Situation) -> str:
    pid = persona["id"]
    kind = action.type
    if kind in ("inject", "say", "remember"):
        source = {"inject": "text", "say": "directive", "remember": "content"}[kind]
        if kind == "say":
            cap = _int_setting(conn, "hooks_say_daily_cap", SAY_DAILY_CAP_DEFAULT)
            gap = _int_setting(conn, "hooks_say_min_gap_minutes", SAY_MIN_GAP_DEFAULT)
            count, last = queue.says_today(conn, pid)
            if count >= cap:
                raise _Skip("say_daily_cap")
            last_at = clock.parse(last)
            if gap > 0 and last_at is not None and clock.now() - last_at < timedelta(minutes=gap):
                raise _Skip("say_min_gap")
        expansion = macros.expand(getattr(action, source), sit)
        if not expansion.ok:
            raise _Skip("no_due_vocab")
        text = expansion.text.strip()
        if not text:
            raise _Skip("empty")
        if kind == "inject":
            queue.enqueue(conn, pid, "inject", {"text": text, "turns_left": action.turns})
            return "inject"
        if kind == "say":
            queue.enqueue(conn, pid, "say", {"directive": text})
            return "say"
        if conn.execute("SELECT 1 FROM memory_items WHERE persona_id = ? AND active = 1 AND content = ?",
                        (pid, text)).fetchone():
            raise _Skip("duplicate_memory")
        conn.execute("INSERT INTO memory_items (persona_id, category, content) VALUES (?, ?, ?)",
                     (pid, action.category, text[:1000]))
        return "remember"
    if kind == "set_var":
        store.set_var(conn, action.name, action.value, action.scope, pid)
        return f"set_var:{action.name}"
    if kind == "inc_var":
        store.inc_var(conn, action.name, action.by, action.scope, pid)
        return f"inc_var:{action.name}"
    if kind in ("activate_entry", "deactivate_entry"):
        queue.enqueue(conn, pid, kind, {"book_id": action.book_id, "uid": action.uid, "turns_left": action.turns})
        return kind
    raise _Skip("unknown_action")


def _run(conn, rule: Rule, persona: dict, event: str, payload: dict, query_text: str) -> bool:
    sid = latest_session(conn, persona["id"])
    sit = Situation(conn, persona, sid, event=payload, query_text=query_text)
    if not check(rule.conditions, sit):
        return False
    state = store.rule_state(conn, rule.id, persona["id"])
    turn = lore_state.current_turn(conn, sid, persona["id"])
    if rule.once_per == "day" and state.get("last_day") == clock.today():
        return False
    if rule.once_per == "session" and state.get("last_session") == BOOT:
        return False
    last_at = clock.parse(state.get("last_at"))
    if rule.cooldown_minutes and last_at and clock.now() - last_at < timedelta(minutes=rule.cooldown_minutes):
        return False
    if rule.cooldown_turns and state.get("last_turn") is not None and turn - state["last_turn"] < rule.cooldown_turns:
        return False
    base = {"rule_name": rule.name}
    if rule.probability < 100 and clock.rng.random() * 100 >= rule.probability:
        store.log(conn, event, rule.id, persona["id"], {**base, "actions": [], "skipped_reason": "probability"})
        return False
    done, notes = [], []
    for action in rule.actions:
        try:
            done.append(_act(conn, action, persona, sit))
        except _Skip as skip:
            notes.append(f"{action.type}:{skip}")
    if not done:
        reason = notes[0].split(":", 1)[1] if notes else "nothing_done"
        store.log(conn, event, rule.id, persona["id"], {**base, "actions": [], "skipped_reason": reason})
        return False
    store.mark_fired(conn, rule.id, persona["id"], turn, BOOT)
    store.log(conn, event, rule.id, persona["id"], {**base, "actions": done, "skipped_reason": None,
                                                    **({"notes": notes} if notes else {})})
    return True


def emit(event: str, persona_id: int | None = None, payload: dict | None = None, *, query_text: str = "") -> list[int]:
    payload = dict(payload or {})
    fired: list[int] = []
    try:
        with closing(connect()) as conn:
            if not enabled(conn):
                return []
            _ensure(conn)
            rules = [r for r in store.list_rules(conn) if r.enabled and r.event == event]
            for rule in rules:
                for persona in _recipients(conn, rule, event, persona_id, payload):
                    try:
                        if _run(conn, rule, persona, event, payload, query_text or str(payload.get("text") or "")):
                            fired.append(rule.id)
                        conn.commit()
                    except Exception as error:
                        conn.rollback()
                        logger.warning("hook 规则 %s 执行失败，跳过", rule.id, exc_info=True)
                        try:
                            store.log(conn, event, rule.id, persona["id"], {"rule_name": rule.name, "actions": [],
                                                                            "skipped_reason": f"error: {error}"[:200]})
                            conn.commit()
                        except Exception:
                            pass
            conn.commit()
    except Exception:
        logger.warning("hook 事件 %s 求值失败，跳过", event, exc_info=True)
    return list(dict.fromkeys(fired))


def emit_soon(event: str, persona_id: int | None = None, payload: dict | None = None, *, resolve=None) -> None:
    """后台发：resolve(conn) 可以在后台线程里补全 payload（比如查标题、语言），返回 None 就不发了。"""
    def job():
        data = dict(payload or {})
        if resolve is not None:
            with closing(connect()) as conn:
                extra = resolve(conn)
            if extra is None:
                return
            data.update(extra)
        emit(event, persona_id, data)

    def safe():
        try:
            job()
        except Exception:
            logger.warning("hook 后台事件 %s 失败，跳过", event, exc_info=True)

    try:
        _executor.submit(safe)
    except Exception:
        logger.warning("hook 后台线程不可用，事件 %s 没发", event, exc_info=True)


def run_soon(fn, *args) -> None:
    """把一件小事丢给 hook 的后台线程（和后台事件排在同一队里），出错只记日志。"""
    def safe():
        try:
            fn(*args)
        except Exception:
            logger.warning("hook 后台任务失败，跳过", exc_info=True)

    try:
        _executor.submit(safe)
    except Exception:
        logger.warning("hook 后台线程不可用", exc_info=True)


def flush(timeout: float = 10.0) -> None:
    """等后台排着的事件都处理完（测试用）。"""
    _executor.submit(lambda: None).result(timeout=timeout)


def fire(event: str, persona_id: int | None = None, payload: dict | None = None) -> dict:
    """前端发事件（只认 chat.open / chat.idle）。"""
    if event not in FRONTEND_EVENTS:
        raise ValueError("前端只能发 chat.open 和 chat.idle")
    payload = dict(payload or {})
    with closing(connect()) as conn:
        if persona_id is None:  # 主聊天：不指定就是主人设
            primary = primary_persona(conn)
            persona_id = primary["id"] if primary else None
        if persona_id is None or _persona(conn, persona_id) is None:
            raise LookupError("没有这个联系人")
        if event == "chat.open":
            seen = store.rule_state(conn, 0, persona_id)
            payload["first_today"] = seen.get("last_day") != clock.today()
            store.mark_fired(conn, 0, persona_id, None, BOOT)
            conn.commit()
        check_lessons(conn)
    fired = emit(event, persona_id, payload)
    with closing(connect()) as conn:
        return {"fired": fired, "pending": queue.pending(conn)}


def check_lessons(conn) -> None:
    """口语课桥读到新课 → study.lesson_finished（每门语言每节课只发一次；72 小时前的旧课不算）。"""
    try:
        from .. import coach_bridge
        for language, lesson in coach_bridge.latest_lessons(conn).items():
            key = _LESSON_KEY + language
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row is not None and row[0] == lesson["id"]:
                continue
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, lesson["id"]))
            conn.commit()
            if coach_bridge.lesson_is_fresh(lesson):
                emit_soon("study.lesson_finished", None, {"lesson_id": lesson["id"], "language": language})
    except Exception:
        logger.warning("口语课新课检查失败，跳过", exc_info=True)


def pending() -> list[dict]:
    with closing(connect()) as conn:
        check_lessons(conn)
        queue.cleanup(conn)
        conn.commit()
        return queue.pending(conn)


def claim_say(persona_id: int | None = None) -> tuple[int, str, int] | None:
    with closing(connect()) as conn:
        item = queue.claim_say(conn, persona_id)
        conn.commit()
        return item


def unclaim(item_id: int) -> None:
    try:
        with closing(connect()) as conn:
            queue.unclaim(conn, item_id)
            conn.commit()
    except Exception:
        logger.warning("主动消息退回队列失败", exc_info=True)


def lesson_key_prefix() -> str:
    return _LESSON_KEY

