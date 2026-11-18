"""世界书引擎（services/lore + routers/lore）离线测试：临时 SQLite、假 provider、假嵌入函数，不连任何模型。

覆盖：关键词 / 正则 / 整词 / 大小写 / 次要关键词四种逻辑；按原形匹配（日语「食べる」命中「食べた」）；
语义触发（假嵌入）和模型不可用；条件触发（星期、idle_days、变量）；粘性 / 冷却 / 延迟跨多轮；分组与权重；
递归和三个递归开关；预算裁剪；三个位置进到对的地方；书改了会话重连；v1→v2 升级幂等；
酒馆 json / 角色卡 json / 角色卡 png 的导入导出往返；试触发不写状态；坏书不影响聊天；跨站请求被拒。
"""
import asyncio
import base64
import json
import random
import sqlite3
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.providers import registry  # noqa: E402
from app.services import (bubbles, chat as chat_service, clock, coach_bridge, hooks, lore, semantic,  # noqa: E402
                          course, word_glosses)
from app.services.lore import state as lore_state, store, transfer  # noqa: E402

JA_REPLY = "うん、いいね！今日はなにしてた？\n⟦mood:happy⟧"
THURSDAY = datetime(2026, 11, 12, 10, 0, 0)  # 2026-11-12 是周四


class FakeProvider:
    def __init__(self, replies=None):
        self.replies, self.calls, self.forgot = list(replies or []), [], []

    async def forget_session(self, key):
        self.forgot.append(key)

    async def drop_all_sessions(self):
        self.forgot.append("*")

    def supports_vision(self):
        return True

    def configured(self):
        return True

    async def health(self):
        return True

    async def stream_chat(self, session_key, system_prompt, user_text, image_paths=None):
        self.calls.append({"key": session_key, "system": system_prompt, "user": user_text})
        await asyncio.sleep(0)
        yield self.replies.pop(0) if self.replies else JA_REPLY


class Base(unittest.TestCase):
    """世界书和 hook 测试共用：临时库 + 两个人设（5 日语 / 6 英语）+ 会话 19。没有测试方法。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "lore.db"
        conn = sqlite3.connect(self.path)
        conn.executescript((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
        conn.execute("DELETE FROM personas")
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (5, 'Tester', 'ja', '{}')")
        conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (6, 'Emma', 'en', '{}')")
        conn.execute("INSERT INTO sessions (id, persona_id, language) VALUES (19, 5, 'ja')")
        for key, value in (("batch_debounce_sec", "0"), ("coach_bridge", "0")):
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
        from app.services.learning import store as learning_store
        conn.row_factory = sqlite3.Row
        learning_store.migrate(conn)  # 学习模块的迁移（vocab_entries.encounters 列、复习卡）
        conn.commit()
        conn.close()
        self.addCleanup(self.temp.cleanup)
        for p in (patch.object(db, "DB_PATH", self.path), patch.object(clock, "rng", random.Random(7))):
            p.start()
            self.addCleanup(p.stop)
        semantic.set_embedder(None)
        self.addCleanup(semantic.reset_embedder)
        self.addCleanup(hooks.flush)  # 后台的 hook 线程用完临时库再删
        chat_service._session_states.clear()
        self._reset_registry()
        self.addCleanup(self._reset_registry)

    def _reset_registry(self):
        registry._session_engine.clear()
        registry._session_intended.clear()
        registry._pinned_at.clear()
        registry._system_fingerprints.clear()
        registry._primary = registry._fallback = registry._custom = None

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def sql(self, query, args=()):
        with closing(self.connect()) as conn:
            rows = conn.execute(query, args).fetchall()
            conn.commit()
            return rows

    def due_cards(self, kinds=("vocab",)):
        """收藏的词/句型同步成复习卡，并让它们现在就到期（排期以 review_cards 为准）。"""
        from app.services.learning import store as learning_store
        with closing(self.connect()) as conn:
            learning_store.sync(conn)
            marks = ",".join("?" * len(kinds))
            conn.execute(f"UPDATE review_cards SET state = 'review', due_at = '2000-01-01 00:00:00' WHERE kind IN ({marks})",
                         kinds)
            conn.commit()

    def persona(self, persona_id=5):
        return dict(self.sql("SELECT * FROM personas WHERE id = ?", (persona_id,))[0])

    def book(self, entries, *, scope="global", name="Test", **settings):
        with closing(self.connect()) as conn:
            saved = store.save_book(conn, name, lore.Book.model_validate({"settings": settings, "entries": entries}),
                                    scope=scope)
            conn.commit()
            return saved.id

    def turn(self, text, *, persona_id=5, sid=19, commit=True, effects=None):
        with closing(self.connect()) as conn:
            n = lore_state.next_turn(conn, sid, persona_id)
            conn.commit()
            result = lore.evaluate_turn(conn, self.persona(persona_id), sid, n, text, effects=effects)
            if commit:
                lore.commit(conn, result)
            conn.commit()
            return result

    @staticmethod
    def uids(result, injected="any"):
        return sorted(a["uid"] for a in result.activated if injected == "any" or a["injected"] == injected)

    @staticmethod
    def why(result, uid):
        return next((s["why"] for s in result.skipped if s["uid"] == uid), None)

    # ---- 聊天链路
    def chat_setup(self):
        self.claude = FakeProvider()
        registry._primary = self.claude
        self.recall = AsyncMock(return_value=[{"when": "昨日", "text": "对方：猫の名前はタマ", "message_ids": [1]}])
        self.extract = AsyncMock()
        patches = [
            patch.object(chat_service.recall_service, "recall", self.recall),
            patch.object(chat_service.recall_service, "embed_new_messages", AsyncMock()),
            patch("app.services.memoryx.maybe_extract", self.extract),
            patch.object(chat_service, "_tokenize", lambda text, lang: [
                {"i": 0, "surface": text, "lemma": text, "reading": "", "pos": "", "clickable": True,
                 "collected": False}]),
            patch.object(word_glosses, "schedule", lambda *a: None),
            patch.object(word_glosses, "attach_cached", lambda *a: None),
            patch.object(chat_service, "first_pause_seconds", lambda: 0),
            patch.object(chat_service, "bubble_pause_seconds", lambda text: 0),
            patch.object(bubbles, "DELTA_PAUSE_SEC", 0),
            patch.object(coach_bridge, "record_fixes", AsyncMock(return_value=0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_turn(self, text, to=None, **extra):
        async def scenario():
            events = [item async for item in chat_service.run_chat_turn(text, to=to, **extra)]
            await asyncio.sleep(0.05)
            return events
        events = asyncio.run(scenario())
        hooks.flush()
        return events

    def client(self):
        from fastapi.testclient import TestClient
        from app import main
        return TestClient(main.app, base_url="http://127.0.0.1:8787")


class MatchingTests(Base):
    def test_keywords_regex_and_secondary_logic(self):
        self.book([
            {"uid": 1, "keys": ["cat"], "content": "plain"},
            {"uid": 2, "keys": ["/ne?ko/i"], "content": "regex"},
            {"uid": 3, "keys": ["cat"], "secondary_keys": ["dog", "fish"], "logic": "and_any", "content": "any"},
            {"uid": 4, "keys": ["cat"], "secondary_keys": ["dog", "fish"], "logic": "and_all", "content": "all"},
            {"uid": 5, "keys": ["cat"], "secondary_keys": ["dog", "fish"], "logic": "not_any", "content": "notany"},
            {"uid": 6, "keys": ["cat"], "secondary_keys": ["dog", "fish"], "logic": "not_all", "content": "notall"},
            {"uid": 7, "keys": ["zebra"], "content": "never"},
        ])
        result = self.turn("My cat met a dog. NEKO!", commit=False)
        self.assertEqual(self.uids(result), [1, 2, 3, 6])
        self.assertEqual(self.why(result, 4), "secondary_logic")
        self.assertEqual(self.why(result, 5), "secondary_logic")
        self.assertEqual(self.why(result, 7), "no_match")
        reasons = {a["uid"]: a["reason"] for a in result.activated}
        self.assertEqual(reasons[2], "regex:/ne?ko/i")
        result = self.turn("a cat with a dog and a fish", commit=False)
        self.assertEqual(self.uids(result), [1, 3, 4])

    def test_whole_words_and_case(self):
        self.book([
            {"uid": 1, "keys": ["cat"], "whole_words": True, "content": "whole"},
            {"uid": 2, "keys": ["cat"], "content": "substring"},
            {"uid": 3, "keys": ["Paris"], "case_sensitive": True, "content": "case"},
            {"uid": 4, "keys": ["猫"], "whole_words": True, "content": "cjk ignores whole words"},
        ])
        result = self.turn("the category of paris 猫だ", commit=False)
        self.assertEqual(self.uids(result), [2, 4])
        self.assertEqual(self.uids(self.turn("a cat in Paris", commit=False)), [1, 2, 3])

    def test_lemma_matching_japanese_and_switch(self):
        self.book([{"uid": 1, "keys": ["食べる"], "content": "lemma on"},
                   {"uid": 2, "keys": ["食べる"], "lemma": False, "content": "lemma off"}])
        result = self.turn("昨日ラーメンを食べた", commit=False)
        self.assertEqual(self.uids(result), [1])
        self.assertTrue(result.activated[0]["reason"].startswith("lemma:"))
        self.assertEqual(self.why(result, 2), "no_match")

    def test_lemma_uses_stored_tokens_of_assistant_messages(self):
        tokens = [{"surface": "行った", "lemma": "行く"}]
        self.sql("INSERT INTO messages (session_id, role, content, tokens_json) VALUES (19, 'assistant', 'きのう行った', ?)",
                 (json.dumps(tokens, ensure_ascii=False),))
        self.book([{"uid": 1, "keys": ["行く"], "content": "go"}])
        self.assertEqual(self.uids(self.turn("うん", commit=False)), [1])

    def test_semantic_trigger_and_unavailable_model(self):
        def fake(texts):
            return [np.array([1.0, 0.0]) if ("猫" in t or "ねこ" in t) else np.array([0.0, 1.0]) for t in texts]

        self.book([{"uid": 1, "title": "猫の話", "semantic": True, "content": "semantic cat"},
                   {"uid": 2, "title": "天気", "semantic": True, "content": "weather"}])
        semantic.set_embedder(fake, tag="fake")
        result = self.turn("うちのねこが可愛い", commit=False)
        self.assertEqual(self.uids(result), [1])
        self.assertTrue(result.activated[0]["reason"].startswith("semantic:"))
        self.assertEqual(self.sql("SELECT count(*) FROM lore_vectors")[0][0], 2)  # 条目向量按内容缓存
        semantic.set_embedder(None)
        result = self.turn("うちのねこが可愛い", commit=False)
        self.assertEqual(self.uids(result), [])
        self.assertEqual(self.why(result, 1), "semantic_unavailable")

    def test_semantic_timeout_does_not_block(self):
        import time

        def slow(texts):
            time.sleep(2)
            return [np.array([1.0, 0.0]) for _ in texts]

        self.book([{"uid": 1, "title": "x", "semantic": True, "content": "slow"}])
        semantic.set_embedder(slow, tag="slow")
        started = time.monotonic()
        result = self.turn("hello", commit=False)
        self.assertLess(time.monotonic() - started, 1.6)
        self.assertEqual(self.why(result, 1), "semantic_unavailable")
        semantic._executor.submit(lambda: None).result(timeout=5)  # 等慢线程收尾


class ConditionTests(Base):
    def test_weekday_idle_days_and_variables(self):
        self.sql("INSERT INTO messages (session_id, role, content, created_at) VALUES (19, 'user', 'やあ', '2026-11-09 09:00:00')")
        self.sql("INSERT INTO hook_vars (scope, persona_id, name, value) VALUES ('persona', 5, 'night_owl', '3')")
        self.book([
            {"uid": 1, "content": "今天是周四", "conditions": [{"field": "weekday", "op": "==", "value": 4}]},
            {"uid": 2, "content": "好久不见", "conditions": [{"field": "idle_days", "op": ">=", "value": 3}]},
            {"uid": 3, "content": "夜猫子", "conditions": [{"field": "var.night_owl", "op": ">=", "value": 3}]},
            {"uid": 4, "content": "周五", "conditions": [{"field": "weekday", "op": "==", "value": 5}]},
            {"uid": 5, "keys": ["猫"], "content": "猫+深夜", "conditions": [{"field": "hour", "op": "between", "value": [22, 3]}]},
        ])
        with patch.object(clock, "now", lambda: THURSDAY):
            result = self.turn("猫", commit=False)
        self.assertEqual(self.uids(result), [1, 2, 3])
        self.assertEqual(self.why(result, 4), "conditions")
        self.assertEqual(self.why(result, 5), "conditions")
        with patch.object(clock, "now", lambda: datetime(2026, 11, 12, 23, 30)):
            self.assertIn(5, self.uids(self.turn("猫", commit=False)))

    def test_conditions_validate(self):
        with self.assertRaises(ValueError):
            lore.Entry.model_validate({"conditions": [{"field": "moon", "op": "==", "value": 1}]})
        with self.assertRaises(ValueError):
            lore.Entry.model_validate({"conditions": [{"field": "hour", "op": "between", "value": 3}]})
        with self.assertRaises(ValueError):
            lore.Entry.model_validate({"keys": ["/([/"]})


class StateTests(Base):
    def test_sticky_cooldown_and_delay_across_turns(self):
        self.book([{"uid": 1, "keys": ["rain"], "sticky": 2, "cooldown": 2, "content": "It rains."},
                   {"uid": 2, "keys": ["rain"], "delay": 3, "content": "delayed"}])
        t1 = self.turn("rain today")  # turn 1：新触发，注入
        self.assertEqual(self.uids(t1, "turn"), [1])
        self.assertIn("It rains.", t1.block)
        self.assertEqual(self.why(t1, 2), "delay")
        t2 = self.turn("sunny")  # turn 2：粘性，激活中但不重复注入
        self.assertEqual(self.uids(t2), [1])
        self.assertEqual(t2.activated[0]["reason"], "sticky")
        self.assertEqual(t2.block, "")
        self.assertEqual(self.uids(self.turn("sunny")), [1])  # turn 3：还在粘性里
        t4 = self.turn("rain again")  # turn 4、5：冷却
        self.assertEqual(self.why(t4, 1), "cooldown")
        self.assertEqual(self.why(self.turn("rain"), 1), "cooldown")
        for i in range(3):
            self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', ?)", (f"m{i}",))
        t6 = self.turn("rain")  # turn 6：冷却过了，重新注入；对话够 3 条，延迟条目也上了
        self.assertEqual(self.uids(t6, "turn"), [1, 2])
        row = self.sql("SELECT activations, last_turn FROM lore_state WHERE uid = 1")[0]
        self.assertEqual((row[0], row[1]), (2, 6))

    def test_turn_entry_injected_once_while_keyword_repeats(self):
        self.book([{"uid": 1, "keys": ["cat"], "content": "cat lore"}])
        self.assertIn("cat lore", self.turn("cat").block)
        self.assertEqual(self.turn("cat again").block, "")
        self.turn("nothing")
        self.assertIn("cat lore", self.turn("cat back").block)


class GroupRecursionBudgetTests(Base):
    def test_group_override_weight_and_sticky_owner(self):
        self.book([
            {"uid": 1, "keys": ["x"], "group": "g", "order": 10, "content": "low"},
            {"uid": 2, "keys": ["x"], "group": "g", "order": 50, "group_override": True, "content": "override"},
            {"uid": 3, "keys": ["y"], "group": "h", "group_weight": 1, "content": "light"},
            {"uid": 4, "keys": ["y"], "group": "h", "group_weight": 1000, "content": "heavy"},
        ])

        class Fixed:
            def random(self):
                return 0.5

        with patch.object(clock, "rng", Fixed()):
            result = self.turn("x y", commit=False)
        self.assertEqual(self.uids(result), [2, 4])
        self.assertEqual(self.why(result, 1), "group")
        self.assertEqual(self.why(result, 3), "group")

    def test_sticky_entry_keeps_its_group(self):
        self.book([{"uid": 1, "keys": ["a"], "group": "g", "sticky": 3, "content": "first"},
                   {"uid": 2, "keys": ["b"], "group": "g", "content": "second"}])
        self.turn("a")
        result = self.turn("b")
        self.assertEqual(self.uids(result), [1])
        self.assertEqual(self.why(result, 2), "group")

    def test_recursion_and_its_three_switches(self):
        entries = [
            {"uid": 1, "keys": ["alpha"], "content": "alpha mentions beta"},
            {"uid": 2, "keys": ["beta"], "content": "beta mentions gamma"},
            {"uid": 3, "keys": ["gamma"], "content": "gamma end"},
            {"uid": 4, "keys": ["beta"], "delay_until_recursion": True, "content": "only via recursion"},
        ]
        book_id = self.book(entries)
        result = self.turn("alpha beta", commit=False)
        self.assertEqual(self.uids(result), [1, 2, 3, 4])
        reasons = {a["uid"]: a["reason"] for a in result.activated}
        self.assertTrue(reasons[3].startswith("recursion:"))
        self.assertTrue(reasons[4].startswith("recursion:"))

        def variant(**changes):
            changed = [dict(e) for e in entries]
            for uid, fields in changes.items():
                changed[int(uid[1:]) - 1].update(fields)
            with closing(self.connect()) as conn:
                store.save_book(conn, "Test", lore.Book.model_validate({"entries": changed}), book_id)
                conn.commit()
            return self.uids(self.turn("alpha", commit=False))

        self.assertEqual(variant(), [1, 2, 3, 4])
        self.assertEqual(variant(u2={"exclude_recursion": True}), [1, 4])  # 2 不被递归触发 → 3 也没了
        self.assertEqual(variant(u1={"prevent_recursion": True}), [1])
        with closing(self.connect()) as conn:
            store.save_book(conn, "Test", lore.Book.model_validate(
                {"settings": {"max_recursion": 1}, "entries": entries}), book_id)
            conn.commit()
        self.assertEqual(self.uids(self.turn("alpha", commit=False)), [1, 2, 4])
        with closing(self.connect()) as conn:
            store.save_book(conn, "Test", lore.Book.model_validate(
                {"settings": {"recursion": False}, "entries": entries}), book_id)
            conn.commit()
        self.assertEqual(self.uids(self.turn("alpha", commit=False)), [1])

    def test_budget_keeps_constants_then_higher_order(self):
        self.book([
            {"uid": 1, "constant": True, "position": "turn", "order": 1, "content": "C" * 10},
            {"uid": 2, "keys": ["k"], "order": 10, "content": "L" * 10},
            {"uid": 3, "keys": ["k"], "order": 200, "content": "H" * 10},
        ], budget_chars=20)
        result = self.turn("k")
        self.assertEqual(self.uids(result, "turn"), [1, 3])
        self.assertEqual(self.why(result, 2), "budget")
        self.assertLess(result.block.index("C" * 10), result.block.index("H" * 10))  # order 小的在前
        self.assertEqual(self.sql("SELECT count(*) FROM lore_state WHERE uid = 2")[0][0], 0)  # 被裁掉的不算激活

    def test_probability_uses_fixed_random_source(self):
        self.book([{"uid": 1, "keys": ["k"], "probability": 30, "content": "maybe"}])

        class Roll:
            def __init__(self, value):
                self.value = value

            def random(self):
                return self.value

        with patch.object(clock, "rng", Roll(0.9)):
            self.assertEqual(self.why(self.turn("k", commit=False), 1), "probability")
        with patch.object(clock, "rng", Roll(0.1)):
            self.assertEqual(self.uids(self.turn("k", commit=False)), [1])


class ChatIntegrationTests(Base):
    def setUp(self):
        super().setUp()
        self.chat_setup()

    def test_three_positions_land_in_the_right_place_and_book_edit_reconnects(self):
        book_id = self.book([
            {"uid": 1, "constant": True, "position": "before_persona", "content": "BEFORE-LORE"},
            {"uid": 2, "constant": True, "content": "AFTER-LORE"},
            {"uid": 3, "keys": ["猫"], "content": "TURN-LORE {{char}}"},
        ])
        events = self.run_turn("猫が好き")
        self.assertEqual(events[-1][0], "done")
        system, user = self.claude.calls[0]["system"], self.claude.calls[0]["user"]
        self.assertLess(system.index("BEFORE-LORE"), system.index("【人物设定】"))
        self.assertLess(system.index("【关于对方，长期记住的事】"), system.index("AFTER-LORE"))
        self.assertLess(system.index("AFTER-LORE"), system.index("【铁律"))
        self.assertNotIn("TURN-LORE", system)
        self.assertLess(user.index("猫の名前はタマ"), user.index("TURN-LORE Tester"))
        self.assertTrue(user.endswith("猫が好き"))
        self.run_turn("猫また")
        self.assertNotIn("TURN-LORE", self.claude.calls[1]["user"])  # 已经在对话历史里了，不重复塞
        self.assertEqual(self.claude.forgot, [])
        r = self.client().put(f"/api/lore/books/{book_id}", json={"book": {"entries": [
            {"uid": 1, "constant": True, "position": "before_persona", "content": "BEFORE-NEW"}]}})
        self.assertEqual(r.status_code, 200)
        self.run_turn("ねえ")
        self.assertEqual(self.claude.forgot, ["p5s19"])  # 书改了：下一条消息前重连
        self.assertIn("BEFORE-NEW", self.claude.calls[2]["system"])

    def test_attached_scope_only_reaches_its_persona(self):
        book_id = self.book([{"uid": 1, "constant": True, "content": "ATTACHED"}], scope="attached")
        self.run_turn("やあ")
        self.assertNotIn("ATTACHED", self.claude.calls[0]["system"])
        self.sql("UPDATE personas SET profile_json = ? WHERE id = 5", (json.dumps({"world_book_ids": [book_id]}),))
        self.run_turn("やあ")
        self.assertIn("ATTACHED", self.claude.calls[1]["system"])
        self.assertEqual(self.claude.forgot, ["p5s19"])  # 挂接关系变了也重连

    def test_broken_book_and_failing_engine_do_not_break_chat(self):
        self.sql("INSERT INTO world_books (name, book_json, scope) VALUES ('bad', '{not json', 'global')")
        self.book([{"uid": 1, "keys": ["猫"], "content": "ok lore"}])
        self.assertEqual(self.run_turn("猫")[-1][0], "done")
        self.assertIn("ok lore", self.claude.calls[0]["user"])
        with patch.object(lore, "evaluate_turn", side_effect=RuntimeError("boom")), \
                patch.object(lore, "system_lore", side_effect=RuntimeError("boom")):
            self.assertEqual(self.run_turn("猫")[-1][0], "done")


class MigrationAndApiTests(Base):
    def test_v1_upgrade_in_place_is_idempotent_and_inline_books_move_out(self):
        v1 = {"version": 1, "entries": [{"title": "常驻", "keywords": [], "content": "always", "enabled": True},
                                        {"title": "猫", "keywords": ["猫"], "content": "cat", "enabled": False}]}
        self.sql("INSERT INTO world_books (id, name, book_json) VALUES (3, 'old', ?)", (json.dumps(v1),))
        self.sql("UPDATE personas SET profile_json = ? WHERE id = 6", (json.dumps({"world_book": v1}),))
        for _ in range(2):
            with closing(self.connect()) as conn:
                lore.migrate_legacy(conn)
                conn.commit()
        raw = json.loads(self.sql("SELECT book_json FROM world_books WHERE id = 3")[0][0])
        self.assertEqual(raw["version"], 2)
        first, second = raw["entries"]
        self.assertEqual((first["constant"], first["position"], first["keys"]), (True, "after_persona", []))
        self.assertEqual((second["keys"], second["enabled"], second["position"]), (["猫"], False, "turn"))
        profile = json.loads(self.sql("SELECT profile_json FROM personas WHERE id = 6")[0][0])
        self.assertEqual(len(profile["world_book_ids"]), 1)
        self.assertEqual(self.sql("SELECT count(*) FROM world_books")[0][0], 2)

    def test_crud_attach_delete_and_teaching_routes_gone(self):
        c = self.client()
        r = c.post("/api/lore/books", json={"name": "World", "book": {"entries": [{"keys": ["猫"], "content": "x"}]}})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual((body["scope"], body["enabled"], body["book"]["version"]), ("attached", True, 2))
        entry = body["book"]["entries"][0]
        self.assertEqual((entry["uid"], entry["position"], entry["order"], entry["logic"]), (1, "turn", 100, "and_any"))
        book_id = body["id"]
        persona = {"name": "Tester", "language": "ja", "profile": {"world_book_ids": [book_id]}}
        self.assertEqual(c.put("/api/personas/5", json=persona).status_code, 200)
        self.assertEqual(c.put("/api/personas/5", json={**persona, "profile": {"world_book_ids": [999]}}).status_code, 422)
        items = c.get("/api/lore/books").json()["items"]
        self.assertEqual(items[0]["attached_persona_ids"], [5])
        self.assertEqual(items[0]["entry_count"], 1)
        self.assertEqual(c.put(f"/api/lore/books/{book_id}", json={"scope": "global", "enabled": False}).json()["scope"], "global")
        self.assertEqual(c.put(f"/api/lore/books/{book_id}", json={"book": {"entries": [{"keys": ["/(/"]}]}}).status_code, 422)
        self.assertEqual(c.post("/api/lore/books", json={"name": "x", "book": {"entries": [{"content": "y" * 4001}]}}).status_code, 422)
        self.assertEqual(c.delete(f"/api/lore/books/{book_id}").status_code, 200)
        self.assertEqual(json.loads(self.sql("SELECT profile_json FROM personas WHERE id = 5")[0][0])["world_book_ids"], [])
        for path in ("/api/teaching/world-books", "/api/teaching/import-world"):
            self.assertIn(c.get(path).status_code, (404, 405))
            self.assertIn(c.post(path, json={}).status_code, (404, 405))

    def test_cross_site_requests_are_refused(self):
        c = self.client()
        evil = {"Origin": "https://evil.example"}
        self.assertEqual(c.get("/api/lore/books", headers=evil).status_code, 403)
        self.assertEqual(c.post("/api/lore/books", json={"name": "x"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(c.post("/api/lore/test", json={"persona_id": 5, "text": "x"}, headers=evil).status_code, 403)
        self.assertEqual(c.post("/api/lore/import", files={"file": ("a.json", b"{}")}, headers=evil).status_code, 403)

    def test_dry_run_reports_and_writes_nothing(self):
        self.book([{"uid": 1, "keys": ["猫"], "content": "TURN {{char}}"},
                   {"uid": 2, "constant": True, "position": "before_persona", "content": "SYSTEM"},
                   {"uid": 3, "keys": ["犬"], "content": "dog"}])
        before = [self.sql(f"SELECT count(*) FROM {t}")[0][0] for t in ("lore_state", "chat_turns", "hook_log", "hook_queue")]
        r = self.client().post("/api/lore/test", json={"persona_id": 5, "text": "猫かわいい"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual({(a["uid"], a["injected"]) for a in body["activated"]}, {(1, "turn"), (2, "system")})
        self.assertIn({"book_id": 1, "uid": 3, "title": "", "why": "no_match"}, body["skipped"])
        self.assertIn("TURN Tester", body["turn_preview"])
        self.assertIn("SYSTEM", body["system_preview"])
        after = [self.sql(f"SELECT count(*) FROM {t}")[0][0] for t in ("lore_state", "chat_turns", "hook_log", "hook_queue")]
        self.assertEqual(before, after)
        self.assertEqual(self.client().post("/api/lore/test", json={"persona_id": 99, "text": "x"}).status_code, 404)


def png_with(texts: dict[str, dict]) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    for key, value in texts.items():
        payload = base64.b64encode(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        out += chunk(b"tEXt", key.encode("latin-1") + b"\x00" + payload)
    return out + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


ST_BOOK = {"entries": {
    "0": {"uid": 0, "key": ["猫", "/ne?ko/i"], "keysecondary": ["犬"], "comment": "猫", "content": "猫の話",
          "constant": False, "selective": True, "selectiveLogic": 3, "order": 120, "position": 4, "disable": False,
          "probability": 60, "useProbability": True, "group": "pets", "groupWeight": 30, "sticky": 2, "cooldown": 1,
          "delay": 0, "depth": 4, "role": 0, "excludeRecursion": True, "automationId": "cat-auto", "vectorized": False},
    "1": {"uid": 1, "key": [], "comment": "世界", "content": "世界の設定", "constant": True, "position": 0,
          "selectiveLogic": 0, "order": 100, "disable": True, "probability": 100, "useProbability": False},
    "2": {"uid": 2, "key": ["雨"], "comment": "EM", "content": "雨の日", "position": 5, "selectiveLogic": 0},
}}


class ImportExportTests(Base):
    def upload(self, name, data):
        return self.client().post("/api/lore/import", files={"file": (name, data)})

    def test_sillytavern_json_import_and_export_round_trip(self):
        r = self.upload("猫の世界.json", json.dumps(ST_BOOK, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual((body["name"], body["entry_count"]), ("猫の世界", 3))
        book = self.client().get(f"/api/lore/books/{body['id']}").json()["book"]
        cat, world, rain = book["entries"]
        self.assertEqual(cat["uid"], 1)  # 酒馆的 uid 0 在这里重新编号
        self.assertEqual((cat["keys"], cat["secondary_keys"], cat["logic"], cat["position"]),
                         (["猫", "/ne?ko/i"], ["犬"], "and_all", "turn"))
        self.assertEqual((cat["order"], cat["probability"], cat["group"], cat["group_weight"], cat["sticky"],
                          cat["cooldown"], cat["exclude_recursion"], cat["automation_id"]),
                         (120, 60, "pets", 30, 2, 1, True, "cat-auto"))
        self.assertEqual(cat["extensions"]["st"], {"depth": 4, "role": 0})
        self.assertEqual((world["constant"], world["position"], world["enabled"], world["probability"]),
                         (True, "before_persona", False, 100))
        self.assertEqual(rain["position"], "after_persona")
        exported = self.client().get(f"/api/lore/books/{body['id']}/export")
        self.assertIn("attachment", exported.headers["content-disposition"])
        data = exported.json()
        first = data["entries"]["0"]
        self.assertEqual((first["key"], first["keysecondary"], first["selectiveLogic"], first["position"],
                          first["depth"], first["role"], first["comment"]),
                         (["猫", "/ne?ko/i"], ["犬"], 3, 4, 4, 0, "猫"))
        self.assertEqual(data["entries"]["2"]["position"], 5)  # 酒馆原来的位置号带回去
        self.assertIn("jine", first["extensions"])
        again = self.upload("again.json", exported.content).json()
        book2 = self.client().get(f"/api/lore/books/{again['id']}").json()["book"]
        self.assertEqual(book2["entries"], book["entries"])

    def test_jine_only_fields_survive_export(self):
        book_id = self.book([{"uid": 1, "keys": ["食べる"], "lemma": True, "semantic_threshold": 0.9,
                              "conditions": [{"field": "weekday", "op": "in", "value": [6, 7]}],
                              "position": "before_persona", "content": "weekend"}], budget_chars=999)
        exported = self.client().get(f"/api/lore/books/{book_id}/export").content
        again = self.upload("x.json", exported).json()
        original = self.client().get(f"/api/lore/books/{book_id}").json()["book"]
        copy = self.client().get(f"/api/lore/books/{again['id']}").json()["book"]
        self.assertEqual(copy, original)

    def test_character_card_json_and_png(self):
        card = {"spec": "chara_card_v2", "data": {"name": "Ame", "character_book": {
            "name": "Ame の本", "scan_depth": 6, "recursive_scanning": False, "token_budget": 500, "entries": [
                {"id": 7, "keys": ["配信"], "secondary_keys": [], "content": "配信者", "enabled": True,
                 "insertion_order": 50, "position": "before_char", "constant": False,
                 "extensions": {"probability": 40, "useProbability": True, "group": "g", "sticky": 1, "depth": 2,
                                "selectiveLogic": 2}},
                {"id": 8, "keys": ["夜"], "content": "夜型", "position": "after_char",
                 "extensions": {"position": 4}}]}}}
        r = self.upload("ame.json", json.dumps(card, ensure_ascii=False).encode())
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual((body["name"], body["entry_count"]), ("Ame の本", 2))
        self.assertTrue(any("token" in w for w in body["warnings"]))
        book = self.client().get(f"/api/lore/books/{body['id']}").json()["book"]
        self.assertEqual((book["settings"]["scan_depth"], book["settings"]["recursion"]), (6, False))
        first, second = book["entries"]
        self.assertEqual((first["uid"], first["position"], first["order"], first["probability"], first["group"],
                          first["sticky"], first["logic"], first["extensions"]), (7, "before_persona", 50, 40, "g", 1,
                                                                                  "not_any", {"depth": 2}))
        self.assertEqual(second["position"], "turn")  # 酒馆写在 extensions 里的位置号优先
        self.assertEqual(self.sql("SELECT count(*) FROM personas")[0][0], 2)  # 只取世界书，不建联系人
        png = png_with({"chara": card})
        r = self.upload("ame.png", png)
        self.assertEqual((r.status_code, r.json()["entry_count"]), (201, 2))
        v3 = {"spec": "chara_card_v3", "data": {"name": "V3", "character_book": {"entries": [
            {"id": 1, "keys": ["x"], "content": "v3 wins"}]}}}
        r = self.upload("v3.png", png_with({"chara": card, "ccv3": v3}))
        self.assertEqual((r.json()["name"], r.json()["entry_count"]), ("V3 的世界书", 1))

    def test_bad_uploads_are_rejected_with_reasons(self):
        self.assertEqual(self.upload("x.png", png_with({})).status_code, 422)
        self.assertEqual(self.upload("x.txt", b"hello").status_code, 422)
        no_book = {"spec": "chara_card_v2", "data": {"name": "x"}}
        r = self.upload("x.json", json.dumps(no_book).encode())
        self.assertEqual(r.status_code, 422)
        self.assertIn("没有世界书", r.json()["detail"])
        broken = {"entries": {"0": {"key": ["/(/"], "content": "bad regex"}, "1": "not an entry"}}
        r = self.upload("b.json", json.dumps(broken).encode())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.json()["warnings"]), 2)


class WorkspaceAgentTests(Base):
    def test_world_save_takes_v2_and_v1_books(self):
        from app.services import workspace_agent as agent
        v2 = {"version": 2, "settings": {"budget_chars": 900},
              "entries": [{"keys": ["猫"], "content": "cat", "sticky": 2, "position": "after_persona"}]}
        proposal = agent.preview_operations([agent.Operation(tool="world.save", args={"name": "V2", "book": v2})], {})
        agent.commit(proposal["proposal"]["id"], False, {})
        v1 = {"entries": [{"title": "Rule", "keywords": [], "content": "always"}]}
        proposal = agent.preview_operations([agent.Operation(tool="world.save", args={"name": "V1", "book": v1})], {})
        agent.commit(proposal["proposal"]["id"], False, {})
        books = agent.inspect_workspace()["world_books"]
        self.assertEqual([b["name"] for b in books], ["V2", "V1"])
        self.assertEqual(books[0]["book"]["settings"], {"budget_chars": 900})
        self.assertEqual(books[0]["book"]["entries"][0], {"uid": 1, "keys": ["猫"], "content": "cat", "sticky": 2,
                                                          "position": "after_persona"})
        self.assertEqual(books[1]["book"]["entries"][0], {"uid": 1, "title": "Rule", "content": "always",
                                                          "constant": True})
        agent.commit(proposal["proposal"]["id"], True, {})
        self.assertEqual([b["name"] for b in agent.inspect_workspace()["world_books"]], ["V2"])


if __name__ == "__main__":
    unittest.main()
