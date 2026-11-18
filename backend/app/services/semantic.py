"""语义相近度：世界书的语义触发、{{due_vocab}} 挑词共用。

用回忆模块已经在用的嵌入模型（multilingual-e5-large，query:/passage: 前缀）。全部计算放在
一个独立后台线程里，调用方只等 `timeout` 秒；模型还没加载好时只在后台触发加载、这一次直接
返回 None（不等它）；模型加载失败、超时、出错也都是 None。调用方拿到 None 就当"语义不可用"。

条目/生词的向量按 (模型, 文本) 的哈希缓存在 lore_vectors 表里，内容不变就不再重算。
测试用 `set_embedder(假函数)` 换掉模型：假函数收一组文本、返回同样多的向量；传 None = 模型不可用。
"""
from __future__ import annotations

import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np

from ..db import get_conn

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="semantic")
_DEFAULT = object()
_embedder: object = _DEFAULT
_tag = "e5-large"
_loading = threading.Lock()
_load_started = False


def set_embedder(fn: Callable[[list[str]], list] | None, tag: str = "test") -> None:
    """测试/诊断用：换掉嵌入函数。None = 当作模型不可用。"""
    global _embedder, _tag
    _embedder, _tag = fn, tag


def reset_embedder() -> None:
    global _embedder, _tag
    _embedder, _tag = _DEFAULT, "e5-large"


def _kick_load() -> None:
    global _load_started
    with _loading:
        if _load_started:
            return
        _load_started = True

    def work():
        from . import recall
        try:
            recall._load_model_sync()
        except Exception:
            logger.warning("语义模型后台加载失败", exc_info=True)

    threading.Thread(target=work, name="semantic-load", daemon=True).start()


def _default_embed(texts: list[str]):
    from . import recall
    if recall._state["failed"]:
        return None
    model = recall._state["model"]
    if model is None:
        _kick_load()
        return None
    return [np.asarray(v, dtype=np.float32) for v in model.embed(texts)]


def available() -> bool:
    """不触发加载、不等：现在能不能用。"""
    if _embedder is None:
        return False
    if _embedder is _DEFAULT:
        from . import recall
        if recall._state["failed"]:
            return False
        if recall._state["model"] is None:
            _kick_load()
            return False
    return True


def _embed(texts: list[str]):
    fn = _default_embed if _embedder is _DEFAULT else _embedder
    if fn is None:
        return None
    result = fn(texts)
    if result is None:
        return None
    return [np.asarray(v, dtype=np.float32) for v in result]


def _digest(text: str) -> str:
    return hashlib.sha256((_tag + "\x00" + text).encode("utf-8")).hexdigest()


def _passage_vectors(passages: list[str]):
    keys = [_digest("passage: " + p) for p in passages]
    cached: dict[str, np.ndarray] = {}
    conn = get_conn()
    try:
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for row in conn.execute(f"SELECT hash, dim, vec FROM lore_vectors WHERE hash IN ({marks})", chunk):
                vec = np.frombuffer(row[2], dtype=np.float32)
                if vec.size == row[1]:
                    cached[row[0]] = vec
        missing = [i for i, key in enumerate(keys) if key not in cached]
        if missing:
            vectors = _embed(["passage: " + passages[i] for i in missing])
            if vectors is None:
                return None
            for i, vec in zip(missing, vectors):
                cached[keys[i]] = vec
            try:  # 缓存写不进去（库忙）就下次再写，不等
                conn.execute("PRAGMA busy_timeout = 200")
                conn.executemany("INSERT OR REPLACE INTO lore_vectors (hash, dim, vec) VALUES (?, ?, ?)",
                                 [(keys[i], int(cached[keys[i]].size), cached[keys[i]].astype(np.float32).tobytes())
                                  for i in missing])
                conn.commit()
            except Exception:
                conn.rollback()
                logger.debug("语义向量缓存这次没写进去", exc_info=True)
    finally:
        conn.close()
    return [cached[key] for key in keys]


def _compute(query: str, passages: list[str]):
    if not available():
        return None
    vectors = _passage_vectors(passages)
    if vectors is None:
        return None
    q = _embed(["query: " + query])
    if not q:
        return None
    qv = q[0]
    qn = float(np.linalg.norm(qv)) or 1e-8
    scores = []
    for vec in vectors:
        if vec.size != qv.size:
            scores.append(0.0)
            continue
        scores.append(float(vec @ qv) / ((float(np.linalg.norm(vec)) or 1e-8) * qn))
    return scores


def similarities(query: str, passages: list[str], *, timeout: float = 0.8) -> list[float] | None:
    """query 和每段 passage 的余弦相似度；不可用/超时/出错返回 None。"""
    if not passages or not (query or "").strip():
        return None
    if not available():
        return None
    future = _executor.submit(_compute, query[:2000], [p[:1000] for p in passages])
    try:
        return future.result(timeout=timeout)
    except Exception:
        logger.info("语义相近度这次没算出来（超时或模型不可用），跳过")
        return None
