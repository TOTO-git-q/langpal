"""日语分词：SudachiPy + sudachidict_core，Mode C（长单位）。

返回 Token 形状字段见 docs/history/API.md。reading 取 reading_form()（片假名）转平假名；
pos 取一级词性（日文原名，如 名詞/動詞）；标点/空白 clickable=False；
collected 恒为 False，交由上游覆写。
"""
from __future__ import annotations

from sudachipy import dictionary, tokenizer

# 片假名(30A1-30F6) -> 平假名(3041-3096)，码位差固定为 0x60
_KATAKANA_START = 0x30A1
_KATAKANA_END = 0x30F6
_HIRA_OFFSET = 0x60

# 不可点击的一级词性：标点符号 / 空白
_NON_CLICKABLE_POS1 = {"補助記号", "空白"}

# 模块级缓存：进程内只构建一次 Tokenizer
_tokenizer_obj = None


def _get_tokenizer():
    global _tokenizer_obj
    if _tokenizer_obj is None:
        _tokenizer_obj = dictionary.Dictionary().create()
    return _tokenizer_obj


def _katakana_to_hiragana(text: str) -> str:
    chars = []
    for ch in text:
        code = ord(ch)
        if _KATAKANA_START <= code <= _KATAKANA_END:
            chars.append(chr(code - _HIRA_OFFSET))
        else:
            chars.append(ch)
    return "".join(chars)


def tokenize(text: str) -> list[dict]:
    """对日语文本分词，返回 Token 形状的 dict 列表。"""
    if not text:
        return []

    tok = _get_tokenizer()
    mode = tokenizer.Tokenizer.SplitMode.C
    morphemes = tok.tokenize(text, mode)

    result: list[dict] = []
    for i, m in enumerate(morphemes):
        surface = m.surface()
        pos1 = m.part_of_speech()[0]
        reading = _katakana_to_hiragana(m.reading_form())
        lemma = m.dictionary_form()
        clickable = pos1 not in _NON_CLICKABLE_POS1 and surface.strip() != ""

        result.append({
            "i": i,
            "surface": surface,
            "lemma": lemma,
            "reading": reading,
            "pos": pos1,
            "clickable": clickable,
            "collected": False,
            "space_after": False,  # 日语词间无空格
        })
    return result
