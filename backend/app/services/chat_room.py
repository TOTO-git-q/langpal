"""主聊天（docs/MAIN-CHAT.md）：一条时间线、主人设 + 副人设、语言拨片、趣味模式。

这里只管"谁、说哪门语言、看到哪了、怎么存怎么读"，真正的生成和投递在 services/chat.py。

- 设置 `chat_main`（MainSettings）和主聊天会话 id `chat_main_session` 都在 settings 表。
- 这一轮谁主讲（点名 / @名字 / 关键词副人设 / 主人设）、说哪门语言（趣味模式随机且不连抽同一门 /
  主人设用拨片 / 副人设用母语）、谁可能插话。
- 每个人设"看到哪了"（chat_seen）和每轮开头的补课块。
- 口吻样本（profile.voice_samples）的校验和每轮确定性抽样。
- 旧对话（主聊天以外的会话）只读列表；主聊天消息列表。
- 启动迁移：会话指针搬家、钉住主聊天会话、糖糖的日语口吻样本种子。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from . import clock, languages, session_pointers

MAIN_KEY = "chat_main"
SESSION_KEY = "chat_main_session"
VOICE_DIR = Path(__file__).resolve().parents[1] / "data" / "voices"
AME_SEED_DIR = Path(__file__).resolve().parents[1] / "data" / "seed" / "ame"
STOCK_FIRST = '{"relation":"朋友","tone":"轻松","keigo":"平辈","interests":["读书","散步","美食"],"free_text":"大学时代认识的好友，说话直接但温柔，喜欢分享日常。"}'
VOICE_MAX_PER_LANGUAGE = 600
VOICE_PICK = 12
CATCH_UP_MESSAGES = 12
CATCH_UP_CHARS = 1500

_HOUR = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
_KEYWORD = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
_STICKER = re.compile(r"^\[sticker:([^\]\s]+)\]$")
_SYSTEM = re.compile(r"^\[system:([a-z_]+)\]$")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["always", "time", "keyword"] = "always"
    start: _HOUR | None = None
    end: _HOUR | None = None
    keywords: list[_KEYWORD] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def check(self):
        if self.type == "time" and (not self.start or not self.end or self.start == self.end):
            raise ValueError("出现时段要填不同的开始和结束时间")
        if self.type == "keyword" and not self.keywords:
            raise ValueError("关键词出现的副人设至少要写一个词")
        return self


class Guest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: int = Field(gt=0)
    enabled: bool = True
    rule: Rule = Field(default_factory=Rule)
    chime: int = Field(25, ge=0, le=100)


class MainSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_id: int | None = Field(None, gt=0)
    language: languages.LanguageTag | None = None
    fun: bool = False
    fun_languages: list[languages.LanguageTag] = Field(default_factory=list, max_length=30)
    primary_chime: int = Field(25, ge=0, le=100)
    guests: list[Guest] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique(self):
        ids = [g.persona_id for g in self.guests]
        if self.primary_id in ids or len(set(ids)) != len(ids):
            raise ValueError("副人设不能重复，也不能和主人设是同一个")
        if len(set(self.fun_languages)) != len(self.fun_languages):
            raise ValueError("趣味模式的语言不能重复")
        return self


# ---------------------------------------------------------------- 人设和设置

def personas(conn) -> dict[int, dict]:
    return {row["id"]: dict(row) for row in conn.execute(
        "SELECT * FROM personas WHERE archived_at IS NULL ORDER BY id")}


def _stored(conn) -> MainSettings:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (MAIN_KEY,)).fetchone()
    if row:
        try:
            return MainSettings.model_validate_json(row[0])
        except ValueError:
            pass
    return MainSettings()


def _most_recent(conn, people: dict[int, dict]) -> int | None:
    """没选过主人设时：最近聊过的那个人设（以前按联系人聊时最常用的那位），都没聊过就取第一个。"""
    row = conn.execute("""SELECT s.persona_id FROM messages m JOIN sessions s ON s.id = m.session_id
                          JOIN personas p ON p.id = s.persona_id WHERE p.archived_at IS NULL
                          ORDER BY m.id DESC LIMIT 1""").fetchone()
    if row and row[0] in people:
        return row[0]
    return next(iter(people), None)


def settings(conn) -> MainSettings:
    """实际生效的设置：主人设不在了就取第一个人设；语言、语言池只留已添加的；副人设只留还在的。"""
    stored, people = _stored(conn), personas(conn)
    catalog = languages.registered(conn)
    primary = stored.primary_id if stored.primary_id in people else _most_recent(conn, people)
    language = stored.language if stored.language in catalog else (
        people[primary]["language"] if primary in people else next(iter(catalog)))
    pool = [tag for tag in stored.fun_languages if tag in catalog] or list(catalog)
    guests = [g for g in stored.guests if g.persona_id in people and g.persona_id != primary]
    return MainSettings(primary_id=primary, language=language, fun=stored.fun, fun_languages=pool,
                        primary_chime=stored.primary_chime, guests=guests)


def save(conn, patch: dict) -> MainSettings:
    current = settings(conn).model_dump()
    merged = MainSettings.model_validate({**current, **patch})
    people, catalog = personas(conn), languages.registered(conn)
    if merged.primary_id not in people or any(g.persona_id not in people for g in merged.guests):
        raise ValueError("请选还在用的人设卡")
    if merged.language not in catalog or any(tag not in catalog for tag in merged.fun_languages):
        raise ValueError("请先添加这门语言")
    if not merged.fun_languages:
        raise ValueError("趣味模式至少要有一门语言")
    if merged.primary_id != current["primary_id"]:
        main_session_id(conn)  # 主人设换人不换时间线：先把现在这段钉住
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (MAIN_KEY, merged.model_dump_json()))
    return settings(conn)


def main_session_id(conn, *, create: bool = False) -> int | None:
    """主聊天的会话 id：钉住的那段；没钉过就把主人设最近的一段钉成主聊天；还没有就（create 时）新建。"""
    row = conn.execute("""SELECT s.id FROM settings k JOIN sessions s ON s.id = CAST(k.value AS INTEGER)
                          WHERE k.key = ?""", (SESSION_KEY,)).fetchone()
    if row:
        return row[0]
    config = settings(conn)
    row = conn.execute("SELECT max(id) FROM sessions WHERE persona_id = ?", (config.primary_id,)).fetchone()
    sid = row[0] if row else None
    if sid is None and create and config.primary_id is not None:
        sid = conn.execute("INSERT INTO sessions (persona_id, language) VALUES (?, ?)",
                           (config.primary_id, config.language)).lastrowid
    if sid is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (SESSION_KEY, str(sid)))
        # 主人设是推断出来的：钉住时间线的同时把她记下来，之后不会因为谁最近说过话而变
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                     (MAIN_KEY, MainSettings(primary_id=config.primary_id).model_dump_json()))
    return sid


def new_main(conn) -> int:
    config = settings(conn)
    if config.primary_id is None:
        raise ValueError("请先创建一张人设卡")
    sid = conn.execute("INSERT INTO sessions (persona_id, language) VALUES (?, ?)",
                       (config.primary_id, config.language)).lastrowid
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (SESSION_KEY, str(sid)))
    return sid


def delete_archive(conn, sid: int) -> bool:
    if sid == main_session_id(conn) or not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone():
        return False
    messages = "SELECT id FROM messages WHERE session_id = ?"
    conn.execute(f"DELETE FROM message_embeddings WHERE message_id IN ({messages})", (sid,))
    for table in ("vocab_entries", "pattern_entries"):
        conn.execute(f"UPDATE {table} SET source_message_id = NULL WHERE source_message_id IN ({messages})", (sid,))
    conn.execute("UPDATE memory_items SET source_session_id = NULL WHERE source_session_id = ?", (sid,))
    for table in ("session_pointers", "lore_state", "chat_turns", "chat_seen"):
        conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
    conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    return True


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold()


def keyword_hit(guest: Guest, text: str) -> bool:
    corpus = _fold(text)
    for keyword in map(_fold, guest.rule.keywords):
        if keyword.isascii() and keyword[:1].isalnum() and keyword[-1:].isalnum():
            if re.search(r"(?<![a-z0-9_])" + re.escape(keyword) + r"(?![a-z0-9_])", corpus):
                return True
        elif keyword and keyword in corpus:
            return True
    return False


def is_present(guest: Guest, text: str, hhmm: str | None = None) -> bool:
    if not guest.enabled:
        return False
    rule = guest.rule
    if rule.type == "always":
        return True
    if rule.type == "time":
        now = hhmm or clock.now().strftime("%H:%M")
        return rule.start <= now < rule.end if rule.start < rule.end else now >= rule.start or now < rule.end
    return keyword_hit(guest, text)


def last_user_text(conn, sid: int | None) -> str:
    row = conn.execute("SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
                       (sid,)).fetchone()
    return row[0] if row else ""


def present_guest_ids(conn, config: MainSettings, text: str | None = None, sid: int | None = None) -> list[int]:
    if text is None:
        text = last_user_text(conn, sid)
    return [g.persona_id for g in config.guests if is_present(g, text)]


def named(config: MainSettings, people: dict[int, dict], text: str) -> int | None:
    """消息以 `@名字` 开头 → 这个人设的 id（只认主人设和启用的副人设）。"""
    stripped = (text or "").lstrip()
    if not stripped.startswith(("@", "＠")):
        return None
    head = _fold(stripped[1:])
    candidates = [config.primary_id] + [g.persona_id for g in config.guests if g.enabled]
    best = None
    for pid in candidates:
        name = _fold(people.get(pid, {}).get("name", ""))
        if name and head.startswith(name) and (best is None or len(name) > len(_fold(people[best]["name"]))):
            best = pid
    return best


def choose_lead(conn, config: MainSettings, text: str, to: int | None) -> int:
    """主讲：点名（to 或 @名字）→ 这条消息触发了关键词规则的副人设 → 主人设。"""
    people = personas(conn)
    allowed = {config.primary_id, *(g.persona_id for g in config.guests if g.enabled)}
    if to is not None:
        if to not in allowed:
            raise ValueError("点名的人不在主聊天里")
        return to
    at = named(config, people, text)
    if at is not None:
        return at
    for guest in config.guests:
        if guest.enabled and guest.rule.type == "keyword" and keyword_hit(guest, text):
            return guest.persona_id
    return config.primary_id


def _last_language(conn, sid: int | None) -> str | None:
    row = conn.execute("SELECT language FROM messages WHERE session_id = ? AND role = 'assistant' "
                       "AND language IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    return row[0] if row else None


def fun_language(config: MainSettings, previous: str | None, rng=None) -> str:
    pool = list(config.fun_languages)
    if len(pool) > 1 and previous in pool:
        pool.remove(previous)
    return (rng or clock.rng).choice(pool)


def choose_language(conn, config: MainSettings, persona: dict, sid: int | None, *, previous: str | None = None) -> str:
    """语言：趣味模式 → 随机（不连着两轮同一门）；主人设 → 拨片；副人设 → 她自己的母语。"""
    if config.fun:
        return fun_language(config, previous if previous is not None else _last_language(conn, sid))
    if persona["id"] == config.primary_id:
        return config.language
    return persona["language"]


def chime_candidates(config: MainSettings, lead_id: int, present: list[int]) -> list[tuple[int, int]]:
    """(人设 id, 插话概率)：在场的、不是主讲的人。主人设不主讲时也算在场，概率是 primary_chime。"""
    out = [(g.persona_id, g.chime) for g in config.guests if g.persona_id in present and g.persona_id != lead_id]
    if lead_id != config.primary_id:
        out.insert(0, (config.primary_id, config.primary_chime))
    return out


def roll_chime(config: MainSettings, lead_id: int, present: list[int], rng=None) -> int | None:
    """最多一个人插话：候选随机排个序，各掷一次，第一个掷中的插话。"""
    rng = rng or clock.rng
    candidates = chime_candidates(config, lead_id, present)
    rng.shuffle(candidates)
    for pid, chance in candidates:
        if chance > 0 and rng.random() * 100 < chance:
            return pid
    return None


# ---------------------------------------------------------------- 看到哪了 / 补课

def _owner(conn, sid: int) -> int | None:
    row = conn.execute("SELECT persona_id FROM sessions WHERE id = ?", (sid,)).fetchone()
    return row[0] if row else None


def has_spoken(conn, sid: int, persona_id: int) -> bool:
    owner = _owner(conn, sid)
    return conn.execute("""SELECT 1 FROM messages WHERE session_id = ? AND role = 'assistant'
                           AND (persona_id = ? OR (persona_id IS NULL AND ? = ?)) LIMIT 1""",
                        (sid, persona_id, owner, persona_id)).fetchone() is not None


def seen_up_to(conn, sid: int, persona_id: int) -> int:
    row = conn.execute("SELECT last_message_id FROM chat_seen WHERE session_id = ? AND persona_id = ?",
                       (sid, persona_id)).fetchone()
    if row:
        return row[0]
    # 没记过：她最后一次开口之前的都算看过（主人设接着自己的旧对话聊，不重补）；从没开过口 = 0
    owner = _owner(conn, sid)
    row = conn.execute("""SELECT max(id) FROM messages WHERE session_id = ? AND role = 'assistant'
                          AND (persona_id = ? OR (persona_id IS NULL AND ? = ?))""",
                       (sid, persona_id, owner, persona_id)).fetchone()
    return row[0] or 0


def mark_seen(conn, sid: int, persona_id: int, message_id: int | None = None) -> None:
    if message_id is None:
        message_id = conn.execute("SELECT coalesce(max(id), 0) FROM messages WHERE session_id = ?", (sid,)).fetchone()[0]
    conn.execute("""INSERT INTO chat_seen (session_id, persona_id, last_message_id) VALUES (?, ?, ?)
                    ON CONFLICT(session_id, persona_id) DO UPDATE SET
                    last_message_id = max(last_message_id, excluded.last_message_id)""", (sid, persona_id, message_id))


def sticker_meanings() -> dict[str, str]:
    from . import prompts
    return {r["id"]: r.get("desc", "") for r in prompts._load_sticker_manifest()}


def describe(content: str, image_path: str | None = None, meanings: dict | None = None) -> str:
    """一条消息给模型看的样子：贴图换成意思，图片标出来。"""
    content = (content or "").strip()
    match = _STICKER.match(content)
    if match:
        meaning = (meanings if meanings is not None else sticker_meanings()).get(match.group(1))
        return f"（发了一张贴图：{meaning}）" if meaning else "（发了一张贴图）"
    if image_path:
        return ("（发了一张图片）" + (" " + content if content else "")).strip()
    return content


def catch_up(conn, sid: int, persona_id: int, *, before_id: int | None = None) -> str:
    """她上次开口之后、这一批之前，主聊天里别人说的话（只补没见过的，最多 12 条 / 1500 字）。"""
    after = seen_up_to(conn, sid, persona_id)
    owner = _owner(conn, sid)
    rows = conn.execute(
        """SELECT m.role, m.content, m.image_path, coalesce(m.persona_id, CASE WHEN m.role = 'assistant' THEN ? END) AS pid,
                  p.name FROM messages m LEFT JOIN personas p ON p.id = coalesce(m.persona_id, CASE WHEN m.role = 'assistant' THEN ? END)
           WHERE m.session_id = ? AND m.id > ? AND (? IS NULL OR m.id < ?) ORDER BY m.id DESC LIMIT 60""",
        (owner, owner, sid, after, before_id, before_id)).fetchall()
    meanings = sticker_meanings()
    lines, used = [], 0
    for row in rows:
        if row["role"] == "assistant" and row["pid"] == persona_id:
            continue
        if _SYSTEM.match((row["content"] or "").strip()):
            continue
        text = describe(row["content"], row["image_path"], meanings)
        if not text:
            continue
        who = "对方" if row["role"] == "user" else (row["name"] or "别人")
        line = f"{who}：{text}"
        if len(lines) >= CATCH_UP_MESSAGES or used + len(line) > CATCH_UP_CHARS:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    lines.reverse()
    return ("【你上次开口之后，主聊天里的新消息（背景：别人说过的话，你都知道；不用逐条回应，"
            "也不要替别人说话）】\n" + "\n".join(lines) + "\n")


# ---------------------------------------------------------------- 口吻样本

def validate_voice_samples(value) -> dict[str, list[str]]:
    if not isinstance(value, dict) or len(value) > 30:
        raise ValueError("口吻样本要按语言分组，最多 30 门语言")
    result = {}
    for tag, lines in value.items():
        tag = languages.canonical(str(tag))
        if not isinstance(lines, list):
            raise ValueError("口吻样本每门语言是一组句子")
        kept = []
        for line in lines:
            line = " ".join(str(line).split()) if isinstance(line, str) else ""
            if not line or line in kept:
                continue
            if not 2 <= len(line) <= 60:
                raise ValueError(f"口吻样本每句 2–60 字：「{line[:20]}…」")
            kept.append(line)
        if len(kept) > VOICE_MAX_PER_LANGUAGE:
            raise ValueError(f"口吻样本每门语言最多 {VOICE_MAX_PER_LANGUAGE} 句")
        if kept:
            result[tag] = kept
    return result


def voice_samples(persona: dict) -> dict[str, list[str]]:
    try:
        profile = json.loads(persona.get("profile_json") or "{}")
        value = profile.get("voice_samples") or {}
        return {k: [s for s in v if isinstance(s, str)] for k, v in value.items() if isinstance(v, list)}
    except (TypeError, ValueError, AttributeError):
        return {}


def pick_voice(samples: list[str], sid: int, persona_id: int, turn: int, count: int = VOICE_PICK) -> list[str]:
    """按（会话, 人设, 轮次）确定性地抽：同一轮重试同一批，下一轮换一批。"""
    def rank(line):
        return hashlib.sha256(json.dumps([sid, persona_id, turn, line], ensure_ascii=False).encode()).hexdigest()
    return sorted(samples, key=rank)[:count]


def voice_block(persona: dict, language: str, sid: int, turn: int) -> str:
    samples = voice_samples(persona).get(language)
    if not samples:
        return ""
    picked = pick_voice(samples, sid, persona["id"], turn)
    return "【口吻参考：只学说法，不把里面的事当成发生过】\n" + "\n".join(f"- {s}" for s in picked) + "\n"


# ---------------------------------------------------------------- 读：主聊天消息、旧对话

def message_view(row, names: dict[int, str], owner: int | None) -> dict:
    content = row["content"] or ""
    sticker = _STICKER.match(content.strip())
    system = _SYSTEM.match(content.strip())
    pid = row["persona_id"] if row["persona_id"] is not None else (owner if row["role"] == "assistant" else None)
    tokens = None
    if row["tokens_json"]:
        try:
            tokens = json.loads(row["tokens_json"])
        except (TypeError, ValueError):
            tokens = None
    item = {"id": row["id"], "role": "system" if system else row["role"], "persona_id": pid,
            "persona_name": names.get(pid) if pid else None, "language": row["language"], "content": content,
            "tokens": tokens, "image_url": f"/uploads/{row['image_path']}" if row["image_path"] else None,
            "sticker": sticker.group(1) if sticker else None, "created_at": row["created_at"],
            "read": bool(row["read_at"]) if row["role"] == "user" else None}
    if system:
        item["kind"] = system.group(1)
        item["content"] = f"{names.get(pid, '')} 来了" if system.group(1) == "enter" else ""
    return item


def _names(conn) -> dict[int, str]:
    return {row[0]: row[1] for row in conn.execute("SELECT id, name FROM personas")}


def messages(conn, sid: int, *, before: int | None = None, limit: int = 50) -> list[dict]:
    rows = conn.execute("""SELECT * FROM messages WHERE session_id = ? AND (? IS NULL OR id < ?)
                           ORDER BY id DESC LIMIT ?""", (sid, before, before, limit)).fetchall()
    names, owner = _names(conn), _owner(conn, sid)
    return [message_view(row, names, owner) for row in reversed(rows)]


def archives(conn) -> list[dict]:
    main = main_session_id(conn)
    rows = conn.execute("""SELECT s.id, s.persona_id, p.name, s.language, s.started_at, count(m.id) AS n,
                                  max(m.created_at) AS last_at
                           FROM sessions s LEFT JOIN messages m ON m.session_id = s.id LEFT JOIN personas p ON p.id = s.persona_id
                           WHERE s.id != coalesce(?, -1) GROUP BY s.id ORDER BY last_at DESC, s.id DESC""",
                        (main,)).fetchall()
    return [{"session_id": r["id"], "persona_id": r["persona_id"], "persona_name": r["name"], "language": r["language"],
             "started_at": r["started_at"], "last_at": r["last_at"], "count": r["n"]} for r in rows]


# ---------------------------------------------------------------- 给 providers 用的历史补种（接缝）

def seed_history(session_key: str, max_messages: int = 40, max_chars: int = 6000) -> list[dict]:
    """常驻会话第一次出现时从库里补种的上文，按人设区分：她自己说的是 assistant，对方和别的人设说的
    是 user（别人的话前面带名字）。掐掉尾部连续的 user 消息（那是这一轮马上要发的）。
    providers 目前按会话 id 补种全部消息（主聊天里会把别人的话当成她说的）——引擎那边改成调用这里。"""
    from contextlib import closing
    from .. import db
    parts = session_pointers.parse(session_key)
    if parts is None:
        return []
    persona_id, sid = parts
    with closing(db.get_conn()) as conn:
        owner = _owner(conn, sid)
        names = _names(conn)
        rows = conn.execute("SELECT role, content, persona_id, image_path FROM messages WHERE session_id = ? "
                            "ORDER BY id ASC", (sid,)).fetchall()
    out = []
    for row in rows:
        content = (row["content"] or "").strip()
        if not content or _STICKER.match(content) or _SYSTEM.match(content):
            continue
        speaker = row["persona_id"] if row["persona_id"] is not None else (owner if row["role"] == "assistant" else None)
        if row["role"] == "assistant" and speaker == persona_id:
            out.append({"role": "assistant", "content": content})
        elif row["role"] == "assistant":
            out.append({"role": "user", "content": f"（{names.get(speaker, '别人')}说）{content}"})
        else:
            out.append({"role": "user", "content": content})
    while out and out[-1]["role"] == "user":
        out.pop()
    kept, total = [], 0
    for item in reversed(out):
        if len(kept) >= max_messages or total + len(item["content"]) > max_chars:
            break
        kept.append(item)
        total += len(item["content"])
    kept.reverse()
    return kept


# ---------------------------------------------------------------- 迁移

def _once(conn, name: str) -> bool:
    """这个迁移跑过没有；没跑过就记上并返回 True。"""
    return conn.execute("INSERT OR IGNORE INTO chat_migrations (name) VALUES (?)", (name,)).rowcount == 1


def seed_voices(conn) -> int:
    """名字以「糖糖」开头的日语人设、人设卡里还没有 voice_samples.ja → 写入种子，每个人设只写一次。"""
    path = VOICE_DIR / "ame.ja.json"
    if not path.is_file():
        return 0
    samples = None
    count = 0
    for row in conn.execute("SELECT id, name, language, profile_json FROM personas").fetchall():
        if row["language"] != "ja" or not (row["name"] or "").startswith("糖糖"):
            continue
        try:
            profile = json.loads(row["profile_json"] or "{}")
        except ValueError:
            continue
        voices = profile.get("voice_samples") if isinstance(profile.get("voice_samples"), dict) else {}
        # 记号先记上：用户之后把样本删光了也不会再被写回来
        if not _once(conn, f"voice_seed:ame.ja:p{row['id']}") or voices.get("ja"):
            continue
        if samples is None:
            samples = json.loads(path.read_text(encoding="utf-8"))["samples"][:VOICE_MAX_PER_LANGUAGE]
        profile["voice_samples"] = {**voices, "ja": samples}
        conn.execute("UPDATE personas SET profile_json = ? WHERE id = ?",
                     (json.dumps(profile, ensure_ascii=False), row["id"]))
        count += 1
    return count


def migrate_debounce(conn) -> None:
    """攒批等待的默认值从 3 秒改成 1.2 秒：库里存的正好是旧默认值就改写；用户自己设过别的值不动。只跑一次。"""
    if not _once(conn, "batch_debounce_default_1.2"):
        return
    row = conn.execute("SELECT value FROM settings WHERE key = 'batch_debounce_sec'").fetchone()
    if row is not None and str(row[0]).strip() in ("3", "3.0", "3.00"):
        conn.execute("UPDATE settings SET value = '1.2' WHERE key = 'batch_debounce_sec'")


def seed_ame(conn, avatar_dir: Path | None = None) -> bool:
    """全新的库：预置的日语人设 1 换成糖糖（人设卡、她的世界书、头像）。只看一次；
    库里已经有别的人设、人设 1 被改过、或者已经聊过天，都不动。"""
    if not _once(conn, "default_persona_ame"):
        return False
    path = AME_SEED_DIR / "persona.json"
    if not path.is_file():
        return False
    rows = conn.execute("SELECT id, name, profile_json FROM personas ORDER BY id").fetchall()
    if [row["id"] for row in rows] != [1, 2, 3] or rows[0]["name"] != "雪菜" or rows[0]["profile_json"] != STOCK_FIRST:
        return False
    if conn.execute("SELECT 1 FROM messages LIMIT 1").fetchone():
        return False
    seed = json.loads(path.read_text(encoding="utf-8"))
    book = seed["world_book"]
    book_id = conn.execute("INSERT INTO world_books (name, book_json, scope, enabled) VALUES (?, ?, ?, ?)",
                           (book["name"], json.dumps(book["book"], ensure_ascii=False), book["scope"], book["enabled"])).lastrowid
    profile = {**seed["profile"], "world_book_ids": [book_id]}
    avatar = None
    picture = AME_SEED_DIR / "avatar.png"
    if avatar_dir is None:
        from ..db import AVATAR_DIR as avatar_dir
    if picture.is_file():
        avatar_dir.mkdir(parents=True, exist_ok=True)
        avatar = "1_ame.png"
        (avatar_dir / avatar).write_bytes(picture.read_bytes())
    conn.execute("UPDATE personas SET name = ?, language = ?, profile_json = ?, avatar = ? WHERE id = 1",
                 (seed["name"], seed["language"], json.dumps(profile, ensure_ascii=False), avatar))
    return True


def migrate(conn) -> None:
    seed_ame(conn)
    session_pointers.migrate(conn)
    migrate_debounce(conn)
    if personas(conn):
        main_session_id(conn)
    seed_voices(conn)
