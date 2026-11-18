"""Official Responses SDK with this application's ChatGPT OAuth credentials."""
import asyncio
import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI, APIError, APIStatusError, APITimeoutError

from . import workspace_agent_siwc as siwc
from . import workspace_agent_siwc_auth as auth


async def complete(payload: dict, *, token_provider=None, transport=None) -> str:
    try:
        token = await (token_provider or auth.get_access_token)()
    except auth.AuthorizationRequired:
        raise siwc.SiwcFailure("authentication", "请先连接 ChatGPT 并选择模型。") from None
    if not isinstance(token, str) or not token or len(token) > 32768 or any(char.isspace() for char in token):
        raise siwc.SiwcFailure("authentication", "请先连接 ChatGPT。")
    body = {**payload, "store": False, "stream": True}
    if isinstance(body.get("input"), str):
        body["input"] = [{"role": "user", "content": body["input"]}]
    body.setdefault("instructions", "Respond to the user's request.")
    from .model_reasoning import get_effort
    effort = get_effort("chatgpt", body.get("model"))
    if effort is not None:
        body.setdefault("reasoning", {"effort": effort})
    if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > siwc.MAX_INPUT_BYTES:
        raise siwc.SiwcFailure("size", "这次内容过长，请缩短后重试。")
    try:
        async with asyncio.timeout(siwc.TIMEOUT_SECONDS), AsyncOpenAI(
            api_key=token, base_url=siwc.BASE, max_retries=0,
            http_client=httpx.AsyncClient(transport=transport, timeout=40, trust_env=False, follow_redirects=False),
        ) as client:
            completed = None
            size = 0
            async with client.responses.with_streaming_response.create(**body) as response:
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type and content_type != "text/event-stream":
                    raise siwc._bad()
                source = SimpleNamespace(aiter_bytes=response.iter_bytes)
                async for name, raw in siwc._events(source):
                    if raw == "[DONE]":
                        if completed is None:
                            raise siwc._bad("interrupted")
                        continue
                    event = siwc._load(raw)
                    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                        raise siwc._bad()
                    kind = event["type"]
                    if name and name != kind:
                        raise siwc._bad()
                    if kind in ("response.failed", "response.incomplete", "error", "response.error"):
                        raise siwc._failure(event)
                    if completed is not None:
                        raise siwc.SiwcFailure("response", "ChatGPT 返回了异常的结束状态。")
                    if kind == "response.output_text.delta":
                        if not isinstance(event.get("delta"), str):
                            raise siwc._bad()
                        size += len(event["delta"].encode("utf-8"))
                        if size > siwc.MAX_OUTPUT_BYTES:
                            raise siwc.SiwcFailure("size", "ChatGPT 返回内容过长。")
                    elif kind == "response.completed":
                        completed = siwc._completed_text(event.get("response"))
            if completed is None:
                raise siwc.SiwcFailure("interrupted", "连接中断，请重试。")
            return completed
    except siwc.SiwcFailure:
        raise
    except auth.AuthorizationRequired:
        raise siwc.SiwcFailure("authentication", "请先连接 ChatGPT 并选择模型。") from None
    except APIStatusError as error:
        if error.status_code in (401, 403):
            raise siwc.SiwcFailure("authentication", "ChatGPT 授权已失效，请重新连接。") from None
        if error.status_code == 429:
            raise siwc.SiwcFailure("rate_limit", "ChatGPT 当前额度受限，请稍后再试。") from None
        raise siwc.SiwcFailure("service", "ChatGPT 暂时无法完成请求。") from None
    except (TimeoutError, httpx.TimeoutException, APITimeoutError):
        raise siwc.SiwcFailure("timeout", "ChatGPT 响应超时，请重试。") from None
    except (APIError, httpx.HTTPError):
        raise siwc.SiwcFailure("network", "暂时连不上 ChatGPT。") from None
    except (ValueError, TypeError, AttributeError):
        raise siwc.SiwcFailure("response", "ChatGPT 返回的内容无法读取。") from None
