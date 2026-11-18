"""Explicitly shared, loopback-only workspace state for a local MCP client."""
import asyncio
import secrets
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# Both ends must be loopback (security.local_request), not merely Origin == Host,
# so DNS rebinding cannot reach the bridge. The local MCP process sends no Origin
# header and passes; a browser page from another site cannot.
from ..security import local_request

router = APIRouter(prefix="/reader/bridge", tags=["reader-mcp"], dependencies=[Depends(local_request)])


@dataclass
class Bridge:
    token: str
    expires: float
    writable: bool
    pending: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)


active: Bridge | None = None


class ShareIn(BaseModel):
    writable: bool = False


class StateIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    id: str = Field(default="", max_length=800)
    title: str = Field(default="", max_length=320)
    page: int = Field(default=1, ge=1)
    total: int = Field(default=1, ge=1)
    selection: str = Field(default="", max_length=1400)


class ResultIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    command: str = Field(max_length=128)
    result: str = Field(max_length=5_500_000)


class CallIn(BaseModel):
    tool: Literal["read_pages", "capture_region", "list_annotations", "reply_annotation", "open_paper", "list_shelf"]
    args: dict = Field(default_factory=dict, max_length=6)


def session(token=None):
    if active is None or active.expires < monotonic():
        raise HTTPException(409, "请先在阅读器里打开「连接本机助手」")
    if token is not None and not secrets.compare_digest(token, active.token):
        raise HTTPException(409, "这个阅读窗口的共享已结束")
    return active


@router.post("/claim")
async def claim(body: ShareIn):
    global active
    if active and active.expires >= monotonic():
        raise HTTPException(409, "已有阅读窗口在共享，请先关闭旧窗口的共享")
    active = Bridge(secrets.token_urlsafe(24), monotonic() + 15, body.writable)
    return {"token": active.token}


@router.post("/poll")
async def poll(body: StateIn):
    bridge = session(body.token)
    bridge.expires = monotonic() + 15
    bridge.snapshot = body.model_dump(exclude={"token"})
    commands = []
    for ident, entry in bridge.pending.items():
        if not entry["taken"]:
            entry["taken"] = True
            commands.append({"id": ident, **entry["call"]})
    return {"commands": commands}


@router.post("/result")
async def result(body: ResultIn):
    bridge = session(body.token)
    entry = bridge.pending.get(body.command)
    if entry and not entry["future"].done():
        entry["future"].set_result(body.result)
    return {"ok": bool(entry)}


@router.post("/release")
async def release(body: StateIn):
    bridge = session(body.token)
    bridge.expires = 0
    for entry in bridge.pending.values():
        if not entry["future"].done():
            entry["future"].set_result('{"error":"共享已关闭"}')
    return {"ok": True}


@router.get("/state")
async def state():
    bridge = session()
    return {**bridge.snapshot, "writable": bridge.writable}


@router.post("/call")
async def call(body: CallIn):
    bridge = session()
    if body.tool == "reply_annotation" and not bridge.writable:
        raise HTTPException(403, "阅读器共享为只读")
    if len(bridge.pending) >= 5:
        raise HTTPException(429, "正在处理其他阅读请求")
    future = asyncio.get_running_loop().create_future()
    ident = secrets.token_urlsafe(16)
    bridge.pending[ident] = {
        "future": future, "taken": False,
        "call": {**body.model_dump(), "document": bridge.snapshot.get("id", "")},
    }
    try:
        return {"result": await asyncio.wait_for(future, 18)}
    except TimeoutError:
        raise HTTPException(504, "阅读器没有应答，请切回阅读窗口") from None
    finally:
        bridge.pending.pop(ident, None)
