"""第四个聊天引擎：ChatGPT 账号登录（SIWC），经官方 openai SDK 的 Responses 接口调用。

上下文和 DeepSeek 一样：provider 按常驻 session_key（p{persona}s{session}）在内存里维护多轮历史，
这个 key 第一次出现（后端刚重启 / 刚降级切过来 / 世界书重连）时从库里补种近期上文；之后每轮只
追加，不冷启动。同一会话的轮次由 services/chat.py 的 gen_lock 串行，这里不再按会话建锁。
ChatGPT 没有原生会话指针，离开这个引擎时只丢内存历史。
"""
import json

from jsonschema import ValidationError, validate

from .base import LLMProvider
from .deepseek import _seed_history_from_db
from ..services import chatgpt_sdk, workspace_agent_siwc as siwc, workspace_agent_siwc_auth as auth

_HISTORY_MAX_MESSAGES = 30


class ChatGPTProvider(LLMProvider):
    def __init__(self):
        self._histories: dict[str, list[dict]] = {}

    def supports_vision(self) -> bool:
        return False  # 图片由 chat.py 交给 Claude 描述成文字

    def configured(self) -> bool:
        return siwc.configured()

    async def health(self) -> bool:
        # 只看本地授权状态，不发探测请求。
        return self.configured()

    def forget_session(self, session_key):
        self._histories.pop(session_key, None)

    def drop_all_sessions(self):
        self._histories.clear()

    def _history_for(self, session_key, system_prompt):
        history = self._histories.get(session_key)
        if history is None:
            # 冻结：只在这个 key 第一次出现时采用 system_prompt，并从 DB 补种近期上文。
            history = [{"role": "system", "content": system_prompt}] + _seed_history_from_db(session_key)
            self._histories[session_key] = history
        return history

    async def _model(self):
        try:
            return await auth.get_selected_model()
        except auth.AuthorizationRequired:
            raise siwc.SiwcFailure("authentication", "请先连接 ChatGPT 并选择模型。") from None

    async def stream_chat(self, session_key, system_prompt, user_text, image_paths=None):
        model = await self._model()
        history = self._history_for(session_key, system_prompt)
        turn = {"role": "user", "content": user_text}
        text = await chatgpt_sdk.complete({
            "model": model, "instructions": history[0]["content"], "input": history[1:] + [turn],
        })
        # 成功才进历史（失败的轮次不留半截）；守门重生成依赖"刚才的回复还在历史里"。
        history.extend([turn, {"role": "assistant", "content": text}])
        if len(history) - 1 > _HISTORY_MAX_MESSAGES:
            del history[1:len(history) - _HISTORY_MAX_MESSAGES]
        yield text

    async def generate_json(self, prompt, schema):
        model = await self._model()
        text = await chatgpt_sdk.complete({
            "model": model,
            "instructions": "Return only one JSON object matching the supplied JSON schema. Do not add Markdown.",
            "input": json.dumps({"request": prompt, "schema": schema}, ensure_ascii=False),
        })
        try:
            result = siwc._load(text)
            if not isinstance(result, dict):
                raise ValueError()
            validate(result, schema)
            return result
        except (ValueError, TypeError, ValidationError):
            raise siwc.SiwcFailure("response", "ChatGPT 返回的格式不符合这次任务，请重试。") from None
