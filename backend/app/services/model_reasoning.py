"""思考档位：从各家接口返回的模型能力里读"这个模型支持哪些档位"，用户在其中选。

- 档位来自接口（Claude SDK 的 supportedEffortLevels、OpenAI/DeepSeek/兼容端点 /models 里的
  supported_reasoning_levels / effort.supported_levels、ChatGPT 账号模型目录）；接口没给时才退回
  DEFAULT_LEVELS，并在返回里标 source="default"，界面据此提示"这是默认列表，接口没有声明"。
- 选择按 引擎 + 连接 + 模型 绑定：换模型或换了自定义端点地址，旧选择自动失效（不再发送）。
- 存放位置：Claude 用 chat_model_claude / chat_reasoning_claude（off = 关扩展思考）；DeepSeek 和
  自定义端点用 settings 的 model_reasoning_<engine>；ChatGPT 存在账号授权记录里（DPAPI）。
"""
import json
import re
from contextlib import closing

from ..db import get_conn
from ..providers._settings import get_setting

PREFIX = "model_reasoning_"
# 接口没声明档位时的保守默认（OpenAI 系 reasoning_effort / Claude effort 的公共子集）。
DEFAULT_LEVELS = ("low", "medium", "high")
CLAUDE_OFF = "off"
_LEVEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_observed: dict = {}


def options(row):
    """从接口返回的一条模型记录里读档位：{levels:[{id,label}], default}。"""
    effort = row.get("effort") if isinstance(row.get("effort"), dict) else {}
    values = row.get("supported_reasoning_levels")
    if values is None:
        values = effort.get("supported_levels")
    if values is None:
        values = row.get("supportedEffortLevels")
    result, seen = [], set()
    if isinstance(values, list):
        for value in values[:64]:
            item = value if isinstance(value, dict) else {"effort": value}
            ident = item.get("effort", item.get("id"))
            if not isinstance(ident, str) or not _LEVEL_RE.fullmatch(ident) or ident in seen:
                continue
            label = item.get("display_name") or item.get("label") or item.get("description") or ident
            result.append({"id": ident, "label": str(label)[:100]})
            seen.add(ident)
    default = row.get("default_reasoning_level", effort.get("default_level"))
    return {"levels": result, "default": default if isinstance(default, str) and default in seen else None}


def with_source(reasoning):
    """接口给了档位就标 api；没给就换成保守默认列表并标 default。"""
    reasoning = dict(reasoning or {"levels": [], "default": None})
    if reasoning.get("levels"):
        return {**reasoning, "source": "api"}
    return {"levels": [{"id": level, "label": level} for level in DEFAULT_LEVELS],
            "default": None, "source": "default"}


def binding(engine):
    return get_setting("custom_base_url").strip().rstrip("/") if engine == "custom" else engine


def _preference(engine):
    try:
        value = json.loads(get_setting(PREFIX + engine, "{}"))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def known_levels(engine, model=None):
    """最近一次从接口读到（或退回默认）的档位 id；model=None 时合并该引擎所有模型。"""
    connection = binding(engine)
    found = set()
    for (eng, conn, ident), levels in _observed.items():
        if eng == engine and conn == connection and (model is None or ident == model):
            found.update(levels)
    return found


def get_effort(engine, model):
    """这次请求要带的思考档位；没选、或选择不属于当前连接/模型时返回 None（不传参数）。"""
    if engine == "claude":
        if model != get_setting("chat_model_claude", "sonnet").strip():
            return None
        value = get_setting("chat_reasoning_claude", CLAUDE_OFF).strip()
        return None if value in ("", CLAUDE_OFF) else value
    if engine == "chatgpt":
        from . import workspace_agent_siwc_auth as auth
        metadata = auth.safe_metadata()
        if metadata.get("selected_model") != model:
            return None
        selected = metadata.get("reasoning_effort")
        allowed = metadata.get("reasoning_levels") or []
        connection = engine
    else:
        connection = binding(engine)
        value = _preference(engine)
        if value.get("model") != model or value.get("connection") != connection:
            return None
        selected, allowed = value.get("effort"), value.get("levels", [])
    allowed = _observed.get((engine, connection, model), allowed)
    return selected if isinstance(selected, str) and isinstance(allowed, list) and selected in allowed else None


def selected(engine, model):
    if engine == "claude":
        if model != get_setting("chat_model_claude", "sonnet").strip():
            return None
        return get_setting("chat_reasoning_claude", CLAUDE_OFF).strip() or CLAUDE_OFF
    return get_effort(engine, model)


def decorate(engine, models):
    """给模型列表补上 reasoning: {levels, default, source, selected}，并记下读到的档位供校验。"""
    connection = binding(engine)
    for row in models:
        ident = row.get("id", row.get("slug"))
        reasoning = with_source(row.get("reasoning"))
        _observed[(engine, connection, ident)] = [item["id"] for item in reasoning["levels"]]
        row["reasoning"] = {**reasoning, "selected": selected(engine, ident)}
    return models


def save(engine, model, effort, reasoning):
    """保存 DeepSeek / 自定义端点 / Claude 的选择（ChatGPT 走 save_chatgpt）。effort=None 表示交给服务默认
    （Claude 则是关掉扩展思考）。档位必须在这个模型读到的列表里。"""
    reasoning = with_source(reasoning)
    allowed = [item["id"] for item in reasoning["levels"]]
    if effort is not None and effort not in allowed and not (engine == "claude" and effort == CLAUDE_OFF):
        raise ValueError("请从当前模型支持的思考档位中选择。")
    with closing(get_conn()) as conn, conn:
        if engine == "claude":
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('chat_model_claude',?)", (model,))
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('chat_reasoning_claude',?)",
                         (effort or CLAUDE_OFF,))
        else:
            value = {"model": model, "connection": binding(engine), "effort": effort, "levels": allowed}
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                         (PREFIX + engine, json.dumps(value, ensure_ascii=False)))
    _observed[(engine, binding(engine), model)] = allowed
    return {"model": model, "reasoning": {**reasoning, "selected": effort or (CLAUDE_OFF if engine == "claude" else None)}}


async def save_chatgpt(model, effort):
    """ChatGPT 的模型和档位：只能从当前账号刚读到的模型目录里选，存进授权记录。"""
    from . import workspace_agent_siwc_auth as auth
    from .model_catalog import chatgpt_models
    rows = await chatgpt_models()
    row = next((item for item in rows if item["id"] == model), None)
    if row is None:
        raise ValueError("请从当前账号返回的模型中选择。")
    auth.runtime().select_model(model, [item["id"] for item in rows], effort=effort, reasoning=row["reasoning"])
    return {"model": model, "reasoning": {**row["reasoning"], "selected": effort}}
