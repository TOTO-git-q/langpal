"""Pinned official DeepSeek Harness transport, with no model-visible host tools.

只给课程管家（services/workspace_agent_deepseek.py）用；主聊天的 DeepSeek 走 providers/deepseek.py 的直连 HTTP。

Each turn owns a disposable Harness home. Chat history stays in LangPal; credentials
are passed via the SDK's supported in-memory api_key option, never a config file.
"""
import asyncio
import importlib.metadata
import json
import os
import tempfile
import threading
from pathlib import Path

from .deepseek import _deepseek_config

SDK_VERSION = "0.2.1rc2"
MESSAGES_BASE = "https://api.deepseek.com/anthropic"
MAX_INPUT_BYTES = 160_000
MAX_OUTPUT_BYTES = 100_000
DISABLED_ROWS = (
    "tool-fs", "tool-working-directory", "persistent-bash", "persistent-pwsh",
    "terminal-bash", "terminal-pwsh", "pty", "subprocess", "attachment-local",
    "session-log-deepseek", "plugin-package-inventory-deepseek",
    "compaction-basic", "image-offload",
)


class DSHFailure(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def installed():
    try:
        return all(importlib.metadata.version(name) == SDK_VERSION for name in
                   ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"))
    except importlib.metadata.PackageNotFoundError:
        return False


def valid_config(config):
    from ..services.model_catalog import model_id
    return (isinstance(config, tuple) and len(config) == 3
            and config[0] == "https://api.deepseek.com"
            and isinstance(config[1], str) and bool(config[1])
            and model_id(config[2]))


def safe_patch(model, system_prompt):
    # sdk-minimal is a standalone, explicit tree. It has no managed credentials,
    # external plugin discovery, local instruction discovery, web, or subagents.
    # Disable its entire tool-producing roster and optional data contributors.
    return ([{"id": name, "disabled": True} for name in DISABLED_ROWS] + [
        {"id": "system-prompt", "config": {"includeHarnessIdentity": False,
            "includeRuntimeContext": False, "personaPrefix": system_prompt}},
        {"id": "llm-deepseek", "config": {"apiKeyEnv": "DEEPSEEK_API_KEY",
            "models": [{"id": model}], "streamIdleTimeoutMs": 30000}},
    ])


def isolated_env(root):
    # The SDK merges env onto os.environ. Explicitly blank every inherited value
    # except OS process-launch necessities, rather than inheriting other tokens,
    # DSH overrides, proxies, Node hooks, or third-party provider configuration.
    allow = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
    env = {key: "" for key in os.environ if key.upper() not in allow}
    env.update(HOME=root, USERPROFILE=root, APPDATA=str(Path(root)/"appdata"),
               LOCALAPPDATA=str(Path(root)/"localappdata"), DSH_TELEMETRY_DISABLED="1")
    return env


async def complete(system_prompt, prompt, *, config=None, harness_factory=None, timeout=90):
    """Official SDK invocation. harness_factory is only for isolated offline tests."""
    config = _deepseek_config() if config is None else config
    if not valid_config(config):
        raise DSHFailure("configuration", "请在模型与账号中配置官方 DeepSeek API。")
    if len((system_prompt + prompt).encode("utf-8")) > MAX_INPUT_BYTES:
        raise DSHFailure("size", "输入材料过多，请缩短后重试。")
    if harness_factory is None and not installed():
        raise DSHFailure("sdk", "DeepSeek Harness SDK 未安装或版本不匹配。")
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    factory = harness_factory or DeepSeekHarness
    from ..services.model_reasoning import get_effort
    effort = get_effort("deepseek", config[2])
    cancelled = threading.Event()
    holder = {}
    lock = threading.Lock()

    def stop():
        cancelled.set()
        with lock:
            h = holder.get("harness")
        if h is not None:
            h.close()

    def work():
        with tempfile.TemporaryDirectory(prefix="langpal-dsh-") as root:
            patch = Path(root) / "langpal.patch.json"
            patch.write_text(json.dumps(safe_patch(config[2], system_prompt), ensure_ascii=False), encoding="utf-8")
            h = factory(DeepSeekHarnessConfig(provider="deepseek-official", model=config[2], reasoning_effort=effort,
                profile="sdk-minimal", cwd=root, runtime_cwd=root,
                dsh_home=str(Path(root)/"home"), patches=(str(patch),),
                env=isolated_env(root), base_url=MESSAGES_BASE, api_key=config[1],
                max_tokens=4096, initialize_timeout_seconds=20,
                request_timeout_seconds=30, shutdown_timeout_seconds=1))
            with lock:
                holder["harness"] = h
            timer = threading.Timer(timeout, stop)
            timer.daemon = True
            try:
                if cancelled.is_set():
                    raise TimeoutError()
                timer.start()
                h.start()
                if cancelled.is_set():
                    raise TimeoutError()
                result = h.run(prompt)
                if cancelled.is_set():
                    raise TimeoutError()
                text = result.final_response
                if result.finish_reason != "completed" or not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
                    raise DSHFailure("response", "DeepSeek Harness 未返回完整有效的结果。")
                return text
            finally:
                timer.cancel()
                with lock:
                    holder.pop("harness", None)
                h.close()
    task = asyncio.create_task(asyncio.to_thread(work))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.to_thread(stop)
        try:
            await asyncio.shield(task)
        except Exception:
            pass
        raise
    except DSHFailure:
        raise
    except Exception:
        # SDK diagnostics may contain provider payloads or process details.
        code = "timeout" if cancelled.is_set() else "service"
        raise DSHFailure(code, "DeepSeek Harness 请求超时。" if code == "timeout" else
                         "DeepSeek Harness 请求失败，请检查模型配置或稍后重试。") from None


def strict_json(text):
    def reject(_):
        raise ValueError("Non-finite JSON")
    return json.loads(text, parse_constant=reject)
