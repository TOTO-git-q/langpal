"""主聊天里几个人设共用一段对话：引擎层按整把 key（p{人设}s{会话}）各管各的。

假 Claude SDK 客户端 + 临时 SQLite，不连任何模型。覆盖：两个人设在同一会话里各自 resume 各自的指针、
互不覆盖；一个人设的坏指针自愈不影响另一个；离开引擎只作废那一把 key；补种只把自己说的当 assistant；
归档副人设清掉她在主聊天里的内存会话和指针；学习模块四个设置键；课程管家 chat.room 工具。
"""
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from claude_agent_sdk import CLIConnectionError, ResultMessage  # noqa: E402

from app import db  # noqa: E402
from app.providers import agent_sdk, deepseek, registry  # noqa: E402
from app.services import chat_room, session_pointers  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "pointers.db"
        conn = sqlite3.connect(self.path)
        conn.executescript((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (5, '糖糖', 'ja', '{}')")
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (6, 'Emma', 'en', '{}')")
        conn.execute("INSERT INTO sessions (id, persona_id, language) VALUES (19, 5, 'ja')")
        conn.execute("INSERT INTO sessions (id, persona_id, language) VALUES (30, 6, 'en')")  # Emma 的旧对话
        conn.execute("INSERT INTO settings (key, value) VALUES ('chat_main_session', '19')")
        conn.execute("INSERT INTO settings (key, value) VALUES ('chat_main', ?)",
                     (json.dumps({"primary_id": 5, "guests": [{"persona_id": 6}]}),))
        conn.commit()
        conn.close()
        p = patch.object(db, "DB_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        self.reset()
        self.addCleanup(self.reset)

    def reset(self):
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


class FakeClient:
    made = []
    bad = set()

    def __init__(self, options):
        self.options = options
        FakeClient.made.append(self)

    async def connect(self):
        if self.options.resume in FakeClient.bad:
            raise CLIConnectionError("cannot resume " + self.options.resume)

    async def disconnect(self):
        pass

    async def query(self, prompt):
        self.prompt = prompt

    async def receive_response(self):
        # 这个客户端被谁用就回报一个只属于它的新 CLI 会话 id
        marker = self.options.system_prompt
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                            num_turns=1, session_id="new-" + marker)


class ClaudePointerTests(Base):
    def setUp(self):
        super().setUp()
        FakeClient.made, FakeClient.bad = [], set()
        for p in (patch.object(agent_sdk, "ClaudeSDKClient", FakeClient),
                  patch.object(agent_sdk, "_resolve_cli_path", return_value=None),
                  patch.object(agent_sdk, "current_session_recap", return_value="")):
            p.start()
            self.addCleanup(p.stop)

    async def _turn(self, provider, key, marker):
        return [part async for part in provider.stream_chat(key, marker, "hi")]

    def test_two_personas_in_one_session_keep_their_own_pointer(self):
        session_pointers.set("p5s19", "cli-ame")
        session_pointers.set("p6s19", "cli-emma")
        provider = agent_sdk.AgentSDKProvider()

        async def scenario():
            await self._turn(provider, "p5s19", "ame")
            await self._turn(provider, "p6s19", "emma")
        asyncio.run(scenario())
        resumed = {c.options.system_prompt: c.options.resume for c in FakeClient.made}
        self.assertEqual(resumed, {"ame": "cli-ame", "emma": "cli-emma"})
        # 各自写回各自的新 id，没有互相覆盖
        self.assertEqual(session_pointers.get("p5s19"), "new-ame")
        self.assertEqual(session_pointers.get("p6s19"), "new-emma")
        self.assertEqual(self.sql("SELECT claude_session_id FROM sessions WHERE id = 19")[0][0], None)  # 旧列不再写

    def test_bad_pointer_heals_only_its_own_key(self):
        session_pointers.set("p5s19", "cli-ame")
        session_pointers.set("p6s19", "cli-broken")
        FakeClient.bad = {"cli-broken"}
        provider = agent_sdk.AgentSDKProvider()
        asyncio.run(provider._connected_client("p6s19", "emma"))
        self.assertEqual([c.options.resume for c in FakeClient.made], ["cli-broken", None])
        self.assertIsNone(session_pointers.get("p6s19"))
        self.assertEqual(session_pointers.get("p5s19"), "cli-ame")

    def test_leaving_an_engine_invalidates_only_that_key(self):
        session_pointers.set("p5s19", "cli-ame")
        session_pointers.set("p6s19", "cli-emma")
        session_pointers.set("p6s30", "cli-emma-old")

        class Fake:
            async def health(self):
                return True

            def configured(self):
                return True

            def forget_session(self, key):
                pass

        async def forget(key):
            pass
        claude = Fake()
        claude.forget_session = forget
        registry._primary, registry._fallback = claude, Fake()
        registry.get_provider("p6s19", is_new_session=False)
        asyncio.run(registry.report_failure("p6s19", RuntimeError("down")))
        self.assertIsNone(session_pointers.get("p6s19"))
        self.assertEqual(session_pointers.get("p5s19"), "cli-ame")
        self.assertEqual(session_pointers.get("p6s30"), "cli-emma-old")
        # 换主引擎时作废的是这个引擎的全部指针
        asyncio.run(registry.drop_all_live_sessions("claude", "deepseek"))
        self.assertIsNone(session_pointers.get("p5s19"))

    def test_reasoning_change_keeps_every_pointer(self):
        session_pointers.set("p5s19", "cli-ame")
        session_pointers.set("p6s19", "cli-emma")
        registry._primary = agent_sdk.AgentSDKProvider()
        asyncio.run(registry.refresh_claude_clients())
        self.assertEqual((session_pointers.get("p5s19"), session_pointers.get("p6s19")), ("cli-ame", "cli-emma"))


class SeedTests(Base):
    def test_seed_counts_only_her_own_lines_as_assistant(self):
        rows = [("user", "おはよう", None), ("assistant", "おはよ！", 5), ("assistant", "Morning!", 6),
                ("user", "Emma, coffee?", None), ("assistant", "Sure, black.", 6), ("user", "いま送ったやつ", None)]
        for role, content, pid in rows:
            self.sql("INSERT INTO messages (session_id, role, content, persona_id) VALUES (19, ?, ?, ?)", (role, content, pid))
        emma = deepseek.DeepSeekProvider()._history_for("p6s19", "system")
        self.assertEqual([m["role"] for m in emma[1:]], ["user", "user", "assistant", "user", "assistant"])
        self.assertEqual(emma[2]["content"], "（糖糖说）おはよ！")
        ame = deepseek.DeepSeekProvider()._history_for("p5s19", "system")
        self.assertEqual([m["content"] for m in ame[1:] if m["role"] == "assistant"], ["おはよ！"])
        # 她最后一次开口之后别人说的都在尾部，补种时掐掉（这一轮的补课块会单独带上）
        self.assertNotIn("Sure, black.", [m["content"] for m in ame[1:] if m["role"] == "assistant"])


class ArchiveTests(Base):
    def client(self):
        from fastapi.testclient import TestClient
        from app import main
        return TestClient(main.app, base_url="http://127.0.0.1:8787")

    def test_archiving_a_guest_drops_her_main_chat_session_and_pointers(self):
        session_pointers.set("p5s19", "cli-ame")
        session_pointers.set("p6s19", "cli-emma")
        session_pointers.set("p6s30", "cli-emma-old")
        with patch.object(registry, "drop_persona_sessions", AsyncMock()) as drop:
            self.assertEqual(self.client().delete("/api/personas/6").status_code, 200)
        drop.assert_awaited_once()
        persona_id, session_ids = drop.call_args.args
        self.assertEqual((persona_id, sorted(session_ids)), (6, [19, 30]))
        self.assertIsNone(session_pointers.get("p6s19"))
        self.assertIsNone(session_pointers.get("p6s30"))
        self.assertEqual(session_pointers.get("p5s19"), "cli-ame")

    def test_primary_can_be_archived_but_not_the_last_card(self):
        c = self.client()
        with patch.object(registry, "drop_persona_sessions", AsyncMock()):
            self.assertEqual(c.delete("/api/personas/5").status_code, 200)
            self.assertEqual(self.sql("SELECT value FROM settings WHERE key = 'chat_main_session'")[0][0], "19")
            others = [r[0] for r in self.sql("SELECT id FROM personas WHERE archived_at IS NULL AND id != 6")]
            for pid in others:
                self.assertEqual(c.delete(f"/api/personas/{pid}").status_code, 200)
            self.assertEqual(c.delete("/api/personas/6").status_code, 409)
        self.assertIsNone(self.sql("SELECT archived_at FROM personas WHERE id = 6")[0][0])

    def test_drop_persona_sessions_forgets_her_key_in_the_main_chat(self):
        forgot = []

        class Mem:
            def forget_session(self, key):
                forgot.append(key)
        registry._fallback = Mem()
        registry._session_engine["p6s19"] = "deepseek"
        registry._session_engine["p5s19"] = "deepseek"
        asyncio.run(registry.drop_persona_sessions(6, [30, 19]))
        self.assertEqual(sorted(forgot), ["p6s19", "p6s30"])
        self.assertNotIn("p6s19", registry._session_engine)
        self.assertIn("p5s19", registry._session_engine)


class LearningSettingsTests(ArchiveTests):
    def test_defaults_and_validation(self):
        c = self.client()
        settings = c.get("/api/settings").json()
        self.assertEqual((settings["review_target_retention"], settings["review_new_per_day"],
                          settings["review_mix"], settings["reading_questions_first"]), (0.9, 12, 1, 0))
        for body in ({"review_target_retention": 0.7}, {"review_target_retention": "x"},
                     {"review_new_per_day": 51}, {"review_new_per_day": 2.5}, {"review_mix": 2},
                     {"reading_questions_first": "yes"}, {"chat_main": "{}"}, {"chat_main_session": "1"},
                     {"reader_zotero_connection": "{}"}):
            self.assertEqual(c.put("/api/settings", json=body).status_code, 422, body)
        r = c.put("/api/settings", json={"review_target_retention": "0.85", "review_new_per_day": 20,
                                         "review_mix": False, "reading_questions_first": 1})
        self.assertEqual(r.status_code, 200, r.text)
        got = r.json()
        self.assertEqual((got["review_target_retention"], got["review_new_per_day"], got["review_mix"],
                          got["reading_questions_first"]), (0.85, 20, 0, 1))
        for hidden in ("chat_main", "chat_main_session", "reader_zotero_connection"):
            self.assertNotIn(hidden, got)


class ChatRoomToolTests(Base):
    def setUp(self):
        super().setUp()
        from app.services import workspace_agent as agent
        self.agent = agent
        self.sql("INSERT INTO personas (id, name, language, profile_json) VALUES (7, 'Lena', 'de', '{}')")

    def preview(self, args):
        return self.agent.preview_operations([self.agent.Operation(tool="chat.room", args=args)], {})["proposal"]

    def main(self):
        return json.loads(self.sql("SELECT value FROM settings WHERE key = 'chat_main'")[0][0])

    def test_preview_apply_undo(self):
        before = self.main()
        p = self.preview({"fun": True, "fun_languages": ["ja", "en"], "primary_chime": 40,
                          "guests": [{"persona_id": 6, "rule": {"type": "keyword", "keywords": ["coffee"]}, "chime": 10},
                                     {"persona_id": 7}]})
        self.assertEqual(self.main(), before)  # 预览不落库
        view = p["changes"][0]
        self.assertEqual(view["tool"], "chat.room")
        self.assertTrue(view["after"]["fun"])
        self.agent.commit(p["id"], False, {})
        saved = self.main()
        self.assertTrue(saved["fun"])
        self.assertEqual(saved["primary_chime"], 40)
        self.assertEqual([g["persona_id"] for g in saved["guests"]], [6, 7])
        self.agent.commit(p["id"], True, {})
        self.assertEqual(self.main(), before)

    def test_switch_primary_keeps_the_timeline(self):
        p = self.preview({"primary_id": 6, "guests": [{"persona_id": 5}]})
        self.agent.commit(p["id"], False, {})
        self.assertEqual(self.main()["primary_id"], 6)
        self.assertEqual(self.sql("SELECT value FROM settings WHERE key = 'chat_main_session'")[0][0], "19")

    def test_invalid_and_conflicts(self):
        with self.assertRaises(self.agent.AgentError):
            self.preview({"guests": [{"persona_id": 99}]})
        with self.assertRaises(self.agent.AgentError):
            self.preview({"language": "fr"})  # 没添加的语言
        p = self.preview({"guests": [{"persona_id": 7}]})
        self.sql("UPDATE personas SET archived_at = datetime('now') WHERE id = 7")
        with self.assertRaises(self.agent.Conflict):
            self.agent.commit(p["id"], False, {})
        self.sql("UPDATE personas SET archived_at = NULL WHERE id = 7")
        q = self.preview({"primary_chime": 5})
        self.sql("UPDATE settings SET value = ? WHERE key = 'chat_main'", (json.dumps({"primary_id": 5}),))
        with self.assertRaises(self.agent.Conflict):  # 外面改过了，不覆盖
            self.agent.commit(q["id"], False, {})

    def test_inspect_and_voice_samples(self):
        summary = self.agent.inspect_workspace()["chat_main"]
        self.assertEqual((summary["primary_id"], summary["primary_name"], summary["session_id"]), (5, "糖糖", 19))
        p = self.agent.preview_operations([self.agent.Operation(tool="persona.edit", args={
            "id": 6, "voice_samples": {"en": ["Oh come on!", "  Oh come on! ", "Fine, fine."]}})], {})["proposal"]
        self.agent.commit(p["id"], False, {})
        profile = json.loads(self.sql("SELECT profile_json FROM personas WHERE id = 6")[0][0])
        self.assertEqual(profile["voice_samples"]["en"], ["Oh come on!", "Fine, fine."])
        with self.assertRaises(self.agent.AgentError):
            self.agent.preview_operations([self.agent.Operation(tool="persona.edit", args={
                "id": 6, "voice_samples": {"en": ["x" * 80]}})], {})


if __name__ == "__main__":
    unittest.main()
