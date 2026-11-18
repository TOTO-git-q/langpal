"""四个聊天引擎（Claude / DeepSeek / 自定义端点 / ChatGPT 账号）的离线回归：临时 SQLite + 假 provider。

覆盖：chatgpt 出错的降级顺序与半开重试；思考档位从接口读、读不到时标 default；保存只接受读到的档位；
SIWC 接口的来源检查；登录 begin 链接由授权运行时自己的本机端口应答（不经过全局访问守卫）。
不读写真实的 %LOCALAPPDATA%\\LangPal\\siwc，不联网。
"""
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.providers import registry  # noqa: E402
from app.services import model_catalog, model_reasoning, workspace_agent_siwc_auth as auth  # noqa: E402


class Fake:
    def __init__(self, healthy=True, claude=False):
        self.healthy, self.forgot = healthy, []
        if claude:
            async def forget_session(key):
                self.forgot.append(key)
            self.forget_session = forget_session

    def forget_session(self, key):
        self.forgot.append(key)

    def configured(self):
        return True

    async def health(self):
        return self.healthy


class TempDB(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "engines.db"
        conn = sqlite3.connect(self.path)
        conn.executescript((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (5, 'Tester', 'ja', '{}')")
        conn.execute("INSERT INTO sessions (id, persona_id, language) VALUES (19, 5, 'ja')")
        conn.execute("INSERT INTO session_pointers (session_id, persona_id, engine, pointer) VALUES (19, 5, 'claude', 'cli-old')")
        conn.commit()
        conn.close()
        p = patch.object(db, "DB_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        self.reset()
        self.addCleanup(self.reset)
        model_reasoning._observed.clear()

    def reset(self):
        registry._session_engine.clear()
        registry._session_intended.clear()
        registry._pinned_at.clear()
        registry._primary = registry._fallback = registry._custom = registry._chatgpt = None

    def setting(self, key, value):
        conn = sqlite3.connect(self.path)
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()

    def value(self, sql):
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(sql).fetchone()
            return row[0] if row else None
        finally:
            conn.close()


class ChatGPTFallbackTests(TempDB):
    def test_chatgpt_falls_back_to_claude_then_deepseek(self):
        gpt, claude, ds = Fake(), Fake(claude=True), Fake()
        registry._chatgpt, registry._primary, registry._fallback = gpt, claude, ds
        self.setting("chat_engine", "chatgpt")
        key = "p5s19"
        self.assertIs(registry.get_provider(key, is_new_session=False), gpt)
        self.assertIs(asyncio.run(registry.report_failure(key, RuntimeError("429"))), claude)
        self.assertIn(key, gpt.forgot)  # 离开 chatgpt 只丢内存历史（它没有原生会话指针）
        self.assertEqual(self.value("SELECT degraded FROM (SELECT value AS degraded FROM settings WHERE key='degraded')"), "1")
        # 半开重试：到点后回到意向引擎 chatgpt，离开 claude 作废它的原生指针
        registry._pinned_at[key] -= registry._RETRY_INTENDED_AFTER_SEC + 1
        self.assertIs(asyncio.run(self._provider_in_loop(key)), gpt)
        self.assertIsNone(self.value("SELECT (SELECT pointer FROM session_pointers WHERE session_id = 19 AND persona_id = 5 AND engine = 'claude')"))
        registry.report_recovery(key)
        self.assertEqual(self.value("SELECT value FROM settings WHERE key='degraded'"), "0")
        # Claude 不可用时直接落到 DeepSeek
        claude.healthy = False
        self.assertIs(asyncio.run(registry.report_failure(key, RuntimeError("down"))), ds)
        # 两个都不可用：不降级，原样报错
        registry._session_engine[key] = "chatgpt"
        ds.healthy = False
        self.assertIsNone(asyncio.run(registry.report_failure(key, RuntimeError("down"))))

    async def _provider_in_loop(self, key):
        return registry.get_provider(key, is_new_session=False)

    def test_chatgpt_accepted_for_every_feature_and_codex_is_claude(self):
        self.setting("chat_engine", "chatgpt")
        self.setting("utility_engine", "chatgpt")
        self.setting("listening_subscription", "chatgpt")
        registry.normalize_settings()
        self.assertEqual(registry.feature_engine("chat"), "chatgpt")
        self.assertEqual(registry.feature_engine("utility"), "chatgpt")
        self.assertEqual(registry.feature_engine("listening"), "chatgpt")
        self.setting("chat_engine", "codex")
        self.assertEqual(registry.feature_engine("chat"), "claude")


class ReasoningTests(TempDB):
    def test_levels_come_from_the_api_or_are_marked_default(self):
        api = model_reasoning.decorate("deepseek", [
            {"id": "thinker", "label": "Thinker", "reasoning": model_reasoning.options({"supported_reasoning_levels": ["minimal", "high"]})},
            {"id": "plain", "label": "Plain"},
        ])
        self.assertEqual(api[0]["reasoning"]["source"], "api")
        self.assertEqual([x["id"] for x in api[0]["reasoning"]["levels"]], ["minimal", "high"])
        self.assertEqual(api[1]["reasoning"]["source"], "default")
        self.assertEqual([x["id"] for x in api[1]["reasoning"]["levels"]], list(model_reasoning.DEFAULT_LEVELS))

    def test_saved_choice_is_bound_to_connection_and_model(self):
        reasoning = model_reasoning.options({"supported_reasoning_levels": ["minimal", "high"]})
        with self.assertRaises(ValueError):
            model_reasoning.save("custom", "thinker", "medium", reasoning)
        self.setting("custom_base_url", "https://one.example/v1")
        model_reasoning.save("custom", "thinker", "minimal", reasoning)
        self.assertEqual(model_reasoning.get_effort("custom", "thinker"), "minimal")
        self.assertIsNone(model_reasoning.get_effort("custom", "other-model"))
        self.setting("custom_base_url", "https://two.example/v1")
        self.assertIsNone(model_reasoning.get_effort("custom", "thinker"))

    def test_claude_choice_writes_the_chat_settings(self):
        reasoning = model_reasoning.options({"supportedEffortLevels": ["low", "high", "max"]})
        model_reasoning.save("claude", "opus", "max", reasoning)
        self.assertEqual(self.value("SELECT value FROM settings WHERE key='chat_model_claude'"), "opus")
        self.assertEqual(self.value("SELECT value FROM settings WHERE key='chat_reasoning_claude'"), "max")
        from app.providers import agent_sdk
        self.assertEqual(agent_sdk._thinking_options(), {"effort": "max"})
        model_reasoning.save("claude", "opus", None, reasoning)
        self.assertEqual(agent_sdk._thinking_options(), {"thinking": {"type": "disabled"}})

    def test_models_endpoint_and_reasoning_endpoint(self):
        from fastapi.testclient import TestClient
        from app import main
        rows = [{"id": "deepseek-chat", "label": "deepseek-chat"},
                {"id": "deepseek-reasoner", "label": "R", "reasoning": {"levels": [{"id": "high", "label": "high"}], "default": "high"}}]
        client = TestClient(main.app, base_url="http://127.0.0.1:8787")
        with patch.object(model_catalog, "discover", AsyncMock(side_effect=lambda engine, transport=None: [dict(r) for r in rows])):
            body = client.get("/api/engines/deepseek/models").json()["models"]
            self.assertEqual([m["reasoning"]["source"] for m in body], ["default", "api"])
            self.assertEqual(client.post("/api/engines/deepseek/reasoning", json={"model": "deepseek-reasoner", "effort": "low"}).status_code, 422)
            ok = client.post("/api/engines/deepseek/reasoning", json={"model": "deepseek-reasoner", "effort": "high"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["reasoning"]["selected"], "high")
            self.assertEqual(model_reasoning.get_effort("deepseek", "deepseek-reasoner"), "high")
            self.assertEqual(client.get("/api/engines/codex/models").status_code, 404)

    def test_chatgpt_models_come_from_the_account_catalog(self):
        listing = [{"slug": "gpt-a", "display_name": "GPT A", "reasoning": {"levels": [{"id": "low", "label": "low"}], "default": None}},
                   {"slug": "gpt-b", "display_name": "GPT B"}]
        runtime = SimpleNamespace(get_access_token=AsyncMock(return_value="t"), select_model=lambda *a, **k: None,
                                  metadata=lambda: {"selected_model": None})
        with patch("app.services.workspace_agent_siwc.list_models", AsyncMock(return_value=listing)), \
                patch.object(auth, "runtime", return_value=runtime):
            rows = asyncio.run(model_catalog.chatgpt_models())
            self.assertEqual([(r["id"], r["reasoning"]["source"]) for r in rows], [("gpt-a", "api"), ("gpt-b", "default")])
            with self.assertRaises(ValueError):
                asyncio.run(model_reasoning.save_chatgpt("not-listed", None))
            self.assertEqual(asyncio.run(model_reasoning.save_chatgpt("gpt-a", "low"))["reasoning"]["selected"], "low")


class SiwcRouteTests(TempDB):
    def client(self, client=("127.0.0.1", 50000)):
        from fastapi.testclient import TestClient
        from app import main
        return TestClient(main.app, base_url="http://127.0.0.1:8787", client=client)

    def test_status_requires_local_same_origin(self):
        fake = SimpleNamespace(enabled=True, metadata=lambda: {"configured": True, "authorization_state": "authorized",
                                                               "selected_model": "gpt-a", "account_label": "someone@example.com"})
        with patch.object(auth, "runtime", return_value=fake):
            c = self.client()
            self.assertEqual(c.get("/api/workspace-agent/siwc/status").status_code, 200)
            self.assertEqual(c.get("/api/workspace-agent/siwc/status", headers={"Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(c.get("/api/workspace-agent/siwc/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
            remote = self.client(client=("192.168.1.20", 50000))
            self.assertEqual(remote.get("/api/workspace-agent/siwc/status").status_code, 403)
            # 会改状态的 POST 还要求 Origin 和 Host 完全对上
            self.assertEqual(c.post("/api/workspace-agent/siwc/login", json={"approved": True}).status_code, 403)

    def test_login_link_is_served_by_the_runtime_not_fastapi(self):
        from app.services import workspace_agent_siwc_live as live

        class Protector:
            def CryptProtectData(self, plain, *args):
                return b"x" + plain

            def CryptUnprotectData(self, raw, *args):
                return None, raw[1:]

        with tempfile.TemporaryDirectory() as folder:
            store = live.DPAPIStore(enabled=True, root=folder, protector=Protector())
            runtime = live.SIWCRuntime(enabled=True, store=store, client=live.OfficialClient(enabled=False))
            try:
                started = runtime.start(approved=True)
                url = started["browser_url"]
                self.assertTrue(url.startswith("http://127.0.0.1:") and "/begin?ticket=" in url)
                self.assertNotIn(":8787", url)
                response = httpx.get(url, follow_redirects=False, trust_env=False, timeout=5)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["location"].startswith(auth.AUTHORIZE_ENDPOINT))
                self.assertTrue(json.loads((Path(folder) / "session.dpapi").read_bytes()[1:])["host_id"].startswith("urn:uuid:"))
            finally:
                runtime.cancel()


if __name__ == "__main__":
    unittest.main()
