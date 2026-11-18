"""Provider 选择与降级切换。业务代码（services/chat.py 等）只 import 这里，不直接实例化 provider。

四个引擎：claude（AgentSDKProvider，主力）、deepseek（DeepSeek 官方 API 直连）、custom（用户自配的
OpenAI 兼容端点）、chatgpt（ChatGPT 账号登录，providers/chatgpt.py）。都懒初始化、进程内单例。
库里遗留的 chat_engine=codex 当 claude，启动时由 normalize_settings() 写回规范值。

策略：
- 每次开新会话读 settings.chat_engine 决定这次用哪个引擎（"意向引擎"），把这个 session_key 钉在它上面。
- 续接已有会话沿用这个 session_key 当前在用的引擎，不做每轮探测。
- 限流/不可用检测是反应式的：services/chat.py 在 stream_chat 抛错时调 report_failure() 换降级引擎重试。
  降级链见 _FALLBACK_CHAIN：chatgpt → claude → deepseek；deepseek → claude；claude/custom → deepseek
  （deepseek 必须 configured() 且 health() 都过才算可用，都不可用返回 None，原样报错）。custom 从不作为降级目标。
  settings.chat_fallback 默认 enabled；设成 none 才关掉自动降级。
- get_utility_provider()（杂活：词卡/句解析/记忆抽取）：auto = 配了 DeepSeek key 走 DeepSeek 直连，
  否则 Claude Haiku。

## 降级后怎么回来（2026-09-25 修）

langpal 是每个人设一条永续会话（前端没有"开新对话"），新会话永远不会来——9/9 Claude 临时 403 了
一次，糖糖从此一直用 DeepSeek 说话，直到两周后才被发现。现在是熔断器的"半开"：被钉住超过
_RETRY_INTENDED_AFTER_SEC 后，下一条消息重新试一次意向引擎；成功就回来（report_recovery 清
degraded），失败就由 report_failure 再钉回去、重新计时。

离开一个引擎时作废它的原生会话指针（session_pointers 表里这把 key 的那份）：它的原生上下文停在离开那一刻，之后的
轮次都只在 DB 里。直接 resume 回去，她会接着一份过期的对话往下说。作废后，下次连接走"新连接 +
当前会话回顾 + 语义回忆"，上下文从 DB 这个唯一真相重建。
"""

import asyncio
import logging
import re
import time

from ..db import get_conn
from ._settings import get_setting
from .agent_sdk import AgentSDKProvider
from .base import LLMProvider
from .deepseek import CustomProvider, DeepSeekProvider

logger = logging.getLogger(__name__)

ENGINES = ("claude", "deepseek", "custom", "chatgpt")
_DEFAULT_ENGINE = "claude"
# 已移除的引擎名：库里存着就当默认的 claude，启动时写回。
_LEGACY_ENGINES = ("codex",)
UTILITY_CHOICES = ("auto", *ENGINES)
FALLBACK_CHOICES = ("enabled", "none")
_FALLBACK_DEFAULT = "enabled"

_primary: AgentSDKProvider | None = None
_fallback: DeepSeekProvider | None = None
_custom: CustomProvider | None = None
_chatgpt: LLMProvider | None = None

# session_key -> 当前实际在用的引擎名
_session_engine: dict[str, str] = {}
# session_key -> 新会话建立时按 settings.chat_engine 选定的"意向引擎"（降级恢复的参照系）
_session_intended: dict[str, str] = {}
# session_key -> 被 report_failure 钉到备用引擎上的时刻（time.monotonic()）
_pinned_at: dict[str, float] = {}

# 当前引擎出错时按顺序尝试的接手引擎（custom 从不作为降级目标）。
_FALLBACK_CHAIN = {
    "chatgpt": ("claude", "deepseek"),
    "deepseek": ("claude",),
    "claude": ("deepseek",),
    "custom": ("deepseek",),
}

# 被钉在备用引擎上多久之后，重新试一次意向引擎。
_RETRY_INTENDED_AFTER_SEC = 600.0

# 各引擎存在 sessions 表里的"原生会话指针"。deepseek/custom 没有：它们每次首现都从 DB 补种。
# 指针按整把 key（p{人设}s{会话}）存在 session_pointers 表（services/session_pointers.py）。
_NATIVE_POINTER_ENGINES = frozenset({"claude"})


def _get_primary() -> AgentSDKProvider:
    global _primary
    if _primary is None:
        _primary = AgentSDKProvider()
    return _primary


def _get_fallback() -> DeepSeekProvider:
    global _fallback
    if _fallback is None:
        _fallback = DeepSeekProvider()
    return _fallback


def _get_custom() -> CustomProvider:
    global _custom
    if _custom is None:
        _custom = CustomProvider()
    return _custom


def _get_chatgpt() -> LLMProvider:
    global _chatgpt
    if _chatgpt is None:
        from .chatgpt import ChatGPTProvider

        _chatgpt = ChatGPTProvider()
    return _chatgpt


def _memory_provider(engine: str):
    """已经构造过的、按内存历史保持上下文的 provider（deepseek/custom/chatgpt）；没构造过返回 None。"""
    return {"deepseek": _fallback, "custom": _custom, "chatgpt": _chatgpt}.get(engine)


def _provider_for(engine: str) -> LLMProvider:
    if engine == "chatgpt":
        return _get_chatgpt()
    if engine == "deepseek":
        return _get_fallback()
    if engine == "custom":
        return _get_custom()
    return _get_primary()


def normalize_engine(value: str | None) -> str:
    v = (value or "").strip()
    if v in _LEGACY_ENGINES:
        return _DEFAULT_ENGINE
    return v if v in ENGINES else _DEFAULT_ENGINE


def _chat_engine_setting() -> str:
    return normalize_engine(get_setting("chat_engine", _DEFAULT_ENGINE))


def fallback_enabled() -> bool:
    return get_setting("chat_fallback", _FALLBACK_DEFAULT).strip() != "none"


def normalize_settings() -> None:
    """启动时调用：把上一轮遗留的 chatgpt/codex 引擎选择写回规范值。只改这三个键，别的设置
    （包括 chat_main / chat_main_session 之类不再读取的旧键）原样不动。"""
    conn = get_conn()
    try:
        rows = dict(conn.execute(
            "SELECT key, value FROM settings WHERE key IN "
            "('chat_engine', 'utility_engine', 'listening_subscription')"
        ).fetchall())
        fixes = {}
        if rows.get("chat_engine") is not None and rows["chat_engine"] not in ENGINES:
            fixes["chat_engine"] = _DEFAULT_ENGINE
        if rows.get("utility_engine") is not None and rows["utility_engine"] not in UTILITY_CHOICES:
            fixes["utility_engine"] = "auto"
        if rows.get("listening_subscription") not in (None, "", *ENGINES):
            fixes["listening_subscription"] = ""
        for key, value in fixes.items():
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        if fixes:
            conn.commit()
            logger.info("引擎设置已规范化：%s", fixes)
    finally:
        conn.close()


def _write_settings(engine: str, degraded: bool) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('engine', ?)", (engine,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('degraded', ?)",
            ("1" if degraded else "0",),
        )
        conn.commit()
    finally:
        conn.close()


def _invalidate_native_pointer(engine: str, session_key: str | None = None) -> None:
    """作废某引擎的原生会话指针：给了 session_key 就只作废这一把 key（这个人设在这段对话里的那份，
    同一段对话里别的人设不受影响），否则作废这个引擎的全部指针。没有原生指针的引擎直接跳过。"""
    if engine not in _NATIVE_POINTER_ENGINES:
        return
    from ..services import session_pointers

    if session_key is None:
        session_pointers.clear(engine=engine)
    elif session_pointers.parse(session_key) is not None:
        session_pointers.clear(session_key, engine=engine)


async def _forget_in_memory(engine: str, session_key: str) -> None:
    """丢掉某引擎为这个会话缓存的内存态（常驻客户端 / 内存历史），尽力而为。"""
    try:
        if engine == "claude" and _primary is not None:
            await _primary.forget_session(session_key)
        elif _memory_provider(engine) is not None:
            _memory_provider(engine).forget_session(session_key)
    except Exception:
        logger.warning("丢弃 %s 在会话 %s 上的内存态失败，跳过", engine, session_key, exc_info=True)


def _intended_for(session_key: str) -> str:
    """这个会话的意向引擎。进程重启后 _session_intended 是空的，这时以 settings 当前值为准
    并记下来——否则 report_recovery 查不到意向引擎，成功了也清不掉 degraded。"""
    return _session_intended.setdefault(session_key, _chat_engine_setting())


def get_provider(session_key: str, *, is_new_session: bool) -> LLMProvider:
    """返回这次调用应该用的 provider。

    新会话：按 settings.chat_engine 选一次，钉住。
    续接会话：沿用这个 session_key 当前在用的引擎；没有记录（比如进程刚重启）时用意向引擎。
    被降级钉在备用引擎上超过 _RETRY_INTENDED_AFTER_SEC 的，这一次改回意向引擎试一次
    （失败了 report_failure 会再钉回去）。降级被关掉时一律回意向引擎。
    """
    if is_new_session:
        engine = _chat_engine_setting()
        _session_intended[session_key] = engine
        _session_engine[session_key] = engine
        _pinned_at.pop(session_key, None)
        return _provider_for(engine)

    intended = _intended_for(session_key)
    engine = _session_engine.get(session_key) or intended
    if engine != intended:
        pinned = _pinned_at.get(session_key)
        if (not fallback_enabled() or pinned is None
                or time.monotonic() - pinned >= _RETRY_INTENDED_AFTER_SEC):
            logger.info("会话 %s 重新尝试意向引擎 %s（当前 %s）", session_key, intended, engine)
            _leave_engine_sync(engine, session_key)
            engine = intended
            _pinned_at.pop(session_key, None)
    _session_engine[session_key] = engine
    return _provider_for(engine)


def _leave_engine_sync(engine: str, session_key: str) -> None:
    """get_provider 是同步函数，离开备用引擎时在这里做清理：作废原生指针（同步 DB 操作），
    丢内存态——claude 的 forget 是协程，交给事件循环去跑。"""
    _invalidate_native_pointer(engine, session_key)
    if engine == "claude":
        if _primary is not None:
            try:
                asyncio.get_running_loop().create_task(_primary.forget_session(session_key))
            except RuntimeError:
                pass  # 没有运行中的事件循环（只可能是测试里直接同步调用），跳过
        return
    if _memory_provider(engine) is not None:
        _memory_provider(engine).forget_session(session_key)


def _utility_engine() -> str:
    """杂活实际走哪个引擎（只读设置，不构造会联网的东西）。"""
    pref = get_setting("utility_engine", "auto").strip()
    if pref in ENGINES:
        return pref
    if _get_fallback().configured():
        return "deepseek"
    return "claude"


def utility_engine_name() -> str:
    """Which engine the small background jobs currently go to: claude / deepseek / custom."""
    return _utility_engine()


def get_utility_provider() -> LLMProvider:
    """杂活入口（词卡/句解析/记忆抽取）：一次性调用，没有会话概念。

    settings.utility_engine：'auto'（默认）/ 'claude' / 'deepseek' / 'custom'。
    auto = 配了 DeepSeek key 就走 DeepSeek 直连（真 API 2-5s），没配走 Claude Haiku
    （经 claude CLI，冷启动慢，靠 agent_sdk 的预热池兜）。聊天人格声音不受影响。"""
    return _provider_for(_utility_engine())


async def get_vision_describer() -> tuple[str, LLMProvider] | None:
    """当前聊天引擎不支持视觉（deepseek，或没配视觉的 custom）时，用 Claude 单独跑一次
    "描述这张图"；Claude 不健康返回 None，调用方退化成"她自己说看不到图片"的文案，不报错。
    settings.vision_engine=none 可以关掉这条（不把图片发给 Claude）。"""
    if get_setting("vision_engine", "claude").strip() == "none":
        return None
    provider = _get_primary()
    try:
        ok = await provider.health()
    except Exception:
        ok = False
    return ("claude", provider) if ok else None


async def report_failure(session_key: str, error: Exception) -> LLMProvider | None:
    """当前引擎在这个 session_key 上调用失败时调用。

    按 _FALLBACK_CHAIN 的顺序试，第一个可用的接手（DeepSeek 必须 configured() 且 health() 都过）；
    都不可用返回 None，原样把错误报给用户——不悄悄换用一个更不靠谱的东西。标记 degraded、把这个
    会话钉在接手的引擎上。chat_fallback=none 时不降级。
    """
    if not fallback_enabled():
        return None
    current = _session_engine.get(session_key, _DEFAULT_ENGINE)
    chain = _FALLBACK_CHAIN.get(current, ("deepseek",))
    target, provider = None, None
    for candidate in chain:
        logger.warning("引擎 %s 在会话 %s 上失败，尝试切换到 %s：%s", current, session_key, candidate, error)
        option = _provider_for(candidate)
        try:
            if candidate == "deepseek":
                ok = option.configured() and await option.health()
            else:
                ok = await option.health()
        except Exception:
            ok = False
        if ok:
            target, provider = candidate, option
            break
    if target is None:
        logger.error("降级目标 %s 都不可用，会话 %s 没有可用引擎", "/".join(chain), session_key)
        return None
    # 离开 current：它的原生上下文从这一刻起过期；目标引擎也清一下内存态，
    # 保证它从 DB 这个唯一真相重建（它可能留着上一段降级时的旧历史）。
    _invalidate_native_pointer(current, session_key)
    await _forget_in_memory(current, session_key)
    await _forget_in_memory(target, session_key)
    _session_engine[session_key] = target
    _pinned_at[session_key] = time.monotonic()
    _write_settings(target, True)
    return provider


def report_recovery(session_key: str) -> None:
    """这次调用成功了：如果这个会话当前用的就是它的意向引擎，把 degraded 清掉。
    还钉在备用引擎上的会话，备用引擎成功不算恢复；到点后 get_provider 会自己回去重试意向引擎。
    """
    current = _session_engine.get(session_key)
    if current is not None and current == _intended_for(session_key):
        _pinned_at.pop(session_key, None)
        _write_settings(current, False)


async def drop_persona_sessions(persona_id: int, session_ids: list[int]) -> None:
    """人设被归档/删除时的尽力清理：丢掉这些 session_key 在各 provider 里的内存态
    （常驻客户端/历史）。DB 行由调用方负责，这里只管内存。"""
    keys = [f"p{persona_id}s{sid}" for sid in session_ids]
    for k in keys:
        _session_engine.pop(k, None)
        _session_intended.pop(k, None)
        _pinned_at.pop(k, None)
        _system_fingerprints.pop(k, None)

    if _primary is not None:
        for k in keys:
            try:
                await _primary.forget_session(k)
            except Exception:
                logger.warning("AgentSDKProvider.forget_session(%s) 失败，跳过", k, exc_info=True)
    for provider in (_fallback, _custom, _chatgpt):
        if provider is not None:
            for k in keys:
                provider.forget_session(k)


async def drop_all_live_sessions(old_engine: str | None = None, new_engine: str | None = None) -> None:
    """settings.chat_engine 改值时调用（routers/config.py 检测到真的变了才调），下一条消息就用新引擎。

    清空 session_key -> 引擎 的全部粘性映射，让每个已构造的 provider 断开/忘掉各自的常驻状态。
    被离开的引擎（old_engine，以及被降级钉在别的引擎上的会话各自正在用的那个）的原生指针全部
    作废，切回来时不会 resume 一份过期的对话。deepseek/custom 下次首现从 DB 补种历史；claude 没有
    可 resume 的指针时用 prompts.current_session_recap() 把当前会话尾部拼进新连接的 system prompt。
    """
    if old_engine:
        _invalidate_native_pointer(old_engine)
    for key, eng in list(_session_engine.items()):
        if eng != old_engine and eng != new_engine:
            _invalidate_native_pointer(eng, key)
    _session_engine.clear()
    _session_intended.clear()
    _pinned_at.clear()

    if _primary is not None:
        try:
            await _primary.drop_all_sessions()
        except Exception:
            logger.warning("AgentSDKProvider.drop_all_sessions() 失败，跳过", exc_info=True)
    if _fallback is not None:
        try:
            _fallback.drop_all_sessions()
        except Exception:
            logger.warning("DeepSeekProvider.drop_all_sessions() 失败，跳过", exc_info=True)
    if _custom is not None:
        try:
            _custom.drop_all_sessions()
        except Exception:
            logger.warning("CustomProvider.drop_all_sessions() 失败，跳过", exc_info=True)
    if _chatgpt is not None:
        try:
            _chatgpt.drop_all_sessions()
        except Exception:
            logger.warning("ChatGPTProvider.drop_all_sessions() 失败，跳过", exc_info=True)


# session_key -> 这个会话连接时系统提示词里那两块世界书的指纹（services/lore 的 system_lore）。
_system_fingerprints: dict[str, str] = {}


async def sync_system_lore(session_key: str, fingerprint: str) -> bool:
    """世界书进系统提示词的部分变了（书改了、挂接变了、条件翻了）：丢掉这个会话在各引擎里的内存态，
    下一次生成就用新的系统提示词重连。Claude 的会话指针不动（resume 接上历史），DeepSeek/custom
    从 DB 重新补种历史。只在 chat.py 拿着 gen_lock、还没开始生成时调用，不会打断在飞的回复。
    返回是否真的触发了重连。"""
    old = _system_fingerprints.get(session_key)
    _system_fingerprints[session_key] = fingerprint
    if old is None or old == fingerprint:
        return False
    logger.info("会话 %s 的世界书设定变了，下一条消息前重连", session_key)
    for engine in ENGINES:
        await _forget_in_memory(engine, session_key)
    return True


async def rotate_native(session_key: str, engine: str = "claude") -> None:
    """换一段新的原生会话（只在安静的时候、没有回复在飞的时候调）：作废这把 key 在这个引擎上的指针，
    丢掉内存里连着的客户端。下一次连接是全新会话，系统提示词里自带「当前会话回顾」接上。"""
    from ..services import session_pointers

    session_pointers.clear(session_key, engine=engine)
    await _forget_in_memory(engine, session_key)


async def warm_session(session_key: str, system_prompt: str, *, is_new_session: bool) -> bool:
    """预热：用这一轮会用到的引擎和系统提示词，把 session_key 的常驻状态提前准备好，不发任何模型请求。
    Claude：connect + resume（provider.warm）；按内存历史保持上下文的引擎：把历史从库里补种好。
    返回是否真的做了什么。出错由调用方兜着。"""
    provider = get_provider(session_key, is_new_session=is_new_session)
    warm = getattr(provider, "warm", None)
    if warm is not None:
        result = warm(session_key, system_prompt)
        if asyncio.iscoroutine(result):
            await result
        return True
    seed = getattr(provider, "_history_for", None)
    if seed is not None:
        seed(session_key, system_prompt)
        return True
    return False


async def refresh_claude_clients() -> None:
    """Claude 的模型/思考档位改了：只断开内存里已 connect() 的常驻客户端，不动任何
    会话指针（session_pointers）。下一条消息用新选项重连并 resume 原会话，上下文不丢。"""
    if _primary is not None:
        try:
            await _primary.drop_all_sessions()
        except Exception:
            logger.warning("刷新 Claude 常驻客户端失败，跳过", exc_info=True)


async def shutdown() -> None:
    """应用不再拥有任何引擎子进程（Claude CLI 客户端随进程退出）。"""
    return None


# ---------------------------------------------------------------------------
# 其它功能（听力、口语课出题、课程评价）按"功能"取 provider；只读设置，不联网。
# ---------------------------------------------------------------------------


def feature_engine(feature: str) -> str:
    if feature == "chat":
        return _chat_engine_setting()
    if feature == "utility":
        return _utility_engine()
    if feature == "listening":
        override = get_setting("listening_subscription").strip()
        return override if override in ENGINES else _chat_engine_setting()
    raise ValueError("Unknown model feature")


def get_feature_engine(feature: str) -> str:
    return feature_engine(feature)


def get_feature_provider(feature: str) -> LLMProvider:
    return _provider_for(feature_engine(feature))


def _chatgpt_status() -> dict:
    """只读内存里的授权状态（启动时已从 DPAPI 恢复），不读凭据、不联网、不返回邮箱。"""
    try:
        from ..services import workspace_agent_siwc_auth as auth

        meta = auth.safe_metadata()
        return {"configured": bool(meta.get("configured") and meta.get("selected_model")),
                "authorized": meta.get("authorization_state") == "authorized",
                "authorization_state": meta.get("authorization_state"),
                "model": meta.get("selected_model"), "reasoning": meta.get("reasoning_effort")}
    except Exception:
        return {"configured": False, "authorized": False, "authorization_state": "unreadable",
                "model": None, "reasoning": None}


def engines_status() -> dict:
    """GET /engines/status 的内容：本地文件存在性 + settings 读取，不做任何网络调用。"""
    from pathlib import Path
    import os

    from .agent_sdk import _resolve_chat_model, _resolve_reasoning
    from .deepseek import _custom_config, _deepseek_config

    claude_cred = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / ".credentials.json"
    claude_ok = claude_cred.is_file()
    deepseek = _deepseek_config()
    custom = _custom_config()
    conn = get_conn()
    try:
        rows = dict(conn.execute(
            "SELECT key, value FROM settings WHERE key IN ('engine', 'degraded', 'utility_engine')"
        ).fetchall())
    finally:
        conn.close()
    return {
        "claude": {
            "available": claude_ok,
            "detail": "已登录（订阅）" if claude_ok else "未登录：在终端运行 claude login",
            "model": _resolve_chat_model(),
            "reasoning": _resolve_reasoning(),
        },
        "deepseek": {"configured": deepseek is not None, "model": deepseek[2] if deepseek else None},
        "custom": {"configured": custom is not None, "model": custom[2] if custom else None},
        "chatgpt": _chatgpt_status(),
        "chat_engine": _chat_engine_setting(),
        "utility_engine": rows.get("utility_engine", "auto"),
        "utility_effective": _utility_engine(),
        "chat_fallback": "enabled" if fallback_enabled() else "none",
        "current_engine": rows.get("engine", _chat_engine_setting()),
        "degraded": rows.get("degraded", "0") == "1",
    }
