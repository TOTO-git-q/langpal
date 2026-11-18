"""Bounded voice configuration helpers; no text-model credentials are used."""
import asyncio
import json
from contextlib import closing
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..db import get_conn
from ..services import character_voice, languages, listening_settings, listening_tts, voice_timbre, voicevox
from ..services.listening_formats import Line
from ..services.model_catalog import parse, CatalogError
from ..services.provider_urls import service_url
from ..security import local_request, same_origin

router = APIRouter(prefix='/voice-settings', tags=['voice-settings'], dependencies=[Depends(local_request)])
character_router = APIRouter(prefix='/voice', tags=['voice'], dependencies=[Depends(same_origin)])
_preview_lock = asyncio.Lock()


@character_router.get('/character')
def get_character_voice(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {'saved': character_voice.load(), 'defaults': character_voice.DEFAULTS,
            'voicevox': {'available': voicevox.available(), 'running': voicevox.running()}}


@character_router.put('/character')
def save_character_voice(body: character_voice.CharacterVoice, response: Response):
    character_voice.save(body)
    return get_character_voice(response)


@character_router.get('/voicevox/speakers')
def voicevox_speakers():
    if not voicevox.available():
        return []
    try:
        return voicevox.speakers()
    except (OSError, voicevox.Unavailable):
        raise HTTPException(502, '合成失败') from None


class CharacterPreview(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    text: str = Field(min_length=2, max_length=480)


class JapanesePreview(CharacterPreview):
    language: Literal['ja']
    voice: character_voice.JapaneseVoice


class EnglishPreview(CharacterPreview):
    language: Literal['en']
    voice: character_voice.EnglishVoice


def _character_preview(body: JapanesePreview | EnglishPreview) -> bytes:
    lines = [Line(speaker='A', text=body.text)]
    if isinstance(body, JapanesePreview):
        if not voicevox.available():
            raise HTTPException(503, '没有找到 VOICEVOX')
        return listening_tts.synthesize(character_voice.japanese_config(body.voice), 'ja', lines)
    config = character_voice.english_config(body.voice)
    if config is None:
        raise HTTPException(503, '合成失败')
    return voice_timbre.synthesize(config, 'en', lines, body.voice.model_dump())


@character_router.post('/preview')
async def character_preview(body: Annotated[JapanesePreview | EnglishPreview, Field(discriminator='language')]):
    if _preview_lock.locked():
        raise HTTPException(409, '合成失败')
    async with _preview_lock:
        task = asyncio.create_task(asyncio.to_thread(_character_preview, body))
        try:
            audio = await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, '合成失败') from None
    return Response(audio, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@router.get('/listening/models')
async def synthesis_models(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    settings, key = await asyncio.to_thread(listening_settings.load)
    if settings.provider != 'compatible' or not settings.base_url:
        raise HTTPException(409, '先保存语音接口。')
    return await _models(settings.base_url, key)


class SynthesisConnection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str = Field(min_length=1, max_length=300)
    api_key: SecretStr | None = Field(default=None, max_length=1024)

    @field_validator('base_url')
    @classmethod
    def normalize_base(cls, value):
        return service_url(value)


@router.post('/listening/models')
async def draft_synthesis_models(body: SynthesisConnection, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    settings, saved = await asyncio.to_thread(listening_settings.load)
    key = (body.api_key.get_secret_value().strip() if body.api_key is not None else
           saved if settings.base_url == body.base_url else '')
    if any(not 32 < ord(char) < 127 for char in key):
        raise HTTPException(422, '密钥格式无效。')
    return await _models(body.base_url, key)


async def _models(base_url, key):
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15) as client:
            async with client.stream('GET', base_url.rstrip('/') + '/models',
                                     headers={'Authorization': 'Bearer ' + key} if key else {}) as upstream:
                if upstream.status_code in (401, 403):
                    raise HTTPException(401, '语音接口鉴权失败。')
                if upstream.status_code in (404, 405):
                    raise HTTPException(409, '接口没有模型列表，可直接填写模型。')
                upstream.raise_for_status()
                raw = bytearray()
                async for chunk in upstream.aiter_bytes(16384):
                    raw.extend(chunk)
                    if len(raw) > 8_000_000:
                        raise ValueError()
        return {'models': parse(json.loads(raw))}
    except HTTPException:
        raise
    except (httpx.HTTPError, TimeoutError, ValueError, CatalogError):
        raise HTTPException(502, '暂时读不到模型列表。') from None


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    language: languages.LanguageTag
    speaker: str = Field(default='A', pattern='^[AB]$')
    text: str = Field(default='', max_length=180)


def _preview_voice(language):
    with closing(get_conn()) as conn:
        if language not in languages.registered(conn):
            raise HTTPException(422, '先添加这门语言。')
    settings, key = listening_settings.load()
    return listening_tts.configured_synthesis(language, settings, key)


@router.post('/listening/preview')
async def preview(body: Preview):
    config = await asyncio.to_thread(_preview_voice, body.language)
    if config is None:
        raise HTTPException(409, '先保存这门语言的音色。')
    text = body.text or {'en': 'A little practice, one conversation at a time.', 'ja': '今日は、どんなことを話しましょうか。'}.get(body.language)
    if not text:
        raise HTTPException(422, '写一句试音文本。')
    if _preview_lock.locked():
        raise HTTPException(409, '上一段还在生成。')
    async with _preview_lock:
        task = asyncio.create_task(asyncio.to_thread(listening_tts.synthesize, config, body.language,
                                                     [Line(speaker=body.speaker, text=text)]))
        try:
            audio = await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
        except Exception:
            raise HTTPException(502, '试音失败，请检查模型和音色。') from None
    return Response(audio, media_type='audio/wav', headers={'Cache-Control': 'no-store'})
