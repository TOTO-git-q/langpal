"""导入导出：酒馆（SillyTavern）世界书 .json、角色卡 .json（V2/V3 的 data.character_book）、
角色卡 .png（tEXt 块 chara / ccv3，base64）。只取世界书，不建联系人。

位置换算：0 → before_persona；1、5、6 → after_persona；2、3、4 → turn（别的数字也当 turn，并给提示）。
认不出的酒馆字段原样放进条目的 extensions，导出时带回去；这里独有的字段导出时放在 extensions.jine。
"""
from __future__ import annotations

import base64
import json
import struct
import zlib
from typing import Any

from pydantic import ValidationError

from .model import MAX_ENTRIES, Book, Entry, parse_regex

MAX_FILE_BYTES = 16 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"
_LOGIC_FROM_ST = {0: "and_any", 1: "not_all", 2: "not_any", 3: "and_all"}
_LOGIC_TO_ST = {v: k for k, v in _LOGIC_FROM_ST.items()}
_JINE_FIELDS = ("lemma", "semantic_threshold", "conditions", "position", "logic")

# 酒馆世界书条目里我们认得的字段（其余原样进 extensions）
_ST_KNOWN = {"uid", "key", "keysecondary", "comment", "content", "constant", "vectorized", "selective",
             "selectiveLogic", "order", "position", "disable", "excludeRecursion", "preventRecursion",
             "delayUntilRecursion", "probability", "useProbability", "group", "groupOverride", "groupWeight",
             "scanDepth", "caseSensitive", "matchWholeWords", "automationId", "sticky", "cooldown", "delay",
             "extensions", "displayIndex"}
# 角色卡（V2 规范）character_book 条目认得的字段
_CARD_KNOWN = {"keys", "content", "extensions", "enabled", "insertion_order", "case_sensitive", "name",
               "priority", "id", "comment", "selective", "secondary_keys", "constant", "position"}
# 酒馆写进角色卡条目 extensions 的字段（snake_case）
_CARD_EXT = {"position", "exclude_recursion", "prevent_recursion", "delay_until_recursion", "probability",
             "useProbability", "depth", "selectiveLogic", "group", "group_override", "group_weight",
             "scan_depth", "case_sensitive", "match_whole_words", "automation_id", "vectorized", "sticky",
             "cooldown", "delay", "role", "use_group_scoring"}


class BadImport(ValueError):
    pass


def _png_cards(data: bytes) -> dict[str, Any]:
    found: dict[str, Any] = {}
    pos = len(_PNG)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        text = None
        if kind == b"tEXt" and b"\x00" in body:
            keyword, _, text = body.partition(b"\x00")
        elif kind == b"iTXt" and b"\x00" in body:
            keyword, _, rest = body.partition(b"\x00")
            compressed, rest = rest[:1], rest[2:]
            _lang, _, rest = rest.partition(b"\x00")
            _tr, _, text = rest.partition(b"\x00")
            if compressed == b"\x01":
                try:
                    text = zlib.decompress(text)
                except zlib.error:
                    text = None
        elif kind == b"IEND":
            break
        else:
            continue
        name = keyword.decode("latin-1").lower()
        if text is None or name not in ("chara", "ccv3"):
            continue
        try:
            found[name] = json.loads(base64.b64decode(text).decode("utf-8"))
        except Exception:
            continue
    return found


def _num(value, default, low=None, high=None):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def _keys(value) -> list[str]:
    if isinstance(value, str):
        value = [k for k in value.split(",")]
    if not isinstance(value, list):
        return []
    return [str(k).strip()[:200] for k in value if str(k).strip()][:40]


def _position(value, warnings: list[str], title: str) -> str:
    if isinstance(value, str):
        return {"before_char": "before_persona", "after_char": "after_persona"}.get(value, "turn")
    number = _num(value, 1)
    if number == 0:
        return "before_persona"
    if number in (1, 5, 6):
        return "after_persona"
    if number not in (2, 3, 4):
        warnings.append(f"「{title}」的插入位置 {value} 这里没有，放到了每轮背景里")
    return "turn"


def _apply_jine(item: dict, ext: dict) -> dict:
    jine = ext.pop("jine", None)
    jine = jine if isinstance(jine, dict) else {}
    for key in _JINE_FIELDS:
        if key in jine:
            item[key] = jine[key]
    for key in ("semantic", "whole_words", "case_sensitive"):
        if key in jine:
            item[key] = jine[key]
    return item


def _from_st(raw: dict, index: int, warnings: list[str]) -> dict:
    title = str(raw.get("comment") or "")[:200]
    ext = dict(raw.get("extensions") or {}) if isinstance(raw.get("extensions"), dict) else {}
    unknown = {key: value for key, value in raw.items() if key not in _ST_KNOWN}
    if unknown:
        ext["st"] = unknown
    st_position = raw.get("position")
    if st_position not in (None, 0, 1, 4):
        ext["st_position"] = st_position
    selective = raw.get("selective", True)
    item = {
        "uid": _num(raw.get("uid"), index, 0, 10**9 - 1) + 1,  # 酒馆从 0 编号，这里从 1
        "title": title,
        "content": str(raw.get("content") or ""),
        "enabled": not raw.get("disable", False),
        "constant": bool(raw.get("constant", False)),
        "keys": _keys(raw.get("key")),
        "secondary_keys": _keys(raw.get("keysecondary")) if selective else [],
        "logic": _LOGIC_FROM_ST.get(_num(raw.get("selectiveLogic"), 0), "and_any"),
        "case_sensitive": bool(raw.get("caseSensitive") or False),
        "whole_words": bool(raw.get("matchWholeWords") or False),
        "semantic": bool(raw.get("vectorized", False)),
        "position": _position(st_position if st_position is not None else 1, warnings, title or f"#{index}"),
        "order": _num(raw.get("order"), 100, -100000, 100000),
        "probability": _num(raw.get("probability"), 100, 0, 100) if raw.get("useProbability", True) else 100,
        "scan_depth": None if raw.get("scanDepth") is None else _num(raw.get("scanDepth"), None, 0, 100),
        "sticky": _num(raw.get("sticky"), 0, 0, 1000),
        "cooldown": _num(raw.get("cooldown"), 0, 0, 1000),
        "delay": _num(raw.get("delay"), 0, 0, 1_000_000),
        "group": str(raw.get("group") or "")[:200],
        "group_weight": _num(raw.get("groupWeight"), 100, 1, 100000),
        "group_override": bool(raw.get("groupOverride", False)),
        "exclude_recursion": bool(raw.get("excludeRecursion", False)),
        "prevent_recursion": bool(raw.get("preventRecursion", False)),
        "delay_until_recursion": bool(raw.get("delayUntilRecursion", False)),
        "automation_id": str(raw.get("automationId") or "")[:120],
        "extensions": ext,
    }
    return _apply_jine(item, ext)


def _from_card(raw: dict, index: int, warnings: list[str]) -> dict:
    ext = dict(raw.get("extensions") or {}) if isinstance(raw.get("extensions"), dict) else {}
    unknown = {key: value for key, value in raw.items() if key not in _CARD_KNOWN}
    if unknown:
        ext["card"] = unknown
    title = str(raw.get("comment") or raw.get("name") or "")[:200]
    position = ext.pop("position", raw.get("position", 1))
    if position not in (None, 0, 1, 4, "before_char", "after_char"):
        ext["st_position"] = position
    selective = raw.get("selective", True)
    item = {
        "uid": _num(raw.get("id"), index + 1, 0, 10**9),
        "title": title,
        "content": str(raw.get("content") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "constant": bool(raw.get("constant", False)),
        "keys": _keys(raw.get("keys")),
        "secondary_keys": _keys(raw.get("secondary_keys")) if selective else [],
        "logic": _LOGIC_FROM_ST.get(_num(ext.pop("selectiveLogic", 0), 0), "and_any"),
        "case_sensitive": bool(ext.pop("case_sensitive", raw.get("case_sensitive")) or False),
        "whole_words": bool(ext.pop("match_whole_words", False) or False),
        "semantic": bool(ext.pop("vectorized", False)),
        "position": _position(position if position is not None else 1, warnings, title or f"#{index}"),
        "order": _num(raw.get("insertion_order"), 100, -100000, 100000),
        "probability": (_num(ext.pop("probability", 100), 100, 0, 100)
                        if ext.pop("useProbability", True) else 100),
        "scan_depth": (lambda v: None if v is None else _num(v, None, 0, 100))(ext.pop("scan_depth", None)),
        "sticky": _num(ext.pop("sticky", 0), 0, 0, 1000),
        "cooldown": _num(ext.pop("cooldown", 0), 0, 0, 1000),
        "delay": _num(ext.pop("delay", 0), 0, 0, 1_000_000),
        "group": str(ext.pop("group", "") or "")[:200],
        "group_weight": _num(ext.pop("group_weight", 100), 100, 1, 100000),
        "group_override": bool(ext.pop("group_override", False)),
        "exclude_recursion": bool(ext.pop("exclude_recursion", False)),
        "prevent_recursion": bool(ext.pop("prevent_recursion", False)),
        "delay_until_recursion": bool(ext.pop("delay_until_recursion", False)),
        "automation_id": str(ext.pop("automation_id", "") or "")[:120],
        "extensions": ext,
    }
    return _apply_jine(item, ext)


def _clean(item: dict, warnings: list[str]) -> dict | None:
    title = item.get("title") or f"#{item.get('uid')}"
    good_keys = []
    for field in ("keys", "secondary_keys"):
        kept = []
        for key in item.get(field) or []:
            try:
                parse_regex(key)
                kept.append(key)
            except ValueError:
                warnings.append(f"「{title}」的正则关键词 {key} 这里用不了，已去掉")
        item[field] = kept
        good_keys.append(kept)
    if len(item.get("content") or "") > 4000:
        warnings.append(f"「{title}」正文超过 4000 字，截掉了后面的部分")
        item["content"] = item["content"][:4000]
    ext = item.get("extensions") or {}
    if len(json.dumps(ext, ensure_ascii=False, default=str)) > 20000:
        warnings.append(f"「{title}」带的酒馆扩展字段太多，没保留")
        item["extensions"] = {}
    try:
        return Entry.model_validate(item).model_dump()
    except ValidationError as error:
        issue = error.errors(include_input=False)[0]
        if issue["loc"] and issue["loc"][0] in ("conditions", "logic", "position", "lemma", "semantic_threshold"):
            # extensions.jine 里的独有字段坏了：退回默认值再试一次
            for key in _JINE_FIELDS:
                item.pop(key, None)
            try:
                return Entry.model_validate(item).model_dump()
            except ValidationError:
                pass
        warnings.append(f"「{title}」有字段不对（{issue['msg']}），跳过了")
        return None


def parse_upload(data: bytes, filename: str = "") -> tuple[str, Book, list[str]]:
    """返回 (书名, 书, 提示)。认不出 / 没有世界书 → BadImport。"""
    if len(data) > MAX_FILE_BYTES:
        raise BadImport("文件太大（上限 16MB）")
    stem = (filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0] or "导入的世界书")[:110]
    if data.startswith(_PNG):
        cards = _png_cards(data)
        source = cards.get("ccv3") or cards.get("chara")
        if source is None:
            raise BadImport("这张图片里没有角色卡数据")
    else:
        try:
            source = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            raise BadImport("文件不是 JSON，也不是带角色卡数据的 PNG") from None
    if not isinstance(source, dict):
        raise BadImport("文件内容不是世界书")
    warnings: list[str] = []
    card = source.get("data") if isinstance(source.get("data"), dict) else None
    if card is not None or "character_book" in source:
        book = (card or source).get("character_book")
        if not isinstance(book, dict):
            raise BadImport("这张角色卡里没有世界书")
        name = str(book.get("name") or "").strip() or f"{(card or source).get('name') or stem} 的世界书"
        raw_entries = book.get("entries") or []
        convert = _from_card
        settings = {}
        if book.get("scan_depth") is not None:
            settings["scan_depth"] = _num(book.get("scan_depth"), 4, 0, 100)
        if book.get("recursive_scanning") is not None:
            settings["recursion"] = bool(book.get("recursive_scanning"))
        if book.get("token_budget"):
            warnings.append("角色卡的 token 预算没有换算，这里按字数预算，用了默认的 1600 字")
    elif "entries" in source:
        name = str(source.get("name") or "").strip() or stem
        raw_entries = source.get("entries")
        convert = _from_st
        settings = {}
        jine = source.get("extensions", {}).get("jine") if isinstance(source.get("extensions"), dict) else None
        if isinstance(jine, dict) and isinstance(jine.get("settings"), dict):
            settings = jine["settings"]
        if isinstance(raw_entries, list) and raw_entries and isinstance(raw_entries[0], dict) and "keys" in raw_entries[0]:
            convert = _from_card  # 有人直接存了 character_book 本体
    else:
        raise BadImport("没认出这是酒馆世界书或角色卡")
    if isinstance(raw_entries, dict):
        raw_entries = [raw_entries[k] for k in sorted(raw_entries, key=lambda k: _num(k, 0))]
    if not isinstance(raw_entries, list):
        raise BadImport("世界书的 entries 格式不对")
    if len(raw_entries) > MAX_ENTRIES:
        warnings.append(f"条目超过 {MAX_ENTRIES} 条，只导入了前 {MAX_ENTRIES} 条")
        raw_entries = raw_entries[:MAX_ENTRIES]
    entries = []
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            warnings.append(f"第 {index + 1} 条不是条目，跳过了")
            continue
        cleaned = _clean(convert(raw, index, warnings), warnings)
        if cleaned is not None:
            entries.append(cleaned)
    try:
        book = Book.model_validate({"version": 2, "settings": settings, "entries": entries})
    except ValidationError:
        book = Book.model_validate({"version": 2, "entries": entries})
        warnings.append("书的设置不对，用了默认值")
    return name[:120], book, warnings


def _st_position(entry: Entry) -> int:
    original = entry.extensions.get("st_position")
    base = {"before_persona": 0, "after_persona": 1, "turn": 4}[entry.position]
    if isinstance(original, int):
        same = (original == 0 and base == 0) or (original in (1, 5, 6) and base == 1) or \
            (original in (2, 3, 4) and base == 4)
        if same:
            return original
    return base


def export(name: str, book: Book) -> dict:
    entries = {}
    for index, entry in enumerate(book.entries):
        ext = {k: v for k, v in entry.extensions.items() if k not in ("jine", "st_position")}
        unknown = ext.pop("st", None)
        unknown = {k: v for k, v in unknown.items() if k not in _ST_KNOWN} if isinstance(unknown, dict) else {}
        jine = {"position": entry.position, "logic": entry.logic, "lemma": entry.lemma,
                "semantic_threshold": entry.semantic_threshold,
                "conditions": [c.model_dump() for c in entry.conditions]}
        entries[str(index)] = {
            "uid": entry.uid - 1,
            "key": list(entry.keys),
            "keysecondary": list(entry.secondary_keys),
            "comment": entry.title,
            "content": entry.content,
            "constant": entry.constant,
            "vectorized": entry.semantic,
            "selective": bool(entry.secondary_keys),
            "selectiveLogic": _LOGIC_TO_ST[entry.logic],
            "order": entry.order,
            "position": _st_position(entry),
            "disable": not entry.enabled,
            "excludeRecursion": entry.exclude_recursion,
            "preventRecursion": entry.prevent_recursion,
            "delayUntilRecursion": entry.delay_until_recursion,
            "probability": entry.probability,
            "useProbability": entry.probability < 100,
            "group": entry.group,
            "groupOverride": entry.group_override,
            "groupWeight": entry.group_weight,
            "scanDepth": entry.scan_depth,
            "caseSensitive": entry.case_sensitive,
            "matchWholeWords": entry.whole_words,
            "automationId": entry.automation_id,
            "sticky": entry.sticky,
            "cooldown": entry.cooldown,
            "delay": entry.delay,
            "displayIndex": index,
            **unknown,
            "extensions": {**ext, "jine": jine},
        }
    return {"name": name, "entries": entries,
            "extensions": {"jine": {"version": 2, "settings": book.settings.model_dump()}}}

