"""LangPal 入口。路由拆在 routers/ 下，每个工作包只动自己的文件。"""
import asyncio
import hmac
import ipaddress
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


# WP-M：项目此前没有任何地方调用过 logging.basicConfig/dictConfig——Python 的 root logger
# 默认只有"最后手段"处理器（只认 WARNING 及以上），所以全项目所有 logger.info(...) 调用
# 一直是静默丢弃的。这里补上最小的 basicConfig（越早调用越好，赶在任何模块第一次打日志之前）。
# uvicorn 自己的 "uvicorn"/"uvicorn.access" 日志走它自己的 dictConfig，不受这里影响。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _load_dotenv() -> None:
    """极简 .env 加载（项目根 langpal/.env，存 DEEPSEEK_API_KEY 等）。
    已存在的环境变量不覆盖；必须在 providers 首次构造前执行——放在 routers import 之前。"""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

from .db import init_db  # noqa: E402
from .routers import (  # noqa: E402
    chat, config, explain, furigana, hooks, listening, lore, memory, notebook, reading, reading_sources, review,
    speaking, study_storage, teaching, voice_settings, workspace_agent,
)
from .security import same_origin  # noqa: E402

app = FastAPI(title="LangPal", version="0.1.0")

for r in (chat.router, explain.router, notebook.router, memory.router, config.router, reading.router,
          listening.router, reading_sources.router, teaching.router, speaking.router, workspace_agent.router,
          review.router, study_storage.router, furigana.router, voice_settings.router, voice_settings.character_router,
          lore.router, hooks.router):
    app.include_router(r, prefix="/api")
from .routers import workspace_agent_siwc  # noqa: E402  (ChatGPT 账号登录：同源 + 本机)
app.include_router(workspace_agent_siwc.router, prefix="/api")
from .routers import reader_bridge, reader_zotero  # noqa: E402  (reader MCP bridge and Zotero shelf; loopback only)
for r in (reader_bridge.router, reader_zotero.router):
    app.include_router(r, prefix="/api")
from .routers import learning as learning_router  # noqa: E402  (今天 / 建议 / 统计，docs/LEARNING.md)
app.include_router(learning_router.router, prefix="/api")


# ---------------------------------------------------------------------------
# 访问控制：本机单用户服务。任何网页都能往 127.0.0.1 发请求，所以私有数据所在的路径
# （/api/*、/uploads/*、/avatars/*）统一在这里守：
#   - 跨站请求（security.same_origin 的判断：Sec-Fetch-Site 是 cross-site/same-site，或 Origin
#     和 Host 对不上）一律 403；
#   - Host 头必须是回环地址，或在环境变量 LANGPAL_ALLOWED_HOSTS（逗号分隔，给局域网/Tailscale
#     访问留口）里——挡 DNS rebinding。
# /api/health 仅在本机放行（桌面壳和口语课服务探活用）。不再挂 CORS：没有合法的跨域调用方
# （口语课服务是服务端直接请求，不带 Origin）。
# ---------------------------------------------------------------------------
_GUARDED_PREFIXES = ("/api/", "/uploads/", "/avatars/")
_OPEN_PATHS = {"/api/health"}
_ACCESS_COOKIE = "lp_access"
_ACCESS_REQUIRED = "需要访问码"


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("LANGPAL_ALLOWED_HOSTS", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _loopback(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _hostname(host_header: str) -> str:
    try:
        return urlsplit("//" + host_header).hostname or ""
    except ValueError:
        return ""


def _host_allowed(host_header: str, hostname: str) -> bool:
    allowed = _allowed_hosts()
    return bool(hostname) and (hostname.lower() in allowed or host_header.lower() in allowed)


def _access_matches(value: bytes) -> bool:
    token = os.environ.get("LANGPAL_ACCESS_TOKEN", "")
    return len(token) >= 16 and hmac.compare_digest(value, token.encode("utf-8"))


@app.get("/unlock")
def unlock(request: Request, code: str = ""):
    host = request.headers.get("host", "")
    hostname = _hostname(host)
    if _loopback(hostname):
        raise HTTPException(404)
    value = code.encode("utf-8")
    if not _host_allowed(host, hostname) or not _access_matches(value):
        raise HTTPException(403, _ACCESS_REQUIRED)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(_ACCESS_COOKIE, value.decode("latin-1"), max_age=30 * 24 * 60 * 60,
                        httponly=True, samesite="strict", path="/")
    return response


@app.middleware("http")
async def _access_guard(request, call_next):
    path = request.url.path
    if path != "/api" and not path.startswith(_GUARDED_PREFIXES):
        return await call_next(request)
    host = request.headers.get("host", "")
    hostname = _hostname(host)
    if _loopback(hostname):
        if path in _OPEN_PATHS:
            return await call_next(request)
    else:
        if not _access_matches(request.cookies.get(_ACCESS_COOKIE, "").encode("latin-1")):
            return JSONResponse({"detail": _ACCESS_REQUIRED}, status_code=403)
        if not _host_allowed(host, hostname):
            return JSONResponse({"detail": "不接受这个主机名的请求"}, status_code=403)
    try:
        same_origin(request)
    except HTTPException as error:
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)
    return await call_next(request)


@app.middleware("http")
async def _no_stale_static(request, call_next):
    """静态资源强制走重验证（304 很便宜，本地回环无感知）。
    背景：Chromium 对无 Cache-Control 的响应按启发式缓存，前端大改版后
    Electron 的持久 profile 会拿旧 JS 配新 HTML 直接报错。"""
    resp = await call_next(request)
    if not request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _restore_chatgpt_authorization() -> None:
    """用户登录过 ChatGPT（settings.chatgpt_enabled=1，或环境变量 LANGPAL_SIWC_ENABLED=1）才启用授权
    运行时，并从 %LOCALAPPDATA%\\LangPal\\siwc\\session.dpapi 读回已保存的授权。只读：不开浏览器、
    不发起新授权、不刷新令牌（令牌到下次真正调用时才按需刷新）。失败只记一行日志。"""
    log = logging.getLogger(__name__)
    try:
        from .providers._settings import get_setting

        if os.environ.get("LANGPAL_SIWC_ENABLED") != "1" and get_setting("chatgpt_enabled") != "1":
            return
        from .services import workspace_agent_siwc_auth

        workspace_agent_siwc_auth.enable_after_user_approval(approved=True)
        workspace_agent_siwc_auth.runtime().resume()
    except Exception:
        log.warning("ChatGPT 保存的授权没能恢复；可以在“模型与账号”里重新连接。")


@app.on_event("startup")
async def _startup():
    init_db()
    # 遗留的 chat_engine=codex 之类写回规范值（只改引擎选择这几个键）。
    try:
        from .providers import registry

        registry.normalize_settings()
    except Exception:
        logging.getLogger(__name__).warning("引擎设置规范化失败，跳过", exc_info=True)
    _restore_chatgpt_authorization()
    # 世界书关键词的原形先在后台算好（第一轮聊天不用现分词），出错不影响启动
    try:
        from contextlib import closing

        from .db import get_conn
        from .services.lore import store as lore_store

        with closing(get_conn()) as conn:
            lore_store.warm_soon(conn)
    except Exception:
        logging.getLogger(__name__).warning("世界书预热没启动，跳过", exc_info=True)
    # WP-M：全库嵌入补算，后台跑、不阻塞启动（幂等，LEFT JOIN 天然只挑缺的；模型不可用会
    # 自己提前退出，见 services/recall.backfill_all docstring）。
    asyncio.create_task(_recall_backfill_task())


async def _recall_backfill_task():
    from .services import recall

    try:
        await recall.backfill_all()
    except Exception:
        logging.getLogger(__name__).warning("recall backfill_all 失败，跳过", exc_info=True)


@app.on_event("shutdown")
async def _shutdown():
    from .providers import registry
    from .services import voicevox

    await asyncio.to_thread(voicevox.stop)
    await registry.shutdown()


# 人设自定义头像：data/avatars/ 直接托管成 /avatars/*（必须在下面的根挂载之前注册，
# 否则会被 "/" 的 catch-all 吃掉）。目录由 init_db() 建好，这里再兜一次底。
from .db import AVATAR_DIR, UPLOAD_DIR  # noqa: E402

AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=AVATAR_DIR), name="avatars")

# 聊天图片消息：data/uploads/ 直接托管成 /uploads/*（同样必须在下面的根挂载之前注册）。
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Claude Design 产出放进 frontend/ 后自动托管
_frontend = Path(__file__).resolve().parents[2] / "frontend"
if (_frontend / "index.html").exists():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
