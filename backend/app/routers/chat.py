"""聊天路由（docs/MAIN-CHAT.md 第四节）：一条主聊天。

真实链路在 services/chat.py；这层只管把 (event, data) 编码成 SSE，和主聊天的设置、消息、旧对话读写。

SSE（POST /chat、POST /chat/proactive）：
    queued                                   —— 本条消息被并进攒批，流立即结束
  | read -> speaker{role:lead} -> guard -> (delta* -> bubble_done)×N -> action*
      [-> speaker{role:chime} -> guard -> (delta* -> bubble_done)] -> done
  | ……中途被打断 -> interrupted（代替 done）
  | error（任何阶段异常）
主动消息多一个可能的开头 system{kind:"enter"}（副人设进场），没有 read；每个事件带 proactive:true。
每个事件带 session_id、persona_id、persona_name、language。
"""
import asyncio
import dataclasses
import json
import re
import unicodedata
import uuid
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import image_utils
from ..db import UPLOAD_DIR, get_conn
from ..security import same_origin
from ..services import chat as chat_service, chat_room, hooks, languages

router = APIRouter(tags=["chat"])

# 聊天图片上传，8MB 上限（头像走 config.py 独立的 3MB 上限，两处场景不同）。
_UPLOAD_MAX_BYTES = 8 * 1024 * 1024


class SceneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tab: str = Field(min_length=1, max_length=32)
    title: str | None = Field(None, max_length=120)
    language: str | None = Field(None, max_length=16)
    text: str = Field("", max_length=8000)
    actions: list[Annotated[str, Field(max_length=160)]] = Field(default_factory=list, max_length=3)


class ChatIn(BaseModel):
    text: str = Field("", max_length=8000)  # 带图 / 贴图的消息允许配文为空
    image_url: str | None = None  # POST /api/uploads/image 返回的 url（也接受裸文件名）
    sticker: Annotated[str, Field(min_length=1, max_length=80)] | None = None  # 贴图 id（GET /api/stickers）
    to: int | None = Field(None, ge=1)  # 点名的人设 id
    via: Literal["stage"] | None = None
    scene: SceneIn | None = None


class ProactiveIn(BaseModel):
    persona_id: int | None = Field(None, ge=1)


@router.post("/uploads/image", dependencies=[Depends(same_origin)])
async def upload_chat_image(file: UploadFile = File(...)):
    """聊天图片上传（multipart，字段名 file）。魔数嗅探真实类型、落盘 data/uploads/{uuid4hex}.{ext}，
    返回 {url, width, height}（宽高解析不出就是 null）。"""
    data = await file.read(_UPLOAD_MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > _UPLOAD_MAX_BYTES:
        raise HTTPException(413, "图片太大（上限 8MB）")
    ext = image_utils.sniff_image_ext(data)
    if ext is None:
        raise HTTPException(415, "只支持 PNG / JPEG / GIF / WebP 图片")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / filename).write_bytes(data)
    dims = image_utils.sniff_image_dimensions(data, ext)
    width, height = dims if dims is not None else (None, None)
    return {"url": f"/uploads/{filename}", "width": width, "height": height}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat", dependencies=[Depends(same_origin)])
async def chat(body: ChatIn):
    async def gen():
        try:
            async for event, data in chat_service.run_chat_turn(
                    body.text, body.image_url, body.sticker, body.to, via=body.via,
                    scene=body.scene.model_dump() if body.scene is not None else None):
                yield _sse(event, data)
        except Exception as e:  # services.chat 内部已经兜了一层，这里是最后一道保险
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat/proactive", dependencies=[Depends(same_origin)])
async def proactive(body: ProactiveIn | None = Body(None)):
    """她主动开口：取最早的一条待发（或指定人设的），没有待发 / 正在回复用户时 done {empty:true}。"""
    persona_id = body.persona_id if body else None

    async def gen():
        try:
            async for event, data in chat_service.run_proactive_turn(persona_id):
                yield _sse(event, data)
        except Exception as e:
            yield _sse("error", {"message": str(e), "proactive": True})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat/main/warm", status_code=202, dependencies=[Depends(same_origin)])
async def warm_main():
    """预热主人设的第一轮（回忆模型、世界书关键词、常驻客户端），立即返回，活在后台做。
    重复调用：正在做就是 running；5 分钟内同样的东西做过，后台直接跳过。"""
    return {"status": chat_service.warm_main()}


@router.on_event("startup")
async def _warm_after_startup():
    """后端启动完成后，距离上次用户消息不到 12 小时就自动预热一次（延后几秒，不挡启动）。"""
    import asyncio
    asyncio.get_running_loop().create_task(chat_service.warm_on_startup())


def _main_view(conn) -> dict:
    config = chat_room.settings(conn)
    sid = chat_room.main_session_id(conn)
    return {**config.model_dump(), "session_id": sid,
            "present_guest_ids": chat_room.present_guest_ids(conn, config, sid=sid),
            "languages": [{"tag": tag, "label": label} for tag, label in languages.registered(conn).items()],
            "pending": sum(item["count"] for item in hooks.queue.pending(conn))}


@router.get("/chat/main", dependencies=[Depends(same_origin)])
def get_main():
    with closing(get_conn()) as conn, conn:
        return _main_view(conn)


@router.put("/chat/main", dependencies=[Depends(same_origin)])
def put_main(patch: dict = Body(...)):
    allowed = set(chat_room.MainSettings.model_fields)
    unknown = set(patch) - allowed
    if unknown:
        raise HTTPException(422, "不认识的设置：" + "、".join(sorted(unknown)))
    try:
        with closing(get_conn()) as conn, conn:
            chat_room.save(conn, patch)
            return _main_view(conn)
    except ValidationError as error:
        issue = error.errors(include_input=False)[0]
        raise HTTPException(422, f"主聊天设置不对：{'.'.join(map(str, issue['loc']))} {issue['msg']}") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/chat/main/new", dependencies=[Depends(same_origin)])
async def new_main():
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        sid = chat_room.main_session_id(conn)
        state = chat_service._session_states.get(f"s{sid}")
        if state is not None and chat_service._busy(state):
            raise HTTPException(409)
        try:
            chat_room.new_main(conn)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return _main_view(conn)


@router.delete("/chat/archives/{session_id}", dependencies=[Depends(same_origin)])
def delete_archive(session_id: int):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not chat_room.delete_archive(conn, session_id):
            raise HTTPException(404, "没有这段旧对话")
    return {"deleted": session_id}


@router.get("/chat/main/messages", dependencies=[Depends(same_origin)])
def main_messages(before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=200)):
    with closing(get_conn()) as conn, conn:
        sid = chat_room.main_session_id(conn)
        return {"session_id": sid, "items": chat_room.messages(conn, sid, before=before, limit=limit) if sid else []}


@router.get("/chat/archives", dependencies=[Depends(same_origin)])
def archives():
    with closing(get_conn()) as conn, conn:
        return {"items": chat_room.archives(conn)}


@router.get("/chat/archives/{session_id}", dependencies=[Depends(same_origin)])
def archive(session_id: int, before: int | None = Query(None, ge=1), limit: int = Query(200, ge=1, le=500)):
    with closing(get_conn()) as conn, conn:
        row = next((a for a in chat_room.archives(conn) if a["session_id"] == session_id), None)
        if row is None:
            raise HTTPException(404, "没有这段旧对话")
        return {**row, "read_only": True,
                "items": chat_room.messages(conn, session_id, before=before, limit=limit)}


@router.get("/stickers", dependencies=[Depends(same_origin)])
def stickers():
    from ..services import prompts
    return {"items": [{"id": r["id"], "url": f"/assets/stickers/{r['file']}", "meaning": r.get("desc", "")}
                      for r in prompts._load_sticker_manifest() if r.get("file")]}


# 朗读一条角色消息：用设置里给这门语言配的听力合成声音（Kokoro 或兼容接口）。角色窗口按音量对口型。
_speech_lock = asyncio.Lock()
_speech_cache: "OrderedDict[tuple, bytes]" = OrderedDict()   # (消息 id, 音色) -> wav
_CHARACTERS = Path(__file__).resolve().parents[3] / "frontend" / "assets" / "live2d" / "characters.json"
_SPEECH_CACHE_SIZE = 24
_SPEECH_MAX_CHARS = 1500


def _speakable(text: str) -> str:
    # 表情符号、私用区字符、变体选择符和连字符念不出来；其余原样交给合成
    kept = "".join(ch for ch in text if unicodedata.category(ch) not in ("So", "Cs", "Co")
                   and not 0xFE00 <= ord(ch) <= 0xFE0F and ch != "‍")
    return " ".join(kept.split())[:_SPEECH_MAX_CHARS]


def _speech_lines(text: str, speaker: str) -> list:
    """按句子切成不超过 480 字的几行（听力合成一行的上限是 500 字）。"""
    from ..services.listening_formats import Line
    parts, chunk = [], ""
    for sentence in re.split(r"(?<=[.!?。！？…])\s*", text):
        if chunk and len(chunk) + len(sentence) + 1 > 480:
            parts.append(chunk)
            chunk = ""
        chunk = f"{chunk} {sentence}".strip() if chunk else sentence
        while len(chunk) > 480:
            parts.append(chunk[:480])
            chunk = chunk[480:]
    if chunk:
        parts.append(chunk)
    return [Line(speaker=speaker, text=p) for p in parts if len(p.strip()) >= 2]


def _speech_source(message_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT m.role, m.content, m.language, p.name AS persona FROM messages m "
                           "LEFT JOIN personas p ON p.id = m.persona_id WHERE m.id = ?", (message_id,)).fetchone()
    if row is None or row["role"] != "assistant":
        raise HTTPException(404, "没有这条消息")
    text = _speakable(row["content"] or "")
    if len(text) < 2:
        raise HTTPException(422, "这条没有能念的字。")
    config, speaker, timbre = _speech_profile(row["language"], row["persona"])
    if config is None:
        raise HTTPException(409, "先在设置里给这门语言选好听力的声音。")
    return row["language"], config, _speech_lines(text, speaker), timbre


def _matched_voice(persona: str | None) -> dict | None:
    if not persona:
        return None
    try:
        characters = json.loads(_CHARACTERS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for character in characters.values():
        voice = character.get("voice")
        if isinstance(voice, dict) and any(persona.startswith(p) for p in character.get("match", [])):
            return voice
    return None


def _character_voice(persona: str | None, language: str | None = None) -> dict | None:
    """角色的朗读音色，`voice` 里按语言写的一项盖在通用的上面。"""
    voice = _matched_voice(persona)
    if voice is None:
        return None
    merged = {k: v for k, v in voice.items() if not isinstance(v, dict)}
    if isinstance(voice.get(language), dict):
        merged.update(voice[language])
    return merged


def _with_base(config, language: str, speaker: str, timbre: dict | None):
    """角色指定了底子音色（`base`，本机 Kokoro 的音色名）而且本机有这个文件，就用它念；否则照设置里的。"""
    from ..services import listening_tts
    base = (timbre or {}).get("base")
    if (not isinstance(base, str) or not isinstance(config, listening_tts.KokoroConfig)
            or not listening_tts.valid_kokoro_voice(language, base)
            or not (config.assets / "voices" / f"{base}.pt").is_file()):
        return config
    return dataclasses.replace(config, voices={**config.voices, speaker: base})


_warming: set = set()


class SpeechWarmIn(BaseModel):
    language: languages.LanguageTag


def _speech_profile(language: str | None, persona: str | None):
    from ..services import character_voice, listening_settings, listening_tts, voicevox

    if language == "ja" and voicevox.available():
        return character_voice.japanese_config(character_voice.load().ja), "A", None
    if language == "en" and _matched_voice(persona) is not None:
        voice = character_voice.load().en
        if config := character_voice.english_config(voice):
            return config, "A", voice.model_dump()
    if not language:
        return None, "A", None
    settings, key = listening_settings.load()
    config = listening_tts.configured_synthesis(language, settings, key)
    if config is None:
        return None, "A", None
    # Kokoro 的音色名第二个字母是性别：有女声就用女声。
    speaker = next((k for k, v in sorted(config.voices.items()) if len(v) > 1 and v[1] == "f"), "A")
    timbre = _character_voice(persona, language)
    return _with_base(config, language, speaker, timbre), speaker, timbre


def _primary_speech_config(language: str):
    with closing(get_conn()) as conn:
        primary = chat_room.settings(conn).primary_id
        row = conn.execute("SELECT name FROM personas WHERE id = ?", (primary,)).fetchone()
    return _speech_profile(language, row["name"] if row else None)[0]


def _speech_cache_key(message_id, config, timbre):
    from ..services.listening_tts import VoicevoxConfig

    voice = dataclasses.asdict(config) if isinstance(config, VoicevoxConfig) else timbre
    return message_id, type(config).__name__, json.dumps(voice, sort_keys=True)


@router.post("/chat/speech/warm", status_code=202, dependencies=[Depends(same_origin)])
async def warm_speech(body: SpeechWarmIn):
    from ..services import listening_tts
    config = await asyncio.to_thread(_primary_speech_config, body.language)
    if config is None:
        return {"ok": False}
    task = asyncio.create_task(asyncio.to_thread(listening_tts.warm, config))
    _warming.add(task)
    task.add_done_callback(_warming.discard)
    return {"ok": True}


@router.post("/chat/messages/{message_id}/speech/warm", status_code=202, dependencies=[Depends(same_origin)])
async def warm_message_speech(message_id: int):
    """鼠标移到「朗读」上就先把本机声音模型加载起来（冷启动要二三十秒），不等它。"""
    from ..services import listening_tts
    try:
        _, config, _, timbre = await asyncio.to_thread(_speech_source, message_id)
    except HTTPException:
        return {"ok": False}
    if _speech_cache_key(message_id, config, timbre) in _speech_cache:
        return {"ok": True}
    task = asyncio.create_task(asyncio.to_thread(listening_tts.warm, config))
    _warming.add(task)
    task.add_done_callback(_warming.discard)
    return {"ok": True}


@router.post("/chat/messages/{message_id}/speech", dependencies=[Depends(same_origin)])
async def message_speech(message_id: int):
    from ..services import listening_tts, voice_timbre
    language, config, lines, timbre = await asyncio.to_thread(_speech_source, message_id)
    key = _speech_cache_key(message_id, config, timbre)
    audio = _speech_cache.get(key)
    if audio is None:
        if not lines:
            raise HTTPException(422, "这条没有能念的字。")
        async with _speech_lock:
            audio = _speech_cache.get(key)
            if audio is None:
                task = asyncio.create_task(asyncio.to_thread(
                    voice_timbre.synthesize, config, language, lines, timbre,
                ) if timbre else asyncio.to_thread(listening_tts.synthesize, config, language, lines))
                try:
                    audio = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await asyncio.gather(task, return_exceptions=True)
                    raise
                except Exception:
                    raise HTTPException(502, "朗读失败，检查一下听力的声音设置。") from None
                _speech_cache[key] = audio
                while len(_speech_cache) > _SPEECH_CACHE_SIZE:
                    _speech_cache.popitem(last=False)
    _speech_cache.move_to_end(key)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/messages/{message_id}/location")
def message_location(message_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT session_id FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "没有这条消息")
        return {"session_id": row[0]}


@router.get("/languages")
def list_languages():
    with closing(get_conn()) as conn:
        return {"items": [{"tag": tag, "label": label} for tag, label in languages.registered(conn).items()]}


@router.delete("/reading/errors/{ident}", dependencies=[Depends(same_origin)])
def delete_reading_error(ident: str):
    from .reading import delete_error
    return delete_error(ident)


@router.post("/languages", status_code=201, dependencies=[Depends(same_origin)])
def add_language(body: languages.LanguageInput):
    try:
        return languages.add(body)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.delete("/languages/{tag}", dependencies=[Depends(same_origin)])
def delete_language(tag: str):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if tag not in languages.registered(conn):
            raise HTTPException(404)
        if chat_room.settings(conn).language == tag:
            raise HTTPException(409, "先把聊天拨到别的语言。")
        if tag in languages.BUILTINS:
            raise HTTPException(409)
        custom = {key: label for key, label in languages.registered(conn).items()
                  if key != tag and key not in languages.BUILTINS}
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (languages.REGISTRY_KEY, json.dumps(custom, ensure_ascii=False)))
    return {"deleted": tag}
