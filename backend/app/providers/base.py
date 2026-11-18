"""LLM Provider 抽象：项目里所有模型访问的唯一通道。

实现两个：agent_sdk.py（主引擎，Claude Agent SDK 走订阅）、deepseek.py（限流降级）。
选择与降级切换收在 registry.get_provider() 里，业务代码不感知具体引擎。
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):

    @abstractmethod
    def stream_chat(
        self,
        session_key: str,
        system_prompt: str,
        user_text: str,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """人设对话。session_key 标识常驻会话（persona+session），逐段 yield 文本。

        image_paths（WP-N）：绝对路径列表，默认 None = 纯文本，所有旧调用点行为不变。
        是否真的把图片发给模型取决于 supports_vision()——不支持视觉的引擎收到非空
        image_paths 应静默忽略图片、只按文字继续，不抛异常（是否该给这个引擎传图片
        是调用方 services/chat.py 先用 supports_vision() 判断好的，这里的忽略只是
        兜底防御，不是主路径）。"""

    def supports_vision(self) -> bool:
        """该引擎是否原生支持把图片发给模型看（而不是靠 services/chat.py 的外部描述兜底）。
        默认 False；claude/codex 覆写为 True，见 docs/history/API-v1.5-images.md 的三引擎能力矩阵。"""
        return False

    @abstractmethod
    async def generate_json(self, prompt: str, schema: dict) -> dict:
        """杂活单次调用（词卡/句子解析/记忆抽取），返回符合 schema 的 dict。
        主引擎用 Haiku 档，降级引擎用 deepseek-chat。"""

    @abstractmethod
    async def health(self) -> bool:
        """引擎是否可用（用于 /api/health 与降级判断）。"""
