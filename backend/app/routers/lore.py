"""世界书接口（docs/LORE-AND-HOOKS.md 1.6）。书挂到联系人上仍然走人设资料的 world_book_ids。"""
from __future__ import annotations

import json
from contextlib import closing
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from ..db import get_conn
from ..security import same_origin
from ..services import chat_room, lore
from ..services.hooks import queue as hook_queue
from ..services.lore import store, transfer
from ..services.lore import state as lore_state

router = APIRouter(prefix="/lore", tags=["lore"], dependencies=[Depends(same_origin)])

Name = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]


class BookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    scope: Literal["global", "attached"] = "attached"
    enabled: bool = True
    book: lore.Book = Field(default_factory=lore.Book)


class BookPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    scope: Literal["global", "attached"] | None = None
    enabled: bool | None = None
    book: lore.Book | None = None


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: int = Field(ge=1)
    text: str = Field("", max_length=4000)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ValidationError):
        issue = error.errors(include_input=False)[0]
        return HTTPException(422, f"世界书有字段不对：{'.'.join(map(str, issue['loc']))} {issue['msg']}")
    return HTTPException(422, str(error))


@router.get("/books")
def list_books():
    with closing(get_conn()) as conn:
        return {"items": store.list_books(conn)}


@router.get("/books/{book_id}")
def get_book(book_id: int):
    with closing(get_conn()) as conn:
        loaded = store.get_book(conn, book_id)
    if loaded is None:
        raise HTTPException(404, "这本世界书不存在")
    return store.view(loaded)


@router.post("/books", status_code=201)
def create_book(body: BookCreate):
    try:
        with closing(get_conn()) as conn, conn:
            saved = store.save_book(conn, body.name, body.book, scope=body.scope, enabled=body.enabled)
            store.warm_soon(conn, [saved])
            return store.view(saved)
    except ValueError as error:
        raise _error(error) from None


@router.put("/books/{book_id}")
def update_book(book_id: int, body: BookPatch):
    with closing(get_conn()) as conn, conn:
        current = store.get_book(conn, book_id)
        if current is None:
            raise HTTPException(404, "这本世界书不存在")
        saved = store.save_book(conn, body.name or current.name,
                                body.book if body.book is not None else current.book, book_id,
                                scope=body.scope, enabled=body.enabled)
        if body.book is not None:
            store.warm_soon(conn, [saved])
        return store.view(saved)


@router.delete("/books/{book_id}")
def delete_book(book_id: int):
    with closing(get_conn()) as conn, conn:
        if not store.delete_book(conn, book_id):
            raise HTTPException(404, "这本世界书不存在")
    return {"ok": True}


@router.post("/import", status_code=201)
async def import_book(file: UploadFile = File(...)):
    data = await file.read(transfer.MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(400, "空文件")
    try:
        name, book, warnings = transfer.parse_upload(data, file.filename or "")
    except transfer.BadImport as error:
        raise HTTPException(422, str(error)) from None
    try:
        with closing(get_conn()) as conn, conn:
            saved = store.save_book(conn, name, book)
            store.warm_soon(conn, [saved])
    except ValueError as error:
        raise _error(error) from None
    return {"id": saved.id, "name": saved.name, "entry_count": len(saved.book.entries), "warnings": warnings}


@router.get("/books/{book_id}/export")
def export_book(book_id: int):
    with closing(get_conn()) as conn:
        loaded = store.get_book(conn, book_id)
    if loaded is None:
        raise HTTPException(404, "这本世界书不存在")
    body = json.dumps(transfer.export(loaded.name, loaded.book), ensure_ascii=False, indent=2)
    filename = quote(f"{loaded.name}.json")
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.post("/test")
def test_trigger(body: TestIn):
    """试触发：按这个联系人当前的对话算一遍"如果现在发这句话"，不写任何状态、不调模型。"""
    with closing(get_conn()) as conn:
        persona = conn.execute("SELECT * FROM personas WHERE id = ? AND archived_at IS NULL",
                               (body.persona_id,)).fetchone()
        if persona is None:
            raise HTTPException(404, "没有这个联系人")
        persona = dict(persona)
        sid = chat_room.main_session_id(conn)  # 试触发按主聊天算
        effects = hook_queue.turn_effects(conn, body.persona_id)
        result = lore.evaluate_turn(conn, persona, sid, lore_state.current_turn(conn, sid, body.persona_id) + 1, body.text,
                                    effects=lore.Effects(forced=effects.forced, suppressed=effects.suppressed))
    system = result.system or lore.SystemLore()
    return {"activated": result.activated, "skipped": result.skipped, "turn_preview": result.block,
            "system_preview": "\n\n".join(part for part in (system.before, system.after) if part)}
