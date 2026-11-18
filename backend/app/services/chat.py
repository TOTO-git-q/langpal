"""主聊天编排（docs/MAIN-CHAT.md）：一条时间线，主人设 + 副人设，每个人设各有各的脑子。

一轮的样子（routers/chat.py 只管把这里 yield 出的 (event, data) 编码成 SSE）：

    queued（这条被并进攒批，没轮到自己）
  | read -> speaker(lead) -> guard -> (delta* -> bubble_done)×N
      [-> speaker(chime) -> guard -> (delta* -> bubble_done)×1] -> done
  | read -> speaker(lead) -> guard -> (delta* -> bubble_done)×(<N) -> interrupted
  | error（任何阶段异常，代替上面任一分支）

每个事件都带 session_id、persona_id、persona_name、language（说话的那个人、这一条用的语言）。

## 谁说话、说哪门语言（services/chat_room.py）

主讲：点名（to 或消息开头的 @名字）→ 这条消息触发了关键词规则的副人设 → 主人设。
语言：趣味模式随机（不连着两轮同一门）→ 主人设用拨片 → 副人设用母语。
插话：主讲完整发完之后，其余在场的人按各自的概率掷一次，最多一个人插一条短的；
用户这时发来消息（在攒批或在等锁）就不插，插到一半被打断就作废（不交接）。

## 每个人设各有各的脑子

- 常驻会话 key 是 `p{人设}s{主聊天会话}`，每个开过口的人设各一份。
- 她的常驻会话里只有她自己参与的轮次，所以每轮开头给她补一段"你上次开口之后别人说了什么"
  （chat_room.catch_up，按 chat_seen 记的水位，只补没见过的）。
- 系统提示词按她自己编（长期记忆、挂的世界书、母语），不含"这一轮的语言"——语言写在每轮背景块
  第一行（prompts.language_line），所以切语言不会让系统提示词变、不会触发重连。
- 语义回忆、记忆抽取、世界书、事件规则按这一轮说话的人设走；课程、语言守门按这一轮的语言走。

## 攒批 + 打断（按主聊天这一条时间线算，几个人设共用一把锁）

- 每个到达的请求把自己的文本并入 `_SessionState.batch_texts`，用"当选等待者"的 Event 顶掉上一个；
  被顶掉的发 queued 结束，真的等到超时的那一条接手生成 + 投递。
- 打断事件在承载者拿到锁之后立刻建：准备期、生成期、投递期来了实质插话 → set → 第一个检查点醒来，
  没发出的气泡进 unsent，下一轮同一个人设再开口时由 interject.preface() 交接（换了人就作废）。
- 她主动开口（run_proactive_turn）也走同一把锁；正在回复用户、或用户消息在攒批时直接返回空的 done。

节奏（规格 2.2）：第一条前停 250 ms，之后每条前停 min(1700, 250 + 18×这条的字数) ms；
贴图单独一条，排在这一轮所有文字之后。
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import AsyncIterator

from ..db import UPLOAD_DIR, get_conn
from ..providers import registry
from . import bubbles, chat_room, coach_bridge, guard, hooks, interject, prompts, session_pointers, course, turn_context
from . import recall as recall_service
from . import actions, clock, languages, scene as scene_context
from .listening_formats import profiles_for

logger = logging.getLogger(__name__)

try:
    from .tokenize import tokenize as _tokenize
except Exception:  # 分词不可用时用空白符切分兜底，保证聊天主链路不断
    logger.warning("services.tokenize 不可用，chat 用空白符切分兜底", exc_info=True)

    def _tokenize(text: str, language: str) -> list[dict]:
        parts = [p for p in text.split() if p]
        return [{"i": i, "surface": p, "lemma": p, "reading": "", "pos": "", "clickable": True, "collected": False}
                for i, p in enumerate(parts)]


# 连发合并（攒批）窗口默认值 + settings 表的 key。<=0 关闭批处理，退回逐条即回。
_BATCH_DEBOUNCE_KEY = "batch_debounce_sec"
_BATCH_DEBOUNCE_DEFAULT = 1.2  # 实测：3 秒的固定等待占了第一条气泡一大截，1.2 秒回复不变差
# 被打断后接得更急的窗口（秒）。
INTERRUPT_DEBOUNCE_SEC = 1.5

# 节奏（docs/MAIN-CHAT.md 2.2）
FIRST_PAUSE_SEC = 0.25
BUBBLE_PAUSE_BASE_SEC = 0.25
BUBBLE_PAUSE_PER_CHAR_SEC = 0.018
BUBBLE_PAUSE_CAP_SEC = 1.7


def first_pause_seconds() -> float:
    return FIRST_PAUSE_SEC


def bubble_pause_seconds(text: str) -> float:
    """第二条起每条前的停顿：min(1700, 250 + 18 × 这条的字数) ms。贴图按 0 字算。"""
    return min(BUBBLE_PAUSE_CAP_SEC, BUBBLE_PAUSE_BASE_SEC + BUBBLE_PAUSE_PER_CHAR_SEC * len(text or ""))


def _get_batch_debounce_sec(conn) -> float:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_BATCH_DEBOUNCE_KEY,)).fetchone()
    if row is None:
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                     (_BATCH_DEBOUNCE_KEY, str(_BATCH_DEBOUNCE_DEFAULT)))
        conn.commit()
        return _BATCH_DEBOUNCE_DEFAULT
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return _BATCH_DEBOUNCE_DEFAULT


def _collected_lemmas(conn, language: str) -> set[str]:
    return {r["lemma"] for r in conn.execute("SELECT DISTINCT lemma FROM vocab_entries WHERE language = ?",
                                             (language,)).fetchall()}


def _mark_collected(tokens: list[dict], collected: set[str]) -> list[dict]:
    for t in tokens:
        t["collected"] = t.get("lemma") in collected
    return tokens


async def _generate(provider, session_key: str, system_prompt: str, user_text: str,
                    image_paths: list[str] | None = None) -> str:
    parts = []
    async for piece in provider.stream_chat(session_key, system_prompt, user_text, image_paths=image_paths):
        parts.append(piece)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 图片消息：不支持视觉的引擎用 Claude 单独描述一次，失败退化成"她自己说看不到图"，绝不报错。
# ---------------------------------------------------------------------------

def _resolve_image_filename(image_url: str | None) -> str | None:
    if not image_url:
        return None
    name = Path(image_url).name
    if not name or not (UPLOAD_DIR / name).is_file():
        logger.warning("chat: image_url 指向的文件不存在，按无图处理：%r", image_url)
        return None
    return name


_NO_VISION_NOTE = (
    "（对方发来一张图片，但你现在看不到图片内容——可以自然地问ta图里是什么，"
    "不要说“我是AI看不了图”这种出戏的话）\n"
)
_IMAGE_DESCRIBE_SYSTEM = (
    "你是一个图片描述助手，只做一件事：用中文简洁客观地描述用户发来的图片内容"
    "（1-2 句话，说清楚图里有什么、主要颜色/形状/文字/数字），不要寒暄、不要多余的话、"
    "不要输出除描述之外的任何内容。"
)


async def _describe_images(provider, image_paths: list[str]) -> str:
    desc_key = f"imgdesc-{uuid.uuid4().hex}"
    prompt = "请描述这张图片的内容。" if len(image_paths) == 1 else "请依次描述这些图片的内容。"
    try:
        text = await _generate(provider, desc_key, _IMAGE_DESCRIBE_SYSTEM, prompt, image_paths=image_paths)
    finally:
        try:
            result = provider.forget_session(desc_key)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning("图片描述用的一次性会话清理失败，忽略", exc_info=True)
    return text.strip()


async def _build_vision_note(provider, image_abs_paths: list[str]) -> tuple[str, list[str] | None]:
    if provider.supports_vision():
        return "", image_abs_paths
    describer = await registry.get_vision_describer()
    if describer is None:
        return _NO_VISION_NOTE, None
    _, desc_provider = describer
    try:
        caption = await _describe_images(desc_provider, image_abs_paths)
        if not caption:
            return _NO_VISION_NOTE, None
        noun = "一张图片" if len(image_abs_paths) == 1 else "几张图片"
        return f"（对方发来{noun}，内容是：{caption}）\n", None
    except Exception:
        logger.warning("图片兜底描述失败，改用无描述文案", exc_info=True)
        return _NO_VISION_NOTE, None


# ---------------------------------------------------------------------------
# 语义回忆：按这一轮说话的人设检索（她的旧对话 + 主聊天里对方和她说的）。
# ---------------------------------------------------------------------------
_RECALL_EXCLUDE_WINDOW = 30
_RECALL_PREFIX = (
    "（这是系统提供的背景资料，不是对方现在说的话：下面是你们以前聊过、可能和这句话有关的"
    "旧片段。你自然地记得这些事，回复时可以自然带到，但不要复读原文、不要提你在看记录。）\n"
)
_RECALL_SUFFIX = "（以上是回忆）\n"


async def _build_recall_block(persona_id: int, session_id: int, query_text: str) -> str:
    if not (query_text or "").strip():
        return ""
    try:
        conn = get_conn()
        try:
            recent_ids = {r["id"] for r in conn.execute(
                "SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, _RECALL_EXCLUDE_WINDOW)).fetchall()}
        finally:
            conn.close()
        hits = await recall_service.recall(persona_id, query_text, recent_ids, k=3, main_session_id=session_id)
        if not hits:
            return ""
        segments = "\n".join(f"【旧对话片段·{h['when']}】\n{h['text']}\n---" for h in hits)
        logger.info("recall: 注入 %d 个片段，p%ds%d", len(hits), persona_id, session_id)
        return _RECALL_PREFIX + segments + "\n" + _RECALL_SUFFIX
    except Exception:
        logger.warning("recall 失败，跳过本轮注入", exc_info=True)
        return ""


def _coach_lesson_note(persona: dict) -> tuple[str, str | None]:
    try:
        conn = get_conn()
        try:
            return coach_bridge.lesson_note(conn, persona)
        finally:
            conn.close()
    except Exception:
        logger.warning("口语课新课提示生成失败，跳过本轮", exc_info=True)
        return "", None


def _coach_mark_seen(persona_id: int, lesson_id: str) -> None:
    try:
        conn = get_conn()
        try:
            coach_bridge.mark_seen(conn, persona_id, lesson_id)
        finally:
            conn.close()
    except Exception:
        logger.warning("口语课新课已读水位写入失败", exc_info=True)


# ---------------------------------------------------------------------------
# 攒批 + 打断的进程内状态（按主聊天这一条时间线；纯内存，重启即清空）。
# ---------------------------------------------------------------------------

class _SessionState:
    __slots__ = ("batch_texts", "batch_images", "batch_ids", "batch_to", "batch_via", "batch_scene", "batch_event", "gen_lock",
                 "delivery_event", "unsent", "sent_before", "barge", "unsent_persona")

    def __init__(self) -> None:
        self.batch_texts: list[str] = []
        self.batch_images: list[str] = []
        self.batch_ids: list[int] = []
        self.batch_to: int | None = None  # 这一批里最后一次点名
        self.batch_via: str | None = None
        self.batch_scene: dict | None = None
        self.batch_event: asyncio.Event | None = None
        self.gen_lock = asyncio.Lock()
        self.delivery_event: asyncio.Event | None = None
        self.unsent: list[str] = []
        self.sent_before: list[str] = []
        self.barge: int = 0
        self.unsent_persona: int | None = None  # unsent 是谁没说完的


_session_states: dict[str, _SessionState] = {}


def _state_for(session_id: int) -> _SessionState:
    key = f"s{session_id}"
    st = _session_states.get(key)
    if st is None:
        st = _session_states[key] = _SessionState()
    return st


def _join_batch(st: _SessionState, text: str, image_filename: str | None, user_ids: list[int],
                to: int | None, *, via=None, scene=None) -> asyncio.Event:
    """并入等待中的批次并顶掉上一个等待者（全程无 await，在单事件循环上原子执行）。"""
    st.batch_texts.append(text)
    st.batch_ids.extend(user_ids)
    st.batch_via, st.batch_scene = via, scene
    if image_filename:
        st.batch_images.append(image_filename)
    if to is not None:
        st.batch_to = to
    old_event = st.batch_event
    my_event = asyncio.Event()
    st.batch_event = my_event
    if old_event is not None:
        old_event.set()
    return my_event


async def _interruptible_sleep(event: asyncio.Event | None, seconds: float) -> bool:
    """睡 seconds 秒，期间若 event 被 set 提前醒来。返回是否被打断。"""
    if event is None:
        if seconds > 0:
            await asyncio.sleep(seconds)
        return False
    if event.is_set():
        return True
    if seconds <= 0:
        return False
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


def _flatten_tokens(bubble_token_lists: list[list[dict]]) -> list[dict]:
    flat, idx = [], 0
    for tokens in bubble_token_lists:
        for t in tokens:
            item = dict(t)
            item["i"] = idx
            flat.append(item)
            idx += 1
    return flat


def _busy(st: _SessionState) -> bool:
    return st.gen_lock.locked() or st.delivery_event is not None or st.batch_event is not None or bool(st.batch_texts)


def _persona(conn, persona_id: int) -> dict:
    row = conn.execute("SELECT * FROM personas WHERE id = ? AND archived_at IS NULL", (persona_id,)).fetchone()
    if row is None:
        raise ValueError(f"人设 {persona_id} 不存在")
    return dict(row)


# ---------------------------------------------------------------------------
# 用户发消息
# ---------------------------------------------------------------------------

async def run_chat_turn(text: str, image_url: str | None = None, sticker: str | None = None,
                        to: int | None = None, *, via=None, scene=None) -> AsyncIterator[tuple[str, dict]]:
    try:
        text = text or ""
        image_filename = _resolve_image_filename(image_url)
        if sticker is not None and sticker not in prompts.sticker_ids():
            raise ValueError("没有这张贴图")
        conn = get_conn()
        try:
            config = chat_room.settings(conn)
            if config.primary_id is None:
                raise ValueError("请先创建一张人设卡")
            sid = chat_room.main_session_id(conn, create=True)
            meanings = chat_room.sticker_meanings()
            user_ids, model_parts = [], []
            # 用户发的贴图单独一条（落库沿用 [sticker:id]），模型看到的是"对方发了一张贴图：意思"
            if sticker is not None:
                user_ids.append(conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (?, 'user', ?)",
                    (sid, f"[sticker:{sticker}]")).lastrowid)
                model_parts.append(chat_room.describe(f"[sticker:{sticker}]", None, meanings))
            if text or image_filename or not user_ids:
                user_ids.append(conn.execute(
                    "INSERT INTO messages (session_id, role, content, image_path) VALUES (?, 'user', ?, ?)",
                    (sid, text, image_filename)).lastrowid)
                if text:
                    model_parts.append(text)
            conn.commit()
            debounce_sec = _get_batch_debounce_sec(conn)
        finally:
            conn.close()

        model_text = "\n".join(model_parts)
        st = _state_for(sid)
        metadata = {"session_id": sid, "persona_id": config.primary_id, "persona_name": None,
                    "language": config.language}

        # 打断判定：已经有一轮（或她主动开口的那一轮、插话）在飞时才有意义。
        inflight_ev = st.delivery_event
        braking = inflight_ev is not None and not interject.is_trivial(model_text)
        if braking:
            inflight_ev.set()
            st.barge += 1

        if debounce_sec > 0:
            wait_secs = INTERRUPT_DEBOUNCE_SEC if braking else debounce_sec
            my_event = _join_batch(st, model_text, image_filename, user_ids, to, via=via, scene=scene)
            try:
                await asyncio.wait_for(my_event.wait(), timeout=wait_secs)
                yield "queued", dict(metadata)  # 被后来者顶替：交给最后一条去发
                return
            except asyncio.TimeoutError:
                pass
        else:
            if st.batch_event is not None:
                st.batch_event.set()
                st.batch_event = None
            st.batch_texts.append(model_text)
            st.batch_ids.extend(user_ids)
            st.batch_via, st.batch_scene = via, scene
            if image_filename:
                st.batch_images.append(image_filename)
            if to is not None:
                st.batch_to = to

        # 确认自己是"这一批最后一条"：立刻把批次取走清空（不要等拿到锁才取）。
        batch_texts = [t for t in st.batch_texts if t] or [model_text]
        batch_images = st.batch_images
        batch_ids = st.batch_ids or user_ids
        batch_to = st.batch_to
        batch_via, batch_scene = st.batch_via, st.batch_scene
        st.batch_via, st.batch_scene = None, None
        st.batch_texts, st.batch_images, st.batch_ids, st.batch_to, st.batch_event = [], [], [], None, None
        joined_text = "\n".join(batch_texts)

        async with st.gen_lock:
            async for item in _round(sid, st, joined_text, batch_images, batch_ids, batch_to,
                                     via=batch_via, scene=batch_scene):
                yield item
    except Exception as e:
        logger.exception("run_chat_turn 未兜住的异常")
        yield "error", {"message": str(e)}


async def _round(sid: int, st: _SessionState, joined_text: str, batch_images: list[str], batch_ids: list[int],
                 to: int | None, *, via=None, scene=None) -> AsyncIterator[tuple[str, dict]]:
    """拿着锁：主讲说完，可能有一个人插话，最后发 done。"""
    conn = get_conn()
    try:
        config = chat_room.settings(conn)
        lead_id = chat_room.choose_lead(conn, config, joined_text, to)
        lead = _persona(conn, lead_id)
        language = chat_room.choose_language(conn, config, lead, sid)
        if scene is not None and scene["tab"] != "talk" and scene.get("language") in languages.registered(conn):
            language = scene["language"]
        present = chat_room.present_guest_ids(conn, config, joined_text)
    finally:
        conn.close()
    # 已读：攒批结束、确定这一轮要回复的那一刻就发（她"拿起手机"），不等回忆/世界书这些准备做完
    if batch_ids:
        conn = get_conn()
        try:
            marks = ",".join("?" * len(batch_ids))
            conn.execute(f"UPDATE messages SET read_at = datetime('now', 'localtime') "
                         f"WHERE id IN ({marks}) AND read_at IS NULL", batch_ids)
            conn.commit()
        finally:
            conn.close()
        yield "read", {"message_ids": list(batch_ids), "session_id": sid, "persona_id": lead["id"],
                       "persona_name": lead["name"], "language": language}
    outcome: dict = {}
    async for item in _speak(lead, sid, st, role="lead", language=language, joined_text=joined_text,
                             batch_images=batch_images, batch_ids=batch_ids, outcome=outcome, via=via, scene=scene):
        yield item
    if outcome.get("status") != "done":
        return
    message_ids = list(outcome["message_ids"])
    done_meta = outcome["meta"]

    # 插话：主讲完整发完、用户没有新消息在排队时才可能
    chimer = None if _busy_with_user(st) else chat_room.roll_chime(config, lead_id, present)
    if chimer is not None:
        conn = get_conn()
        try:
            person = _persona(conn, chimer)
            chime_language = chat_room.choose_language(conn, config, person, sid, previous=language)
        finally:
            conn.close()
        chime: dict = {}
        async for name, data in _speak(person, sid, st, role="chime", language=chime_language, joined_text="",
                                       batch_images=[], batch_ids=[], outcome=chime):
            if name in ("interrupted", "error"):
                continue  # 插话被打断/出错就作废，不影响主讲这一轮
            yield name, data
        if chime.get("status") == "done":
            message_ids += chime["message_ids"]
        elif chime.get("status") == "interrupted":
            st.unsent, st.sent_before, st.unsent_persona = [], [], None  # 插话取消，不交接
    yield "done", {"message_ids": message_ids, **done_meta}


def _busy_with_user(st: _SessionState) -> bool:
    return st.batch_event is not None or bool(st.batch_texts)


# ---------------------------------------------------------------------------
# 她主动开口（services/hooks 的 say 动作排进来的）
# ---------------------------------------------------------------------------

_PROACTIVE_PROMPT = (
    "（这是系统提示，不是对方说的话，回复里不要提到这条提示，也不要复述它：这一轮对方没有发新消息，"
    "是你自己想主动找对方说话。下面是你此刻的念头，用你自己的口吻、像平时发消息那样自然地开口，"
    "别说“系统”“提示”“任务”这类词。）\n你的念头：{directive}\n"
)
_ENTER_PROMPT = "（你刚走进这个聊天，别人之前在聊什么见上面。打个招呼或者直接接话都行。）\n"
_PROACTIVE_DEFAULT = "好一阵没聊了，想找对方说说话。"
_CHIME_PROMPT = (
    "（这是系统提示，不是对方说的话，不要提到它：上面是刚刚主聊天里的对话，现在不是轮到你主讲，"
    "你在旁边想插一句。只发一条很短的气泡（一两句话以内），自然地接上刚才的话头，"
    "不用跟对方打招呼，也不要替别人说话。）\n"
)


async def run_proactive_turn(persona_id: int | None = None) -> AsyncIterator[tuple[str, dict]]:
    """POST /api/chat/proactive：取最早的一条待发（给了 persona_id 就只取她的），像平时一样生成、拆气泡、
    落库。没有待发、或主聊天正在回复用户/在攒批 → 直接 done {empty: true}。事件都带 proactive: true。
    规则限定的副人设此刻不在场 → 先发一个 system {kind: "enter"} 胶囊（她"进场"），再说话。"""
    tag = {"proactive": True}
    try:
        from . import hooks

        conn = get_conn()
        try:
            config = chat_room.settings(conn)
            sid = chat_room.main_session_id(conn, create=config.primary_id is not None)
            conn.commit()
        finally:
            conn.close()
        empty = {"session_id": sid, "persona_id": persona_id, "persona_name": None, "language": None,
                 "empty": True, **tag}
        if sid is None or _busy(_state_for(sid)):
            yield "done", empty
            return
        item = await asyncio.to_thread(hooks.claim_say, persona_id)
        if item is None:
            yield "done", empty
            return
        item_id, directive, speaker_id = item
        st = _state_for(sid)
        if _busy(st):  # 取队列那一下用户正好发来了消息：退回队列，让用户的消息先走
            hooks.unclaim(item_id)
            yield "done", empty
            return
        await st.gen_lock.acquire()  # 上面刚判过没被占，这里不会等
        delivered = failed = False
        capsule_id = None
        try:
            conn = get_conn()
            try:
                config = chat_room.settings(conn)
                person = _persona(conn, speaker_id)
                language = chat_room.choose_language(conn, config, person, sid)
                present = (speaker_id == config.primary_id
                           or speaker_id in chat_room.present_guest_ids(conn, config, sid=sid))
                if not present:
                    capsule_id = conn.execute(
                        "INSERT INTO messages (session_id, role, content, persona_id, language) "
                        "VALUES (?, 'assistant', '[system:enter]', ?, ?)", (sid, speaker_id, language)).lastrowid
                    conn.commit()
            finally:
                conn.close()
            meta = {"session_id": sid, "persona_id": speaker_id, "persona_name": person["name"],
                    "language": language, **tag}
            if capsule_id is not None:
                yield "system", {"kind": "enter", "text": f"{person['name']} 来了", "message_id": capsule_id, **meta}
            outcome: dict = {}
            prompt = (_ENTER_PROMPT if capsule_id else "") + _PROACTIVE_PROMPT.format(
                directive=directive.strip() or _PROACTIVE_DEFAULT)
            async for name, data in _speak(person, sid, st, role="lead", language=language, joined_text="",
                                           batch_images=[], batch_ids=[], outcome=outcome, directive=prompt):
                delivered = delivered or name == "bubble_done"
                failed = failed or name == "error"
                yield name, {**data, **tag}
            if outcome.get("status") == "done":
                ids = ([capsule_id] if capsule_id else []) + list(outcome["message_ids"])
                yield "done", {"message_ids": ids, **outcome["meta"], **tag}
        finally:
            st.gen_lock.release()
            if failed and not delivered:
                hooks.unclaim(item_id)  # 一条都没发出去：留着下次再试
                if capsule_id is not None:
                    conn = get_conn()
                    try:
                        conn.execute("DELETE FROM messages WHERE id = ?", (capsule_id,))
                        conn.commit()
                    finally:
                        conn.close()
    except Exception as e:
        logger.exception("run_proactive_turn 未兜住的异常")
        yield "error", {"message": str(e), **tag}


async def _maybe_rotate(session_key: str, *, before_message_id: int | None = None) -> bool:
    """原生会话轮换（docs/MAIN-CHAT.md 1.3）：跑满 60 轮或用满 7 天、并且这条时间线已经安静 3 小时以上，
    就作废指针、下一次连接开一段新的。出错只记日志、照旧 resume。"""
    try:
        due = await asyncio.to_thread(session_pointers.due_for_rotation, session_key,
                                      before_message_id=before_message_id)
        if due is None:
            return False
        await registry.rotate_native(session_key)
        logger.info("原生会话轮换：%s 跑了 %d 轮、%.1f 天，换一段新的", session_key, due["turns"], due["age_days"])
        return True
    except Exception:
        logger.warning("原生会话轮换检查失败，照旧 resume", exc_info=True)
        return False


def _system_for(conn, persona: dict, sid: int):
    """这个人设在主聊天里的系统提示词（连接时冻结的那份）。正常一轮和预热都用这一个函数，
    保证两边一字不差——不然预热连好的客户端会被当成"世界书变了"重连掉。
    返回 (系统提示词, 世界书系统部分, 她是不是第一次在这段对话里开口)。"""
    first_time = not chat_room.has_spoken(conn, sid, persona["id"])
    context_card = prompts.build_context_card(conn, persona["id"], sid) if first_time else ""
    system_lore = turn_context.system_lore(conn, persona, sid)
    return prompts.compile_system_prompt(conn, persona, context_card, lore=system_lore), system_lore, first_time


# ---------------------------------------------------------------------------
# 预热（POST /api/chat/main/warm）：把"主人设的第一轮"里和用户消息无关的准备提前做完
# ---------------------------------------------------------------------------
WARM_FRESH_SEC = 300.0
_warm_state: dict = {"key": None, "at": 0.0, "task": None, "lore_warmed": False}


def _load_recall_model() -> None:
    recall_service._load_model_sync()


def _warm_lore_once() -> None:
    if _warm_state["lore_warmed"]:
        return
    from .lore import store as lore_store
    conn = get_conn()
    try:
        lore_store.warm_soon(conn)
    finally:
        conn.close()
    _warm_state["lore_warmed"] = True


def _warm_target() -> dict | None:
    conn = get_conn()
    try:
        config = chat_room.settings(conn)
        if config.primary_id is None:
            return None
        sid = chat_room.main_session_id(conn, create=True)
        conn.commit()
        persona = _persona(conn, config.primary_id)
        system_prompt, system_lore, first_time = _system_for(conn, persona, sid)
    finally:
        conn.close()
    engine = registry.feature_engine("chat")
    return {"sid": sid, "session_key": f"p{persona['id']}s{sid}", "system_prompt": system_prompt,
            "fingerprint": system_lore.fingerprint, "first_time": first_time,
            "key": (persona["id"], sid, engine, hashlib.sha256(system_prompt.encode()).hexdigest())}


async def _do_warm() -> None:
    try:
        try:
            await asyncio.to_thread(_load_recall_model)
        except Exception:
            logger.warning("预热：回忆模型没加载上（之后按需再试）", exc_info=True)
        try:
            _warm_lore_once()
        except Exception:
            logger.warning("预热：世界书关键词预热没启动", exc_info=True)
        target = await asyncio.to_thread(_warm_target)
        if target is None:
            return
        fresh = time.monotonic() - _warm_state["at"] < WARM_FRESH_SEC
        if target["key"] == _warm_state["key"] and fresh:
            return  # 5 分钟内同一个主人设、同一个引擎、同一份系统提示词已经预热过
        if _state_for(target["sid"]).gen_lock.locked():
            return  # 正在回复：那一轮自己会连
        await _maybe_rotate(target["session_key"])
        await registry.sync_system_lore(target["session_key"], target["fingerprint"])
        await registry.warm_session(target["session_key"], target["system_prompt"],
                                    is_new_session=target["first_time"])
        _warm_state.update(key=target["key"], at=time.monotonic())
        logger.info("预热完成：%s", target["session_key"])
    except Exception:
        logger.warning("预热失败（不影响聊天，第一轮自己再连）", exc_info=True)
    finally:
        _warm_state["task"] = None


def warm_main() -> str:
    """开始预热，立即返回：running（已经在做）/ started。换主人设、换引擎、系统提示词变了都会重做；
    同样的东西 5 分钟内做过就是空操作（在后台判断）。"""
    task = _warm_state["task"]
    if task is not None and not task.done():
        return "running"
    _warm_state["task"] = asyncio.get_running_loop().create_task(_do_warm())
    return "started"


async def warm_on_startup(delay: float = 5.0) -> None:
    """后端启动完成后：距离上次用户消息不到 12 小时就自动预热一次（延后几秒，不挡启动）。"""
    try:
        await asyncio.sleep(delay)
        conn = get_conn()
        try:
            row = conn.execute("SELECT max(created_at) FROM messages WHERE role = 'user'").fetchone()
        finally:
            conn.close()
        from . import clock
        last = clock.parse(row[0]) if row else None
        if last is not None and (clock.now() - last).total_seconds() < 12 * 3600:
            warm_main()
            task = _warm_state["task"]
            if task is not None:
                await task
    except Exception:
        logger.warning("启动预热没做成", exc_info=True)


# ---------------------------------------------------------------------------
# 一个人设说一次话：准备 → 生成 → 守门 → 拆气泡 → 按节奏投递 → 落库 → 后台钩子
# ---------------------------------------------------------------------------

async def _speak(persona: dict, sid: int, st: _SessionState, *, role: str, language: str, joined_text: str,
                 batch_images: list[str], batch_ids: list[int], outcome: dict,
                 directive: str | None = None, via=None, scene=None) -> AsyncIterator[tuple[str, dict]]:
    """调用方已经拿着 st.gen_lock。不发 done（由调用方在插话之后统一发），结果写进 outcome：
    {"status": "done"|"interrupted"|"error", "message_ids": [...], "meta": {...}}。

    role：lead（主讲：读用户消息、课程照常；read 由 _round 在这之前发）/ chime（插话：一条短的、不算课程）。
    directive：她主动开口时给模型的那段话（不落库）。"""
    persona_id = persona["id"]
    session_key = f"p{persona_id}s{sid}"
    proactive = directive is not None
    speaking = {**persona, "language": language}  # 这一轮按本轮语言算的人设副本（课程、世界书、规则）
    meta = {"session_id": sid, "persona_id": persona_id, "persona_name": persona["name"], "language": language}
    outcome.update(status="error", message_ids=[], meta=meta)
    delivery_ev = None
    yield "speaker", {**meta, "role": role}
    try:
        # 上一轮被打断没说完的话：只交接给同一个人
        if st.unsent_persona == persona_id:
            pre = interject.preface(st.unsent, st.sent_before, st.barge)
        else:
            pre = ""
        st.unsent, st.sent_before, st.unsent_persona = [], [], None

        # 打断事件拿到锁之后立刻建：准备期、生成期的实质插话同样能刹住。
        delivery_ev = asyncio.Event()
        st.delivery_event = delivery_ev

        conn = get_conn()
        try:
            system_prompt, system_lore, first_time = _system_for(conn, persona, sid)
            catch_up = chat_room.catch_up(conn, sid, persona_id, before_id=min(batch_ids) if batch_ids else None)
            registered = languages.registered(conn)
        finally:
            conn.close()
        await registry.sync_system_lore(session_key, system_lore.fingerprint)

        recall_block = await _build_recall_block(persona_id, sid, joined_text or catch_up)
        coach_note, coach_lesson_id = _coach_lesson_note(speaking) if role == "lead" else ("", None)
        extras = await turn_context.prepare_async(speaking, sid, joined_text, batch_ids,
                                                  proactive=proactive, role=role)
        voice = chat_room.voice_block(persona, language, sid, extras.turn)

        # 原生会话太长又刚好安静了很久：这一轮开一段新的（拿着锁、还没开始生成，不会打断在飞的回复）
        await _maybe_rotate(session_key, before_message_id=min(batch_ids) if batch_ids else None)
        provider = registry.get_provider(session_key, is_new_session=first_time)
        image_abs_paths = [str((UPLOAD_DIR / fn).resolve()) for fn in batch_images if (UPLOAD_DIR / fn).is_file()]
        vision_note, send_image_paths = "", None
        if image_abs_paths:
            vision_note, send_image_paths = await _build_vision_note(provider, image_abs_paths)

        # 背景块顺序：本轮语言 → 补课 → 口吻样本 → 口语课新课 → 语义回忆 → 世界书 + hook 提示 →
        # 打断交接 → 图片 → 对方这一轮的消息（或主动开口 / 插话的说明）
        background = (prompts.language_line(language) + catch_up + voice + coach_note + recall_block
                      + extras.block + pre + vision_note)
        formats = {key: profile.label for key, profile in profiles_for(language).items()}
        if role == "lead" and not proactive:
            if scene is not None:
                with closing(get_conn()) as conn, conn:
                    course_line = course.brief(conn, language, clock.now())
                background += actions.prompt_block(language, registered, formats, course_line)
                background += scene_context.scene_block(scene, registered.get(scene.get("language")))
            if via == "stage":
                background += scene_context.STAGE_LINE
        if directive is not None:
            user_text = background + directive
        elif role == "chime":
            user_text = background + _CHIME_PROMPT
        else:
            user_text = background + "\n【对方本轮消息】\n" + joined_text


        try:
            reply = await _generate(provider, session_key, system_prompt, user_text, image_paths=send_image_paths)
            registry.report_recovery(session_key)
        except Exception as primary_err:
            fallback = await registry.report_failure(session_key, primary_err)
            if fallback is None:
                st.delivery_event = None
                yield "error", {"message": f"聊天引擎暂时不可用：{primary_err}", **meta}
                return
            provider = fallback
            try:
                reply = await _generate(provider, session_key, system_prompt, user_text,
                                        image_paths=send_image_paths if provider.supports_vision() else None)
            except Exception as fallback_err:
                st.delivery_event = None
                yield "error", {"message": f"降级引擎也失败了：{fallback_err}", **meta}
                return

        # 生成成功：世界书粘性/冷却、hook 的 inject 用掉一轮
        await turn_context.commit_async(extras)
        if coach_lesson_id:
            _coach_mark_seen(persona_id, coach_lesson_id)

        # 标记（fix / mood）在守门前剥掉，永远不进气泡、不落库
        reply, fixes = coach_bridge.extract_fixes(reply)
        reply, mood = bubbles.strip_mood(reply)
        reply, reply_actions = actions.extract(reply, languages=registered, formats=formats)

        retries = 0
        ok = guard.check(bubbles.strip_sticker_lines_for_guard(reply), language)
        if not ok and not delivery_ev.is_set():
            try:
                retried = await _generate(provider, session_key, system_prompt, guard.correction_prompt(language))
                retried, fixes = coach_bridge.extract_fixes(retried)
                retried, mood = bubbles.strip_mood(retried)
                retried, reply_actions = actions.extract(retried, languages=registered, formats=formats)
                retries, reply = 1, retried
                ok = guard.check(bubbles.strip_sticker_lines_for_guard(retried), language)
            except Exception:
                logger.exception("guard 重生成失败，照发第一次的结果（打标 failed）")
                ok = False
        status = "pass" if (ok and retries == 0) else ("retried" if ok else "failed")

        bubble_items = bubbles.split_bubbles_with_stickers(reply, prompts.sticker_ids()) if reply.strip() else []
        # 贴图单独一条，排在这一轮所有文字之后
        bubble_items = [b for b in bubble_items if b["sticker"] is None] + \
                       [b for b in bubble_items if b["sticker"] is not None]
        if role == "chime":  # 插话只要一条短的
            bubble_items = bubble_items[:1]
        yield "guard", {"status": status, "retries": retries, "mood": mood, **meta}

        conn = get_conn()
        try:
            collected = _collected_lemmas(conn, language)
        finally:
            conn.close()

        sent_texts: list[str] = []
        sent_tokens: list[list[dict]] = []
        message_ids: list[int] = []
        interrupted = delivery_ev.is_set()
        from . import word_glosses
        prepared_tokens: dict[int, list[dict]] = {}

        def prepare_words(index):
            item = bubble_items[index]
            if item["sticker"] is not None or index in prepared_tokens:
                return
            tokens = _mark_collected(_tokenize(item["text"], language), collected)
            prepared_tokens[index] = tokens
            try:
                word_glosses.schedule(item["text"], language, tokens)
            except Exception:
                logger.debug("词义预热未启动", exc_info=True)

        if bubble_items:
            prepare_words(0)
        try:
            for i, item in enumerate(bubble_items):
                bubble_text, sticker_id = item["text"], item["sticker"]
                prepare_words(i)
                pause = first_pause_seconds() if i == 0 else bubble_pause_seconds("" if sticker_id else bubble_text)
                if await _interruptible_sleep(delivery_ev, pause):
                    interrupted = True
                    break
                tokens: list[dict] = []
                stopped_mid_bubble = False
                if sticker_id is None:
                    tokens = prepared_tokens[i]
                    for chunk in bubbles.delta_chunks(bubble_text):
                        yield "delta", {"text": chunk, "bubble": i, **meta}
                        if await _interruptible_sleep(delivery_ev, bubbles.DELTA_PAUSE_SEC):
                            stopped_mid_bubble = True
                            break
                if stopped_mid_bubble:
                    interrupted = True
                    break
                if sticker_id is not None:
                    tokens_json = None
                else:
                    try:
                        word_glosses.attach_cached(tokens, bubble_text, language)
                    except Exception:
                        logger.debug("词义缓存不可用，保留原分词", exc_info=True)
                    tokens_json = json.dumps(tokens, ensure_ascii=False)
                conn = get_conn()
                try:
                    message_id = conn.execute(
                        "INSERT INTO messages (session_id, role, content, tokens_json, guard_flag, persona_id, language) "
                        "VALUES (?, 'assistant', ?, ?, ?, ?, ?)",
                        (sid, bubble_text, tokens_json, 0 if status != "failed" else 1, persona_id, language)).lastrowid
                    conn.commit()
                finally:
                    conn.close()
                yield "bubble_done", {"bubble": i, "message_id": message_id, "tokens": tokens, "sticker": sticker_id,
                                      "text": "" if sticker_id else bubble_text, **meta}
                sent_texts.append(bubble_text)
                sent_tokens.append(tokens)
                message_ids.append(message_id)
        finally:
            st.delivery_event = None
            _mark_seen(sid, persona_id)

        outcome["message_ids"] = message_ids
        if interrupted or delivery_ev.is_set():
            delivered_n = len(sent_texts)
            st.unsent = [it["text"] for it in bubble_items[delivered_n:]]
            st.sent_before = list(sent_texts)
            st.unsent_persona = persona_id
            outcome["status"] = "interrupted"
            yield "interrupted", {"delivered": delivered_n, **meta}
            return

        st.barge = 0
        if role == "lead" and not proactive:
            for action in reply_actions:
                yield "action", {**action, **meta}
        outcome["status"] = "done"
        try:
            await asyncio.to_thread(session_pointers.count_turn, session_key)
        except Exception:
            logger.warning("原生会话轮数没记上", exc_info=True)
        # 学习记录（docs/LEARNING.md）：只在完整发完的轮次做，放后台，出错只记日志
        _learning_after_turn(language, sid, joined_text if role == "lead" else "", sent_tokens, len(fixes),
                             record=role == "lead")
        if role == "lead" and not proactive:
            if fixes:
                asyncio.create_task(coach_bridge.record_fixes(persona_id, persona["name"], language, fixes, joined_text))
        asyncio.create_task(_run_background_hooks(sid, persona_id))
        turn_context.after_reply(persona_id, sid, mood, len(sent_texts), len(fixes), proactive,
                                 language=language, role=role)
    except Exception as e:
        logger.exception("聊天这一轮未兜住的异常")
        if delivery_ev is not None and st.delivery_event is delivery_ev:
            st.delivery_event = None
        outcome["status"] = "error"
        yield "error", {"message": str(e), **meta}


def _learning_after_turn(language: str, sid: int, user_text: str, bubble_tokens: list[list[dict]], fixes: int, *,
                         record: bool) -> None:
    """一轮完整发完之后（后台线程）：
    - 用户这条消息里用到了到期的已收藏词 → learning.chat_success（一次弱的"记得"）；
    - 这一轮双方消息里出现的已收藏词 → learning.encounter_lemmas（碰见一次）；
    - 主讲的每一轮记一条学习记录 study_events(kind="chat")。语言是这一轮的语言。"""
    def job():
        try:
            from . import learning

            user_lemmas = [t.get("lemma") or t.get("surface") or "" for t in _tokenize(user_text, language)] \
                if user_text.strip() else []
            her_lemmas = [t.get("lemma") or t.get("surface") or "" for tokens in bubble_tokens for t in tokens]
            conn = get_conn()
            try:
                if user_lemmas:
                    learning.chat_success(conn, language, user_lemmas)
                if user_lemmas or her_lemmas:
                    learning.encounter_lemmas(conn, language, user_lemmas + her_lemmas)
                if record:
                    learning.record_event(conn, "chat", language, str(sid), {"turns": 1, "fixes": fixes})
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("这一轮的学习记录没写上（不影响聊天）", exc_info=True)

    hooks.run_soon(job)


def _mark_seen(sid: int, persona_id: int) -> None:
    try:
        conn = get_conn()
        try:
            chat_room.mark_seen(conn, sid, persona_id)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("看到哪了没记上", exc_info=True)


async def _run_background_hooks(session_id: int, persona_id: int) -> None:
    # 词义预热已在每个气泡投递前启动；这里只做这个人设的长期记忆抽取和向量索引。
    try:
        from .memoryx import maybe_extract

        await maybe_extract(session_id, persona_id)
    except Exception:
        logger.warning("memoryx 抽取失败，跳过", exc_info=True)
    try:
        await recall_service.embed_new_messages(session_id)
    except Exception:
        logger.warning("recall embed_new_messages 失败，跳过", exc_info=True)
