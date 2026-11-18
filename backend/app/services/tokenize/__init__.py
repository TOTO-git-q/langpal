"""Native tokenizers plus a Unicode fallback for registered languages.

对上游暴露单一函数 tokenize(text, language) -> list[dict]，按 language 路由到
ja.py / en.py / de.py 各自的实现。返回值形状见 docs/history/API.md 的 Token 契约。
"""
from __future__ import annotations

import re
import threading

from .. import languages
from . import de, en, ja

_ROUTES = {
    "ja": ja.tokenize,
    "en": en.tokenize,
    "de": de.tokenize,
}
# SudachiPy 的分词器对象不能被两个线程同时用（会抛 "Already borrowed"），spaCy 的懒加载也不防并发。
# 世界书的原形匹配在后台线程里分词，聊天在事件循环线程里分词，这把锁让它们排队。
_lock = threading.RLock()


def tokenize(text: str, language: str) -> list[dict]:
    """Variants inherit their base tokenizer. Other tags retain exact text surfaces."""
    impl = _ROUTES.get(languages.base(language))
    if impl is not None:
        with _lock:
            return impl(text)
    parts = re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*|[\s\S]", text)
    return [{"i": i, "surface": part, "lemma": part.casefold(), "reading": "", "pos": "",
             "clickable": any(char.isalpha() for char in part), "collected": False}
            for i, part in enumerate(parts)]
