"""关键词匹配：字面、`/正则/flags`、整词、按原形（lemma），以及次要关键词的四种逻辑。

按原形匹配：扫描范围里的消息用现有分词器取每个词的原形，拼成一段"原形文本"（日语直接连写，
其他语言用空格隔开），关键词本身也取一遍原形，两边都和原文、原形文本比。助手气泡落库时已经
带了分词结果（messages.tokens_json），直接用；用户消息现分（结果按文本缓存）。分词器出错就
只比原文，不影响别的。
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import OrderedDict
from functools import lru_cache

from .model import Entry, parse_regex

logger = logging.getLogger(__name__)

_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힯]")
_token_cache: OrderedDict[tuple[str, str], tuple[str, ...]] = OrderedDict()
_TOKEN_CACHE_MAX = 1024


def fold(text: str, case_sensitive: bool) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return text if case_sensitive else text.casefold()


def _tokenizer():
    try:
        from ..tokenize import tokenize
        return tokenize
    except Exception:
        return None


def lemmas(text: str, language: str, tokens: list[dict] | None = None) -> tuple[str, ...]:
    if tokens is not None:
        return tuple(str(t.get("lemma") or t.get("surface") or "") for t in tokens if isinstance(t, dict))
    key = (language, text)
    hit = _token_cache.get(key)
    if hit is not None:
        _token_cache.move_to_end(key)
        return hit
    tokenize = _tokenizer()
    result: tuple[str, ...] = ()
    if tokenize is not None and text:
        try:
            result = tuple(str(t.get("lemma") or t.get("surface") or "") for t in tokenize(text, language))
        except Exception:
            logger.debug("分词失败，这段只按字面匹配", exc_info=True)
    _token_cache[key] = result
    if len(_token_cache) > _TOKEN_CACHE_MAX:
        _token_cache.popitem(last=False)
    return result


def _join(words: tuple[str, ...], language: str) -> str:
    words = tuple(w for w in words if w.strip())
    return "".join(words) if language.split("-")[0] in ("ja", "zh") else " ".join(words)


@lru_cache(maxsize=65536)  # 书里所有关键词的原形都放得下，第二轮起不再分词
def key_lemma(key: str, language: str) -> str:
    return _join(lemmas(key, language), language)


class Corpus:
    """一段要扫描的文本（几条消息拼起来），原文和原形文本都懒算、算过就缓存。"""

    def __init__(self, parts: list[tuple[str, list[dict] | None]], language: str):
        self.parts = [(text or "", tokens) for text, tokens in parts if text]
        self.language = language
        self.raw = "\n".join(text for text, _ in self.parts)
        self._folded: dict[bool, str] = {}
        self._lemma: dict[bool, str] = {}

    def folded(self, case_sensitive: bool) -> str:
        if case_sensitive not in self._folded:
            self._folded[case_sensitive] = fold(self.raw, case_sensitive)
        return self._folded[case_sensitive]

    def lemma_text(self, case_sensitive: bool) -> str:
        if case_sensitive not in self._lemma:
            joined = "\n".join(_join(lemmas(text, self.language, tokens), self.language) for text, tokens in self.parts)
            self._lemma[case_sensitive] = fold(joined, case_sensitive)
        return self._lemma[case_sensitive]


def _plain_hit(needle: str, haystack: str, whole_words: bool) -> bool:
    if not needle or not haystack:
        return False
    if whole_words and not _CJK.search(needle):
        return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None
    return needle in haystack


@lru_cache(maxsize=65536)
def _prepared(key: str, case_sensitive: bool):
    """每个关键词只准备一次：(正则或 None, 折叠后的字面)。写错的正则当作永远不命中。"""
    try:
        pattern = parse_regex(key)
    except ValueError:
        return False, ""
    return pattern, fold(key, case_sensitive)


@lru_cache(maxsize=65536)
def _lemma_needle(key: str, language: str) -> str:
    """关键词的原形（折叠后）；和关键词本身只差大小写时返回空串（分词器顺手改了大小写不算另一个词形）。"""
    lemma = key_lemma(key, language)
    base = fold(lemma, False)
    return base if base and base != fold(key, False) else ""


def key_hit(key: str, corpus: Corpus, entry: Entry, use_lemma: bool) -> str | None:
    """命中返回原因（'key:x' / 'lemma:x' / 'regex:/x/'），没命中返回 None。"""
    pattern, needle = _prepared(key, entry.case_sensitive)
    if pattern is False:
        return None
    if pattern is not None:
        return f"regex:{key}" if pattern.search(corpus.raw) else None
    if _plain_hit(needle, corpus.folded(entry.case_sensitive), entry.whole_words):
        return f"key:{key}"
    if use_lemma and not entry.case_sensitive:  # 区分大小写的条目只按字面（分词器会改原形的大小写）
        text = corpus.lemma_text(False)
        if _plain_hit(needle, text, entry.whole_words):
            return f"lemma:{key}"
        base = _lemma_needle(key, corpus.language)
        if base and _plain_hit(base, text, entry.whole_words):
            return f"lemma:{key}"
    return None


def warm(keys, language: str) -> None:
    """提前把关键词的原形算好（启动后、书保存后在后台跑），第一轮聊天就不用现分。"""
    for key in keys:
        if _prepared(key, False)[0] is None:
            _lemma_needle(key, language)

def first_hit(keys: list[str], corpus: Corpus, entry: Entry, use_lemma: bool) -> str | None:
    for key in keys:
        reason = key_hit(key, corpus, entry, use_lemma)
        if reason:
            return reason
    return None


def secondary_ok(entry: Entry, corpus: Corpus, use_lemma: bool) -> bool:
    if not entry.secondary_keys:
        return True
    hits = [key_hit(key, corpus, entry, use_lemma) is not None for key in entry.secondary_keys]
    if entry.logic == "and_any":
        return any(hits)
    if entry.logic == "and_all":
        return all(hits)
    if entry.logic == "not_any":
        return not any(hits)
    return not all(hits)  # not_all
