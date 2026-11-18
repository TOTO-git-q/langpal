"""记忆抽取服务：从会话消息里抽取关于用户的持久事实/偏好/约定，写入 memory_items。

触发策略：session 每新增满 10 条消息（相对上次抽取的水位）触发一次。
水位存在 settings 表里（key = memx_watermark_session_{id}），跨进程重启不丢。

对外只有一个入口：maybe_extract(session_id, persona_id=None)。主聊天里按这一轮说话的人设各抽各的。由上游（WP-A，聊天落库之后）调用；
这里不主动轮询、不自己起后台循环。
"""
from ..db import get_conn
from ..providers.registry import get_utility_provider

MEMORY_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "本轮抽取到的持久信息条目，没有新信息就返回空数组",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["fact", "preference", "event", "promise"],
                    },
                    "content": {
                        "type": "string",
                        "description": "中文，单条独立简短陈述，一条一个信息点",
                    },
                },
                "required": ["category", "content"],
            },
        },
    },
    "required": ["items"],
}

_BATCH_SIZE = 10
_VALID_CATEGORIES = {"fact", "preference", "event", "promise"}


def _watermark_key(session_id: int) -> str:
    return f"memx_watermark_session_{session_id}"


def _get_watermark(conn, session_id: int) -> int:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (_watermark_key(session_id),)
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def _set_watermark(conn, session_id: int, value: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (_watermark_key(session_id), str(value)),
    )


def _build_prompt(transcript: str) -> str:
    return f"""你在读一段用户和 ta 的语伴角色之间的聊天记录（角色是 AI 人设，「用户」是真人）。

聊天记录（按时间顺序，「用户」= 真人说话，「角色」= AI 人设说话）：
{transcript}

请只抽取关于「用户」（真人）本人的、值得长期记住的持久信息，用于角色以后聊天时保持连贯、记得对方。
分类：
- fact：客观事实（身份、经历、背景等）
- preference：偏好、喜好、习惯
- event：发生过或计划中的具体事件
- promise：双方之间的约定、承诺、待兑现的事项

要求：
- 只抽取「持久」信息（长期成立或值得后续追问的），不要抽取寒暄、临时情绪、这句话本身的字面转述。
- 每条独立成句，简短（一句话），一条只讲一个信息点。
- 用中文书写。
- 这段记录里如果没有新的、值得记的持久信息，就返回空数组 —— 宁缺毋滥，不要为了凑数硬编。
- 不要重复记录已经明显是常识或无信息量的内容。

严格按 schema 输出 JSON，不要输出 schema 之外的字段，不要输出任何解释性前后缀文字。"""


def _persona_rows(conn, session_id: int, persona_id: int, owner: int) -> list:
    """主聊天：对这个人设来说的聊天记录 = 对方说的 + 她自己说的（别的人设说的不算）。"""
    return conn.execute(
        """SELECT role, content FROM messages WHERE session_id = ? AND (role = 'user' OR persona_id = ?
           OR (persona_id IS NULL AND ? = ?)) AND content NOT LIKE '[system:%' ORDER BY id ASC""",
        (session_id, persona_id, owner, persona_id)).fetchall()


async def maybe_extract(session_id: int, persona_id: int | None = None) -> None:
    """persona_id：主聊天里这一轮说话的人设（记忆写到她名下、只看她参与的消息、水位各记各的）；
    不给就是这段会话的主人（旧的一人一会话做法）。"""
    conn = get_conn()
    try:
        session_row = conn.execute(
            "SELECT persona_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session_row is None:
            return
        owner = session_row["persona_id"]
        if persona_id is None:
            persona_id = owner
        rows_all = _persona_rows(conn, session_id, persona_id, owner)
        key = f"{_watermark_key(session_id)}_p{persona_id}"
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is not None:
            watermark = int(row["value"])
        elif persona_id == owner:
            # 从旧水位（按会话全部消息计数）换算过来，不把已经抽过的再抽一遍
            old = _get_watermark(conn, session_id)
            watermark = conn.execute(
                """SELECT count(*) FROM (SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?)
                   WHERE (role = 'user' OR persona_id = ? OR (persona_id IS NULL AND ? = ?))
                   AND content NOT LIKE '[system:%'""",
                (session_id, old, persona_id, owner, persona_id)).fetchone()[0]
        else:
            watermark = 0
        total = len(rows_all)

        if total - watermark < _BATCH_SIZE:
            return  # 未满一批，不触发

        rows = rows_all[watermark:]
        transcript = "\n".join(
            f"{'用户' if r['role'] == 'user' else '角色'}: {r['content']}" for r in rows
        )

        def advance():
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(total)))

        if not transcript.strip():
            advance()
            conn.commit()
            return

        try:
            provider = get_utility_provider()
            raw = await provider.generate_json(_build_prompt(transcript), MEMORY_EXTRACT_SCHEMA)
        except Exception:
            # 引擎不可用/调用失败：不推进水位，下次调用时这批消息会重新尝试抽取
            return

        items = raw.get("items") or []
        for item in items:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            category = item.get("category")
            if category not in _VALID_CATEGORIES:
                category = "fact"
            conn.execute(
                "INSERT INTO memory_items (persona_id, category, content, source_session_id) "
                "VALUES (?, ?, ?, ?)",
                (persona_id, category, content, session_id),
            )

        advance()
        conn.commit()
    finally:
        conn.close()