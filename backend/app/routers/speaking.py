"""Read the lesson history of the speaking service configured in JINE."""
import asyncio
import json
from contextlib import closing
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..db import get_conn
from ..services.coach_bridge import coach_service
from ..services.coach_bridge import DEFAULT_SERVICE_URL
from ..security import local_request

router = APIRouter(prefix="/speaking", tags=["speaking"], dependencies=[Depends(local_request)])


def _managed_url():
    with closing(get_conn()) as conn:
        if coach_service(conn) != DEFAULT_SERVICE_URL:
            raise HTTPException(409, '当前口语连接由外部服务管理。')
    return DEFAULT_SERVICE_URL


def _service_url():
    with closing(get_conn()) as conn:
        return coach_service(conn)


async def _configuration(method, path, body=None):
    url = await asyncio.to_thread(_managed_url)
    try:
        async with asyncio.timeout(22), httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=20) as client:
            async with client.stream(method, url + path, json=body if method != 'GET' else None) as upstream:
                raw = bytearray()
                async for chunk in upstream.aiter_bytes(16384):
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError()
                if upstream.status_code >= 400:
                    message = '口语服务暂未支持这项设置。' if upstream.status_code == 404 else '口语连接未完成，请检查密钥、地址和模型。'
                    raise HTTPException(409 if upstream.status_code == 404 else 422, message)
                upstream.raise_for_status()
                return json.loads(raw)
    except HTTPException:
        raise
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise HTTPException(502, '口语服务暂时不可用。') from None


@router.get('/settings')
async def speaking_settings(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    result = await _configuration('GET', '/api/settings')
    if not isinstance(result, dict) or not isinstance(result.get('settings'), dict):
        raise HTTPException(502, '口语设置格式有误。')
    return {key: result.get(key) for key in ('settings', 'keyConfigured', 'mock')}


class SettingsWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    settings: dict


@router.put('/settings')
async def update_settings(body: SettingsWrite, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if len(json.dumps(body.settings)) > 32000:
        raise HTTPException(422, '设置内容过长。')
    await _configuration('PUT', '/api/settings', body.settings)
    return await speaking_settings(response)


@router.get('/connection')
async def connection(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    result = await _configuration('GET', '/api/connection')
    if not isinstance(result, dict):
        raise HTTPException(502, '口语连接格式有误。')
    return result


class ConnectionWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['openai', 'compatible'] = 'openai'
    baseUrl: str = Field(min_length=1, max_length=300)
    textProvider: Literal['jine', 'voice_api'] = 'jine'
    realtime: dict = Field(default_factory=dict)
    apiKey: SecretStr | None = Field(default=None, max_length=1024)
    clearKey: bool = False


@router.put('/connection')
async def update_connection(body: ConnectionWrite, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    data = body.model_dump(exclude_none=True, exclude={'apiKey'})
    if body.apiKey is not None:
        data['apiKey'] = body.apiKey.get_secret_value()
    return await _configuration('PUT', '/api/connection', data)


class SetupWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    settings: dict
    connection: ConnectionWrite


@router.put('/setup')
async def setup(body: SetupWrite, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if len(json.dumps(body.settings)) > 32000:
        raise HTTPException(422, '设置内容过长。')
    connection = body.connection.model_dump(exclude_none=True, exclude={'apiKey'})
    if body.connection.apiKey is not None:
        connection['apiKey'] = body.connection.apiKey.get_secret_value()
    return await _configuration('PUT', '/api/setup', {'settings': body.settings, 'connection': connection})


@router.get('/models')
async def models(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return await _configuration('GET', '/api/models')


@router.post('/models')
async def connect_models(body: ConnectionWrite, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    data = body.model_dump(exclude_none=True, exclude={'apiKey'})
    if body.apiKey is not None:
        data['apiKey'] = body.apiKey.get_secret_value()
    return await _configuration('POST', '/api/connection/models', data)


class Authoring(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['LessonCard', 'LessonReport', 'HomeworkCheck', 'PlacementResult']
    prompt: str = Field(min_length=1, max_length=150000)
    schema_: dict = Field(alias='schema')


@router.post('/authoring')
async def authoring(body: Authoring, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    def refs(value):
        if isinstance(value, dict):
            if '$ref' in value and (not isinstance(value['$ref'], str) or not value['$ref'].startswith('#/')):
                raise ValueError()
            for item in value.values():
                refs(item)
        elif isinstance(value, list):
            for item in value:
                refs(item)
    try:
        from jsonschema import Draft202012Validator
        if len(json.dumps(body.schema_)) > 100000:
            raise ValueError()
        refs(body.schema_)
        Draft202012Validator.check_schema(body.schema_)
    except Exception:
        raise HTTPException(422, '课程结构无效。') from None
    from ..providers.registry import get_feature_provider
    try:
        result = await asyncio.wait_for(get_feature_provider('chat').generate_json(body.prompt, body.schema_), timeout=105)
        Draft202012Validator(body.schema_).validate(result)
    except Exception:
        raise HTTPException(503, '主模型暂时不能完成出题。') from None
    return {'value': result}


async def _read(path: str):
    url = await asyncio.to_thread(_service_url)
    try:
        async with asyncio.timeout(8), httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", f"{url}{path}", headers={"Accept": "application/json"}) as upstream:
                if upstream.status_code == 404:
                    raise HTTPException(404, "口语服务没有返回这份记录")
                upstream.raise_for_status()
                data = bytearray()
                async for chunk in upstream.aiter_bytes(chunk_size=16_384):
                    data.extend(chunk)
                    if len(data) > 5_000_000:
                        raise ValueError("Lesson response too large")
                return json.loads(data)
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise HTTPException(502, "暂时读不到口语记录") from None


@router.get("/lessons")
async def lessons(response: Response):
    response.headers["Cache-Control"] = "no-store"
    items = await _read("/api/lessons")
    if not isinstance(items, list):
        raise HTTPException(502, "口语服务没有返回课时列表")
    fields = ("id", "lang", "createdAt", "status", "kind")
    return [{key: item.get(key) for key in fields} for item in items if isinstance(item, dict)]


@router.get("/lessons/{lesson_id}")
async def lesson(lesson_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,80}$")], response: Response):
    response.headers["Cache-Control"] = "no-store"
    result = await _read(f"/api/lessons/{lesson_id}")
    if not isinstance(result, dict):
        raise HTTPException(502, "口语服务没有返回课时内容")
    card = result.get("card")
    return {
        "title": card.get("unit") if isinstance(card, dict) else None,
        "report": result.get("report") or result.get("placement"),
        "transcript": result.get("transcript"),
    }


# 口语课的本机识别服务（3211）。识别模型约 1.6 GB，没下过时要人点了才下；这里转一下它的状态和「下载」。
ASR_URL = "http://127.0.0.1:3211"


def _asr(data):
    if not isinstance(data, dict):
        return {"running": False}
    number = lambda value: value if isinstance(value, int) and value >= 0 else None
    return {"running": True, "ready": bool(data.get("ready")), "missing": bool(data.get("missing")),
            "downloading": bool(data.get("downloading")), "downloaded": number(data.get("downloaded_bytes")),
            "total": number(data.get("total_bytes")), "failed": bool(data.get("error")) and not data.get("ready")}


async def _asr_call(method: str, path: str):
    try:
        async with asyncio.timeout(6), httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=5) as client:
            reply = await client.request(method, ASR_URL + path)
            reply.raise_for_status()
            return _asr(reply.json())
    except (httpx.HTTPError, TimeoutError, ValueError):
        return {"running": False}


@router.get("/asr")
async def asr_status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await _asr_call("GET", "/health")


@router.post("/asr/download")
async def asr_download():
    return await _asr_call("POST", "/download")
