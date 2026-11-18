"""每一轮聊天在生成前后要做的世界书 + hook 的事。chat.py 只在这里留调用点。

- `system_lore`：编系统提示词时用的世界书两块（before_persona / after_persona）+ 指纹。
- `prepare`：生成前。轮数 +1 → 发 chat.user_message（主动消息不发）→ 取 hook 留下的 inject 和
  强制/压住的条目 → 算这一轮的世界书 → 拼成背景块里的一段。整体有超时，超时或出错就当没有。
- `commit`：生成成功后。写世界书的粘性/冷却状态、把 hook 的 inject 等用掉一轮、发 lore.activated。
- `after_reply`：一轮发完。记下她这条的情绪（last_mood 条件用）、后台发 chat.reply。

任何一步出错都只记日志，聊天照常。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from dataclasses import dataclass, field

from ..db import get_conn
from . import hooks, lore
from .hooks import queue
from .lore import state as lore_state

logger = logging.getLogger(__name__)

PREPARE_TIMEOUT = 2.0  # 世界书 + hook 准备最多等这么久，超时这一轮就不带，聊天照常


@dataclass
class TurnExtras:
    persona_id: int | None = None
    session_id: int | None = None
    turn: int = 0
    block: str = ""
    lore: lore.TurnLore | None = None
    effects: queue.TurnEffects | None = None
    hook_injects: list[str] = field(default_factory=list)


def system_lore(conn, persona: dict, session_id: int | None) -> lore.SystemLore:
    try:
        suppressed = queue.turn_effects(conn, persona["id"]).suppressed if hooks.enabled(conn) else set()
        return lore.system_lore(conn, persona, session_id, effects=lore.Effects(suppressed=suppressed))
    except Exception:
        logger.warning("世界书（系统提示词部分）没算出来，这次不放", exc_info=True)
        return lore.SystemLore()


def _inject_block(texts: list[str]) -> str:
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return ""
    return ("【这一轮的额外提示（背景，不是对方说的话；照着调整就好，不要提到这些提示）】\n"
            + "\n".join(f"- {t}" for t in texts) + "\n")


def prepare(persona: dict, session_id: int, batch_text: str, batch_ids=(), *, proactive: bool = False,
            role: str = "lead") -> TurnExtras:
    """persona 是这一轮说话的人设；它的 language 已经换成了这一轮的语言（chat.py 传进来的副本）。
    role：lead（主讲，会发 chat.user_message）/ chime（插话）/ proactive（她主动开口）。"""
    extras = TurnExtras(persona_id=persona["id"], session_id=session_id)
    try:
        with closing(get_conn()) as conn:
            turn = lore_state.next_turn(conn, session_id, persona["id"])
            conn.commit()
        extras.turn = turn
    except Exception:
        logger.warning("对话轮数没记上，这一轮不算世界书", exc_info=True)
        return extras
    if not proactive and role == "lead":
        try:
            hooks.emit("chat.user_message", persona["id"], {"text": batch_text[:2000], "length": len(batch_text),
                                                       "language": persona.get("language")},
                       query_text=batch_text)
        except Exception:
            logger.warning("chat.user_message 事件没发出去", exc_info=True)
    try:
        with closing(get_conn()) as conn:
            if hooks.enabled(conn):
                extras.effects = queue.turn_effects(conn, persona["id"])
                extras.hook_injects = list(extras.effects.injects)
            effects = lore.Effects(forced=extras.effects.forced if extras.effects else set(),
                                   suppressed=extras.effects.suppressed if extras.effects else set())
            extras.lore = lore.evaluate_turn(conn, persona, session_id, turn, batch_text, batch_ids, effects=effects)
    except Exception:
        logger.warning("世界书这一轮没算出来，跳过", exc_info=True)
    extras.block = (extras.lore.block if extras.lore else "") + _inject_block(extras.hook_injects)
    return extras


async def prepare_async(persona: dict, session_id: int, batch_text: str, batch_ids=(), *,
                        proactive: bool = False, role: str = "lead") -> TurnExtras:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(prepare, persona, session_id, batch_text, list(batch_ids), proactive=proactive,
                              role=role),
            timeout=PREPARE_TIMEOUT)
    except Exception:
        logger.warning("世界书 / hook 准备超时或出错，这一轮不带", exc_info=True)
        return TurnExtras(persona_id=persona.get("id"), session_id=session_id)


def commit(extras: TurnExtras) -> None:
    try:
        with closing(get_conn()) as conn:
            if extras.lore is not None:
                lore.commit(conn, extras.lore)
            if extras.effects is not None:
                queue.consume_turn(conn, extras.effects)
            conn.commit()
    except Exception:
        logger.warning("世界书状态 / hook 队列没写上", exc_info=True)
        return
    for event in (extras.lore.events if extras.lore else []):
        hooks.emit_soon("lore.activated", extras.persona_id, event)


async def commit_async(extras: TurnExtras) -> None:
    if extras.lore is None and extras.effects is None:
        return
    try:
        await asyncio.to_thread(commit, extras)
    except Exception:
        logger.warning("世界书状态提交失败", exc_info=True)


def after_reply(persona_id: int, session_id: int, mood, bubbles: int, fixes: int, proactive: bool,
                language: str | None = None, role: str = "lead") -> None:
    """立刻返回：记情绪、发 chat.reply 都在 hook 的后台线程里做。"""
    def job():
        try:
            with closing(get_conn()) as conn:
                lore_state.set_mood(conn, session_id, persona_id, mood)
                conn.commit()
        except Exception:
            logger.warning("情绪没记上", exc_info=True)
        hooks.emit("chat.reply", persona_id, {"mood": mood, "bubbles": bubbles, "fixes": fixes,
                                              "proactive": proactive, "language": language, "role": role})

    hooks.run_soon(job)
