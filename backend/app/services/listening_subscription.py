"""Listening authoring uses the application's shared model registry.

No independent CLI, credential lookup or hidden provider fallback lives here.
"""
from ..providers import registry


def selected_provider() -> str:
    return registry.get_feature_engine("listening")


async def generate(prompt: str, schema: dict | None = None) -> dict:
    provider = registry.get_feature_provider("listening")
    return await provider.generate_json(prompt, schema if schema is not None else {"type": "object"})
