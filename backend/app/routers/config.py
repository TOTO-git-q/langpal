"""配置路由：personas / settings / health / usage / engines。
M0=内存 mock。WP-D 改为 SQLite 真实现；health 的引擎状态由 WP-A 接 registry。
usage：Claude 订阅额度（移植自 NGO桌宠 usage-poller.mjs 的官方 oauth/usage 接口）。
v1.3（WP-K）：settings 密钥掩码 + 引擎相关新键、DELETE /personas/{id}、GET /engines/status，
详见 docs/history/API-v1.3-engines.md。
"""
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import image_utils
from ..db import AVATAR_DIR, get_conn
from ..providers.agent_sdk import REASONING_LEVELS
from ..providers.registry import ENGINES, FALLBACK_CHOICES, UTILITY_CHOICES
from ..services import languages, lore
from ..services import course
from ..services.provider_urls import is_private_host
from ..services.reading_format_settings import DEFAULTS_KEY, FORMAT_PREFIX
from ..services.reading_style import STYLE_KEY
from ..security import same_origin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

# 密钥类 settings key：GET 永远掩码返回，PUT 有专门的忽略/删除规则（见 docs/history/API-v1.3-engines.md §2）。
_SECRET_KEYS = ("deepseek_api_key", "custom_api_key", "listening_synthesis_api_key")
_BOOL_KEYS = ("degraded", "websearch_enabled", "coach_bridge", "hooks_enabled")
# 由各自功能的专用接口读写，通用 GET/PUT /settings 不碰（不显示，PUT 422）：
# - chat_main / chat_main_session：主聊天的设置和钉住的会话 id，走 GET/PUT /api/chat/main（services/chat_room）
# - chatgpt_enabled：ChatGPT 登录时由 /workspace-agent/siwc/login 写
# - reader_zotero_connection：阅读器的 Zotero 连接，走 routers/reader_zotero.py
_DEDICATED_SETTINGS = {"listening_synthesis", "listening_synthesis_api_key", "coach_service_url",
                       "coach_language_tags", DEFAULTS_KEY, STYLE_KEY, languages.REGISTRY_KEY,
                       "chatgpt_enabled", "chat_main", "chat_main_session", "reader_zotero_connection"}
# 已退役、不再读取的键：库里的值原样保留（不删用户数据），只是不再对外显示、也不许再写。
_RETIRED_SETTINGS: set[str] = {"teaching_evaluator"}
# 学习模块（复习排程 / 阅读）的设置：键 -> (默认值, 解析校验函数)
def _ratio(value):
    number = float(value)
    if isinstance(value, bool) or not 0.80 <= number <= 0.95:
        raise ValueError
    return round(number, 4)


def _int_0_50(value):
    if isinstance(value, bool) or not str(value).strip().isdigit() or not 0 <= int(str(value).strip()) <= 50:
        raise ValueError
    return int(str(value).strip())


def _flag(value):
    if value in (True, 1, "1", "true"):
        return 1
    if value in (False, 0, "0", "false"):
        return 0
    raise ValueError


_LEARNING_SETTINGS = {
    "review_target_retention": (0.9, _ratio, "0.80–0.95 之间的小数"),
    "review_new_per_day": (12, _int_0_50, "0–50 的整数"),
    "review_mix": (1, _flag, "0 或 1"),
    "reading_questions_first": (0, _flag, "0 或 1"),
}
_CLAUDE_SETTINGS = ("chat_model_claude", "chat_reasoning_claude")
_SETTING_DEFAULTS = {"chat_engine": "claude", "utility_engine": "auto", "chat_fallback": "enabled",
                     "chat_model_claude": "sonnet", "chat_reasoning_claude": "off",
                     "user_name": ""}
# 事件 hook（docs/LORE-AND-HOOKS.md 2.5）：总开关 + 她主动发消息的节流。键 -> (默认, 下限, 上限)
_HOOK_INT_SETTINGS = {"hooks_say_daily_cap": (4, 0, 50), "hooks_say_min_gap_minutes": (30, 0, 1440)}


def _dedicated(key: str) -> bool:
    return (key in _DEDICATED_SETTINGS or key in _RETIRED_SETTINGS
            or key.startswith((FORMAT_PREFIX, course.SETTINGS_PREFIX, "teaching_saved_outline:", "model_reasoning_", "hooks_lesson_seen:")))


def _hook_int(key: str, value) -> int:
    default, low, high = _HOOK_INT_SETTINGS[key]
    try:
        return min(high, max(low, int(float(value))))
    except (TypeError, ValueError):
        return default


def _mask_secret(value: str) -> str:
    tail = value[-4:] if len(value) >= 4 else value
    return "····" + tail


class PersonaIn(BaseModel):
    name: str
    language: str
    profile: dict


def _profile_json(body: PersonaIn, conn) -> str:
    try:
        if body.language not in languages.BUILTINS:
            raise ValueError("角色资料语言请选日语、英语或德语。聊天语言可从主聊天随时切换。")
        return json.dumps(course.validate_profile(body.profile, body.language, conn), ensure_ascii=False)
    except ValueError as error:
        if hasattr(error, "errors"):
            error = error.errors(include_input=False)[0]["msg"]
        raise HTTPException(422, "角色设定有误：" + str(error)) from None


def row_to_dict(row):
    """将 sqlite3.Row 转为 dict"""
    if row is None:
        return None
    return dict(row)


def persona_row_to_dict(row):
    """将 personas 的 Row 转为 dict，解析 profile_json，并把 avatar 文件名换算成前端可直接
    用的 URL（avatar_url；没设过头像就是 None，前端回退首字母/情绪头像）。"""
    if row is None:
        return None
    d = dict(row)
    if "profile_json" in d:
        d["profile"] = json.loads(d["profile_json"])
        del d["profile_json"]
    avatar = d.pop("avatar", None)
    # 文件名里带上传时间戳 → URL 天然带版本，换头像后浏览器不会拿旧缓存
    d["avatar_url"] = f"/avatars/{avatar}" if avatar else None
    return d


# ---------------------------------------------------------------------------
# 人设头像上传（multipart）。不依赖 Pillow：按魔数嗅探真实图片类型，原样落盘，
# 前端 CSS 已经是 object-fit:cover 的圆形裁切，不需要服务端缩放。
# ---------------------------------------------------------------------------
_AVATAR_MAX_BYTES = 3 * 1024 * 1024

# 魔数嗅探 + 宽高解析已提到 image_utils.py（WP-N 起聊天图片上传也要用同一份逻辑，
# 别抄两份）；这里保留 _sniff_image_ext 这个名字只是不想动下面已经在用它的调用点。
_sniff_image_ext = image_utils.sniff_image_ext


def _remove_avatar_file(filename: str | None) -> None:
    """删旧头像文件。filename 只可能是本模块自己生成的（persona_id_时间戳.ext），
    仍然做一次 name 归一，杜绝任何路径穿越的可能。"""
    image_utils.remove_file(AVATAR_DIR, filename)


@router.post("/personas/{persona_id}/avatar")
async def upload_persona_avatar(persona_id: int, file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(413, "图片太大（上限 3MB）")
    ext = _sniff_image_ext(data)
    if ext is None:
        raise HTTPException(415, "只支持 PNG / JPEG / GIF / WebP 图片")

    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT avatar FROM personas WHERE id = ?", (persona_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        old = row["avatar"]

        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{persona_id}_{int(time.time())}.{ext}"
        (AVATAR_DIR / filename).write_bytes(data)

        cursor.execute("UPDATE personas SET avatar = ? WHERE id = ?", (filename, persona_id))
        conn.commit()
        if old and old != filename:
            _remove_avatar_file(old)

        cursor.execute("SELECT * FROM personas WHERE id = ?", (persona_id,))
        return persona_row_to_dict(cursor.fetchone())
    finally:
        conn.close()


@router.delete("/personas/{persona_id}/avatar")
async def delete_persona_avatar(persona_id: int):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT avatar FROM personas WHERE id = ?", (persona_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        cursor.execute("UPDATE personas SET avatar = NULL WHERE id = ?", (persona_id,))
        conn.commit()
        _remove_avatar_file(row["avatar"])

        cursor.execute("SELECT * FROM personas WHERE id = ?", (persona_id,))
        return persona_row_to_dict(cursor.fetchone())
    finally:
        conn.close()


@router.get("/personas")
async def list_personas():
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM personas WHERE archived_at IS NULL ORDER BY id")
        rows = cursor.fetchall()
        items = [persona_row_to_dict(row) for row in rows]
        return {"items": items}
    finally:
        conn.close()


@router.post("/personas", dependencies=[Depends(same_origin)])
async def create_persona(body: PersonaIn):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        profile_json = _profile_json(body, conn)
        cursor.execute("""
            INSERT INTO personas (name, language, profile_json)
            VALUES (?, ?, ?)
        """, (body.name, body.language, profile_json))
        conn.commit()

        cursor.execute("SELECT * FROM personas WHERE id = ?", (cursor.lastrowid,))
        new_persona = cursor.fetchone()
        return persona_row_to_dict(new_persona)
    finally:
        conn.close()


@router.put("/personas/{persona_id}", dependencies=[Depends(same_origin)])
async def update_persona(persona_id: int, body: PersonaIn):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # 先查找是否存在
        cursor.execute("SELECT * FROM personas WHERE id = ? AND archived_at IS NULL", (persona_id,))
        existing = cursor.fetchone()
        if existing is None:
            raise HTTPException(404, "not found")

        profile_json = _profile_json(body, conn)
        cursor.execute("""
            UPDATE personas
            SET name = ?, language = ?, profile_json = ?
            WHERE id = ?
        """, (body.name, body.language, profile_json, persona_id))
        conn.commit()

        cursor.execute("SELECT * FROM personas WHERE id = ?", (persona_id,))
        updated = cursor.fetchone()
        return persona_row_to_dict(updated)
    finally:
        conn.close()


@router.delete("/personas/{persona_id}", dependencies=[Depends(same_origin)])
async def delete_persona(persona_id: int):
    """软删除：只写 archived_at（聊天记录、记忆都留着），并清掉这个人设在各引擎里的内存会话和原生会话指针。

    主聊天登记在主人设名下，副人设在主聊天里也有自己的常驻会话（p{她}s{主聊天}），所以要清的会话是
    "她名下的会话 + 主聊天"。归档主人设可以（先钉住主聊天会话，时间线交给下一张人设卡，见 chat_room.settings）；
    最后一张人设卡不能归档。"""
    from ..services import chat_room, session_pointers

    conn = get_conn()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            active = [row[0] for row in conn.execute("SELECT id FROM personas WHERE archived_at IS NULL")]
            if persona_id not in active:
                raise HTTPException(404, "没有这张角色卡")
            if len(active) == 1:
                raise HTTPException(409, "这是最后一张人设卡，不能归档。先新建一张再归档它。")
            lore.migrate_legacy(conn)
            main_sid = chat_room.main_session_id(conn)  # 归档前钉住主聊天：主人设换人不换时间线
            conn.execute("UPDATE personas SET archived_at = datetime('now') WHERE id = ? AND archived_at IS NULL",
                         (persona_id,))
        session_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM sessions WHERE persona_id = ?", (persona_id,)
        ).fetchall()]
        if main_sid is not None and main_sid not in session_ids:
            session_ids.append(main_sid)
    finally:
        conn.close()
    try:
        session_pointers.clear(persona_id=persona_id)
    except Exception:
        logger.warning("清理人设 %s 的会话指针失败，跳过", persona_id, exc_info=True)
    try:
        from ..providers import registry

        await registry.drop_persona_sessions(persona_id, session_ids)
    except Exception:
        logger.warning("registry.drop_persona_sessions(%s) 失败，跳过内存态清理", persona_id, exc_info=True)
    return {"ok": True}


@router.get("/settings")
async def get_settings():
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings")
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            key = row["key"]
            value = row["value"]
            if _dedicated(key):
                continue
            if key in _BOOL_KEYS:
                settings[key] = value == "1"
            elif key in _HOOK_INT_SETTINGS:
                settings[key] = _hook_int(key, value)
            elif key in _LEARNING_SETTINGS:
                default, parse, _ = _LEARNING_SETTINGS[key]
                try:
                    settings[key] = parse(value)
                except (TypeError, ValueError):
                    settings[key] = default
            elif key in _SECRET_KEYS:
                settings[key] = _mask_secret(value) if value else None
            else:
                settings[key] = value
        for key in set(_SECRET_KEYS) - _DEDICATED_SETTINGS:
            settings.setdefault(key, None)
        # 没存过的引擎相关键按实际生效的默认值显示；库里遗留的 chatgpt/codex 显示成 claude。
        from ..providers.registry import normalize_engine

        if "chat_engine" in settings:
            settings["chat_engine"] = normalize_engine(settings["chat_engine"])
        for key, default in _SETTING_DEFAULTS.items():
            settings.setdefault(key, default)
        settings.setdefault("hooks_enabled", True)
        for key, (default, _, _) in _HOOK_INT_SETTINGS.items():
            settings.setdefault(key, default)
        for key, (default, _, _) in _LEARNING_SETTINGS.items():
            settings.setdefault(key, default)
        # deepseek_api_key 的 .env 兜底：settings 库里没配才看 .env（和 provider 侧的
        # 解析顺序一致），前端只关心"有没有配置"，不关心来源。
        if settings.get("deepseek_api_key") is None:
            env_val = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            if env_val:
                settings["deepseek_api_key"] = _mask_secret(env_val)
        return settings
    finally:
        conn.close()


@router.put("/settings", dependencies=[Depends(same_origin)])
async def put_settings(patch: dict):
    if any(key in patch for key in ("chat_model_codex", "chat_reasoning_codex")):
        raise HTTPException(422, "Codex 已从 LangPal 移除。")
    if "user_name" in patch:
        value = patch["user_name"]
        if not isinstance(value, str) or len(value.strip()) > 24:
            raise HTTPException(422)
        patch["user_name"] = value.strip()
    if "chat_engine" in patch and patch["chat_engine"] not in ENGINES:
        raise HTTPException(422, "聊天引擎只能选 " + " / ".join(ENGINES))
    if "utility_engine" in patch and patch["utility_engine"] not in UTILITY_CHOICES:
        raise HTTPException(422, "杂活引擎只能选 " + " / ".join(UTILITY_CHOICES))
    if "vision_engine" in patch and patch["vision_engine"] not in ("none", "claude"):
        raise HTTPException(422, "看图引擎只能选 claude 或 none")
    if "chat_fallback" in patch and patch["chat_fallback"] not in FALLBACK_CHOICES:
        raise HTTPException(422, "降级策略只能选 enabled 或 none")
    if "chat_reasoning_claude" in patch:
        from ..services.model_reasoning import known_levels

        allowed = {*REASONING_LEVELS, *known_levels("claude")}
        if patch["chat_reasoning_claude"] not in allowed:
            raise HTTPException(422, "Claude 思考档位只能选 off 或模型声明的档位：" + " / ".join(sorted(allowed)))

    if "hooks_enabled" in patch and patch["hooks_enabled"] not in (True, False, 0, 1, "0", "1"):
        raise HTTPException(422, "hooks_enabled 只能是开或关")
    if "hooks_enabled" in patch:
        patch["hooks_enabled"] = patch["hooks_enabled"] not in (False, 0, "0")
    for key, (_, parse, rule) in _LEARNING_SETTINGS.items():
        if key in patch:
            try:
                patch[key] = parse(patch[key])
            except (TypeError, ValueError):
                raise HTTPException(422, f"{key} 要是 {rule}") from None
    for key, (_, low, high) in _HOOK_INT_SETTINGS.items():
        if key in patch:
            value = patch[key]
            if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).strip().isdigit() \
                    or not low <= int(str(value).strip()) <= high:
                raise HTTPException(422, f"{key} 要是 {low}–{high} 之间的整数")
            patch[key] = int(str(value).strip())
    if any(map(_dedicated, patch)):
        raise HTTPException(422, "请在对应功能的设置中修改")
    if "listening_subscription" in patch and patch["listening_subscription"] not in ("", *ENGINES):
        raise HTTPException(422, "听力出题引擎只能选空（跟随聊天引擎）或 " + " / ".join(ENGINES))
    for key in ("chat_model_claude", "deepseek_model", "custom_model"):
        from ..services.model_catalog import model_id
        if key in patch and (not isinstance(patch[key], str) or (patch[key] and not model_id(patch[key]))):
            raise HTTPException(422, "模型名称过长或包含无效字符。")
    conn = get_conn()
    try:
        cursor = conn.cursor()
        if {"custom_base_url", "custom_api_key"}.intersection(patch):
            cursor.execute("BEGIN IMMEDIATE")
            existing = dict(cursor.execute(
                "SELECT key, value FROM settings WHERE key IN ('custom_base_url', 'custom_api_key')"
            ).fetchall())
            old_url = existing.get("custom_base_url", "").strip().rstrip("/")
            url = str(patch.get("custom_base_url", old_url) or "").strip().rstrip("/")
            new_key = str(patch.get("custom_api_key") or "").strip()
            untouched_key = "custom_api_key" not in patch or new_key.startswith("····")
            effective_key = existing.get("custom_api_key", "") if untouched_key else new_key
            if old_url != url:
                effective_key = "" if untouched_key else new_key
                patch["custom_api_key"] = effective_key
            if url:
                try:
                    parsed = urlsplit(url)
                    if (not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment
                            or any(char.isspace() for char in url) or "\\" in url
                            or (parsed.scheme != "https" and not (
                                parsed.scheme == "http" and is_private_host(parsed.hostname) and not effective_key
                            ))):
                        raise ValueError("invalid URL")
                    _ = parsed.port
                except ValueError:
                    raise HTTPException(422, "请用 HTTPS，或使用免密钥的本机／私网 HTTP 端点") from None
            elif effective_key:
                raise HTTPException(422, "请先填写自定义端点 URL")
            if "custom_base_url" in patch:
                patch["custom_base_url"] = url
        # WP-M：chat_engine 真的变了值才触发"立即生效"（registry.drop_all_live_sessions）；
        # 同值重复 PUT（比如前端 change 事件误触发）不该白白断开所有在飞常驻客户端。
        engine_changed = False
        if "chat_engine" in patch:
            from ..providers.registry import normalize_engine

            row = cursor.execute(
                "SELECT value FROM settings WHERE key = 'chat_engine'"
            ).fetchone()
            old_engine = normalize_engine(row["value"] if row is not None else None)
            new_engine = str(patch["chat_engine"])
            engine_changed = new_engine != old_engine
        # Claude 模型/思考档位真的变了：断开常驻客户端让新选项在下一条消息生效（不清会话指针）。
        claude_changed = False
        for key in _CLAUDE_SETTINGS:
            if key in patch:
                row = cursor.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
                if (row["value"] if row is not None else None) != str(patch[key]):
                    claude_changed = True
        for key, value in patch.items():
            if key in _BOOL_KEYS:
                db_value = "1" if value else "0"
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, db_value),
                )
            elif key in _SECRET_KEYS:
                str_value = "" if value is None else str(value)
                if str_value.startswith("····"):
                    # 前端把 GET 回来的掩码串原样回传（用户没碰这个输入框）：忽略，不动库。
                    continue
                if str_value == "":
                    cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
                else:
                    cursor.execute(
                        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                        (key, str_value),
                    )
                # 密钥明文任何情况下不进日志——这里也确实没有任何 logger 调用碰到 str_value。
            else:
                db_value = str(value)
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, db_value),
                )
        conn.commit()
    finally:
        conn.close()

    if engine_changed:
        try:
            from ..providers import registry

            await registry.drop_all_live_sessions(old_engine, new_engine)
        except Exception:
            logger.warning(
                "registry.drop_all_live_sessions() 失败，跳过（引擎设置已保存，"
                "但正在飞的常驻客户端可能没断开，效果类似旧版“要开新会话才生效”）",
                exc_info=True,
            )
    elif claude_changed:
        from ..providers import registry

        await registry.refresh_claude_clients()

    return await get_settings()


@router.get("/engines/status")
async def engines_status():
    """轻量状态：本地文件存在性 + settings 读取，不做任何网络调用。"""
    from ..providers import registry

    return registry.engines_status()


@router.get("/engines/{engine}/models", dependencies=[Depends(same_origin)])
async def provider_models(engine: str):
    """连上接口后读到的模型列表（只读）。每个模型带 reasoning: {levels, default, source, selected}，
    source=api 表示档位来自接口，default 表示接口没声明、给的是保守默认列表。"""
    from ..services.model_catalog import CatalogError, models
    if engine not in ENGINES:
        raise HTTPException(404, "没有这个引擎")
    try:
        return {"models": await models(engine)}
    except CatalogError as error:
        raise HTTPException(502, str(error), headers={"Cache-Control": "no-store"}) from None


class ReasoningChoice(BaseModel):
    model: str
    effort: str | None = None  # None = 交给服务默认；Claude 里 None / "off" = 关扩展思考


@router.post("/engines/{engine}/reasoning", dependencies=[Depends(same_origin)])
async def select_reasoning(engine: str, body: ReasoningChoice):
    """选模型 + 思考档位：先重新读一次接口，只接受这个模型读到的档位（读不到时是默认列表）。
    Claude 写 chat_model_claude/chat_reasoning_claude 并刷新常驻客户端（不清会话指针）；
    ChatGPT 存进账号授权记录；DeepSeek/自定义端点存 model_reasoning_<engine>。"""
    from ..services import model_reasoning
    from ..services.model_catalog import CatalogError, model_id, models
    if engine not in ENGINES:
        raise HTTPException(404, "没有这个引擎")
    if not model_id(body.model):
        raise HTTPException(422, "模型名称过长或包含无效字符。")
    try:
        if engine == "chatgpt":
            return await model_reasoning.save_chatgpt(body.model, body.effort)
        rows = await models(engine)
        selected = next((row for row in rows if row["id"] == body.model), None)
        if selected is None:
            raise ValueError("请从这个连接返回的模型中选择。")
        result = model_reasoning.save(engine, body.model, body.effort, selected["reasoning"])
    except (CatalogError, ValueError) as error:
        raise HTTPException(422, str(error), headers={"Cache-Control": "no-store"}) from None
    except Exception:
        raise HTTPException(409, "请从当前账号返回的模型和思考档位中选择。", headers={"Cache-Control": "no-store"}) from None
    if engine == "claude":
        from ..providers import registry

        await registry.refresh_claude_clients()
    return result


# Claude 订阅额度：读 ~/.claude/.credentials.json 的 OAuth token 调官方接口。
# 安全约定（与 usage-poller.mjs 相同）：token 只用于这一个官方地址，绝不进日志/响应/落盘。
# 60s 进程内缓存；任何失败返回上一次的成功值，从没成功过则 {"available": False}。
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_usage_cache: dict = {"t": 0.0, "data": None}


@router.get("/usage")
async def usage():
    now = time.time()
    if _usage_cache["data"] is not None and now - _usage_cache["t"] < 60:
        return _usage_cache["data"]
    try:
        cred = json.loads(
            (Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8")
        )
        token = (cred.get("claudeAiOauth") or {}).get("accessToken")
        if not isinstance(token, str) or len(token) < 20:
            raise ValueError("no token")
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(
                _USAGE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
            )
            res.raise_for_status()
            d = res.json()

        def _num(v):
            return v if isinstance(v, (int, float)) else None

        data = {
            "available": True,
            "five_hour_pct": _num((d.get("five_hour") or {}).get("utilization")),
            "five_hour_resets": (d.get("five_hour") or {}).get("resets_at"),
            "seven_day_pct": _num((d.get("seven_day") or {}).get("utilization")),
            "seven_day_resets": (d.get("seven_day") or {}).get("resets_at"),
        }
        if data["five_hour_pct"] is None and data["seven_day_pct"] is None:
            raise ValueError("bad shape")
        _usage_cache.update(t=now, data=data)
        return data
    except Exception:
        if _usage_cache["data"] is not None:
            return _usage_cache["data"]
        return {"available": False}


@router.get("/health")
async def health():
    conn = get_conn()
    try:
        # 获取 engine 和 degraded 设置
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings WHERE key IN ('engine', 'degraded')")
        rows = cursor.fetchall()
        settings = {row["key"]: row["value"] for row in rows}

        # 判断 mode
        try:
            from ..providers.registry import get_utility_provider
            get_utility_provider()
            mode = "live"
        except Exception:
            mode = "mock"

        return {
            "status": "ok",
            "mode": mode,
            "engine": settings.get("engine", "agent_sdk"),
            "degraded": settings.get("degraded", "0") == "1",
        }
    finally:
        conn.close()
