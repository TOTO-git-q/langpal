"""解析服务：词卡（explain/word）与句子结构解析（explain/sentence）。

统一走 registry.get_provider().generate_json(prompt, schema)（杂活档，Haiku/deepseek-chat）。
解释文字一律中文书写，面向学习者，结合调用方传入的整句语境作答。

缓存：explain_cache 表（app.db.get_conn）。
- word 键 = language + lemma + sha1(sentence)
- sentence 键 = language + sha1(sentence)
命中直接返回 cached=true，不落一次新的 payload。

预生成入口 pregen_for_message() 保持兼容；批量简释在 word_glosses 中管理。
简释不会覆盖这里的完整词卡缓存。
"""
import asyncio
import hashlib
import json

from ..db import get_conn
from ..providers.registry import get_utility_provider
from .languages import display

# ---------------------------------------------------------------------------
# schema（转给 provider.generate_json 的结构约束；对齐 docs/history/API.md 词卡/句解析形状，
# 不含 cached —— 该字段由服务层根据缓存命中情况填充，不让模型生成）
# ---------------------------------------------------------------------------

WORD_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "lemma": {"type": "string"},
        "surface": {"type": "string"},
        "reading": {"type": "string", "description": "仅日语给出假名读音，英/德留空字符串"},
        "pos": {"type": "string"},
        "meaning_zh": {"type": "string", "description": "结合语境的中文释义，不是词典义项罗列"},
        "usage_in_context": {"type": "string", "description": "结合给定整句，说明该词在此处的具体用法，中文"},
        "register_note": {"type": ["string", "null"], "description": "语体/场合提示，中文，可空"},
        "grammar_note": {
            "type": ["string", "null"],
            "description": (
                "中文。德语名词给冠词+复数；德语动词给是否规则变化；"
                "英语动词给不规则变化（过去式/过去分词）；日语给活用类型与变形说明；"
                "不适用则可空。"
            ),
        },
    },
    "required": [
        "lemma", "surface", "reading", "pos",
        "meaning_zh", "usage_in_context", "register_note", "grammar_note",
    ],
}

SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation_zh": {"type": "string"},
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "role": {"type": "string", "description": "中文角色标签，如「主题」「谓语」「宾语」"},
                    "note": {"type": "string", "description": "中文说明"},
                },
                "required": ["text", "role", "note"],
            },
        },
        "grammar_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "explanation_zh": {"type": "string"},
                    "example": {"type": "string"},
                },
                "required": ["pattern", "explanation_zh", "example"],
            },
        },
    },
    "required": ["translation_zh", "chunks", "grammar_points"],
}

_LANG_NAME = {"ja": "日语", "en": "英语", "de": "德语"}

_word_jobs = {}


# ---------------------------------------------------------------------------
# 缓存存取
# ---------------------------------------------------------------------------

def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _word_cache_key(language: str, lemma: str, sentence: str) -> str:
    return f"{language}:{lemma}:{_sha1(sentence)}"


def _detail_cache_key(language, lemma, surface, sentence, occurrence=None):
    if occurrence is None:
        return _word_cache_key(language, lemma, sentence)
    return 'detail:v2:' + _sha1(json.dumps([language, lemma, surface, sentence, occurrence], ensure_ascii=False))


def _sentence_cache_key(language: str, sentence: str) -> str:
    return f"{language}:{_sha1(sentence)}"


def _get_cached(kind: str, cache_key: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT payload_json FROM explain_cache WHERE kind = ? AND cache_key = ?",
            (kind, cache_key),
        ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None
    finally:
        conn.close()


def _set_cached(kind: str, cache_key: str, payload: dict) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO explain_cache (kind, cache_key, payload_json) VALUES (?, ?, ?)",
            (kind, cache_key, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

def _build_word_prompt(language: str, lemma: str, surface: str, sentence: str) -> str:
    lang_name = _LANG_NAME.get(language) or display(language)
    return f"""你是外语学习助手，为学习者制作一张词卡。目标语言：{lang_name}（language={language}）。

目标词（词典形）：{lemma}
原句中的实际写法：{surface}
所在整句（务必结合此语境作答，不要脱离语境泛泛而谈）：{sentence}

请用自然、面向学习者的中文完成各字段：
- reading：仅当 language=ja 时给出该词在这句里的假名读音；language=en/de 时留空字符串 ""。
- pos：词性，简短标注即可。
- meaning_zh：该词在这句语境下最贴切的中文释义（挑此处最合适的义项，不要罗列词典所有义项）。
- usage_in_context：结合这句话，具体说明这个词在此处怎么用、为什么这样用，1-2 句中文。
- register_note：语体/使用场合提示（口语、书面、敬语、俚语等），中文；没有特别之处可写「通用」，不要留空。
- grammar_note：中文书写。
  - 若 language=de 且为名词：必须给出冠词（der/die/das）与复数形式。
  - 若 language=de 且为动词：说明是否规则变化及关键变位提示。
  - 若 language=en 且为动词：若为不规则动词，给出过去式/过去分词；规则动词可写「规则变化」。
  - 若 language=ja：给出该词的活用类型（如五段/一段/サ变等）与在此句中的变形说明；不活用的词（名词等）可说明相关语法点或留空字符串。
  - 其余情况不适用时可留空字符串。

除目标语言本身的词汇/例句外，所有解释文字必须是中文。严格按 schema 输出 JSON，不要输出 schema 之外的字段，不要输出任何解释性前后缀文字。"""


def _build_sentence_prompt(language: str, sentence: str) -> str:
    lang_name = _LANG_NAME.get(language) or display(language)
    return f"""你是外语学习助手，为学习者解析一整句{lang_name}（language={language}）的结构。

原句：{sentence}

请完成：
- translation_zh：整句自然的中文翻译。
- chunks：把原句切成若干有意义的语块（短语级别，不要拆到单字），每个语块给出：
  - text：语块原文
  - role：该语块在句中的功能，用中文短标签（如「主题」「谓语」「宾语」「状语」「连体修饰」等）
  - note：中文说明，讲清楚为什么是这个功能、有什么语法点
  chunks 拼接起来应能还原原句（允许标点归属就近语块）。
- grammar_points：挑这句话里对学习者有价值的 1-3 个语法点，每项给出：
  - pattern：语法点名称/固定搭配
  - explanation_zh：中文讲解，面向学习者，自然易懂
  - example：一个例句（可以直接用原句节选，或另举一个同结构短例句）
  没有值得讲的语法点可返回空数组。

所有讲解文字用中文书写（目标语言原文/例句本身除外）。严格按 schema 输出 JSON，不要输出 schema 之外的字段，不要输出任何解释性前后缀文字。"""


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

async def explain_word(language: str, lemma: str, surface: str, sentence: str, occurrence: int | None = None) -> dict:
    """Coalesce repeated detail requests; cancellation only closes that caller."""
    key = (asyncio.get_running_loop(), language, lemma, surface, sentence, occurrence)
    task = _word_jobs.get(key)
    if task is None:
        task = asyncio.create_task(_explain_word(language, lemma, surface, sentence, occurrence))
        _word_jobs[key] = task
        def finished(done):
            if _word_jobs.get(key) is done:
                _word_jobs.pop(key, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
    return await asyncio.shield(task)


async def _explain_word(language: str, lemma: str, surface: str, sentence: str, occurrence: int | None = None) -> dict:
    cache_key = _detail_cache_key(language, lemma, surface, sentence, occurrence)
    cached = _get_cached("word", cache_key)
    if cached is not None:
        result = dict(cached)
        result["cached"] = True
        return result

    provider = get_utility_provider()
    prompt = _build_word_prompt(language, lemma, surface, sentence)
    if occurrence is not None:
        prompt += f'\n目标是上述原句中这个词（词典形相同且写法相同）的第 {occurrence + 1} 次出现，请结合该位置解释，其他位置的同词不算。'
    raw = await provider.generate_json(prompt, WORD_CARD_SCHEMA)

    payload = {
        "lemma": raw.get("lemma") or lemma,
        "surface": raw.get("surface") or surface,
        "reading": raw.get("reading") or "",
        "pos": raw.get("pos") or "",
        "meaning_zh": raw.get("meaning_zh") or "",
        "usage_in_context": raw.get("usage_in_context") or "",
        "register_note": raw.get("register_note") or None,
        "grammar_note": raw.get("grammar_note") or None,
    }
    _set_cached("word", cache_key, payload)

    result = dict(payload)
    result["cached"] = False
    return result


async def explain_sentence(language: str, sentence: str) -> dict:
    cache_key = _sentence_cache_key(language, sentence)
    cached = _get_cached("sentence", cache_key)
    if cached is not None:
        result = dict(cached)
        result["cached"] = True
        return result

    provider = get_utility_provider()
    raw = await provider.generate_json(_build_sentence_prompt(language, sentence), SENTENCE_SCHEMA)

    payload = {
        "translation_zh": raw.get("translation_zh") or "",
        "chunks": raw.get("chunks") or [],
        "grammar_points": raw.get("grammar_points") or [],
    }
    _set_cached("sentence", cache_key, payload)

    result = dict(payload)
    result["cached"] = False
    return result



async def pregen_for_message(text: str, language: str, tokens: list[dict]) -> None:
    """Compatibility hook; new chat delivery schedules per-bubble summaries."""
    from .word_glosses import schedule
    schedule(text, language, tokens)
