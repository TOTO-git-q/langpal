"""嵌入式回忆 RAG：把每个人设名下的历史消息编码成向量存起来，聊天时用当前这句话去检索
语义相关的旧片段（哪怕对方换了说法问），拼进下一轮生成的 user_text 最前面，让人设显得
"自己记得"很久以前聊过的事，而不是只靠 system prompt 里那份人工摘要的长期记忆
（services/memoryx.py 的 memory_items，抽取门槛高、粒度粗）。

## 模型选型（跟 WP-M 任务书原计划的差异，见 docs/worklogs/WP-M.md）

契约首选 `intfloat/multilingual-e5-small`；现场核实这版 fastembed（0.8.0）的
`TextEmbedding.list_supported_models()` 里 e5 家族**只有** `intfloat/multilingual-e5-large`
（1024 维，qdrant 转的 onnx），没有 small 型号。对比了列表里其它多语候选（体积更小的
`paraphrase-multilingual-MiniLM-L12-v2`/`-mpnet-base-v2`），e5-large 是能拿到的质量最强的
多语模型，改用它——本项目单用户本机场景，2.24GB 体积 + 稍慢的推理换检索准确度划算。
`_MODEL_DIM` 如实写 1024，不是原计划的 384。

e5 系约定：查询文本前缀 `"query: "`，被索引文本前缀 `"passage: "`——这是训练时的输入格式，
不是可选的装饰，不加会明显掉点。

## 阈值实测（cosine，intfloat/multilingual-e5-large）——两轮标定，第二轮才是最终值

第一轮：拿干净的、刻意写的平行句子（比如 "うちの猫の名前はタマ" vs "うちのペットの名前
覚えてる？"）测，命中 0.80~0.85 / 不命中 0.73~0.795，看起来 0.80 是个合理阈值。

**但接进 8792 实例、用真实的随手打字的聊天片段（带「〜だよね」「笑」这种语气词/口癖）
实测后发现第一轮的阈值不够**：真实聊天文本里，同一种"随意聊天的语域"本身就会把所有句子的
cosine 都往上顶——不管话题相不相关。实测例子（persona 7 测试人设，见验证记录）：问一句跟
历史完全无关的"最近見た映画で面白かったのある？"，对"うちの猫の名前は「ズッキーニ将軍」"
这条完全无关的旧消息也能算出 0.817 的 cosine；而真正问"猫の名前なんだっけ"这种改写复述，
对真正相关的旧消息能到 0.84~0.89。也就是说，**真实数据下命中和不命中的分界线比干净句子
测出来的更靠右**：不命中的上限实测到了 0.817，命中的下限（同一话题里稍弱的邻句）在 0.84
附近，中间有一段干净的空隙。`RECALL_THRESHOLD` 改拍在这段空隙里的 `0.83`，比第一轮凭
干净句子拍的 0.80 更保守——宁可漏召一些边界命中，也不要在真实使用中把无关旧话题错当成
"相关背景"塞给模型（复现"聊着聊着聊到不相关的话题里"这种诡异感）。

## 模型缓存 / Windows 已知噪音

fastembed 默认缓存路径（本机实测）：
`%TEMP%/fastembed_cache/`（含 `models--qdrant--multilingual-e5-large-onnx/` 标准 HF 缓存布局
+ `fast-multilingual-e5-large/` fastembed 自己的展开目录，推理实际读后者）——这是系统 TEMP
目录，不是持久盘符，部署到别的机器 / 系统清理 TEMP 后需要重新触发一次下载（首次调用会自动
补，只是要保证能连外网/hf-mirror）。
本机没开 Windows Developer Mode，`huggingface_hub` 建 symlink 会失败（`WinError 1314`），
fastembed 捕获后自动回退到它自己的镜像源——每次进程里第一次 `TextEmbedding(...)` 实例化都会
打一条 "Could not download...Falling back to other sources" 的 ERROR 级日志，即使模型早就在
本地缓存、实际没有真的重新下载。纯噪音，不影响正确性，本次没有动环境变量/开发者模式去消它。

## 加载失败 = 整个回忆功能静默关闭（本进程生命周期内不重试）

首次真正用到模型（第一次 embed_new_messages/recall 调用，或 backfill 遇到第一批非贴纸消息）
才会尝试 `TextEmbedding(model_name=...)`；失败一次就把 `_state["failed"]` 钉死，这个后端
进程剩下的生命周期里所有回忆相关函数直接 no-op，不重试、不抛错——不希望聊天主链路因为一个
可选增强功能的环境问题被拖慢或报错。下次进程重启会重新尝试。
"""

from __future__ import annotations

import asyncio
import logging
import threading

import numpy as np

from ..db import get_conn
from .prompts import _time_phase

logger = logging.getLogger(__name__)

_MODEL_NAME = "intfloat/multilingual-e5-large"
_MODEL_DIM = 1024

# 实测标定，见模块 docstring——两轮标定后的最终值：真实聊天片段的不命中上限约 0.817，
# 命中下限约 0.84，0.83 卡在这段空隙里，偏保守（宁可漏召，不要瞎召不相关话题）。
RECALL_THRESHOLD = 0.83

# 命中后的邻域扩展：同会话内按 id 相邻的前后各 N 条（含命中自身）拼成片段。
_NEIGHBOR_RADIUS = 2
# 一轮 recall() 最多返回几个（合并去重后的）片段。
_DEFAULT_K = 3
# 所有返回片段拼起来的总字符预算（粗切，不做智能摘要）。
_TOTAL_CHAR_BUDGET = 600

# backfill：每批处理的消息数 + 批间让路的 sleep（见 backfill_all docstring）。
_BACKFILL_BATCH = 64
_BACKFILL_SLEEP_SEC = 0.2

# ---------------------------------------------------------------------------
# 模型单例：懒加载 + 失败即永久关闭（本进程生命周期内）。
# ---------------------------------------------------------------------------

_state: dict = {"model": None, "failed": False}
_load_lock = threading.Lock()


def _load_model_sync():
    if _state["failed"]:
        return None
    if _state["model"] is not None:
        return _state["model"]
    with _load_lock:
        # 双检：可能在等锁期间被另一个线程加载完/标记失败了。
        if _state["failed"]:
            return None
        if _state["model"] is not None:
            return _state["model"]
        try:
            from fastembed import TextEmbedding

            model = TextEmbedding(model_name=_MODEL_NAME)
            _state["model"] = model
            logger.info("recall: 嵌入模型 %s 加载成功", _MODEL_NAME)
            return model
        except Exception:
            logger.warning(
                "recall: 嵌入模型加载失败，回忆功能本进程生命周期内整体关闭", exc_info=True
            )
            _state["failed"] = True
            return None


async def _embed_batch(texts: list[str]) -> list[np.ndarray] | None:
    """CPU 密集（ONNX 推理），扔进线程池跑，不占事件循环。模型不可用时返回 None。"""

    def _work():
        model = _load_model_sync()
        if model is None:
            return None
        return [np.asarray(v, dtype=np.float32) for v in model.embed(texts)]

    return await asyncio.to_thread(_work)


def is_disabled() -> bool:
    """给调用方/诊断用：模型是否已经确认加载失败（不代表还没试过）。"""
    return _state["failed"]


def _is_eligible(content: str | None) -> str | None:
    """返回可嵌入的正文文本；贴纸气泡（"[sticker:" 开头）/ 空文本返回 None（= 该跳过）。"""
    text = (content or "").strip()
    if not text or text.startswith(("[sticker:", "[system:")):
        return None
    return text


# ---------------------------------------------------------------------------
# 写入：新消息嵌入 + 全库补算
# ---------------------------------------------------------------------------


async def _embed_and_store(rows) -> None:
    """rows: sqlite3.Row 列表，至少含 id/content。贴纸/空文本写哨兵行（model='skip', dim=0）
    使其在 LEFT JOIN 意义上"已处理"，backfill 才能真正终止；真消息但模型不可用时不写任何行，
    留给下次进程重启重试。"""
    eligible: list[tuple[int, str]] = []
    skip_ids: list[int] = []
    for r in rows:
        text = _is_eligible(r["content"])
        if text is None:
            skip_ids.append(r["id"])
        else:
            eligible.append((r["id"], text))

    conn = get_conn()
    try:
        for mid in skip_ids:
            conn.execute(
                "INSERT OR IGNORE INTO message_embeddings (message_id, model, dim, vector) "
                "VALUES (?, 'skip', 0, ?)",
                (mid, b""),
            )
        conn.commit()

        if not eligible:
            return

        texts = [f"passage: {t}" for _, t in eligible]
        vecs = await _embed_batch(texts)
        if vecs is None:
            return  # 模型不可用：这批真消息留空，下次重试（skip 行已经提交，不受影响）

        for (mid, _), vec in zip(eligible, vecs):
            conn.execute(
                "INSERT OR IGNORE INTO message_embeddings (message_id, model, dim, vector) "
                "VALUES (?, ?, ?, ?)",
                (mid, _MODEL_NAME, _MODEL_DIM, vec.astype(np.float32).tobytes()),
            )
        conn.commit()
    finally:
        conn.close()


async def embed_new_messages(session_id: int) -> None:
    """挂进 chat.py 的 _run_background_hooks：把该会话还没嵌入的消息批量补上。
    调用方已经把 try/except+warning 包好了（照 maybe_extract 的方式），这里不用自己兜底。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT m.id, m.content FROM messages m "
            "LEFT JOIN message_embeddings me ON me.message_id = m.id "
            "WHERE m.session_id = ? AND me.message_id IS NULL "
            "ORDER BY m.id ASC",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return
    await _embed_and_store(rows)


async def backfill_all() -> None:
    """后端启动时的后台补算：分批把全库还没嵌入的消息补上。幂等——LEFT JOIN 天然只挑缺的，
    重复跑/中途重启都不会重算已有的。批间 sleep 只是让路给正常聊天请求，不是限速安全措施
    （本项目单用户本机规模，万级消息批量跑一遍也就几分钟量级）。

    模型这个进程里一旦确认加载失败（is_disabled()==True），立刻停止整个 backfill（不然会
    卡在同一批"真消息但编不出向量"上反复空转）——剩余消息留到下次进程重启重试。
    """
    while True:
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT m.id, m.content FROM messages m "
                "LEFT JOIN message_embeddings me ON me.message_id = m.id "
                "WHERE me.message_id IS NULL ORDER BY m.id ASC LIMIT ?",
                (_BACKFILL_BATCH,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return
        await _embed_and_store(rows)
        if _state["failed"]:
            logger.info("recall backfill: 嵌入模型不可用，停止补算，剩余消息留到下次进程启动重试")
            return
        await asyncio.sleep(_BACKFILL_SLEEP_SEC)


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


def _format_when(created_at: str | None) -> str:
    ts = created_at or ""
    date_part, _, time_part = ts.partition(" ")
    phase = _time_phase(time_part)
    return f"{date_part} {phase}".strip() or "之前"


def _session_order(conn, session_id: int) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT m.id, m.role, m.content, m.created_at, coalesce(m.persona_id, s.persona_id) AS speaker, "
            "p.name AS speaker_name FROM messages m JOIN sessions s ON s.id = m.session_id "
            "LEFT JOIN personas p ON p.id = coalesce(m.persona_id, s.persona_id) "
            "WHERE m.session_id = ? ORDER BY m.id ASC",
            (session_id,),
        ).fetchall()
    ]


async def recall(
    persona_id: int,
    query_text: str,
    exclude_message_ids,
    k: int = _DEFAULT_K,
    *,
    main_session_id: int | None = None,
) -> list[dict]:
    """返回该人设名下语义相关的旧对话片段：`[{"text", "when", "message_ids"}, ...]`。

    - 只搜这个 persona 名下所有会话的消息（跨会话）。
    - `exclude_message_ids`：调用方传当前会话最近窗口，避免"回忆"到刚刚才说过的话。
    - 命中做邻域扩展（同会话前后各 `_NEIGHBOR_RADIUS` 条，含命中自身），重叠/相邻的邻域
      合并成一个片段，避免同一段旧对话被重复引用两次。
    - 总预算 `_TOTAL_CHAR_BUDGET` 字符，超预算截断（保最靠前的、按时间顺序）。
    - 模型不可用 / 没有任何候选 / 全部低于阈值 → 返回 `[]`（不是异常）。

    `message_ids` 是额外加的字段（不影响任务书里 `{text, when}` 的核心形状），供调用方
    （chat.py）只记 id 不记全文地打日志，方便观察召回质量又不把聊天内容写进日志。
    """
    if is_disabled():
        return []

    exclude = set(exclude_message_ids or [])

    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT me.message_id AS id, me.vector AS vector, me.dim AS dim,
                   m.session_id AS session_id, m.created_at AS created_at
            FROM message_embeddings me
            JOIN messages m ON m.id = me.message_id
            JOIN sessions s ON s.id = m.session_id
            WHERE me.dim > 0 AND (
                (s.persona_id = ? AND s.id != coalesce(?, -1))
                OR (m.session_id = ? AND (m.role = 'user' OR m.persona_id = ?
                    OR (m.persona_id IS NULL AND s.persona_id = ?))))
            """,
            (persona_id, main_session_id, main_session_id, persona_id, persona_id),
        ).fetchall()
    finally:
        conn.close()

    candidates = [dict(r) for r in rows if r["id"] not in exclude]
    if not candidates:
        return []

    qvecs = await _embed_batch([f"query: {query_text}"])
    if not qvecs:
        return []
    qvec = qvecs[0]
    qnorm = float(np.linalg.norm(qvec)) or 1e-8

    ids = [c["id"] for c in candidates]
    mat = np.vstack([np.frombuffer(c["vector"], dtype=np.float32) for c in candidates])
    norms = np.linalg.norm(mat, axis=1)
    norms[norms == 0] = 1e-8
    scores = (mat @ qvec) / (norms * qnorm)

    meta = {c["id"]: c for c in candidates}
    scored = [
        (mid, float(score))
        for mid, score in zip(ids, scores)
        if score >= RECALL_THRESHOLD
    ]
    if not scored:
        return []
    scored.sort(key=lambda t: -t[1])

    conn = get_conn()
    try:
        session_orders: dict[int, list[dict]] = {}

        def order_for(session_id: int) -> list[dict]:
            if session_id not in session_orders:
                session_orders[session_id] = _session_order(conn, session_id)
            return session_orders[session_id]

        # 每个命中 -> (session_id, start_idx, end_idx, score) 邻域窗口（索引是该会话消息
        # 按 id 升序排列后的下标，不是消息 id 本身——避免"同会话相邻两条消息 id 未必连续"
        # 的隐患，比如两个人设并发使用共享自增 id 时）。
        spans_by_session: dict[int, list[list]] = {}
        for mid, score in scored:
            session_id = meta[mid]["session_id"]
            order = order_for(session_id)
            idx = next((i for i, row in enumerate(order) if row["id"] == mid), None)
            if idx is None:
                continue
            start = max(0, idx - _NEIGHBOR_RADIUS)
            end = min(len(order) - 1, idx + _NEIGHBOR_RADIUS)
            spans_by_session.setdefault(session_id, []).append([start, end, score])

        merged: list[tuple[int, int, int, float]] = []  # (session_id, start, end, score)
        for session_id, spans in spans_by_session.items():
            spans.sort(key=lambda s: s[0])
            cur = None
            for s in spans:
                if cur is None:
                    cur = s
                elif s[0] <= cur[1] + 1:
                    cur[1] = max(cur[1], s[1])
                    cur[2] = max(cur[2], s[2])
                else:
                    merged.append((session_id, cur[0], cur[1], cur[2]))
                    cur = s
            if cur is not None:
                merged.append((session_id, cur[0], cur[1], cur[2]))

        if not merged:
            return []

        merged.sort(key=lambda g: -g[3])
        top = merged[: max(k, 1)]
        # 呈现顺序按时间先后（跨会话也按 created_at，不是按分数）。
        top.sort(key=lambda g: order_for(g[0])[g[1]]["created_at"] or "")

        results: list[dict] = []
        total_chars = 0
        for session_id, start, end, score in top:
            order = order_for(session_id)
            span_rows = order[start : end + 1]
            lines = []
            mids = []
            for row in span_rows:
                text = _is_eligible(row["content"])
                if text is None:
                    continue
                # 主聊天：别的人设说的标她的名字，不当成「你」
                if row["role"] != "assistant":
                    label = "对方"
                elif row.get("speaker") in (None, persona_id):
                    label = "你"
                else:
                    label = row.get("speaker_name") or "别人"
                lines.append(f"{label}：{text}")
                mids.append(row["id"])
            if not lines:
                continue
            body = "\n".join(lines)
            remaining = _TOTAL_CHAR_BUDGET - total_chars
            if remaining <= 0:
                break
            if len(body) > remaining:
                body = body[:remaining].rstrip() + "…"
            total_chars += len(body)
            when = _format_when(span_rows[-1]["created_at"])
            results.append({"text": body, "when": when, "message_ids": mids})
            if total_chars >= _TOTAL_CHAR_BUDGET:
                break

        return results
    finally:
        conn.close()
