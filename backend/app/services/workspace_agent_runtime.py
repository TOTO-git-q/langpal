"""课程管家的模型调用：Claude（Agent SDK）/ DeepSeek（DSH harness）/ ChatGPT（账号登录）三选一。

默认跟随主聊天引擎（settings.chat_engine）；也可以每轮单独指定。选中的那家不可用就直接报错，
不会自动换到别家（提案是要用户确认的改动，换模型会改变它的判断依据）。
"""

AGENT_PROVIDERS = ("claude", "deepseek", "chatgpt")


class RuntimeFailure(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _adapters():
    from . import workspace_agent_claude, workspace_agent_deepseek, workspace_agent_siwc
    return {"claude": workspace_agent_claude, "deepseek": workspace_agent_deepseek, "chatgpt": workspace_agent_siwc}


def main_engine():
    from ..providers import registry
    return registry.feature_engine("chat")


def resolve_provider(provider=None):
    """None / 'main' = 跟随主聊天引擎；主引擎是自定义端点时课程管家没有对应的适配器，要求明选。"""
    if provider in (None, "", "main"):
        try:
            provider = main_engine()
        except Exception:
            raise RuntimeFailure("provider_required", "读不到模型设置，请为这一轮明确选择模型。") from None
        if provider not in AGENT_PROVIDERS:
            raise RuntimeFailure("provider_required",
                                 "主聊天引擎是自定义端点，课程管家不能用它。请为这一轮选择 Claude、DeepSeek 或 ChatGPT。")
        return provider
    if provider not in AGENT_PROVIDERS:
        raise RuntimeFailure("provider_required", "课程管家只能用 Claude、DeepSeek 或 ChatGPT。")
    return provider


def _safe_capabilities(name, module):
    try:
        item = module.capabilities()
    except Exception:
        item = {"configured": False, "availability_note": "读不到这个模型服务的配置。"}
    return {"id": name, "label": item.get("label") or name, "configured": bool(item.get("configured")),
            "vision": bool(item.get("vision")), "model": item.get("model"),
            "configuration_state": item.get("configuration_state"),
            "availability_note": item.get("availability_note", "")}


def capabilities():
    """各家可不可用（本地检查，不联网）+ 跟随主引擎时实际会用哪家。"""
    providers = [_safe_capabilities(name, module) for name, module in _adapters().items()]
    try:
        main = main_engine()
    except Exception:
        main = None
    default = main if main in AGENT_PROVIDERS else None
    chosen = next((p for p in providers if p["id"] == default), None)
    return {"providers": providers, "main_engine": main, "default_provider": default,
            "default_note": "" if default else "主聊天引擎不是 Claude / DeepSeek / ChatGPT，课程管家需要每轮明确选择。",
            "available": any(p["configured"] for p in providers),
            "image_input": bool(chosen and chosen["configured"] and chosen["vision"])}


async def generate(prompt, context, tools, *, images=(), provider=None):
    provider = resolve_provider(provider)
    module = _adapters()[provider]
    choice = module.capabilities()
    if not choice.get("configured"):
        raise RuntimeFailure("provider_unavailable", choice.get("availability_note") or "所选模型服务尚未就绪，请检查该服务的配置。")
    if images and not choice.get("vision"):
        raise RuntimeFailure("images_unsupported", "所选模型服务不支持图片。请移除本轮图片，或选择支持图片的服务。")
    try:
        return await module.generate(prompt, context, tools, images=images)
    except module.ProviderFailure as error:
        raise RuntimeFailure(error.code, str(error)) from error
