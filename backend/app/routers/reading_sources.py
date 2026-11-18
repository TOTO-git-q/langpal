"""Reader source registry: one list for built-in and custom sources.

Reading is same-origin. Changing or testing sources needs a local request (or a
same-origin one when LANGPAL_READER_REMOTE_ADMIN=1). Turning on "allow private
network" for a source, or fetching such a source, always needs a local request.
"""
import asyncio
import json
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from ..security import local_request, same_origin
from ..services import languages, reading_sources as sources

router = APIRouter(prefix="/reader/sources", tags=["reader-sources"], dependencies=[Depends(same_origin)])


def _admin(request: Request):
    if os.environ.get("LANGPAL_READER_REMOTE_ADMIN") == "1":
        same_origin(request)
    else:
        local_request(request)


def private_fetch_allowed(request: Request) -> bool:
    """Only a request from this computer may reach private-network sources."""
    try:
        local_request(request)
    except HTTPException:
        return False
    return True


async def _body(request):
    # Parse here so malformed config responses can never echo an API key.
    data = bytearray()
    async for block in request.stream():
        data.extend(block)
        if len(data) > 65_536:
            raise HTTPException(413, "来源配置过大")
    try:
        body = json.loads(data) if data else {}
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "来源配置须为 JSON 对象") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "来源配置须为 JSON 对象")
    return body


def _manage(action, *args, **options):
    try:
        return action(*args, **options)
    except KeyError:
        raise HTTPException(404, "找不到该来源") from None
    except sources.SourceError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("")
def list_sources(kind: Literal["article", "paper"] | None = None, lang: languages.LanguageTag | None = None):
    return {"items": sources.list_sources(kind, lang)}


@router.post("", status_code=201, dependencies=[Depends(_admin)])
async def create_source(request: Request):
    body = await _body(request)
    return await asyncio.to_thread(_manage, sources.create_source, body, trusted=private_fetch_allowed(request))


@router.put("/order", dependencies=[Depends(_admin)])
async def reorder_sources(request: Request):
    ids = (await _body(request)).get("ids")
    if not isinstance(ids, list) or len(ids) > 30 or any(not isinstance(item, str) or len(item) > 80 for item in ids):
        raise HTTPException(422, "来源排序须提供有效的来源列表")
    return {"items": await asyncio.to_thread(_manage, sources.reorder_sources, ids)}


@router.patch("/{source_id}", dependencies=[Depends(_admin)])
async def edit_source(source_id: str, request: Request):
    body = await _body(request)
    return await asyncio.to_thread(_manage, sources.edit_source, source_id, body, trusted=private_fetch_allowed(request))


@router.delete("/{source_id}", dependencies=[Depends(_admin)])
def delete_source(source_id: str):
    _manage(sources.delete_source, source_id)
    return {"ok": True}


async def _test(source_id, body, trusted):
    query = body.pop("query", "")
    if not isinstance(query, str) or len(query) > 300:
        raise HTTPException(422, "测试检索词过长或格式不符")
    config = body.pop("source", body)
    if not isinstance(config, dict):
        raise HTTPException(422, "来源配置须为 JSON 对象")
    try:
        return await sources.test_source(source_id, config, query, trusted=trusted)
    except KeyError:
        raise HTTPException(404, "找不到该来源") from None
    except sources.SourceError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/test", dependencies=[Depends(_admin)])
async def test_draft(request: Request):
    """Try a configuration that has not been saved (or a saved one, by `id`)."""
    body = await _body(request)
    source_id = body.pop("id", None)
    if source_id is not None and (not isinstance(source_id, str) or len(source_id) > 80):
        raise HTTPException(422, "来源编号无效")
    return await _test(source_id, body, private_fetch_allowed(request))


@router.post("/{source_id}/test", dependencies=[Depends(_admin)])
async def test_saved(source_id: str, request: Request):
    return await _test(source_id, await _body(request), private_fetch_allowed(request))
