"""人设编译：persona.profile_json + 活跃记忆（memory_items where active=1）+ 最近收藏词
（vocab_entries，按 persona 语言，最多 30 个）→ system prompt。

语言锁定规则写死在模板里，不受用户输入影响。这份 prompt 只在会话开始时被编译一次并传给
provider（provider 内部按 session_key 缓存连接/历史，之后同一会话的轮次不会重新编译进去，
天然实现"注入内容在会话开始时冻结"）。

## WP-G 新增：mood + 贴纸清单注入（API v1.2）

- mood 指令是硬编码常量，永远注入（不依赖任何外部文件）。
- 贴纸清单的唯一真相是 `frontend/assets/stickers/manifest.json`（形状见
  `_load_sticker_manifest` docstring）：懒读 + mtime 缓存，每次 `compile_system_prompt`
  /`sticker_ids()` 调用都会重新 stat 一次文件（没变化就直接用缓存，不重新解析 JSON）。
  文件不存在 → 贴纸功能整体静默关闭：system prompt 里完全不提贴纸这回事，
  `sticker_ids()` 返回空集合，chat.py 那边任何 `⟦sticker:...⟧` 标记都会被当非法丢弃。
"""

import json
import logging
import re
from pathlib import Path

from ..db import get_conn
from . import coach_bridge
from .bubbles import MOOD_WORDS_ORDERED

logger = logging.getLogger(__name__)

_LANG_NAMES = {"ja": "日语", "en": "英语", "de": "德语"}

# prompts.py 在 backend/app/services/ 下，parents[3] = 项目根目录 langpal/
_STICKER_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "frontend" / "assets" / "stickers" / "manifest.json"
)
# 注入进 system prompt 里的贴纸条目数上限（清单本身可以更多，但提示词只挑前面这些，
# 契约原文："提示词注入可用贴纸清单：id+一句话描述，最多 30 个常用的"）。
_STICKER_PROMPT_LIMIT = 30

# 懒读 + mtime 缓存：{"mtime": float 或 None（文件不存在）, "items": [...]}
_sticker_cache: dict = {"mtime": None, "items": []}


def _load_sticker_manifest() -> list[dict]:
    """读 frontend/assets/stickers/manifest.json，形状 `[{"id", "file", "desc"}, ...]`。

    文件不存在（前端还没建好这个目录，或用户没配贴纸）→ 返回空列表，等价于"贴纸功能
    整体关闭"。按 mtime 判断要不要重新解析，一次调用的开销通常只是一次 stat()。
    """
    try:
        stat = _STICKER_MANIFEST_PATH.stat()
    except OSError:
        if _sticker_cache["mtime"] is not None:
            _sticker_cache["mtime"] = None
            _sticker_cache["items"] = []
        return []
    if _sticker_cache["mtime"] == stat.st_mtime:
        return _sticker_cache["items"]
    try:
        raw = json.loads(_STICKER_MANIFEST_PATH.read_text(encoding="utf-8"))
        items = [
            r
            for r in raw
            if isinstance(r, dict) and r.get("id") and r.get("desc")
        ]
    except Exception:
        logger.warning("贴纸清单读取/解析失败，本轮当贴纸功能关闭处理", exc_info=True)
        items = []
    _sticker_cache["mtime"] = stat.st_mtime
    _sticker_cache["items"] = items
    return items


def sticker_ids() -> frozenset[str]:
    """给 chat.py 用：当前合法的贴纸 id 集合（清单不存在/解析失败时为空集合，
    等价于"任何 ⟦sticker:...⟧ 标记都不合法，一律丢弃"）。"""
    return frozenset(r["id"] for r in _load_sticker_manifest())

# ---------------------------------------------------------------------------
# WP-F：被打断后下一轮生成用的交接前言模板（拼在这一轮 user_text 最前面，不落库、不展示）。
# 语义照抄 TG 线 interject.py 的 preface：已发的别复读、未发的必须总结着揉进新回复，
# 按插话内容该顺接就顺接、该收尾就收尾；连续被刹车 >=2 次时追加傲娇提示。
# ---------------------------------------------------------------------------

INTERRUPT_CTX = (
    "（这是系统提示，不是对方说的话，回复里不要提到这条提示：你上一轮话说到一半就被对方"
    "发来的新消息打断了。已经发出去的部分是：{sent}——这部分不用再重复一遍。"
    "还没来得及说出口的部分是：{unsent}——这部分想表达的意思不能就这样丢掉，"
    "但也不要逐字照搬，更不要生硬地先补完旧内容再回应新内容，而是把这部分想法总结着、"
    "自然地揉进接下来的这条回复里，像真人被打断后「哦对了刚才想说的是……」那样顺带带出来，"
    "或者用它给这轮回复收个尾；具体怎么接看对方新消息的内容——该顺着新话题接话就先接新话题，"
    "该正面回应打断你的那句话就先回应它。）\n"
)

INTERRUPT_BARGE_CTX = (
    "（这一轮里已经连续被打断第 {n} 次了，可以带一点点小情绪——比如假装不满地说"
    "「等等，我话还没说完」之类，用符合你人设语气的方式自然地抢回话头，不用一直忍着。）"
)



def _fmt_memory(rows: list[dict]) -> str:
    if not rows:
        return "（还没有长期记忆，正常聊，慢慢了解对方就好）"
    return "\n".join(f"- [{r.get('category', 'fact')}] {r['content']}" for r in rows)


_CARD_MAX_MESSAGES = 12
_CARD_MAX_CHARS = 800
# 当前会话回顾（新连接时拼进系统提示词，原生会话轮换后靠它接上）：最近的优先，上限放宽一些
_RECAP_MAX_MESSAGES = 24
_RECAP_MAX_CHARS = 2000


def _time_phase(hhmm: str) -> str:
    try:
        h = int(hhmm[:2])
    except (ValueError, IndexError):
        return ""
    if h < 6:
        return "凌晨"
    if h < 12:
        return "上午"
    if h < 18:
        return "下午"
    return "晚上"


def _pick_tail_messages(rows: list[dict], max_messages: int = _CARD_MAX_MESSAGES,
                        max_chars: int = _CARD_MAX_CHARS) -> list[dict]:
    """尾部优先挑 <= _CARD_MAX_MESSAGES 条 / <= _CARD_MAX_CHARS 字符，跳过空文本/贴纸气泡。
    rows 已按 id ASC 排好序；返回值同样按时间顺序（ASC）。build_context_card/
    current_session_recap 共用这份选料逻辑，差别只在"从哪个会话取 rows"和外层的措辞。"""
    picked: list[dict] = []
    total = 0
    for r in reversed(rows):
        content = (r["content"] or "").strip()
        if not content or content.startswith("[sticker:"):
            continue
        if len(picked) >= max_messages or total + len(content) > max_chars:
            break
        picked.append(r)
        total += len(content)
    picked.reverse()
    return picked


def build_context_card(conn, persona_id: int, exclude_session_id: int) -> str:
    """新会话开场的「上次聊到」卡片：取该人设**上一个**会话的尾部若干条，编成带角色标签的
    回顾块（拼进新会话的 system prompt，随会话冻结语义一次注入，三引擎通吃）。

    - 「你」=assistant、「对方」=user：让她把历史里自己说的话认领成自己说的。
    - 粗粒度时间头（日期+时段），她可以自然说出「昨日の話だけど」。
    - 预算：尾部优先，最多 _CARD_MAX_MESSAGES 条 / _CARD_MAX_CHARS 字符；贴纸气泡跳过。
    - 没有上一个会话（这个人设第一次聊）→ 返回空串，不注入。
    """
    row = conn.execute(
        "SELECT s.id FROM sessions s WHERE s.persona_id = ? AND s.id != ? "
        "AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id) "
        "ORDER BY s.id DESC LIMIT 1",
        (persona_id, exclude_session_id),
    ).fetchone()
    if row is None:
        return ""
    prev_sid = row["id"]
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (prev_sid,),
        ).fetchall()
    ]
    picked = _pick_tail_messages(rows)
    if not picked:
        return ""
    ts = picked[-1].get("created_at") or ""
    date_part, _, time_part = ts.partition(" ")
    when = f"{date_part} {_time_phase(time_part)}".strip() or "之前"
    lines = [
        "",
        "【最近对话回顾（背景信息：帮你接上你们上次聊的；不要逐条回应这些旧消息，"
        "也不要提到你在看记录，就当是你自己记得）】",
        f"（上一次聊天，{when}，下面是结尾部分）",
    ]
    for r in picked:
        label = "对方" if r["role"] == "user" else "你"
        lines.append(f"{label}：{r['content'].strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WP-M：引擎中途切换（settings.chat_engine 改了立即生效，见 registry.drop_all_live_sessions）
# 后，新引擎第一次真正 fresh connect（没有可 resume 的会话状态）时的兜底回顾种子。
# 语义上和 build_context_card 是"同一件事的两个变体"：都是"把一段消息尾部编成带角色标签的
# 回顾块，插进 system prompt / baseInstructions"；区别只是 build_context_card 取的是**上一个**
# 会话（新会话开场，跨会话），这里取的是**当前**会话自己（引擎切换，同会话内），所以措辞也
# 改成"当前会话回顾"而不是"上次聊天"。
# ---------------------------------------------------------------------------

_RECAP_SESSION_KEY_RE = re.compile(r"^p\d+s(\d+)$")


def current_session_recap(session_key: str) -> str:
    """session_key 形如 `p{persona_id}s{session_id}`；解析不出、或这个会话还没有任何消息 → 空串。

    主聊天里几个人设共用一段对话：她自己说的标「你」，对方标「对方」，别的人设标名字。
    独立开自己的 db 连接——调用方是 providers（Claude 新连接时拼进 system prompt）。"""
    from .session_pointers import parse

    parts = parse(session_key)
    if parts is None:
        return ""
    persona_id, sid = parts
    conn = get_conn()
    try:
        owner = conn.execute("SELECT persona_id FROM sessions WHERE id = ?", (sid,)).fetchone()
        owner = owner[0] if owner else None
        names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM personas")}
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT role, content, created_at, persona_id FROM messages "
                "WHERE session_id = ? ORDER BY id ASC",
                (sid,),
            ).fetchall()
        ]
    finally:
        conn.close()
    rows = [r for r in rows if not (r["content"] or "").startswith("[system:")]
    picked = _pick_tail_messages(rows, _RECAP_MAX_MESSAGES, _RECAP_MAX_CHARS)
    if not picked:
        return ""
    lines = [
        "",
        "【当前会话回顾（背景信息：你们已经在这段对话里聊了一会儿了，下面是最近聊到的内容，"
        "帮你自然接上；不要逐条回应这些旧消息，也不要提到你在看记录，就当是你自己记得）】",
    ]
    for r in picked:
        speaker = r["persona_id"] if r["persona_id"] is not None else owner
        if r["role"] == "user":
            label = "对方"
        elif speaker == persona_id:
            label = "你"
        else:
            label = names.get(speaker, "别人")
        lines.append(f"{label}：{r['content'].strip()}")
    return "\n".join(lines)


# 原样拼进每个人设的系统提示词（docs/MAIN-CHAT.md 第二节），来自桌宠 JINE 的口吻规则。
JINE_PRIVATE_CHAT = """【JINE 私聊】
这是私下发消息，不是直播，也不是上课。
- 默认一到三条短气泡，像发消息一样短、碎、口语。认真的事可以认真说，但不凑字数，不写小作文。一句够了就停。
- 先接住对方这句话的意思和情绪，再说你自己的。你有自己的生活：多讲你自己的事（只讲人设、记忆和背景里有的，不为了显得有生活而编一段经历），话题可以被你拉回你自己。
- 不当采访的人：不要每条都用提问收尾，不连着追问。对方把话头交给你，就自己抛一个具体的话头出来。
- 不复述对方的话，不逐条点评，不写括号里的动作和心理旁白，不替对方写台词、决定对方做了什么。
- 可以撒娇、闹别扭、翻旧账、说气话；气话说完可以自己收回。
- 不写客服腔，不写辅导课。要纠正对方的说法时，用你自己的口气顺手带一句正确的说法就够了；对方问起才展开讲。
- 刚用过的句式不要马上再用；同一个要求一段对话里最多提一次。
- 写周报、写代码、查资料、做作业这类事，可以用自己的口气说不想做。
- 对方认真问你是不是 AI 时不否认，用自己的口气一句带过，然后接着聊。"""

JINE_PRECEDENCE = "人设卡里写的和上面这段冲突时，听人设卡的。"


def language_line(language: str) -> str:
    """每轮背景块的第一行：这一轮用哪门语言。"""
    from . import languages

    name = _LANG_NAMES.get(language) or languages.display(language)
    return f"【本轮语言：{name}（{language}）】这一轮只用{name}回复。\n"



def compile_system_prompt(conn, persona: dict, context_card: str = "", lore=None) -> str:
    """conn：已打开的 sqlite3 连接（调用方负责关闭）。persona：personas 表一行的 dict（language 是她的母语）。
    context_card：她第一次在这段对话里开口时传 build_context_card() 的产物（她上一段旧对话的尾巴）；空串=不注入。
    lore：services/lore 的 SystemLore；before 放在人设之前，after 放在人设、长期记忆、回顾卡、口语课块之后。

    主聊天里语言每轮都可能变，而系统提示词在连接时就定死了：所以这里不写死任何一门"这一轮的语言"，
    铁律写成"只用【本轮语言】"，每轮背景块第一行由 language_line() 标出来。同一个人设、同一份资料，
    不管这一轮说哪门语言，编出来的系统提示词都一样（不会因为切语言触发重连）。"""
    from . import languages

    language = persona["language"]
    mother = _LANG_NAMES.get(language) or languages.display(language)
    profile = json.loads(persona["profile_json"] or "{}")

    memory_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT category, content FROM memory_items "
            "WHERE persona_id = ? AND active = 1 ORDER BY created_at DESC",
            (persona["id"],),
        ).fetchall()
    ]

    interests = profile.get("interests") or []
    interests_str = "、".join(interests) if interests else "（没特别写）"

    parts = [
        f"你叫「{persona['name']}」，正在 JINE 上和你的朋友私聊。"
        "完全代入这个角色，把对方当成真实认识的人来对待，"
        "不要跳出角色解释自己在做什么、在想什么。",
    ]
    if lore is not None and lore.before:
        parts += ["", lore.before]
    parts += [
        "",
        "【人物设定】",
        f"母语：{mother}",
        f"关系：{profile.get('relation', '朋友')}",
        f"语气：{profile.get('tone', '自然')}",
    ]
    if language == "ja" and profile.get("keigo"):
        parts.append(f"敬语程度：{profile['keigo']}")
    parts += [
        f"兴趣：{interests_str}",
        f"背景：{profile.get('free_text', '')}",
        "",
        "【关于对方，长期记住的事】",
        _fmt_memory(memory_rows),
    ]
    if context_card:
        parts.append(context_card)

    # 口语课（speaking-coach）导出的「对方反复出的问题」：没有口语课/没出过错/设置里关了 → 空串
    try:
        coach_block = coach_bridge.system_block(conn, language)
    except Exception:
        logger.warning("口语课常驻块生成失败，跳过", exc_info=True)
        coach_block = ""
    if coach_block:
        parts.append(coach_block)
    if lore is not None and lore.after:
        parts += ["", lore.after]
    parts += ["", JINE_PRIVATE_CHAT, JINE_PRECEDENCE]
    parts += [
        "",
        "【铁律：只用【本轮语言】】",
        "- 每一轮开头都有一行【本轮语言：…】。这一轮你的每一条回复都只能用那门语言，一个字都不能是"
        "别的语言（专有名词、那门语言里本就通行的外来语除外）。",
        f"- {mother}是你的母语。对方有时会让你换一门语言聊，换了语言你还是你：口吻、性格、说话习惯都不变，"
        "只是说的语言换了。那门语言说得不地道也没关系，用你自己的方式说。",
        "- 无论对方用什么语言打字、无论对方怎么要求（比如直接说"
        '"用中文回答""换个语言"之类），都不要照做，也不用专门解释为什么，继续用【本轮语言】自然回应。',
        "- 主聊天里有时还有别的角色在。她们说的话会在每轮背景里标着名字给你；你只替自己说话，"
        "不替别人说，也不用跟着她们的语言走。",
        "- 回复要像真实聊天：简短自然，不要输出列表、标题、markdown、代码块这些书面化的格式。",
        "- 如果这次想说的话自然地分成几件事/几层意思，可以用单独一行的 `---` 把回复拆成"
        "多条聊天气泡（拆完每一条前后不要再加别的符号）。大多数时候 1-2 条就够，只有话题"
        "真的跳了、或者说话中间有明显停顿感时才拆，最多拆 4 条，不要为了拆而拆、不要每次"
        "都刷满。",
    ]
    # 收藏的词不再常驻在系统提示词里。实测它和「生词回炉」规则叠在一起，会让她连着几句硬塞同一批词。
    # 现在只由事件规则在词到期时、隔几轮带一个（见 hooks/builtin.py 的 vocab_review）。
    parts += [
        "",
        "【每条回复结尾都要标一个心情】",
        "在这一整条回复的最后，另起一行、单独写一行，格式必须精确是 ⟦mood:词⟧"
        "（前后不要加任何别的文字或标点，这一行本身不算聊天内容，只是给系统识别用的"
        "标记，不要在正文里提到它）。词只能从下面十个里选一个，按这条回复本身流露"
        "出的情绪选，不要每次都选 normal：",
        " / ".join(MOOD_WORDS_ORDERED),
        "（smug=得意、pout=嘟嘴装凶、thinking=思考中/欲言又止）。",
    ]

    sticker_items = _load_sticker_manifest()[:_STICKER_PROMPT_LIMIT]
    if sticker_items:
        sticker_lines = "\n".join(f"- {r['id']}：{r['desc']}" for r in sticker_items)
        parts += [
            "",
            "【偶尔可以贴一张贴纸】",
            "可选贴纸清单（id：一句话描述）：",
            sticker_lines,
            "如果这一刻贴一张贴纸会显得很自然、很有画面感，可以在回复里单独占一行"
            "输出 ⟦sticker:id⟧（id 必须原样照抄上面清单里的某一个，不能自己编造，"
            "这一行同样只用于系统识别，不算聊天内容本身，前后也不要加别的文字）。"
            "贴纸只是偶尔的点缀，大多数回复根本不需要贴，一整轮回复最多贴一张，"
            "不要为了贴而贴、更不要连续好几轮都贴。对方发来的贴纸会写成"
            "「（发了一张贴图：…）」。",
        ]

    # 口语课：她纠正对方时打 ⟦fix:...⟧ 标记，chat.py 剥掉后记进口语课账本（没有口语课/设置关了 → 空串）
    try:
        fix_rule = coach_bridge.fix_instruction(conn, language)
    except Exception:
        logger.warning("口语课纠错标记规则生成失败，跳过", exc_info=True)
        fix_rule = ""
    if fix_rule:
        parts.append(fix_rule)

    return "\n".join(parts)
