"""world_books 表的读写、挂接关系、旧数据迁移。所有函数都收调用方开好的连接。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from .model import MAX_BOOKS, Book, compact, is_v1

logger = logging.getLogger(__name__)

MAX_ATTACHED = 12
INLINE_BOOK_ID = 0  # 人设资料里内嵌的旧世界书（还没迁成共享书时）在状态表里用 0 号


@dataclass(frozen=True)
class LoadedBook:
    id: int
    name: str
    scope: str
    enabled: bool
    book: Book


# book_id -> (原始 json, 解析好的 Book)。每轮都要读书，解析一次缓存住，json 变了才重解析。
_parsed: dict[int, tuple[str, Book]] = {}


def parse(raw: str, book_id: int | None = None) -> Book:
    if book_id is not None:
        hit = _parsed.get(book_id)
        if hit is not None and hit[0] == raw:
            return hit[1]
    book = Book.model_validate_json(raw)
    if book_id is not None:
        _parsed[book_id] = (raw, book)
    return book


def _profile(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _row_book(row) -> LoadedBook | None:
    try:
        book = parse(row["book_json"], row["id"])
    except (ValidationError, ValueError):
        logger.warning("世界书 %s 解析失败，这本书先不生效", row["id"], exc_info=True)
        return None
    return LoadedBook(row["id"], row["name"], row["scope"] or "attached", bool(row["enabled"]), book)


def attached_persona_ids(conn) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for row in conn.execute("SELECT id, profile_json FROM personas WHERE archived_at IS NULL ORDER BY id"):
        ids = _profile(row["profile_json"]).get("world_book_ids")
        if isinstance(ids, list):
            for book_id in ids:
                if isinstance(book_id, int):
                    result.setdefault(book_id, []).append(row["id"])
    return result


def list_books(conn) -> list[dict]:
    attached = attached_persona_ids(conn)
    items = []
    for row in conn.execute("SELECT id, name, book_json, scope, enabled FROM world_books ORDER BY id"):
        loaded = _row_book(row)
        items.append({"id": row["id"], "name": row["name"], "scope": row["scope"] or "attached",
                      "enabled": bool(row["enabled"]),
                      "entry_count": len(loaded.book.entries) if loaded else 0,
                      "attached_persona_ids": attached.get(row["id"], []),
                      **({} if loaded else {"broken": True})})
    return items


def get_book(conn, book_id: int) -> LoadedBook | None:
    row = conn.execute("SELECT id, name, book_json, scope, enabled FROM world_books WHERE id = ?",
                       (book_id,)).fetchone()
    return _row_book(row) if row else None


def view(loaded: LoadedBook) -> dict:
    return {"id": loaded.id, "name": loaded.name, "scope": loaded.scope, "enabled": loaded.enabled,
            "book": loaded.book.model_dump()}


def save_book(conn, name: str, book: Book, book_id: int | None = None, *, scope: str | None = None,
              enabled: bool | None = None) -> LoadedBook:
    raw = book.model_dump_json()
    if book_id is None:
        if conn.execute("SELECT count(*) FROM world_books").fetchone()[0] >= MAX_BOOKS:
            raise ValueError(f"世界书最多 {MAX_BOOKS} 本")
        book_id = conn.execute(
            "INSERT INTO world_books (name, book_json, scope, enabled) VALUES (?, ?, ?, ?)",
            (name, raw, scope or "attached", 1 if enabled is None else int(enabled))).lastrowid
    else:
        sets, args = ["name = ?", "book_json = ?"], [name, raw]
        if scope is not None:
            sets.append("scope = ?")
            args.append(scope)
        if enabled is not None:
            sets.append("enabled = ?")
            args.append(int(enabled))
        if not conn.execute(f"UPDATE world_books SET {', '.join(sets)} WHERE id = ?", (*args, book_id)).rowcount:
            raise LookupError("这本世界书已不存在")
    return get_book(conn, book_id)


def insert_with_id(conn, book_id: int, name: str, book: Book) -> None:
    """课程管家撤销/应用用：按预先分好的 id 新建。"""
    conn.execute("INSERT INTO world_books (id, name, book_json) VALUES (?, ?, ?)",
                 (book_id, name, book.model_dump_json()))


def delete_book(conn, book_id: int) -> bool:
    if not conn.execute("DELETE FROM world_books WHERE id = ?", (book_id,)).rowcount:
        return False
    for row in conn.execute("SELECT id, profile_json FROM personas").fetchall():
        profile = _profile(row["profile_json"])
        ids = profile.get("world_book_ids")
        if isinstance(ids, list) and book_id in ids:
            profile["world_book_ids"] = [i for i in ids if i != book_id]
            conn.execute("UPDATE personas SET profile_json = ? WHERE id = ?",
                         (json.dumps(profile, ensure_ascii=False), row["id"]))
    conn.execute("DELETE FROM lore_state WHERE book_id = ?", (book_id,))
    _parsed.pop(book_id, None)
    return True


def books_for(conn, persona: dict) -> list[LoadedBook]:
    """这个联系人这一轮生效的书：启用的全局书 + 启用的、挂在它身上的书（按挂接顺序）。"""
    profile = _profile(persona.get("profile_json"))
    attached = profile.get("world_book_ids")
    attached = [i for i in attached if isinstance(i, int)] if isinstance(attached, list) else []
    rows = conn.execute("SELECT id, name, book_json, scope, enabled FROM world_books WHERE enabled = 1 "
                        "ORDER BY id").fetchall()
    by_id = {row["id"]: row for row in rows}
    picked = [row for row in rows if (row["scope"] or "attached") == "global"]
    seen = {row["id"] for row in picked}
    for i in attached:
        if i in by_id and i not in seen:
            picked.append(by_id[i])
            seen.add(i)
    books = [b for b in (_row_book(row) for row in picked) if b is not None]
    if "world_book_ids" not in profile and isinstance(profile.get("world_book"), dict):
        try:
            books.append(LoadedBook(INLINE_BOOK_ID, f"{persona.get('name', '')} 的世界书", "attached", True,
                                    Book.model_validate(profile["world_book"])))
        except (ValidationError, ValueError):
            pass
    return books


def warm_soon(conn, books: list[LoadedBook] | None = None) -> None:
    """后台把关键词的原形先算好（顺带把分词器加载起来），第一轮聊天就不用现分。不碰数据库。"""
    import threading

    from . import match
    languages = sorted({row[0] for row in conn.execute(
        "SELECT DISTINCT language FROM personas WHERE archived_at IS NULL")})
    if books is None:
        books = [b for b in (_row_book(r) for r in conn.execute(
            "SELECT id, name, book_json, scope, enabled FROM world_books WHERE enabled = 1")) if b]
    keys = [k for lb in books for e in lb.book.entries if e.enabled and (e.lemma is not False)
            for k in (*e.keys, *e.secondary_keys)]
    if not keys or not languages:
        return

    def work():
        try:
            for language in languages:
                match.warm(keys, language)
        except Exception:
            logger.debug("世界书关键词预热失败（不影响使用）", exc_info=True)

    threading.Thread(target=work, name="lore-warm", daemon=True).start()


def validate_profile(profile: dict, conn=None) -> dict:
    """人设资料里和世界书有关的两个键：内嵌的旧 world_book、挂接的 world_book_ids。"""
    result = dict(profile)
    if "voice_samples" in profile:  # 主聊天的口吻样本（docs/MAIN-CHAT.md 2.1）也在这里一起校验
        from ..chat_room import validate_voice_samples
        result["voice_samples"] = validate_voice_samples(profile["voice_samples"])
    if "world_book" in profile:
        result["world_book"] = Book.model_validate(profile["world_book"]).model_dump()
    if "world_book_ids" in profile:
        ids = profile["world_book_ids"]
        if (not isinstance(ids, list) or len(ids) > MAX_ATTACHED or any(type(i) is not int or i < 1 for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError(f"角色最多可挂接 {MAX_ATTACHED} 本不同的世界书")
        if conn is not None and ids and not set(ids).issubset(r[0] for r in conn.execute("SELECT id FROM world_books")):
            raise ValueError("有一本世界书已不存在")
    return result


def world_books(conn) -> list[dict]:
    """课程管家看的形状：{id, name, book}，book 只留非默认字段。"""
    result = []
    for row in conn.execute("SELECT id, name, book_json, scope, enabled FROM world_books ORDER BY id"):
        loaded = _row_book(row)
        if loaded is not None:
            result.append({"id": loaded.id, "name": loaded.name, "book": compact(loaded.book)})
    return result


def migrate_legacy(conn) -> None:
    """启动时：version 1 的书原地升级；人设里内嵌的旧书拆成一本共享书挂回去。幂等。"""
    for row in conn.execute("SELECT id, book_json FROM world_books").fetchall():
        try:
            data = json.loads(row["book_json"])
        except (TypeError, ValueError):
            continue
        if is_v1(data):
            try:
                book = Book.model_validate(data)
            except (ValidationError, ValueError):
                logger.warning("世界书 %s 升级失败，原样保留", row["id"], exc_info=True)
                continue
            conn.execute("UPDATE world_books SET book_json = ? WHERE id = ?", (book.model_dump_json(), row["id"]))
    for row in conn.execute("SELECT id, name, profile_json FROM personas").fetchall():
        profile = _profile(row["profile_json"])
        if "world_book_ids" in profile or "world_book" not in profile:
            continue
        try:
            book = Book.model_validate(profile["world_book"])
        except (ValidationError, ValueError):
            continue
        if not book.entries:
            continue
        saved = save_book(conn, f"{row['name'][:110]} 的世界书", book)
        profile["world_book_ids"] = [saved.id]
        conn.execute("UPDATE personas SET profile_json = ? WHERE id = ?",
                     (json.dumps(profile, ensure_ascii=False), row["id"]))
