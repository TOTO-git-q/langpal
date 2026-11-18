"""琐碎 / 实质插话判定 + 被打断后下一轮生成用的交接前言。

语义照抄 TG 线（tgbot/interject.py），适配点：TG 那边 `is_trivial` 靠语料库的
`vault._content_ngrams` 判断"有没有实义词"，langpal 没有那套语料库，这里改用轻量启发式
（见 `is_trivial` 的 docstring），够用、不追求语言学精确。

- **琐碎插话不刹车**：纯标点/纯 emoji/颜文字/单字附和/短到没实义内容——真人不会因为对方
  回个"？"就把说到一半的话咽回去重说，让当前投递继续把话说完。
- **实质插话刹车 + 交接**：停在下一条气泡之前，把"已发出的/没发完的"记下来，下一轮生成时
  当前言注入，逼她把没说完的内容**总结着合并**进新回复，而不是失忆或者硬邦邦先把旧话说完
  再答新话。
"""

from __future__ import annotations

import re
import unicodedata

from . import prompts

# 纯网络笑/附和/寒暄词：整条=没料。日/英/德各配一份，不追求穷尽，够挡住最常见的琐碎回应。
TRIVIAL_WORDS = {
    # 日语
    "うん", "うんうん", "そう", "そうそう", "まじ", "へえ", "へー", "え", "えー", "ええ",
    "はい", "いいね", "わかる", "www", "w", "ww", "ｗ", "ｗｗｗ", "草", "笑", "なるほど",
    "おっけ", "おっけー", "おけ",
    # 英语
    "ok", "okk", "okok", "okay", "k", "kk", "lol", "lmao", "www", "ww", "haha", "hahaha",
    "hhh", "hehe", "yep", "yeah", "yup", "yo", "hi", "hey", "hmm", "hm", "uh", "huh", "orz",
    # 德语
    "ja", "joa", "achso", "krass", "echt", "genau", "klar", "aha", "boah", "ne", "nee",
    "haha", "hehe",
}

# 含汉字/3 个以上字母的拉丁词，视为"可能带实义"的信号（短文本判定里用来避免误杀）。
_HAN_RE = re.compile(r"[一-鿿]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# 短到判琐碎的长度阈值（字符数）。
_SHORT_LEN = 6


def _is_pure_symbolic(text: str) -> bool:
    """去空白后，剩下的字符是不是（近乎）全是标点/符号（含大多数 emoji 与颜文字）——判琐碎。

    颜文字里常混进一两个"看着像符号、实际 unicode 分类是字母"的字符（如 (´;ω;`) 里的 ω、
    (T_T) 里的 T），严格要求"一个非标点/符号字符都没有"会把这类常见颜文字误判成实义内容，
    所以放宽到"整体很短 + 非标点/符号字符不超过 2 个"也算纯符号/颜文字。
    """
    core = text.strip()
    if not core:
        return True
    non_symbolic = 0
    for ch in core:
        if ch.isspace():
            continue
        category = unicodedata.category(ch)  # 'P*' 标点 / 'S*' 符号（含大部分 emoji）
        if category[0] in ("P", "S"):
            continue
        non_symbolic += 1
    if non_symbolic == 0:
        return True
    return non_symbolic <= 2 and len(core) <= 10


def is_trivial(text: str) -> bool:
    """插进来的这句是不是"没实质内容"的——是则不该打断正在投递的回复。

    判定顺序：空 → 词表命中 → 纯标点/emoji/颜文字 → 短（<=6 字符）且没有汉字/拉丁实词信号。
    """
    t = (text or "").strip()
    if not t:
        return True
    if t.lower() in TRIVIAL_WORDS:
        return True
    if _is_pure_symbolic(t):
        return True
    if len(t) <= _SHORT_LEN:
        if _HAN_RE.search(t):
            return False  # 含汉字，多半是有实义的短句（如"痛い""助けて"）
        if _LATIN_WORD_RE.search(t):
            return False  # 含 3 字母以上的拉丁词，多半不是纯语气词
        return True
    return False


def preface(unsent: list[str], sent_before: list[str], barge_count: int = 0) -> str:
    """被打断后的下一轮生成前言。没有未发内容（unsent 为空）→ 空串，不注入。

    sent_before 为空 = 一条都没发出去就被打断（连"思考停顿"那一下都没扛过去）。
    barge_count = 这一轮回复被"实质插话"刹车了几次（调用方数好、消费即清零传进来）；
    >=2 时在前言末尾追加一句情绪提示，允许带点小情绪抢回话头。
    """
    if not unsent:
        return ""
    out = prompts.INTERRUPT_CTX.format(
        sent=" / ".join(sent_before) if sent_before else "（这次一条都还没发出去）",
        unsent=" / ".join(unsent),
    )
    if barge_count >= 2:
        out += prompts.INTERRUPT_BARGE_CTX.format(n=barge_count)
    return out
