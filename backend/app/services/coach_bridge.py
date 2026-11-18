"""口语课（speaking-coach）⇄ 聊天对象。

正方向：让人设知道对方在口语课上反复出的问题、刚上完的课（system_block / lesson_note）。
反方向：她在聊天里纠正了对方 → 记进口语课账本（fix_instruction / extract_fixes / record_fixes，见文件后半）。

数据来源是口语课自己导出的 `speaking-coach/data/bridge/langpal.json`（口语课 server/src/bridge.ts 写，
债务/错题/批改报告一变就重写）。里面只有课上真实观察到的问题——口语课预置的「起始债务」没出现过
就不算对方的问题，不会进来。形状：

    {"version": 1, "updatedAt": iso, "langs": {"ja": {
        "lessonsDone": int,
        "lastLesson": {"id", "date", "unit", "comment", "errors": [{"said","correct","reason"}], "next", "homework"} | null,
        "debts": [{"id","name","name_zh","category","rule","impact","recent30d","total","lastSeen","examples":[{"said","correct"}]}]
    }}}

两处用法：
1. `system_block(language)`：拼进 system prompt 的「对方在口语课上反复出的问题」，和长期记忆一样随会话
   冻结（本地模式下 JINE 每次启动都会重启后端，所以至少每天刷新一次）。
2. `lesson_note(conn, persona)`：对方上完一节新课后，下一轮聊天在 user_text 前面拼一次「刚上完课」的
   背景提示，让她当场就能提起——不用等会话重开。每个人设各记一个已读水位（settings 表
   `coach_lesson_seen_p{id}`），生成成功后才 `mark_seen`，失败了下一轮还会再带上。

文件不存在 / 解析失败 / 设置里关了（settings.coach_bridge = "0"）→ 一律当没有口语课，什么都不注入，
绝不影响聊天主链路。路径可用环境变量 COACH_BRIDGE_FILE 覆盖，默认是 langpal 旁边的 speaking-coach。
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .provider_urls import service_url

logger = logging.getLogger(__name__)

_LANG_NAMES = {"ja": "日语", "en": "英语", "de": "德语"}
_DEFAULT_PATH = (
    Path(__file__).resolve().parents[3].parent / "speaking-coach" / "data" / "bridge" / "langpal.json"
)
_SETTING_KEY = "coach_bridge"
SERVICE_KEY = "coach_service_url"
DEFAULT_SERVICE_URL = "http://127.0.0.1:3210"
# 课上完超过这么久才第一次被读到（比如很久没开 JINE）就不当「刚上完」的新鲜事说了，只留在常驻块里
_FRESH_HOURS = 72

_cache: dict = {"path": None, "mtime": None, "data": None}


def bridge_path() -> Path:
    env = os.environ.get("COACH_BRIDGE_FILE", "").strip()
    return Path(env) if env else _DEFAULT_PATH


def _load() -> dict | None:
    path = bridge_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _cache.update(path=path, mtime=None, data=None)
        return None
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("langs"), dict):
            raise ValueError("unexpected shape")
    except Exception:
        logger.warning("口语课导出文件读取/解析失败，当作没有口语课：%s", path, exc_info=True)
        data = None
    _cache.update(path=path, mtime=mtime, data=data)
    return data


def coach_service(conn) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SERVICE_KEY,)).fetchone()
    if row is not None:
        try:
            return service_url(row["value"], origin_only=True)
        except ValueError:
            pass
    return DEFAULT_SERVICE_URL


def set_coach_service(conn, value: str) -> str:
    url = service_url(value, origin_only=True) if value else DEFAULT_SERVICE_URL
    if url == DEFAULT_SERVICE_URL:
        conn.execute("DELETE FROM settings WHERE key = ?", (SERVICE_KEY,))
    else:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (SERVICE_KEY, url))
    return url


def enabled(conn) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_SETTING_KEY,)).fetchone()
    return (row is None or row["value"] != "0") and coach_service(conn) == DEFAULT_SERVICE_URL


def _lang_data(language: str) -> dict | None:
    data = _load()
    if not data:
        return None
    entry = data["langs"].get(language)
    return entry if isinstance(entry, dict) else None


def _parse_time(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _when(value: str) -> str:
    """ISO 时间 → 「今天/昨天/11月3日」+ 时段，按本机时区。"""
    dt = _parse_time(value)
    if dt is None:
        return "最近"
    local = dt.astimezone()
    today = datetime.now().astimezone().date()
    days = (today - local.date()).days
    day = "今天" if days == 0 else "昨天" if days == 1 else f"{local.month}月{local.day}日"
    h = local.hour
    phase = "凌晨" if h < 6 else "上午" if h < 12 else "下午" if h < 18 else "晚上"
    return day + phase


def _clip(text, limit: int = 80) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def system_block(conn, language: str, *, conversation_first: bool = False) -> str:
    """常驻块：老师记下、还没改掉的问题（最多 5 条，每条带 1-2 个原话例子）。没有就返回空串。"""
    if not enabled(conn):
        return ""
    entry = _lang_data(language)
    if not entry:
        return ""
    debts = [d for d in entry.get("debts") or [] if isinstance(d, dict) and d.get("name")]
    last = entry.get("lastLesson") if isinstance(entry.get("lastLesson"), dict) else None
    if not debts and not last:
        return ""
    lang_name = _LANG_NAMES.get(language, language)
    lines = [
        "",
        f"【对方练{lang_name}时反复出的问题（背景信息：对方最近在上口语课，下面是错题账本里还没改掉的——"
        "有的是课上老师记的，有的是你以前在聊天里纠正过的——按要紧程度排）】",
    ]
    for d in debts:
        title = d["name"] + (f"（{d['name_zh']}）" if d.get("name_zh") else "")
        line = f"- {title}：{_clip(d.get('rule'), 60)}"
        examples = [x for x in d.get("examples") or [] if isinstance(x, dict) and x.get("said")]
        if examples:
            line += "。比如" + "、".join(
                f"把「{_clip(x['correct'], 30)}」说成「{_clip(x['said'], 30)}」" for x in examples
            )
        if d.get("category") == "pronunciation":
            line += "（发音问题，打字聊天里看不出来，知道就好，别硬找）"
        lines.append(line)
    if last and last.get("comment"):
        lines.append(f"最近一节课（{_when(last.get('date'))}）老师的总评：{_clip(last['comment'], 120)}")
    if conversation_first:
        lines.append("这是备查背景。平时先接话，只有对方请你帮忙改日语或用词妨碍理解时才参考。")
    else:
        lines.append(
            "聊天时留意这些：对方正好又犯了，就用你自己的方式顺手点一下，把对的说法给出来（一次最多点一个，"
            "别展开讲语法、别像老师上课）；对方用对了可以随口夸一句。不要主动把这些列出来，不要提"
            "「老师的记录」「账本」这类词，就当是对方跟你聊过自己最近在练这些。"
        )
    return "\n".join(lines)


def open_debts(conn, language: str) -> int:
    """口语课错题账本里这门语言还没改掉的条目数（给世界书/hook 的条件用）；没有口语课 = 0。"""
    if not enabled(conn):
        return 0
    entry = _lang_data(language)
    return sum(1 for d in (entry or {}).get("debts") or [] if isinstance(d, dict) and d.get("name"))


def latest_lessons(conn) -> dict[str, dict]:
    """{语言: 最近一节课}，只含有 id 的；给 hook 的 study.lesson_finished 用。"""
    if not enabled(conn):
        return {}
    data = _load() or {}
    result = {}
    for language, entry in (data.get("langs") or {}).items():
        last = entry.get("lastLesson") if isinstance(entry, dict) else None
        if isinstance(last, dict) and last.get("id"):
            result[language] = last
    return result


def lesson_is_fresh(lesson: dict) -> bool:
    done_at = _parse_time(lesson.get("date"))
    return done_at is not None and (datetime.now(timezone.utc) - done_at).total_seconds() <= _FRESH_HOURS * 3600


def _seen_key(persona_id: int) -> str:
    return f"coach_lesson_seen_p{persona_id}"


def lesson_note(conn, persona: dict) -> tuple[str, str | None]:
    """对方上完了一节这个人设还没听说过的新课 → (一次性背景提示, 课的 id)；否则 ("", None)。

    第一次读到导出文件时，已经超过 _FRESH_HOURS 的旧课直接记为已读，不翻旧账。"""
    if not enabled(conn):
        return "", None
    entry = _lang_data(persona["language"])
    last = entry.get("lastLesson") if entry else None
    if not isinstance(last, dict) or not last.get("id"):
        return "", None
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_seen_key(persona["id"]),)).fetchone()
    if row is not None and row["value"] == last["id"]:
        return "", None
    done_at = _parse_time(last.get("date"))
    if done_at is None or (datetime.now(timezone.utc) - done_at).total_seconds() > _FRESH_HOURS * 3600:
        mark_seen(conn, persona["id"], last["id"])
        return "", None

    lang_name = _LANG_NAMES.get(persona["language"], persona["language"])
    unit = f"（{_clip(last['unit'], 40)}）" if last.get("unit") else ""
    parts = [
        f"（这是系统提供的背景，不是对方现在说的话：对方{_when(last.get('date'))}刚上完一节{lang_name}口语课{unit}。"
    ]
    errors = [e for e in last.get("errors") or [] if isinstance(e, dict) and e.get("said")]
    if errors:
        parts.append("老师批改出的主要问题：")
        for e in errors:
            reason = f"（{_clip(e['reason'], 50)}）" if e.get("reason") else ""
            parts.append(f"- 说成了「{_clip(e['said'], 40)}」，应该是「{_clip(e.get('correct'), 40)}」{reason}")
    if last.get("comment"):
        parts.append(f"老师的总评：{_clip(last['comment'], 120)}")
    if last.get("homework"):
        parts.append(f"留的作业：{_clip(last['homework'], 80)}")
    parts.append(
        "就当是对方跟你说过上课的事：可以挑合适的时机自然地提一句、关心一下，也可以在接下来的聊天里留意这几个错；"
        "但别一下子全念出来，别像老师那样逐条讲评，这一轮该接对方的话就先接对方的话。）\n"
    )
    return "\n".join(parts), last["id"]


def mark_seen(conn, persona_id: int, lesson_id: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (_seen_key(persona_id), lesson_id),
    )
    conn.commit()


# ===========================================================================
# 反方向：聊天里她纠正了对方 → 记进口语课账本。
#
# 1. fix_instruction：system prompt 里要求她纠正时顺手在回复末尾打一行 ⟦fix:原文片段=>正确说法⟧。
# 2. extract_fixes：chat.py 在剥 mood 之前把这些标记行剥掉（标记永远不进气泡、不落库）。
# 3. record_fixes（后台任务，整轮完整发完才跑）：原文片段必须真的出现在对方这一批消息里（防她编），
#    再让杂活引擎对照口语课导出的 catalog 判断「是不是真错」并归到账本的某一项，最后往口语课的
#    `data/inbox/langpal.jsonl` 追加一行一条（形状见口语课 server/src/inbox.ts 的 ChatFix）。
#    口语课启动时和运行中每 15 秒入账。只追加，从不改写；口语课没装/没导出过/设置关了 → 什么都不做。
# ===========================================================================

_FIX_RE = re.compile(r"⟦fix[:：]\s*(.+?)\s*(?:=>|⇒|→)\s*(.+?)\s*⟧")
_COACH_LANGS = ("ja", "en")
_NORM_RE = re.compile(r"[\s　、。，,.!?！？「」『』\"'“”‘’…~〜]")
_CATEGORIES = ["grammar", "vocabulary", "register", "collocation", "rhythm_structure", "pronunciation"]
_IMPACTS = ["unnatural", "impolite", "unintelligible"]


def inbox_path() -> Path:
    env = os.environ.get("COACH_INBOX_FILE", "").strip()
    return Path(env) if env else bridge_path().parent.parent / "inbox" / "langpal.jsonl"


def fix_instruction(conn, language: str) -> str:
    """有口语课（导出文件在）、语言是口语课教的、设置没关 → 给她的打标记规则；否则空串。"""
    if language not in _COACH_LANGS or not enabled(conn) or not bridge_path().exists():
        return ""
    return "\n".join([
        "",
        "【纠正时顺手打个标记】",
        "如果这条回复里你纠正了对方刚才发的消息里的说法（语法、用词、语气场合、搭配都算），就在整条回复"
        "最后、心情标记那一行的上面，每处纠正单独写一行：⟦fix:原文片段=>正确说法⟧。原文片段必须从对方"
        "的消息里一字不差地照抄，只截出有问题的那一小段；正确说法写你给对方的那个版本。没有纠正就不要写，"
        "只是聊天里换个说法、开玩笑的不算。这一行只给系统识别，正文里不要提到它。",
    ])


def extract_fixes(text: str) -> tuple[str, list[tuple[str, str]]]:
    """剥掉所有 ⟦fix:...⟧ 标记（不管在不在单独一行），返回 (干净文本, [(原文片段, 正确说法)])。
    剥完变空的行整行去掉，免得气泡里留空行。"""
    fixes: list[tuple[str, str]] = []
    kept: list[str] = []
    for line in (text or "").splitlines():
        if "⟦fix" not in line:
            kept.append(line)
            continue
        for m in _FIX_RE.finditer(line):
            fixes.append((m.group(1).strip(), m.group(2).strip()))
        rest = _FIX_RE.sub("", line)
        if rest.strip():
            kept.append(rest.rstrip())
    return "\n".join(kept).rstrip(), fixes


def _norm(s: str) -> str:
    return _NORM_RE.sub("", s or "")


def match_fixes(fixes: list[tuple[str, str]], user_text: str) -> list[tuple[str, str]]:
    """只留原文片段确实出现在对方消息里、且改了东西的；去重。"""
    hay = _norm(user_text)
    out: list[tuple[str, str]] = []
    for said, correct in fixes:
        ns, nc = _norm(said), _norm(correct)
        if not ns or not nc or ns == nc or len(said) > 200 or len(correct) > 200 or ns not in hay:
            continue
        if (said, correct) not in out:
            out.append((said, correct))
    return out


_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "keep": {"type": "boolean"},
                    "reason": {"type": "string", "description": "中文一句话：原来的说法为什么不对/不自然"},
                    "category": {"type": "string", "enum": _CATEGORIES},
                    "impact": {"type": "string", "enum": _IMPACTS},
                    "debt_id": {"type": "string", "description": "清单里最贴切那一项的 id；都不贴切填空串"},
                    "new_debt_name": {"type": "string"},
                    "new_debt_name_zh": {"type": "string"},
                    "new_rule": {"type": "string"},
                },
                "required": ["index", "keep", "reason", "category", "impact", "debt_id",
                             "new_debt_name", "new_debt_name_zh", "new_rule"],
            },
        }
    },
    "required": ["items"],
}


def _classify_prompt(language: str, user_text: str, fixes: list[tuple[str, str]], catalog: list[dict]) -> str:
    lang_name = _LANG_NAMES.get(language, language)
    fix_lines = "\n".join(f"{i}. 「{s}」→「{c}」" for i, (s, c) in enumerate(fixes))
    cat_lines = "\n".join(
        f"- {d['id']}：{d.get('name', '')}（{d.get('name_zh', '')}）〔{d.get('category', '')}〕{_clip(d.get('rule'), 60)}"
        for d in catalog
    ) or "（暂时没有）"
    return (
        f"你在帮一个{lang_name}学习者整理错题。下面是他在聊天里发的消息，以及聊天对象回复时给他指出的纠正。\n\n"
        f"他的消息：\n{_clip(user_text, 600)}\n\n纠正（序号. 「他的原话」→「改成」）：\n{fix_lines}\n\n"
        f"他的错题账本里已有这些问题类别（id：名字（中文）〔类型〕规则）：\n{cat_lines}\n\n"
        "对每一条纠正输出一项（index 对应上面的序号）：\n"
        "- keep：他原来的说法确实错了或明显不自然才填 true；只是换个说法、开玩笑、原话其实没问题，填 false。\n"
        "- reason：中文一句话说清为什么。\n"
        "- category：grammar 语法 / vocabulary 用词 / register 语气场合敬语 / collocation 搭配 / "
        "rhythm_structure 表达结构 / pronunciation 发音（打字聊天里一般不会是这个）。\n"
        "- impact：unintelligible 会让人听不懂 / impolite 失礼 / unnatural 能懂但不自然。\n"
        "- debt_id：从账本清单里挑最贴切的一项填它的 id；没有贴切的填空串，并填 new_debt_name"
        f"（用{lang_name}写，像清单里的名字那样短）、new_debt_name_zh（中文名）、new_rule（中文一句规则）；"
        "挑到了的话这三项填空串。\n"
        '只输出 JSON：{"items": [...]}'
    )


def _append_inbox(lines: list[dict]) -> None:
    path = inbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(payload)  # 一次写完：口语课读到半行会跳过、下次再读


async def record_fixes(persona_id: int, persona_name: str, language: str, fixes: list[tuple[str, str]], user_text: str) -> int:
    """后台任务：把她这一轮的纠正归类后写进口语课收件箱。返回写入条数；任何问题都只记日志、返回 0。"""
    try:
        from ..db import get_conn
        from ..providers.registry import get_utility_provider

        if language not in _COACH_LANGS or not bridge_path().exists():
            return 0
        conn = get_conn()
        try:
            if not enabled(conn):
                return 0
        finally:
            conn.close()
        fixes = match_fixes(fixes, user_text)
        if not fixes:
            return 0
        entry = _lang_data(language) or {}
        catalog = [d for d in entry.get("catalog") or [] if isinstance(d, dict) and d.get("id")]
        by_id = {d["id"]: d for d in catalog}

        raw = await get_utility_provider().generate_json(
            _classify_prompt(language, user_text, fixes, catalog), _FIX_SCHEMA
        )
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        lines: list[dict] = []
        used: set[int] = set()
        for item in (raw or {}).get("items") or []:
            try:
                idx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if idx in used or not 0 <= idx < len(fixes) or not item.get("keep"):
                continue
            used.add(idx)
            said, correct = fixes[idx]
            debt = by_id.get(str(item.get("debt_id") or "").strip())
            category = item.get("category") if item.get("category") in _CATEGORIES else "grammar"
            impact = item.get("impact") if item.get("impact") in _IMPACTS else "unnatural"
            name = debt["name"] if debt else _clip(item.get("new_debt_name"), 80)
            if not name:
                continue
            lines.append({
                "v": 1,
                "id": uuid.uuid4().hex,
                "at": now,
                "lang": language,
                "persona": _clip(persona_name, 60),
                "said": said,
                "correct": correct,
                "reason": _clip(item.get("reason"), 300),
                "category": debt.get("category", category) if debt else category,
                "impact": debt.get("impact", impact) if debt else impact,
                "debt_id": debt["id"] if debt else None,
                "debt_name": name,
                "debt_name_zh": _clip(debt.get("name_zh") if debt else item.get("new_debt_name_zh"), 80),
                "rule": _clip(debt.get("rule") if debt else item.get("new_rule"), 300),
            })
        if lines:
            _append_inbox(lines)
            logger.info("coach: p%d 的 %d 条纠正已写进口语课收件箱（%s）", persona_id, len(lines),
                        "、".join(f"{x['said']}→{x['correct']}" for x in lines))
        return len(lines)
    except Exception:
        logger.warning("口语课收件箱写入失败，这一轮的纠正没记上", exc_info=True)
        return 0
