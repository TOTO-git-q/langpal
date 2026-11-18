"""OpenAI 兼容 REST provider 的通用实现，泛化自原来专属 DeepSeek 的实现。

无状态的 REST API，但 base.py 的接口只给 session_key + 单条 user_text（不传历史），
所以这里在 provider 内部按 session_key 自己维护一份消息历史（含冻结的 system_prompt），
行为上和 agent_sdk 的"常驻会话"对齐：同一 session_key 的后续轮次复用第一次传入的
system_prompt，新的 system_prompt 参数会被忽略。

`OpenAICompatProvider` 构造时传入一次读取完整服务配置的函数。请求期间使用该快照，
避免地址和密钥来自两次不同的保存。

没配 api_key/base_url 时 configured()=False，且 stream_chat/generate_json 直接抛错，
不悄悄换用别的东西——由 registry 决定要不要用这个 provider。
"""

import base64
import json
import logging
import os
import re
from contextlib import closing
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlsplit

import httpx

from ..db import get_conn
from ..image_utils import EXT_MEDIA_TYPE
from ..services.provider_urls import is_private_host
from ._settings import get_setting
from .base import LLMProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 历史补种：内存 _histories 机制保持不变（守门重试依赖"刚才的坏回复还在历史里"），
# 但 session_key 第一次出现（后端刚重启 / 主引擎中途降级切过来）时不再从零开始，
# 而是从 DB 的 messages 表把这个会话的近期上文补种进去——重启/降级不再失忆。
# 主聊天里几个人设共用一段对话：只有这个 key 的人设自己说的算 assistant，别人的话带名字算 user
# （services/chat_room.seed_history）。chatgpt provider 也用这一个函数。
# ---------------------------------------------------------------------------
_SEED_MAX_MESSAGES = 30
_SEED_MAX_CHARS = 6000


def _seed_history_from_db(session_key: str) -> list[dict]:
    """这个人设（session_key = p{人设}s{会话}）视角的近期上文；尾部连续的 user 消息已掐掉（那是这一批
    马上作为本轮 user_text 追加的）。预算：尾部优先，最多 _SEED_MAX_MESSAGES 条 / _SEED_MAX_CHARS 字。"""
    from ..services import chat_room
    return chat_room.seed_history(session_key, max_messages=_SEED_MAX_MESSAGES, max_chars=_SEED_MAX_CHARS)

DEEPSEEK_API_BASE = "https://api.deepseek.com"


def _deepseek_key() -> str:
    """settings 库里有就用库里的，没有回退 .env（DEEPSEEK_API_KEY）。"""
    v = get_setting("deepseek_api_key").strip()
    if v:
        return v
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def _deepseek_model() -> str:
    return get_setting("deepseek_model", "deepseek-chat").strip() or "deepseek-chat"


def _deepseek_config() -> tuple[str, str, str] | None:
    key = _deepseek_key()
    return (DEEPSEEK_API_BASE, key, _deepseek_model()) if key else None


def _custom_config(*, require_model: bool = True) -> tuple[str, str, str] | None:
    with closing(get_conn()) as conn:
        rows = dict(conn.execute("SELECT key, value FROM settings WHERE key IN "
                                 "('custom_base_url', 'custom_api_key', 'custom_model')"))
    base_url, key, model = (rows.get(name, "").strip() for name in ("custom_base_url", "custom_api_key", "custom_model"))
    try:
        parts = urlsplit(base_url)
        private = is_private_host(parts.hostname)
    except ValueError:
        return None
    if (require_model and not model) or not parts.hostname or (not key and not private):
        return None
    if parts.scheme != "https" and not (parts.scheme == "http" and private and not key):
        return None
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        return None
    return base_url.rstrip("/"), key, model


def _effort(engine: str, model: str) -> str | None:
    """用户在"模型与账号"里给这个连接+模型选过思考档位才带上 reasoning_effort；没选不传。"""
    from ..services.model_reasoning import get_effort
    return get_effort(engine, model)


def _image_url_block(path: str) -> dict[str, Any] | None:
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError:
        logger.warning("openai_compat: 读取图片失败，跳过这张：%s", path, exc_info=True)
        return None
    ext = p.suffix.lower().lstrip(".")
    media_type = EXT_MEDIA_TYPE.get(ext, "image/png")
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}


class OpenAICompatProvider(LLMProvider):

    def __init__(
        self,
        name: str,
        config_fn: Callable[[], tuple[str, str, str] | None],
        supports_vision: bool = False,
    ) -> None:
        self._name = name
        self._config_fn = config_fn
        self._histories: dict[str, list[dict]] = {}
        # WP-N：deepseek-chat 是纯文本模型，不支持视觉——不伪造，False；custom 是用户自配的
        # OpenAI 兼容端点，按标准 image_url content block 发（未接过真实端点实测，见 worklog）。
        self._vision = supports_vision

    def supports_vision(self) -> bool:
        return self._vision

    def configured(self) -> bool:
        """本地检查是否有完整配置，连通性由 health()/实际调用确认。"""
        return self._config_fn() is not None

    def forget_session(self, session_key: str) -> None:
        self._histories.pop(session_key, None)

    def drop_all_sessions(self) -> None:
        """WP-M：引擎切换时调用——清空全部内存历史；下次这个 session_key 出现会重新
        `_seed_history_from_db` 从 DB 补种（`_history_for` 本来就是这个语义，并不丢记忆）。"""
        self._histories.clear()

    @staticmethod
    def _headers(key: str) -> dict:
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _require_config(self) -> tuple[str, str, str]:
        config = self._config_fn()
        if config is None:
            raise RuntimeError(f"{self._name}: 模型服务未配置")
        return config

    def _history_for(self, session_key: str, system_prompt: str) -> list[dict]:
        history = self._histories.get(session_key)
        if history is None:
            # 冻结：只在这个 session_key 第一次出现时采用 system_prompt。
            # 同时从 DB 补种近期上文（后端重启 / 主引擎中途降级切过来时不失忆）。
            seed = _seed_history_from_db(session_key)
            if seed:
                logger.info(
                    "%s: 会话 %s 首次出现，从 DB 补种 %d 条上文",
                    self._name, session_key, len(seed),
                )
            history = [{"role": "system", "content": system_prompt}] + seed
            self._histories[session_key] = history
        return history

    async def stream_chat(
        self,
        session_key: str,
        system_prompt: str,
        user_text: str,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[str]:
        base_url, key, model = self._require_config()
        history = self._history_for(session_key, system_prompt)
        # 不支持视觉的引擎（deepseek）静默忽略 image_paths（防御性——正常情况下
        # services/chat.py 已经用 supports_vision() 判断好了，不会把图片传到这里）。
        if image_paths and self._vision:
            blocks: list[dict[str, Any]] = []
            if user_text:
                blocks.append({"type": "text", "text": user_text})
            for path in image_paths:
                block = _image_url_block(path)
                if block is not None:
                    blocks.append(block)
            content: Any = blocks if blocks else user_text
        else:
            content = user_text
        history.append({"role": "user", "content": content})
        payload = {"model": model, "messages": history, "stream": True}
        effort = _effort(self._name, model)
        if effort is not None:
            payload["reasoning_effort"] = effort
        full_parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers=self._headers(key),
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        text = delta.get("content")
                        if text:
                            full_parts.append(text)
                            yield text
        except httpx.HTTPError:
            # 失败的话把这轮塞进去的 user 消息撤回，避免历史里留一条没有回应的用户轮次
            if history and history[-1].get("role") == "user":
                history.pop()
            raise
        history.append({"role": "assistant", "content": "".join(full_parts)})

    async def generate_json(self, prompt: str, schema: dict) -> dict:
        base_url, key, model = self._require_config()
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你只输出符合要求的 JSON，不要多余文字、不要 markdown 代码块。",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        effort = _effort(self._name, model)
        if effort is not None:
            payload["reasoning_effort"] = effort
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            resp = await client.post(
                f"{base_url}/chat/completions", headers=self._headers(key), json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    async def health(self) -> bool:
        config = self._config_fn()
        if config is None:
            return False
        base_url, key, _ = config
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                resp = await client.get(f"{base_url}/models", headers=self._headers(key))
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


class DeepSeekProvider(OpenAICompatProvider):
    """向后兼容的类名 + 固定 DeepSeek 官方配置（base_url 不可配，model/key 可配）。"""

    def __init__(self) -> None:
        super().__init__("deepseek", _deepseek_config, supports_vision=False)


class CustomProvider(OpenAICompatProvider):
    """settings.custom_base_url / custom_api_key / custom_model 三个都由用户配置。"""

    def __init__(self) -> None:
        super().__init__("custom", _custom_config, supports_vision=True)
