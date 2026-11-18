"""Dictionary-backed Japanese readings. Input never leaves this process."""
import re
from functools import lru_cache

from .tokenize import _lock  # 和分词共用一把锁：Sudachi 分词器不能被两个线程同时用
from .tokenize.ja import _get_tokenizer, _katakana_to_hiragana
from sudachipy import tokenizer

KANJI = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆ヶ]')
KANA = re.compile(r'^[\u3040-\u309f\u30a0-\u30ffー]+$')


def _parts(surface, reading):
    """Keep visible okurigana outside ruby where its alignment is unambiguous."""
    prefix = 0
    while prefix < min(len(surface), len(reading)) and _katakana_to_hiragana(surface[prefix]) == reading[prefix] and not KANJI.search(surface[prefix]):
        prefix += 1
    suffix = 0
    while suffix < min(len(surface) - prefix, len(reading) - prefix) and _katakana_to_hiragana(surface[-1-suffix]) == reading[-1-suffix] and not KANJI.search(surface[-1-suffix]):
        suffix += 1
    end = len(surface) - suffix if suffix else len(surface)
    read_end = len(reading) - suffix if suffix else len(reading)
    result = []
    if prefix:
        result.append({'text': surface[:prefix], 'reading': ''})
    middle = surface[prefix:end]
    if middle:
        result.append({'text': middle, 'reading': reading[prefix:read_end]})
    if suffix:
        result.append({'text': surface[end:], 'reading': ''})
    return result


@lru_cache(maxsize=128)
def annotate(text):
    result = []
    with _lock:
        morphemes = list(_get_tokenizer().tokenize(text, tokenizer.Tokenizer.SplitMode.C))
    for token in morphemes:
        surface = token.surface()
        reading = _katakana_to_hiragana(token.reading_form())
        # Unknown proper names and alphabet/digit-only tokens should not get invented readings.
        eligible = bool(KANJI.search(surface) and KANA.fullmatch(reading) and not token.is_oov())
        result.append({'text': surface, 'reading': reading if eligible else '',
                       'parts': _parts(surface, reading) if eligible else [{'text': surface, 'reading': ''}]})
    if ''.join(token['text'] for token in result) != text:
        return [{'text': text, 'reading': '', 'parts': [{'text': text, 'reading': ''}]}]
    return result
