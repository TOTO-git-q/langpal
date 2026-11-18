"""主引擎：Claude Agent SDK，走本机 `claude` CLI 的订阅认证（无需 API key）。

聊天走 ClaudeSDKClient 常驻会话：每个 session_key（persona+session）对应一个已 connect() 的
客户端，缓存在本 provider 实例里，进程存活期间反复复用 —— 这样系统提示词只在会话第一次
connect() 时生效一次，之后同一 session_key 的所有轮次都复用同一个 CLI 子进程 + 对话状态，
天然实现"人设/记忆注入只在会话开始时冻结"（新系统提示词传进来也不会再生效，直到这个
session_key 被 drop 掉重连）。

杂活（词卡/句子解析/记忆抽取等一次性 JSON 生成）走一次性的 query()，档位 Haiku，不占用/
不污染聊天的常驻会话。

不接自定义工具（v1 范围内），tools=[] 彻底禁用全部内置工具（Bash/Read/Edit/...），
确保这是纯对话、没有权限提示会卡住无人值守的服务端调用。
"""

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    CLIConnectionError,
    CLIJSONDecodeError,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ProcessError,
    ResultMessage,
    StreamEvent,
    TextBlock,
    query,
)

from ..db import get_conn
from ..image_utils import EXT_MEDIA_TYPE
from ..services.prompts import current_session_recap
from ._settings import get_setting
from .base import LLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WP-N：图片消息。SDK 的 ClaudeSDKClient.query() 接受 str | AsyncIterable[dict]——
# 非字符串分支把每个 dict 原样 json.dumps 写进 CLI 的 stdin，不做任何校验/转换
# （见 .venv/Lib/site-packages/claude_agent_sdk/client.py 的 query() 实现）。字符串
# 分支自己拼的消息形状是 {"type":"user","message":{"role":"user","content":<str>},
# "parent_tool_use_id":None}，content 字段本来就是 Anthropic Messages API 的形状——
# 把它换成 [{"type":"text",...},{"type":"image","source":{...}}] 这种 content block
# 列表，就是 API 原生的多模态消息格式，不需要开 Read 工具、不需要 CLI 的 @路径 语法。
# ---------------------------------------------------------------------------


def _image_content_block(path: str) -> dict[str, Any] | None:
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError:
        logger.warning("agent_sdk: 读取图片失败，跳过这张：%s", path, exc_info=True)
        return None
    ext = p.suffix.lower().lstrip(".")
    media_type = EXT_MEDIA_TYPE.get(ext, "image/png")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


def _build_vision_message(user_text: str, image_paths: list[str]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for path in image_paths:
        block = _image_content_block(path)
        if block is not None:
            blocks.append(block)
    if user_text:
        blocks.append({"type": "text", "text": user_text})
    return {
        "type": "user",
        "message": {"role": "user", "content": blocks},
        "parent_tool_use_id": None,
    }

# ---------------------------------------------------------------------------
# Claude CLI 会话续接（对齐 codex 线程的 thread/resume 语义）：
# CLI 的会话文件持久在 ~/.claude 下，SDK 的 ResultMessage 每轮都带 session_id。
# 指针按整把 session_key（p{人设}s{会话}）存进 session_pointers 表：主聊天里几个人设共用
# 一段对话，各有各的 Claude 会话，互不覆盖。后端重启后用 options.resume 续接——上下文不丢。
# 旧列 sessions.claude_session_id 已迁走，不再读写。
# ---------------------------------------------------------------------------
POINTER_ENGINE = "claude"


def _load_claude_session_id(session_key: str) -> str | None:
    from ..services import session_pointers
    return session_pointers.get(session_key, POINTER_ENGINE)


def _store_claude_session_id(session_key: str, value: str | None) -> None:
    from ..services import session_pointers
    session_pointers.set(session_key, value, POINTER_ENGINE)


def _find_windows_claude_exe() -> str | None:
    """Windows 专用：定位 npm 全局安装里真正的原生 claude.exe。

    claude_agent_sdk 在 Windows 上会拒绝直接执行 npm 装出来的 claude.cmd/claude.ps1 shim
    （cmd.exe 参数注入风险，SDK 自己的安全策略），但 npm 包其实内置了一个原生 claude.exe——
    只是 PATH 上暴露给 `claude` 命令的是那层 .cmd shim，`shutil.which("claude")` 找不到
    里面这个真正能被直接 CreateProcess 的原生可执行文件。这里把它挖出来，直接把
    ClaudeAgentOptions.cli_path 指过去，不装/不改任何东西。
    """
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(
            Path(appdata)
            / "npm"
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
    try:
        result = subprocess.run(
            ["npm", "root", "-g"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            candidates.append(
                Path(result.stdout.strip())
                / "@anthropic-ai"
                / "claude-code"
                / "bin"
                / "claude.exe"
            )
    except Exception:
        logger.debug("npm root -g 查询失败，跳过（不影响 APPDATA 兜底路径）", exc_info=True)
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


_windows_cli_path: str | None = None
_windows_cli_resolved = False


def _resolve_cli_path() -> str | None:
    """非 Windows 直接返回 None，让 SDK 走自己正常能用的默认查找逻辑。"""
    global _windows_cli_path, _windows_cli_resolved
    if sys.platform != "win32":
        return None
    if not _windows_cli_resolved:
        exe_on_path = shutil.which("claude.exe")
        _windows_cli_path = exe_on_path or _find_windows_claude_exe()
        _windows_cli_resolved = True
        if _windows_cli_path:
            logger.info("Windows 原生 claude.exe 定位到：%s", _windows_cli_path)
        else:
            logger.warning("没找到原生 claude.exe，聊天引擎在这台 Windows 机器上大概率不可用")
    return _windows_cli_path


CHAT_MODEL = "sonnet"
UTILITY_MODEL = "haiku"

REASONING_LEVELS = ("off", "low", "medium", "high", "xhigh", "max")
_REASONING_DEFAULT = "off"


def _resolve_chat_model() -> str:
    """settings.chat_model_claude（默认 sonnet）。只对新建的 client 生效；改设置时
    routers/config.py 会调 registry.refresh_claude_clients() 断开常驻客户端，下一条消息
    用新模型重连并 resume 原会话（会话指针不动）。"""
    v = get_setting("chat_model_claude", CHAT_MODEL).strip()
    from ..services.model_catalog import model_id
    return v if model_id(v) else CHAT_MODEL


def _resolve_reasoning() -> str:
    """settings.chat_reasoning_claude：off（默认，不开扩展思考），或 SDK 为当前模型声明的某个档位
    （POST /engines/claude/reasoning 按接口读到的列表校验后写入；REASONING_LEVELS 只是常见值）。"""
    v = get_setting("chat_reasoning_claude", _REASONING_DEFAULT).strip().lower()
    return v if re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", v) else _REASONING_DEFAULT


def _resolve_effort(model=None) -> str | None:
    """思考档位对应的 SDK effort；off 时为 None。model 参数只为兼容旧调用点，不再使用。"""
    level = _resolve_reasoning()
    return None if level == "off" else level


def _thinking_options() -> dict[str, Any]:
    """聊天客户端的思考相关 ClaudeAgentOptions 字段。"""
    effort = _resolve_effort()
    if effort is None:
        return {"thinking": {"type": "disabled"}}
    return {"effort": effort}

# health() 是本地、零 I/O 的粗判：CLI 存不存在 + 最近是否报过错，不做真实探测请求
# （真实的限流/不可用检测是 stream_chat/generate_json 抛错时反应式触发，见 registry.py）。
_HEALTH_COOLDOWN_SEC = 30.0

_JSON_SYSTEM_PROMPT = (
    "你只输出一个合法 JSON 对象或数组，不要任何解释文字，不要 markdown 代码块包裹，"
    "不要多余的前后缀。"
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _extract_json(text: str):
    text = (text or "").strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"agent_sdk generate_json: 无法从回复中解析出 JSON：{text[:200]!r}")


class _UtilityPool:
    """杂活（generate_json）的预热备用客户端池——解决"点词等一个 CLI 冷启动"的延迟。

    语义：每个客户端**只用一次**（上下文天然干净，JSON 任务互不污染），acquire 取走后
    立刻在后台暖新客户端补位；下一次调用直接拿到已 connect() 的进程，延迟≈纯生成时间。
    池空时（连发超过池深、或刚启动补位没跟上）现场冷启动兜底，行为等同旧实现。
    disconnect 也放后台，不占调用方的关键路径。
    """

    def __init__(self, size: int = 2) -> None:
        self._size = size
        self._pool: list[ClaudeSDKClient] = []
        self._warming = 0

    @staticmethod
    def _options() -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=_JSON_SYSTEM_PROMPT,
            model=UTILITY_MODEL,
            tools=[],
            allowed_tools=[],
            max_turns=1,
            cli_path=_resolve_cli_path(),
        )

    @staticmethod
    async def _spawn() -> ClaudeSDKClient:
        client = ClaudeSDKClient(options=_UtilityPool._options())
        await client.connect()
        return client

    def topup(self) -> None:
        """后台补位到目标池深；没有运行中的事件循环时静默跳过（比如同步上下文里初始化）。"""
        need = self._size - len(self._pool) - self._warming
        for _ in range(max(0, need)):
            self._warming += 1

            async def _fill() -> None:
                try:
                    self._pool.append(await self._spawn())
                except Exception:
                    logger.warning("utility pool 暖机失败（下次调用现场冷启动兜底）", exc_info=True)
                finally:
                    self._warming -= 1

            try:
                asyncio.get_running_loop().create_task(_fill())
            except RuntimeError:
                self._warming -= 1
                return

    async def acquire(self) -> ClaudeSDKClient:
        client = self._pool.pop() if self._pool else None
        self.topup()
        if client is None:
            client = await self._spawn()  # 池空兜底：等同旧的一次性冷启动
        return client

    def discard(self, client: ClaudeSDKClient) -> None:
        async def _bye() -> None:
            try:
                await client.disconnect()
            except Exception:
                pass

        try:
            asyncio.get_running_loop().create_task(_bye())
        except RuntimeError:
            pass


class AgentSDKProvider(LLMProvider):
    """LLMProvider 实现：主引擎。一个进程内单例（由 registry 持有）。"""

    def __init__(self) -> None:
        self._clients: dict[str, ClaudeSDKClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._resumed: set[str] = set()  # 本进程里靠 resume 续起来的 session_key（失败时要清掉库里的坏 id）
        self._last_failure_at: float = 0.0
        self._utility_pool = _UtilityPool()
        self._utility_pool.topup()  # 启动就开始暖机（无事件循环时静默跳过，首次调用再暖）

    def _note_failure(self) -> None:
        self._last_failure_at = time.monotonic()

    def _lock_for(self, session_key: str) -> asyncio.Lock:
        lock = self._locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_key] = lock
        return lock

    async def _connected_client(
        self, session_key: str, system_prompt: str
    ) -> ClaudeSDKClient:
        client = self._clients.get(session_key)
        if client is not None:
            return client
        # 有落库的 CLI 会话 id 就先尝试 resume（跨后端重启续上下文）；resume 连不上再退全新会话
        resume_id = _load_claude_session_id(session_key)
        attempts = [resume_id, None] if resume_id else [None]
        last_err: Exception | None = None
        for attempt in attempts:
            effective_system_prompt = system_prompt
            if attempt is None:
                # 真正 fresh connect（没有会话指针可 resume，或 resume 那次连接
                # 失败退回这里）：WP-M——如果 DB 里这个会话已经有历史（比如刚从别的引擎切
                # 过来），把当前会话尾部拼进 system prompt，避免"新引擎=瞬间失忆"。
                try:
                    recap = current_session_recap(session_key)
                except Exception:
                    logger.warning("current_session_recap 失败，跳过（不影响主连接）", exc_info=True)
                    recap = ""
                if recap:
                    effective_system_prompt = system_prompt + recap
            options = ClaudeAgentOptions(
                system_prompt=effective_system_prompt,
                model=_resolve_chat_model(),
                resume=attempt,
                tools=[],  # 彻底禁用内置工具：纯对话，v1 不接自定义工具
                allowed_tools=[],
                include_partial_messages=True,  # 打开逐字 delta（StreamEvent）
                cli_path=_resolve_cli_path(),  # Windows: 绕开 npm 的 .cmd shim，直连原生 exe
                **_thinking_options(),
            )
            client = ClaudeSDKClient(options=options)
            try:
                await client.connect()
            except (CLIConnectionError, ProcessError) as e:
                last_err = e
                if attempt is not None:
                    logger.warning("claude 会话 resume 失败，清掉坏 id 改用全新会话：%s", session_key)
                    _store_claude_session_id(session_key, None)
                    continue
                self._note_failure()
                raise
            if attempt is not None:
                self._resumed.add(session_key)
            else:
                self._resumed.discard(session_key)
            self._clients[session_key] = client
            return client
        self._note_failure()
        raise last_err  # attempts 至少含 None，理论到不了这里；保险

    async def warm(self, session_key: str, system_prompt: str) -> None:
        """预热（POST /api/chat/main/warm）：把这个 key 的常驻客户端先连好（connect + resume），不发任何请求。
        和 stream_chat 用同一把锁：预热还在连的时候来了第一轮，第一轮等它连完直接用，不会连两次。"""
        async with self._lock_for(session_key):
            await self._connected_client(session_key, system_prompt)

    async def forget_session(self, session_key: str) -> None:
        """人设/会话被删除时的尽力清理：断开这个 session_key 的常驻客户端（有就断，没有就跳过）。"""
        await self._drop_session(session_key)

    async def drop_all_sessions(self) -> None:
        """WP-M：引擎切换时调用——断开**全部**在飞常驻客户端（不分 persona/session）。
        `claude_session_id` 落在 DB 里，断开这里的内存客户端不影响下次 resume。"""
        for session_key in list(self._clients.keys()):
            await self._drop_session(session_key)

    async def _drop_session(self, session_key: str) -> None:
        client = self._clients.pop(session_key, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                logger.exception("agent_sdk disconnect 出错（忽略）：%s", session_key)

    def supports_vision(self) -> bool:
        return True

    async def stream_chat(
        self,
        session_key: str,
        system_prompt: str,
        user_text: str,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[str]:
        lock = self._lock_for(session_key)
        async with lock:
            client = await self._connected_client(session_key, system_prompt)
            got_delta = False
            tail_parts: list[str] = []
            try:
                if image_paths:
                    message = _build_vision_message(user_text, image_paths)

                    async def _one_shot():
                        yield message

                    await client.query(_one_shot())
                else:
                    await client.query(user_text)
                async for message in client.receive_response():
                    if isinstance(message, StreamEvent):
                        event = message.event or {}
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                piece = delta.get("text") or ""
                                if piece:
                                    got_delta = True
                                    yield piece
                        continue
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text:
                                tail_parts.append(block.text)
                        continue
                    if isinstance(message, ResultMessage):
                        if message.is_error:
                            self._note_failure()
                            raise RuntimeError(
                                "agent_sdk result error: "
                                f"{message.subtype} {message.result or ''} "
                                f"(http={message.api_error_status})"
                            )
                        # 每轮都把 CLI 会话 id 落库（resume 后 id 可能轮换，存最新的）
                        new_cli_sid = getattr(message, "session_id", None)
                        if new_cli_sid:
                            _store_claude_session_id(session_key, new_cli_sid)
                        break
            except (CLIConnectionError, ProcessError, CLIJSONDecodeError):
                self._note_failure()
                if session_key in self._resumed:
                    # resume 起来的客户端在对话期才暴雷（会话文件坏/过期）：清掉坏 id，
                    # 避免下次重连又拿同一个 id 死循环
                    self._resumed.discard(session_key)
                    _store_claude_session_id(session_key, None)
                await self._drop_session(session_key)
                raise
            if not got_delta and tail_parts:
                # 兜底：这个 CLI 版本没有转发逐字 stream_event，退化成整段一次性吐出，不丢文本
                yield "".join(tail_parts)

    async def generate_json(self, prompt: str, schema: dict) -> dict:
        # 预热池：客户端已 connect()，这里的延迟≈纯 Haiku 生成时间（旧实现每次冷启动 CLI）
        client = await self._utility_pool.acquire()
        text_parts: list[str] = []
        try:
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text:
                            text_parts.append(block.text)
                elif isinstance(message, ResultMessage) and message.is_error:
                    self._note_failure()
                    raise RuntimeError(
                        f"agent_sdk generate_json error: {message.subtype} {message.result}"
                    )
        except (CLIConnectionError, ProcessError, CLIJSONDecodeError):
            self._note_failure()
            raise
        finally:
            self._utility_pool.discard(client)  # 一次一用，断开放后台
        return _extract_json("".join(text_parts))

    async def health(self) -> bool:
        if sys.platform == "win32":
            cli_ok = _resolve_cli_path() is not None
        else:
            cli_ok = shutil.which("claude") is not None
        if not cli_ok:
            return False
        if time.monotonic() - self._last_failure_at < _HEALTH_COOLDOWN_SEC:
            return False
        return True
