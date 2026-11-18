"""语言守门：确保 AI 回复完全落在目标语言里。

- ja：平/片假名占比的启发式。日语口语几乎不可能一个假名都不出现（纯汉字/罗马字的回复
  几乎必然是中文或英文答错了语言），所以用"有没有假名"就能可靠判定，比通用语言检测器
  更适合日语这种和中文共享汉字的情况。
- en/de：lingua-language-detector。检测语言集合刻意只给"目标语言 + 中文"，不加载多余的
  语言模型（既省启动时间，也够用——最常见的答错情形就是整段冒出中文）。
"""

import re
from functools import lru_cache

from lingua import IsoCode639_1, IsoCode639_3, Language, LanguageDetectorBuilder

from . import languages

_KANA_RE = re.compile(r"[぀-ヿ]")  # 平假名 + 片假名
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)  # 任意语言的字母，用来判断"这句话里有没有文字"

_LINGUA_TARGETS = {"en": Language.ENGLISH, "de": Language.GERMAN}
_detector = LanguageDetectorBuilder.from_languages(
    Language.ENGLISH, Language.GERMAN, Language.CHINESE
).build()

_LANG_NAMES = {"ja": "日语", "en": "英语", "de": "德语"}


def _target(tag: str):
    code = languages.base(tag).upper()
    if len(code) == 2 and (iso := getattr(IsoCode639_1, code, None)):
        return Language.from_iso_code_639_1(iso)
    if len(code) == 3 and (iso := getattr(IsoCode639_3, code, None)):
        return Language.from_iso_code_639_3(iso)
    return None


@lru_cache(maxsize=12)
def _detector_with(target):
    known = {Language.ENGLISH, Language.GERMAN, Language.CHINESE, Language.JAPANESE}
    if target is not None:
        known.add(target)
    return LanguageDetectorBuilder.from_languages(*known).build()


def check(text: str, language: str) -> bool:
    """粗判 text 是否符合 language 的语言锁定。

    空文本 / 纯标点数字（无法判定）视为通过，不误杀。
    """
    if not text or not _LETTER_RE.search(text):
        return True

    base = languages.base(language)
    if base == "ja":
        # 只要出现假名就判定为日语；一个假名都没有（纯汉字或纯罗马字）几乎不可能是正常日语口语
        return bool(_KANA_RE.search(text))

    target = _LINGUA_TARGETS.get(base) or _target(base)
    if target is None:
        return True  # 未知语言不拦截
    detector = _detector if base in _LINGUA_TARGETS else _detector_with(target)
    detected = detector.detect_language_of(text)
    return detected == target


def correction_prompt(language: str) -> str:
    """守门没过时，作为下一轮"用户消息"发给 provider 的纠正指令。

    不落库、不展示给用户——只是塞进和 provider 的常驻会话里，让它用同样的人设重说一遍。
    """
    name = _LANG_NAMES.get(language) or languages.display(language)
    return (
        f"（这是系统提示，不是对方说的话，回复里也不要提到这条提示：你刚才那句回复没有"
        f"完全用{name}写。请只用{name}把刚才想表达的内容重新说一遍，人设、语气、"
        f"内容意图都不变，就是换成{name}重说。）"
    )
