"""Versioned exam practice formats. Language models choose a fitting format and write the items."""
import re
from .languages import base

LENGTH_LIMITS = {"en": (15, 1400), "ja": (150, 3200)}
CHARACTER_LANGUAGES = {"ja", "zh", "th", "lo", "km", "my"}


def character_count(language):
    return base(language) in CHARACTER_LANGUAGES


def limits(language, custom=False):
    if custom or language not in LENGTH_LIMITS:
        return (40, 3200) if character_count(language) else (15, 1400)
    return LENGTH_LIMITS[language]


def article_length(language, text):
    if character_count(language):
        return len(re.sub(r"\s+", "", text))
    return len(re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE))


def textbook_excerpt(text, minimum, maximum, target):
    """Select a continuous source passage, preferring intact paragraph boundaries."""
    def best_passage(edges):
        best = None
        for start in edges[:-1]:
            for end in edges:
                if end <= start:
                    continue
                passage = text[start:end].strip()
                length = article_length("en", passage)
                if length > maximum:
                    break
                if length >= minimum:
                    distance = abs(length - target)
                    if best is None or distance < best[0]:
                        best = distance, passage
        return best[1] if best else ""

    def boundaries(pattern):
        return [0, *(m.end() for m in re.finditer(pattern, text)), len(text)]

    return best_passage(boundaries(r"\n\n+")) or best_passage(boundaries(r"\n\n+|(?<=[.!?])\s+(?=[A-Z“])"))

FORMATS = {
    "toefl_daily": {
        "language": "en", "minimum": 15, "count": 3,
        "label": "TOEFL iBT · Read in Daily Life",
        "fit": "实际生活中会遇到的通知、邮件、日程、公共信息等，有目的、约束或行动信息。",
        "skills": "用英语提问。考用途、适用条件、细节或下一步。干扰项可改变对象、时间或例外。",
    },
    "toefl_academic": {
        "language": "en", "minimum": 150, "count": 5,
        "label": "TOEFL iBT · Read an Academic Passage",
        "fit": "有完整主题和论述结构的学术科普、说明或分析文字，能从原文取证。",
        "skills": "用英语提问。覆盖主旨、明示信息、推断及语篇功能中的不同能力。",
    },
    # JLPT N1 読解: lengths follow the real sections (短文 ~200字, 中文 ~500字, 長文 ~1000字).
    "jlpt_short": {
        "language": "ja", "minimum": 150, "maximum": 450, "count": 1,
        "label": "JLPT N1 · 内容理解（短文）",
        "fit": "200 字左右、意思完整的一段日语：随笔、说明、评论或通知的一段，有可概括的要点或笔者想法。",
        "skills": "照 N1 内容理解（短文）出：一题，问「筆者の言いたいことは何か」「〜とはどういうことか」"
                  "这类要读懂整段才能答的问题；四个选项都用原文的词但意思有关键差异。",
    },
    "jlpt_mid": {
        "language": "ja", "minimum": 350, "maximum": 800, "count": 3,
        "label": "JLPT N1 · 内容理解（中文）",
        "fit": "500 字左右的日语说明文、随笔或评论，有因果、对比或笔者的看法。",
        "skills": "照 N1 内容理解（中文）出：三题，依次考下划线部分的理由或所指（「〜とあるが、なぜか」"
                  "「〜とは何か」）、段落之间的关系、笔者的看法；题目顺序与原文顺序一致。",
    },
    "jlpt_long": {
        "language": "ja", "minimum": 700, "count": 4,
        "label": "JLPT N1 · 内容理解（長文）",
        "fit": "1000 字左右、有多个信息单元和段落联系的日语文章，可问文意和文脉。",
        "skills": "照 N1 内容理解（長文）出：四题，考指代、理由、段落要旨，最后一题问「この文章で筆者が最も言いたいことは何か」。",
    },
    "jlpt_theme": {
        "language": "ja", "minimum": 700, "count": 3,
        "label": "JLPT N1 · 主張理解（長文）",
        "fit": "1000 字左右的日语论说文，有作者主张、例证和限定，能区分作者与被引述者。",
        "skills": "照 N1 主張理解出：三题，考例证的作用、笔者对某观点的态度，最后一题问笔者的主张；"
                  "不要把被引述的立场当成笔者的立场。",
    },
    "gre_rc": {
        "language": "en", "minimum": 70, "count": 4, "options": 5,
        "label": "GRE · 阅读理解（五选一）",
        "fit": "论证、研究说明或观点对照；能从原文分析作者立场、证据与结论、让步或推论。",
        "skills": "用英语提问。测试论证结构、句子作用、作者立场、隐含前提或可由证据推出的结论。",
    },
}


def profiles(language, exam="toefl", material="article", custom=None):
    if custom:
        if custom["language"] != language:
            return {}
        return {
            custom["id"]: {
                "language": language, "minimum": custom["min_length"], "maximum": custom["max_length"],
                "label": custom["name"], "count": custom["question_count"],
                "fit": "篇幅符合并有足够完整的原文依据支持这些出题方向：" + custom["skills"],
                "skills": custom["skills"],
            },
        }
    if language not in {"en", "ja"}:
        lower, upper = limits(language)
        return {"general": {"language": language, "minimum": lower, "maximum": upper,
                            "label": "通用阅读", "count": 4,
                            "fit": "观点或事实完整，有足够原文支持四道问题。",
                            "skills": "用目标语言考主旨、明示细节、语篇关系和可从原文推出的推断。"}}
    return {key: profile for key, profile in FORMATS.items()
            if profile["language"] == language and (key == "gre_rc") == (exam == "gre")
            and not (material == "textbook" and key == "toefl_daily")}


def allowed(language, text, exam="toefl", material="article", custom=None):
    length = article_length(language, text)
    if language == "ja" and not custom:
        length = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text))
    return {key: profile for key, profile in profiles(language, exam, material, custom).items()
            if profile["minimum"] <= length <= profile.get("maximum", length)}


def question_count(key, language, text, custom=None):
    if custom:
        return custom["question_count"]
    if key == "general":
        return profiles(language)["general"]["count"]
    length = article_length(language, text)
    if (key == "toefl_daily" and length < 75) or (key == "gre_rc" and length < 220):
        return 2
    return FORMATS[key]["count"]
