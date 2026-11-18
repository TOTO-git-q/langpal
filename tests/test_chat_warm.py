"""聊天手感：攒批等待 1.2 秒、预热（POST /api/chat/main/warm）、read 提前发。临时库 + 假 Claude SDK，不连模型。

假 SDK：真的 AgentSDKProvider，只把 ClaudeSDKClient 换成数 connect 次数的假客户端，
这样能钉住"预热后第一轮不再 connect""预热和第一轮并发只连一次""预热的系统提示词和正常一轮一字不差"。
"""
import asyncio
import json
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

try:
    import test_lore as base
except ImportError:  # python -m unittest tests.test_chat_warm
    from tests import test_lore as base

from app.providers import agent_sdk, registry  # noqa: E402
from app.services import chat as chat_service, chat_room, clock, hooks, session_pointers  # noqa: E402


class FakeClient:
    made: list = []
    connect_delay = 0.0
    fail_connects = 0

    def __init__(self, options):
        self.options = options
        self.prompts = []
        FakeClient.made.append(self)

    async def connect(self):
        if FakeClient.connect_delay:
            await asyncio.sleep(FakeClient.connect_delay)
        if FakeClient.fail_connects:
            FakeClient.fail_connects -= 1
            raise agent_sdk.CLIConnectionError("synthetic connect failure")

    async def disconnect(self):
        pass

    async def query(self, prompt):
        self.prompts.append(prompt)

    async def receive_response(self):
        yield AssistantMessage(content=[TextBlock(text=base.JA_REPLY)], model="fake")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="cli-fake")


class WarmBase(base.Base):
    def setUp(self):
        super().setUp()
        self.chat_setup()  # 先装好别的假东西；Claude 换成真的 provider + 假客户端
        FakeClient.made, FakeClient.connect_delay, FakeClient.fail_connects = [], 0.0, 0
        for p in (patch.object(agent_sdk, "ClaudeSDKClient", FakeClient),
                  patch.object(agent_sdk, "_resolve_cli_path", return_value=None),
                  patch.object(chat_service, "_load_recall_model", lambda: None)):
            p.start()
            self.addCleanup(p.stop)
        self.provider = agent_sdk.AgentSDKProvider()
        registry._primary = self.provider
        self.seen_systems = []
        original = self.provider.stream_chat

        def spy(key, system, user, image_paths=None):
            self.seen_systems.append(system)
            return original(key, system, user, image_paths=image_paths)

        self.provider.stream_chat = spy
        chat_service._warm_state.update(key=None, at=0.0, task=None)
        self.addCleanup(chat_service._warm_state.update, key=None, at=0.0, task=None)

    async def warm(self):
        chat_service.warm_main()
        task = chat_service._warm_state["task"]
        if task is not None:
            await task

    async def collect(self, text):
        return [item async for item in chat_service.run_chat_turn(text)]


class WarmTests(WarmBase):
    def test_after_warming_the_first_turn_does_not_connect_and_uses_the_same_prompt(self):
        async def scenario():
            await self.warm()
            self.assertEqual(len(FakeClient.made), 1)
            return await self.collect("やあ")

        events = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(len(FakeClient.made), 1)  # 第一轮没有再 connect
        self.assertEqual(self.seen_systems[0], FakeClient.made[0].options.system_prompt)  # 一字不差
        self.assertEqual(FakeClient.made[0].prompts and len(FakeClient.made[0].prompts), 1)  # 预热不发请求
        self.assertEqual(self.sql("SELECT count(*) FROM messages WHERE role = 'assistant'")[0][0], 1)

    def test_warming_sends_nothing_and_writes_no_conversation(self):
        asyncio.run(self.warm())
        self.assertEqual(len(FakeClient.made), 1)
        self.assertEqual(FakeClient.made[0].prompts, [])
        self.assertEqual(self.sql("SELECT count(*) FROM messages")[0][0], 0)

    def test_warm_and_first_turn_in_parallel_connect_once(self):
        FakeClient.connect_delay = 0.3

        async def scenario():
            chat_service.warm_main()
            await asyncio.sleep(0.05)
            events = await self.collect("やあ")
            task = chat_service._warm_state["task"]
            if task is not None:
                await task
            return events

        events = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(len(FakeClient.made), 1)

    def test_warm_is_idempotent_and_redone_after_changes(self):
        async def scenario():
            self.assertEqual(chat_service.warm_main(), "started")
            self.assertEqual(chat_service.warm_main(), "running")  # 正在做：空操作
            await chat_service._warm_state["task"]
            await self.warm()  # 5 分钟内同样的东西做过：后台直接跳过
            self.assertEqual(len(FakeClient.made), 1)
            self.assertIsNotNone(chat_service._warm_state["key"])
            # 换主人设：预热状态作废，给新主人设连
            with closing(self.connect()) as conn:
                chat_room.save(conn, {"primary_id": 6})
                conn.commit()
            await self.warm()
            self.assertEqual(len(FakeClient.made), 2)
            self.assertEqual(self.provider._clients.keys(), {"p5s19", "p6s19"})
            # 过了 5 分钟、什么都没变：已经连着，不会再连
            chat_service._warm_state["at"] -= chat_service.WARM_FRESH_SEC + 1
            await self.warm()
            self.assertEqual(len(FakeClient.made), 2)

        asyncio.run(scenario())

    def test_world_book_change_invalidates_the_warm_state(self):
        async def scenario():
            await self.warm()
            key = chat_service._warm_state["key"]
            self.book([{"uid": 1, "constant": True, "content": "NEW SYSTEM LORE"}])
            await self.warm()
            self.assertNotEqual(chat_service._warm_state["key"], key)
            self.assertEqual(len(FakeClient.made), 2)  # 世界书变了：丢掉旧客户端，用新提示词连
            return await self.collect("やあ")

        events = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(len(FakeClient.made), 2)
        self.assertIn("NEW SYSTEM LORE", FakeClient.made[-1].options.system_prompt)

    def test_warm_failure_leaves_chat_working(self):
        FakeClient.fail_connects = 1
        with patch.object(chat_service, "_load_recall_model", side_effect=RuntimeError("no model")):
            asyncio.run(self.warm())
        self.assertIsNone(chat_service._warm_state["key"])
        events = asyncio.run(self.collect("やあ"))
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(len(FakeClient.made), 2)  # 预热那次失败了，第一轮自己连

    def test_startup_warms_only_after_recent_use(self):
        stamp = clock.stamp(clock.now() - timedelta(days=2))
        self.sql("INSERT INTO messages (session_id, role, content, created_at) VALUES (19, 'user', 'old', ?)", (stamp,))
        asyncio.run(chat_service.warm_on_startup(delay=0))
        self.assertEqual(len(FakeClient.made), 0)
        self.sql("INSERT INTO messages (session_id, role, content, created_at) VALUES (19, 'user', 'recent', ?)",
                 (clock.stamp(clock.now() - timedelta(hours=1)),))
        asyncio.run(chat_service.warm_on_startup(delay=0))
        self.assertEqual(len(FakeClient.made), 1)

    def test_warm_endpoint(self):
        c = self.client()
        with patch.object(chat_service, "warm_main", return_value="started") as warm:
            r = c.post("/api/chat/main/warm")
            self.assertEqual((r.status_code, r.json()), (202, {"status": "started"}))
            self.assertEqual(c.post("/api/chat/main/warm", headers={"Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(c.post("/api/chat/main/warm", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        warm.assert_called_once()


class RotationTests(WarmBase):
    """原生会话轮换：跑满 60 轮或用满 7 天、并且安静 3 小时以上 → 下一次连接开一段新的。"""

    def pointer(self, key="p5s19", ptr="cli-old", turns=0, age_days=0):
        session_pointers.set(key, ptr)
        self.sql("UPDATE session_pointers SET turns = ?, created_at = ? WHERE pointer = ?",
                 (turns, clock.stamp(clock.now() - timedelta(days=age_days)), ptr))

    def history(self, hours_ago, n=30):
        for i in range(n):
            role, pid = ("user", None) if i % 2 == 0 else ("assistant", 5)
            self.sql("INSERT INTO messages (session_id, role, persona_id, content, created_at) VALUES (19, ?, ?, ?, ?)",
                     (role, pid, f"昔の話 {i}", clock.stamp(clock.now() - timedelta(hours=hours_ago, minutes=n - i))))

    def test_sixty_turns_and_quiet_rotates_on_warm_and_recap_carries_over(self):
        self.pointer(turns=60)
        self.history(hours_ago=4)
        with self.assertLogs("app.services.chat", level="INFO") as logs:
            asyncio.run(self.warm())
        self.assertTrue(any("原生会话轮换：p5s19 跑了 60 轮" in line for line in logs.output))
        client = FakeClient.made[0]
        self.assertIsNone(client.options.resume)  # 不带 resume：新的一段
        self.assertIn("【当前会话回顾", client.options.system_prompt)
        self.assertIn("对方：昔の話 28", client.options.system_prompt)
        self.assertIn("你：昔の話 29", client.options.system_prompt)
        recap = client.options.system_prompt.split("【当前会话回顾", 1)[1]
        self.assertEqual(recap.count("昔の話"), 24)  # 放宽到 24 条，留最近的
        self.assertNotIn("昔の話 5\n", recap)
        self.assertIsNone(session_pointers.get("p5s19"))
        events = asyncio.run(self.collect("ひさしぶり"))
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(len(FakeClient.made), 1)  # 第一轮用的就是预热连好的新会话
        current = session_pointers.info("p5s19")
        self.assertEqual((current["pointer"], current["turns"]), ("cli-fake", 1))  # 指针换新、轮数从头算

    def test_below_threshold_or_recently_active_keeps_resuming(self):
        self.pointer(turns=59)
        self.history(hours_ago=4)
        asyncio.run(self.warm())
        self.assertEqual(FakeClient.made[-1].options.resume, "cli-old")
        self.provider._clients.clear()
        chat_service._warm_state.update(key=None, at=0.0)
        self.sql("UPDATE session_pointers SET turns = 60")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', 'たった今')")  # 刚聊过
        asyncio.run(self.warm())
        self.assertEqual(FakeClient.made[-1].options.resume, "cli-old")
        self.assertEqual(session_pointers.info("p5s19")["turns"], 60)

    def test_seven_days_old_rotates_at_turn_start_but_the_new_message_does_not_count(self):
        self.pointer(turns=3, age_days=8)
        self.history(hours_ago=5, n=4)
        events = asyncio.run(self.collect("おはよう"))
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertIsNone(FakeClient.made[0].options.resume)
        self.assertEqual(session_pointers.info("p5s19")["turns"], 1)

    def test_never_rotates_while_replying(self):
        self.pointer(turns=10)
        rotations = []
        original = registry.rotate_native

        async def spy(key, engine="claude"):
            rotations.append((key, len(FakeClient.made)))
            await original(key, engine)

        async def scenario():
            with patch.object(registry, "rotate_native", spy), \
                    patch.object(session_pointers, "due_for_rotation", return_value={"turns": 99, "age_days": 9}), \
                    patch.object(chat_service, "first_pause_seconds", lambda: 0.4):
                turn = asyncio.create_task(self.collect("やあ"))
                await asyncio.sleep(0.15)
                await self.warm()  # 回复还在冒：预热直接跳过，不轮换
                return await turn

        events = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(rotations, [("p5s19", 0)])  # 只在这一轮开始连接之前换过一次

    def test_each_persona_counts_on_its_own(self):
        self.pointer("p5s19", "cli-5", turns=60)
        self.pointer("p6s19", "cli-6", turns=3)
        self.history(hours_ago=4, n=2)
        self.assertIsNotNone(session_pointers.due_for_rotation("p5s19"))
        self.assertIsNone(session_pointers.due_for_rotation("p6s19"))
        session_pointers.count_turn("p6s19")
        self.assertEqual((session_pointers.info("p5s19")["turns"], session_pointers.info("p6s19")["turns"]), (60, 4))
        session_pointers.set("p6s19", "cli-6b")  # 同一段原生会话换了 id：轮数和开始时间不变
        self.assertEqual(session_pointers.info("p6s19")["turns"], 4)

    def test_memory_watermark_is_untouched_by_rotation(self):
        self.pointer(turns=60)
        self.history(hours_ago=4, n=12)
        self.sql("INSERT INTO settings (key, value) VALUES ('memx_watermark_session_19_p5', '12')")
        events = asyncio.run(self.collect("ただいま"))
        hooks.flush()
        self.assertEqual(events[-1][0], "done")
        self.assertIsNone(FakeClient.made[0].options.resume)
        self.assertEqual(self.sql("SELECT value FROM settings WHERE key = 'memx_watermark_session_19_p5'")[0][0], "12")
        self.extract.assert_awaited_once_with(19, 5)  # 抽取照常按她自己的水位走

    def test_memory_history_engines_seed_the_latest_thirty(self):
        from app.providers import deepseek
        self.history(hours_ago=1, n=50)
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', '今のメッセージ')")
        seeded = deepseek._seed_history_from_db("p5s19")
        texts = [m["content"] for m in seeded]
        self.assertLessEqual(len(seeded), 30)
        self.assertIn("昔の話 49", texts)
        self.assertNotIn("昔の話 0", texts)
        self.assertNotIn("今のメッセージ", texts)  # 这一轮马上要发的不补


class RhythmTests(base.Base):
    def setUp(self):
        super().setUp()
        self.chat_setup()

    def test_default_debounce_and_one_time_migration(self):
        self.sql("DELETE FROM settings WHERE key = 'batch_debounce_sec'")
        with closing(self.connect()) as conn:
            self.assertEqual(chat_service._get_batch_debounce_sec(conn), 1.2)

        def migrate(value):
            self.sql("INSERT OR REPLACE INTO settings (key, value) VALUES ('batch_debounce_sec', ?)", (value,))
            with closing(self.connect()) as conn:
                chat_room.migrate_debounce(conn)
                conn.commit()
            return self.sql("SELECT value FROM settings WHERE key = 'batch_debounce_sec'")[0][0]

        self.assertEqual(migrate("2"), "2")  # 用户自己设过的不动（标记也记上了）
        self.sql("DELETE FROM chat_migrations")
        self.assertEqual(migrate("3.0"), "1.2")
        self.assertEqual(migrate("3"), "3")  # 只改一次：之后用户再设成 3 也不动
        self.sql("DELETE FROM chat_migrations")
        self.assertEqual(migrate("3"), "1.2")

    def test_two_quick_messages_still_merge_at_1_2_seconds(self):
        self.sql("UPDATE settings SET value = '1.2' WHERE key = 'batch_debounce_sec'")

        async def scenario():
            first = asyncio.create_task(self._collect("ねえ"))
            await asyncio.sleep(0.3)
            second = await self._collect("聞いて")
            return await first, second

        first, second = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual([n for n, _ in first], ["queued"])
        names = [n for n, _ in second]
        self.assertEqual(names[:3], ["read", "speaker", "guard"])
        self.assertEqual(len(dict(second)["read"]["message_ids"]), 2)  # 两条一起已读
        self.assertEqual(len(self.claude.calls), 1)
        self.assertTrue(self.claude.calls[0]["user"].endswith("ねえ\n聞いて"))

    async def _collect(self, text):
        return [item async for item in chat_service.run_chat_turn(text)]


if __name__ == "__main__":
    unittest.main()
