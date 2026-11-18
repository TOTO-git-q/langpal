"""聊天核心回到"每个人设一条对话"后的离线回归：临时 SQLite + 假 provider，不连任何模型。

覆盖：常驻 session key p{persona}s{session}、语义回忆注入、长期记忆抽取后台钩子、「上次聊到」卡片、
语言守门重生成、mood/sticker/fix 标记不落库、口语课桥双向、图片消息、插话打断、
降级默认开且失败会切换、遗留 chatgpt/codex 引擎当 claude、
Claude 会话指针续接与坏 id 自愈、DeepSeek 首次从 DB 补种、设置与人设归档、跨站请求 403。
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.providers import agent_sdk, deepseek, registry  # noqa: E402
from app.services import bubbles, chat as chat_service, coach_bridge, guard, hooks, course, word_glosses  # noqa: E402

JA_REPLY = "うん、元気だよ！今日はなにしてた？\n⟦mood:happy⟧"


class FakeProvider:
    def __init__(self, name, replies=None, *, vision=True, fail=False, claude=False):
        self.name, self.replies, self.vision, self.fail = name, list(replies or []), vision, fail
        self.calls, self.forgot = [], []
        if claude:
            async def forget_session(key):
                self.forgot.append(key)

            async def drop_all_sessions():
                self.forgot.append("*")

            self.forget_session, self.drop_all_sessions = forget_session, drop_all_sessions

    def forget_session(self, key):
        self.forgot.append(key)

    def drop_all_sessions(self):
        self.forgot.append("*")

    def supports_vision(self):
        return self.vision

    def configured(self):
        return True

    async def health(self):
        return True

    async def stream_chat(self, session_key, system_prompt, user_text, image_paths=None):
        self.calls.append({"key": session_key, "system": system_prompt, "user": user_text, "images": image_paths})
        if self.fail:
            raise RuntimeError("synthetic engine failure")
        yield self.replies.pop(0) if self.replies else JA_REPLY


class TempDB(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "chat.db"
        conn = sqlite3.connect(self.path)
        conn.executescript((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (5, 'Tester', 'ja', '{}')")
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (6, 'Emma', 'en', '{}')")
        conn.execute("INSERT INTO sessions (id, persona_id, language) VALUES (19, 5, 'ja')")
        for key, value in (("batch_debounce_sec", "0"), ("coach_bridge", "0")):
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        p = patch.object(db, "DB_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(hooks.flush)  # 后台的 hook 线程用完临时库再删
        self._reset_registry()
        self.addCleanup(self._reset_registry)

    def _reset_registry(self):
        registry._session_engine.clear()
        registry._session_intended.clear()
        registry._pinned_at.clear()
        registry._primary = registry._fallback = registry._custom = registry._chatgpt = None

    def sql(self, query, args=()):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(query, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def setting(self, key, value):
        self.sql("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


class ChatTurnTests(TempDB):
    """主聊天（docs/MAIN-CHAT.md）：人设 5 是主人设，会话 19 是她原来那段、被钉成主聊天。"""

    def setUp(self):
        super().setUp()
        chat_service._session_states.clear()
        self.setting("chat_main", json.dumps({"primary_id": 5}))  # 库里还有预置的 1/2/3 号人设
        self.claude = FakeProvider("claude", claude=True)
        registry._primary = self.claude
        self.recall = AsyncMock(return_value=[{"when": "昨日", "text": "对方：猫の名前はタマ", "message_ids": [1]}])
        self.extract = AsyncMock()
        self.embed = AsyncMock()
        self.coach_record = AsyncMock(return_value=1)
        patches = [
            patch.object(chat_service.recall_service, "recall", self.recall),
            patch.object(chat_service.recall_service, "embed_new_messages", self.embed),
            patch("app.services.memoryx.maybe_extract", self.extract),
            patch.object(chat_service, "_tokenize", lambda text, lang: [{"i": 0, "surface": text, "lemma": text, "reading": "", "pos": "", "clickable": True, "collected": False}]),
            patch.object(word_glosses, "schedule", lambda *a: None),
            patch.object(word_glosses, "attach_cached", lambda *a: None),
            patch.object(chat_service, "first_pause_seconds", lambda: 0),
            patch.object(chat_service, "bubble_pause_seconds", lambda text: 0),
            patch.object(bubbles, "DELTA_PAUSE_SEC", 0),
            patch.object(coach_bridge, "record_fixes", self.coach_record),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_turn(self, text, image_url=None, *, to=None, sticker=None, settle=True):
        async def scenario():
            events = [item async for item in chat_service.run_chat_turn(text, image_url, sticker, to)]
            if settle:
                await asyncio.sleep(0.05)  # 让后台钩子（记忆抽取/向量索引/口语课记账）跑完
            return events
        events = asyncio.run(scenario())
        hooks.flush()
        return events

    def test_main_chat_turn_uses_resident_key_recall_and_memory_hook(self):
        events = self.run_turn("元気？")
        names = [name for name, _ in events]
        self.assertEqual(names[:3], ["read", "speaker", "guard"])  # 已读在她拿起手机那一刻
        self.assertEqual(names[-1], "done")
        self.assertEqual(self.claude.calls[0]["key"], "p5s19")
        self.recall.assert_awaited_once()
        self.assertEqual(self.recall.call_args.args[0], 5)
        self.assertIn("猫の名前はタマ", self.claude.calls[0]["user"])
        self.extract.assert_awaited_once_with(19, 5)
        self.embed.assert_awaited_once_with(19)
        done = dict(events)["done"]
        self.assertEqual((done["session_id"], done["persona_id"], done["persona_name"], done["language"]),
                         (19, 5, "Tester", "ja"))
        rows = self.sql("SELECT role, content, persona_id, language, read_at FROM messages WHERE session_id = 19 ORDER BY id")
        self.assertEqual([r["role"] for r in rows], ["user", "assistant"])
        self.assertIsNotNone(rows[0]["read_at"])
        self.assertEqual((rows[1]["persona_id"], rows[1]["language"]), (5, "ja"))
        self.assertNotIn("⟦", rows[1]["content"])
        self.run_turn("うん")
        self.assertEqual([c["key"] for c in self.claude.calls], ["p5s19", "p5s19"])
        self.assertEqual(self.claude.forgot, [])

    def test_guest_first_time_gets_her_old_session_as_context_card(self):
        self.sql("INSERT INTO sessions (id, persona_id, language) VALUES (21, 6, 'en')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (21, 'user', 'I watched a movie yesterday')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (21, 'assistant', 'Nice, which one?')")
        self.setting("chat_main", json.dumps({"primary_id": 5, "primary_chime": 0, "guests": [{"persona_id": 6}]}))
        self.claude.replies = ["Hey there, good to see you!\n⟦mood:happy⟧"]
        events = self.run_turn("@Emma hi", settle=False)
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(self.claude.calls[0]["key"], "p6s19")
        self.assertIn("I watched a movie yesterday", self.claude.calls[0]["system"])
        self.assertEqual([d["language"] for n, d in events if n == "speaker"], ["en"])

    def test_naming_someone_outside_the_chat_is_refused(self):
        events = self.run_turn("hi", to=6)
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(self.claude.calls, [])

    def test_archived_primary_hands_the_timeline_to_the_next_persona(self):
        self.run_turn("元気？")
        self.sql("UPDATE personas SET archived_at = datetime('now') WHERE id = 5")
        events = self.run_turn("もしもし？")
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(self.claude.calls[-1]["key"], "p1s19")  # 剩下的第一张人设卡接手  # 主人设换人不换时间线

    def test_language_guard_regenerates_in_same_session_and_strips_markers(self):
        self.claude.replies = [
            "Hello there, how are you doing today?\n⟦mood:happy⟧",
            "ねえ、それは「行きます」のほうが自然だよ。\n⟦sticker:not-a-real-sticker⟧\n⟦fix:行くます=>行きます⟧\n⟦mood:smug⟧",
        ]
        events = self.run_turn("明日学校に行くます")
        guard_event = dict(events)["guard"]
        self.assertEqual((guard_event["status"], guard_event["retries"], guard_event["mood"]), ("retried", 1, "smug"))
        self.assertEqual(len(self.claude.calls), 2)
        self.assertEqual(self.claude.calls[1]["key"], "p5s19")
        self.assertEqual(self.claude.calls[1]["user"], guard.correction_prompt("ja"))
        stored = " ".join(r["content"] for r in self.sql("SELECT content FROM messages WHERE role = 'assistant'"))
        for marker in ("⟦", "mood:", "fix:", "sticker:"):
            self.assertNotIn(marker, stored)
        self.coach_record.assert_awaited_once()
        self.assertEqual(self.coach_record.call_args.args[3], [("行くます", "行きます")])

    def test_coach_lesson_note_is_injected_and_marked_seen(self):
        with patch.object(coach_bridge, "lesson_note", return_value=("【刚上完口语课】\n", "lesson-1")), \
                patch.object(coach_bridge, "mark_seen") as seen:
            self.run_turn("ただいま")
        self.assertIn("【刚上完口语课】", self.claude.calls[0]["user"])
        seen.assert_called_once()
        self.assertEqual(seen.call_args.args[1:], (5, "lesson-1"))

    def test_image_message_is_passed_to_vision_engine(self):
        with tempfile.TemporaryDirectory() as uploads:
            name = "a" * 32 + ".png"
            (Path(uploads) / name).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            with patch.object(chat_service, "UPLOAD_DIR", Path(uploads)):
                self.run_turn("", f"/uploads/{name}")
        self.assertEqual(len(self.claude.calls[0]["images"]), 1)
        self.assertEqual(self.sql("SELECT image_path FROM messages WHERE role = 'user'")[0]["image_path"], name)

    def test_interjection_interrupts_delivery_and_hands_over(self):
        self.claude.replies = ["一つ目だよ\n---\n二つ目だよ\n---\n三つ目だよ\n⟦mood:normal⟧", JA_REPLY]

        async def scenario():
            with patch.object(chat_service, "first_pause_seconds", lambda: 0.4):
                first = asyncio.create_task(self._collect("長い話して"))
                await asyncio.sleep(0.1)
                second = await self._collect("ちょっと待って、やっぱり別の話")
                return await first, second

        first, second = asyncio.run(scenario())
        self.assertEqual(first[-1][0], "interrupted")
        self.assertEqual(second[-1][0], "done")
        self.assertIn("二つ目だよ", self.claude.calls[1]["user"])  # 没发出的话交接给下一轮

    async def _collect(self, text):
        return [item async for item in chat_service.run_chat_turn(text)]


    def test_failure_falls_back_to_deepseek_by_default(self):
        self.claude.fail = True
        fallback = FakeProvider("deepseek")
        registry._fallback = fallback
        self.sql("INSERT OR REPLACE INTO session_pointers (session_id, persona_id, engine, pointer) VALUES (19, 5, 'claude', 'cli-old')")
        events = self.run_turn("元気？")
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(fallback.calls[0]["key"], "p5s19")
        self.assertIsNone(self.sql("SELECT (SELECT pointer FROM session_pointers WHERE session_id = 19 AND persona_id = 5 AND engine = 'claude')")[0][0])
        self.assertEqual(self.sql("SELECT value FROM settings WHERE key = 'degraded'")[0][0], "1")

    def test_fallback_can_be_turned_off(self):
        self.setting("chat_fallback", "none")
        self.claude.fail = True
        registry._fallback = FakeProvider("deepseek")
        events = self.run_turn("元気？")
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(registry._fallback.calls, [])


class RegistryTests(TempDB):
    def test_fallback_defaults_on_and_half_open_retry(self):
        self.assertTrue(registry.fallback_enabled())
        claude, ds = FakeProvider("claude", claude=True), FakeProvider("deepseek")
        registry._primary, registry._fallback = claude, ds
        key = "p5s19"
        self.assertIs(registry.get_provider(key, is_new_session=False), claude)
        self.assertIs(asyncio.run(registry.report_failure(key, RuntimeError("403"))), ds)
        self.assertIs(registry.get_provider(key, is_new_session=False), ds)
        registry._pinned_at[key] -= registry._RETRY_INTENDED_AFTER_SEC + 1
        self.assertIs(registry.get_provider(key, is_new_session=False), claude)
        registry.report_recovery(key)
        self.assertEqual(self.sql("SELECT value FROM settings WHERE key = 'degraded'")[0][0], "0")

    def test_chatgpt_is_an_engine_and_legacy_codex_is_claude(self):
        gpt = FakeProvider("chatgpt")
        registry._chatgpt = gpt
        self.setting("chat_engine", "chatgpt")
        self.assertIs(registry.get_provider("p5s19", is_new_session=True), gpt)
        registry.normalize_settings()
        self.assertEqual(self.sql("SELECT value FROM settings WHERE key = 'chat_engine'")[0][0], "chatgpt")
        claude = FakeProvider("claude", claude=True)
        for legacy in ("codex",):
            self._reset_registry()
            registry._primary = claude
            self.setting("chat_engine", legacy)
            self.setting("utility_engine", legacy)
            self.setting("listening_subscription", legacy)
            self.assertIs(registry.get_provider("p5s19", is_new_session=True), claude)
            self.assertEqual(registry.feature_engine("chat"), "claude")
            registry.normalize_settings()
            rows = dict((r[0], r[1]) for r in self.sql("SELECT key, value FROM settings WHERE key IN ('chat_engine','utility_engine','listening_subscription')"))
            self.assertEqual(rows, {"chat_engine": "claude", "utility_engine": "auto", "listening_subscription": ""})

    def test_utility_auto_prefers_deepseek_key(self):
        # A developer's .env may carry a real key; this test is about the stored setting only.
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.assertEqual(registry._utility_engine(), "claude")
            self.setting("deepseek_api_key", "synthetic-key")
            self.assertEqual(registry._utility_engine(), "deepseek")
            self.setting("utility_engine", "claude")
            self.assertEqual(registry._utility_engine(), "claude")

    def test_refresh_claude_keeps_session_pointers(self):
        claude = FakeProvider("claude", claude=True)
        registry._primary = claude
        self.sql("INSERT OR REPLACE INTO session_pointers (session_id, persona_id, engine, pointer) VALUES (19, 5, 'claude', 'cli-keep')")
        asyncio.run(registry.refresh_claude_clients())
        self.assertEqual(claude.forgot, ["*"])
        self.assertEqual(self.sql("SELECT (SELECT pointer FROM session_pointers WHERE session_id = 19 AND persona_id = 5 AND engine = 'claude')")[0][0], "cli-keep")

    def test_reasoning_setting_maps_to_sdk_options(self):
        self.assertEqual(agent_sdk._thinking_options(), {"thinking": {"type": "disabled"}})
        self.setting("chat_reasoning_claude", "high")
        self.setting("chat_model_claude", "opus")
        self.assertEqual(agent_sdk._thinking_options(), {"effort": "high"})
        self.assertEqual(agent_sdk._resolve_chat_model(), "opus")


class ProviderSessionTests(TempDB):
    def test_claude_resumes_stored_id_and_heals_bad_one(self):
        from claude_agent_sdk import CLIConnectionError

        made = []

        class FakeClient:
            def __init__(self, options):
                self.options = options
                made.append(self)

            async def connect(self):
                if self.options.resume == "bad-id":
                    raise CLIConnectionError("cannot resume")

            async def disconnect(self):
                pass

        with patch.object(agent_sdk, "ClaudeSDKClient", FakeClient), \
                patch.object(agent_sdk, "_resolve_cli_path", return_value=None):
            provider = agent_sdk.AgentSDKProvider()
            self.sql("INSERT OR REPLACE INTO session_pointers (session_id, persona_id, engine, pointer) VALUES (19, 5, 'claude', 'good-id')")
            asyncio.run(provider._connected_client("p5s19", "system"))
            self.assertEqual(made[-1].options.resume, "good-id")
            self.assertNotIn("no-session-persistence", made[-1].options.extra_args)

            provider = agent_sdk.AgentSDKProvider()
            self.sql("INSERT OR REPLACE INTO session_pointers (session_id, persona_id, engine, pointer) VALUES (19, 5, 'claude', 'bad-id')")
            asyncio.run(provider._connected_client("p5s19", "system"))
            self.assertIsNone(made[-1].options.resume)
            self.assertIsNone(self.sql("SELECT (SELECT pointer FROM session_pointers WHERE session_id = 19 AND persona_id = 5 AND engine = 'claude')")[0][0])

    def test_deepseek_seeds_history_from_db_once(self):
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', 'おはよう')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'assistant', 'おはよ！')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', 'いま送ったやつ')")
        provider = deepseek.DeepSeekProvider()
        history = provider._history_for("p5s19", "system")
        self.assertEqual([m["role"] for m in history], ["system", "user", "assistant"])
        self.assertIs(provider._history_for("p5s19", "other"), history)


class ApiTests(TempDB):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app import main

        cls.TestClient, cls.main = TestClient, main

    def client(self, base="http://127.0.0.1:8787"):
        return self.TestClient(self.main.app, base_url=base)

    def test_cross_site_requests_are_refused(self):
        c = self.client()
        self.assertEqual(c.get("/api/languages").status_code, 200)
        self.assertEqual(c.get("/api/languages", headers={"Origin": "http://127.0.0.1:8787"}).status_code, 200)
        self.assertEqual(c.get("/api/languages", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(c.get("/api/languages", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(c.post("/api/chat", json={"persona_id": 5, "text": "x"}, headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(c.get("/uploads/nothing.png", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(c.get("/avatars/nothing.png", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertNotIn("access-control-allow-origin", c.get("/api/languages", headers={"Origin": "https://evil.example"}).headers)

    def test_host_must_be_loopback_or_allowed(self):
        rebound = self.client("http://evil.example")
        self.assertEqual(rebound.get("/api/languages").status_code, 403)
        self.assertEqual(rebound.get("/api/health").status_code, 403)
        token = "test-access-code-123"
        with patch.dict(os.environ, {"LANGPAL_ALLOWED_HOSTS": "evil.example, 100.64.0.2",
                                     "LANGPAL_ACCESS_TOKEN": token}):
            rebound.cookies.set("lp_access", token)
            self.assertEqual(rebound.get("/api/languages").status_code, 200)
            lan = self.client("http://100.64.0.2:8787")
            lan.cookies.set("lp_access", token)
            self.assertEqual(lan.get("/api/languages").status_code, 200)
        self.assertEqual(self.client("http://localhost:8787").get("/api/languages").status_code, 200)

    def test_main_chat_routes_exist_and_languages_has_no_persona(self):
        c = self.client()
        for path in ("/api/chat/main", "/api/chat/archives", "/api/stickers"):  # 主聊天回来了
            self.assertEqual(c.get(path).status_code, 200, path)
        body = c.get("/api/languages").json()
        self.assertNotIn("persona_id", body)
        self.assertIn("ja", [item["tag"] for item in body["items"]])

    def test_settings_defaults_and_validation(self):
        c = self.client()
        self.setting("chat_engine", "codex")
        settings = c.get("/api/settings").json()
        self.assertEqual(settings["chat_engine"], "claude")
        self.assertNotIn("chatgpt_enabled", settings)
        self.assertEqual(settings["chat_fallback"], "enabled")
        for patch_body in ({"chat_engine": "codex"}, {"chatgpt_enabled": "1"}, {"chat_reasoning_claude": "huge"},
                           {"teaching_evaluator": "maybe"}, {"chat_main": "{}"}):
            self.assertEqual(c.put("/api/settings", json=patch_body).status_code, 422, patch_body)

    def test_user_name_settings(self):
        c = self.client()
        self.assertEqual(c.get("/api/settings").json()["user_name"], "")
        for value, expected in (("  ピ  ", "ピ"), ("名" * 24, "名" * 24), ("   ", "")):
            result = c.put("/api/settings", json={"user_name": value})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["user_name"], expected)
            self.assertEqual(c.get("/api/settings").json()["user_name"], expected)
        for value in ("名" * 25, None, 12, True, [], {}):
            self.assertEqual(c.put("/api/settings", json={"user_name": value}).status_code, 422)
        self.assertEqual(c.get("/api/settings").json()["user_name"], "")

    def test_reasoning_change_refreshes_claude_without_clearing_sessions(self):
        c = self.client()
        self.sql("INSERT OR REPLACE INTO session_pointers (session_id, persona_id, engine, pointer) VALUES (19, 5, 'claude', 'cli-keep')")
        with patch.object(registry, "refresh_claude_clients", AsyncMock()) as refresh, \
                patch.object(registry, "drop_all_live_sessions", AsyncMock()) as drop_all:
            self.assertEqual(c.put("/api/settings", json={"chat_reasoning_claude": "high"}).status_code, 200)
        refresh.assert_awaited_once()
        drop_all.assert_not_called()
        self.assertEqual(self.sql("SELECT (SELECT pointer FROM session_pointers WHERE session_id = 19 AND persona_id = 5 AND engine = 'claude')")[0][0], "cli-keep")

    def test_archiving_persona_drops_its_live_sessions(self):
        c = self.client()
        with patch.object(registry, "drop_persona_sessions", AsyncMock()) as drop:
            self.assertEqual(c.delete("/api/personas/5").status_code, 200)
        drop.assert_awaited_once_with(5, [19])
        self.assertIsNotNone(self.sql("SELECT archived_at FROM personas WHERE id = 5")[0][0])
        self.assertEqual(len(self.sql("SELECT id FROM sessions WHERE id = 19")), 1)

    def test_engine_status_is_four_engines(self):
        status = self.client().get("/api/engines/status").json()
        for engine in ("claude", "deepseek", "custom", "chatgpt"):
            self.assertIn(engine, status)
        self.assertNotIn("account_label", status["chatgpt"])
        for retired in ("codex", "providers", "feature_routes"):
            self.assertNotIn(retired, status)
        self.assertEqual(status["chat_fallback"], "enabled")


if __name__ == "__main__":
    unittest.main()
