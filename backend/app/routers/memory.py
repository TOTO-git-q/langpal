"""记忆路由：条目查看 / 编辑 / 删除（设定屏用）。
M0=内存 mock。WP-D 改为 SQLite 真实现。
"""
from contextlib import closing
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..db import get_conn
from ..security import same_origin

router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(same_origin)])


class MemoryPatch(BaseModel):
    content: str | None = None
    category: str | None = None
    active: bool | None = None


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    persona_id: int = Field(gt=0)
    category: Literal['fact', 'preference', 'event', 'promise'] = 'fact'
    content: str = Field(min_length=1, max_length=4000)
    active: bool = True


def row_to_dict(row):
    """将 sqlite3.Row 转为 dict，并转换 active 整数为 bool"""
    if row is None:
        return None
    d = dict(row)
    if "active" in d and d["active"] is not None:
        d["active"] = bool(d["active"])
    return d


@router.get("")
async def list_memory(persona_id: int | None = None):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        if persona_id is None:
            cursor.execute("SELECT * FROM memory_items")
        else:
            cursor.execute("SELECT * FROM memory_items WHERE persona_id = ?", (persona_id,))
        rows = cursor.fetchall()
        items = [row_to_dict(row) for row in rows]
        return {"items": items}
    finally:
        conn.close()


@router.post('', status_code=201, dependencies=[Depends(same_origin)])
async def create_memory(body: MemoryCreate):
    with closing(get_conn()) as conn, conn:
        persona = conn.execute('SELECT id FROM personas WHERE id=? AND archived_at IS NULL', (body.persona_id,)).fetchone()
        if persona is None:
            raise HTTPException(404, '找不到这个角色。')
        cursor = conn.execute('INSERT INTO memory_items(persona_id,category,content,active) VALUES(?,?,?,?)',
                              (body.persona_id, body.category, body.content, int(body.active)))
        return row_to_dict(conn.execute('SELECT * FROM memory_items WHERE id=?', (cursor.lastrowid,)).fetchone())


@router.put("/{item_id}")
async def update_memory(item_id: int, body: MemoryPatch):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # 先查找是否存在
        cursor.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,))
        existing = cursor.fetchone()
        if existing is None:
            raise HTTPException(404, "not found")

        # 部分更新
        updates = {}
        if body.content is not None:
            updates["content"] = body.content
        if body.category is not None:
            updates["category"] = body.category
        if body.active is not None:
            updates["active"] = int(body.active)

        if updates:
            # 始终更新 updated_at
            updates["updated_at"] = "datetime('now', 'localtime')"
            set_clause = ", ".join([f"{k} = ?" if k != "updated_at" else f"{k} = datetime('now', 'localtime')" for k in updates.keys()])
            values = [v for k, v in updates.items() if k != "updated_at"]
            values.append(item_id)
            cursor.execute(f"UPDATE memory_items SET {set_clause} WHERE id = ?", values)
            conn.commit()

        # 返回更新后的条目
        cursor.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,))
        updated = cursor.fetchone()
        return row_to_dict(updated)
    finally:
        conn.close()


@router.delete("/{item_id}")
async def delete_memory(item_id: int):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "not found")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
