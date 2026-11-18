"""连上各家接口之后读到什么模型就列什么：Claude（SDK 初始化信息）、DeepSeek / 自定义端点（/models）、
ChatGPT 账号（账号模型目录）。只读，不保存。思考档位的读取和保存在 services/model_reasoning.py。
"""
import asyncio
import json

import httpx
import tempfile

from ..providers.deepseek import _deepseek_config, _custom_config
from .model_reasoning import decorate, options

MAX_BYTES = 8_000_000
ENGINES = ("claude", "deepseek", "custom", "chatgpt")


class CatalogError(ValueError):
    pass

def model_id(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and value.strip() == value and not any(
        ord(char) < 32 or ord(char) == 127 for char in value)


def parse(value):
    rows = value.get("data") if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) > 4096:
        raise CatalogError("服务返回的模型目录无法读取。")
    models, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not model_id(row.get("id")):
            raise CatalogError("服务返回的模型目录无法读取。")
        ident = row["id"]
        if ident in seen:
            continue
        label = row.get("display_name") or row.get("name") or ident
        if not isinstance(label, str) or not label.strip() or len(label) > 300:
            label = ident
        item = {"id": ident, "label": label}
        if "effort" in row or "supported_reasoning_levels" in row:
            item["reasoning"] = options(row)
        models.append(item)
        seen.add(ident)
    return models


async def discover(engine, *, transport=None):
    if engine == "claude":
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        from ..providers.agent_sdk import _resolve_cli_path
        try:
            with tempfile.TemporaryDirectory(prefix="jine-models-", ignore_cleanup_errors=True) as folder:
                async with asyncio.timeout(25), ClaudeSDKClient(options=ClaudeAgentOptions(
                    cli_path=_resolve_cli_path(), cwd=folder, tools=[], allowed_tools=[], setting_sources=[],
                )) as client:
                    info = await client.get_server_info()
            rows = (info or {}).get("models", [])
            return [{"id": row["value"], "label": row.get("displayName") or row["value"],
                     "reasoning": options(row)} for row in rows
                    if isinstance(row, dict) and model_id(row.get("value"))]
        except Exception:
            raise CatalogError("暂时无法读取 Claude SDK 的模型信息，请重试。") from None
    if engine == "deepseek":
        config = _deepseek_config()
    elif engine == "custom":
        config = _custom_config(require_model=False)
    elif engine == "chatgpt":
        return await _chatgpt_rows(transport=transport)
    else:
        raise CatalogError("这个连接没有提供 API 模型目录。")
    if config is None:
        raise CatalogError("请先保存这个服务的连接信息。")
    base, key, _ = config
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(
            transport=transport, timeout=15, trust_env=False, follow_redirects=False,
        ) as client:
            async with client.stream("GET", base.rstrip("/") + "/models",
                headers={"Authorization": "Bearer " + key} if key else {}) as response:
                if response.status_code in (401, 403):
                    raise CatalogError("服务鉴权失败，请检查这个连接的密钥。")
                if response.status_code in (404, 405):
                    raise CatalogError("这个服务暂未提供模型目录，可以直接填写模型名。")
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise CatalogError("服务的模型目录过大。")
        return parse(json.loads(data))
    except CatalogError:
        raise
    except (httpx.HTTPError, TimeoutError):
        raise CatalogError("暂时无法读取模型目录，请重试。") from None
    except (ValueError, TypeError):
        raise CatalogError("服务返回的模型目录无法读取。") from None


async def _chatgpt_rows(*, transport=None):
    from . import workspace_agent_siwc as siwc, workspace_agent_siwc_auth as auth
    try:
        token_provider = auth.runtime().get_access_token
        rows = await siwc.list_models(token_provider=token_provider, transport=transport)
    except auth.AuthorizationRequired:
        raise CatalogError("请先连接 ChatGPT 账号。") from None
    except siwc.SiwcFailure as error:
        raise CatalogError("ChatGPT 授权已失效，请重新连接。" if error.code == "authentication"
                           else "暂时无法读取 ChatGPT 模型列表，请重试。") from None
    return [{"id": row["slug"], "slug": row["slug"], "label": row["display_name"],
             **({"reasoning": row["reasoning"]} if "reasoning" in row else {})} for row in rows]


async def models(engine, *, transport=None):
    """GET /engines/{engine}/models 的内容：模型列表 + 每个模型的思考档位（接口没给时标 source=default）。"""
    if engine not in ENGINES:
        raise CatalogError("没有这个引擎。")
    return decorate(engine, await discover(engine, transport=transport))


async def chatgpt_models(*, transport=None):
    return await models("chatgpt", transport=transport)
