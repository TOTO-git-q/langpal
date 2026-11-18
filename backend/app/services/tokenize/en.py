"""英语分词：spaCy（en_core_web_sm）。

返回 Token 形状字段见 docs/history/API.md。lemma 用 token.lemma_；pos 用 token.pos_ 的可读形式；
reading 恒为空串；标点 clickable=False；collected 恒为 False，交由上游覆写。
space_after 记录该 token 后是否有空格（spaCy whitespace_），供前端按顺序拼接时还原间距。
"""
from __future__ import annotations

import spacy

_MODEL_NAME = "en_core_web_sm"

# spaCy 通用词性标注(UPOS) -> 可读英文形式
_POS_READABLE = {
    "ADJ": "adjective",
    "ADP": "adposition",
    "ADV": "adverb",
    "AUX": "auxiliary",
    "CCONJ": "coordinating conjunction",
    "DET": "determiner",
    "INTJ": "interjection",
    "NOUN": "noun",
    "NUM": "numeral",
    "PART": "particle",
    "PRON": "pronoun",
    "PROPN": "proper noun",
    "PUNCT": "punctuation",
    "SCONJ": "subordinating conjunction",
    "SYM": "symbol",
    "VERB": "verb",
    "X": "other",
    "SPACE": "space",
}

# 不可点击的 UPOS：标点 / 空白
_NON_CLICKABLE_UPOS = {"PUNCT", "SPACE"}

# 模块级缓存：进程内只加载一次
_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load(_MODEL_NAME)
    return _nlp


def tokenize(text: str) -> list[dict]:
    """对英语文本分词，返回 Token 形状的 dict 列表。"""
    if not text:
        return []

    nlp = _get_nlp()
    doc = nlp(text)

    result: list[dict] = []
    for i, token in enumerate(doc):
        upos = token.pos_
        clickable = upos not in _NON_CLICKABLE_UPOS and token.text.strip() != ""

        result.append({
            "i": i,
            "surface": token.text,
            "lemma": token.lemma_,
            "reading": "",
            "pos": _POS_READABLE.get(upos, upos),
            "clickable": clickable,
            "collected": False,
            "space_after": bool(token.whitespace_),
        })
    return result
