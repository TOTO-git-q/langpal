"""事件 hook（services/hooks + routers/hooks + /api/chat/proactive）离线测试：临时 SQLite、假 provider，不连模型。

覆盖：每个事件都从它真正的来源发出并触发到规则；七种动作的效果；宏（含 due_vocab 的挑词和作废）；
once_per / 冷却（分钟、轮数）/ 概率；总开关；自带规则写入且升级不覆盖用户改过的、不能删；
学习类事件落到最近聊过的同语言联系人；主动消息的完整一轮、节流、过期、和用户消息的互斥、失败退回队列；
/api/hooks/meta 的形状；规则校验和上限；变量和日志接口；设置项；坏规则不影响聊天；跨站请求被拒。
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

try:
    import test_lore as base
except ImportError:  # python -m unittest tests.test_hooks
    from tests import test_lore as base

from app.services import bubbles, chat as chat_service, clock, hooks, semantic, course  # noqa: E402
from app.services.hooks import builtin as hook_builtin, engine as hook_engine, store as hook_store  # noqa: E402

THURSDAY = base.THURSDAY


def sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


class HookBase(base.Base):
    def setUp(self):
        super().setUp()
        self.chat_setup()
        self.c = self.client()

    def quiet_builtins(self):
        with closing(hook_engine.connect()) as conn:
            hook_engine.ensure_seeded(conn)
            conn.commit()
        self.sql("UPDATE hook_rules SET enabled = 0 WHERE builtin IS NOT NULL")

    def rule(self, event, actions=None, **fields):
        body = {"name": fields.pop("name", event), "event": event,
                "actions": actions or [{"type": "inc_var", "name": "n_" + event, "scope": "global"}], **fields}
        r = self.c.post("/api/hooks/rules", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def var(self, name, persona_id=None):
        rows = self.sql("SELECT value FROM hook_vars WHERE name = ? AND persona_id = ?", (name, persona_id or 0))
        return json.loads(rows[0][0]) if rows else None

    def fire(self, event="chat.open", persona_id=5, **payload):
        r = self.c.post("/api/hooks/fire", json={"event": event, "persona_id": persona_id, "payload": payload})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def log(self):
        return self.c.get("/api/hooks/log?limit=500").json()["items"]

    def old_message(self, days=3, persona_session=19):
        stamp = clock.stamp(clock.now() - timedelta(days=days, hours=1))
        self.sql("INSERT INTO messages (session_id, role, content, created_at) VALUES (?, 'user', 'またね', ?)",
                 (persona_session, stamp))


class EventSourceTests(HookBase):
    def test_every_event_is_emitted_by_its_real_source(self):
        self.quiet_builtins()
        for event in hooks.EVENTS:
            conditions = [{"field": "event.automation_id", "op": "==", "value": "auto1"}] \
                if event == "lore.activated" else []
            self.rule(event, conditions=conditions)
        # chat.open / chat.idle：前端发
        self.fire("chat.open")
        self.fire("chat.idle", minutes=12)
        # chat.user_message / chat.reply / lore.activated：聊天一轮
        self.book([{"uid": 1, "keys": ["猫"], "automation_id": "auto1", "content": "cat"}])
        self.assertEqual(self.run_turn("猫かわいい")[-1][0], "done")
        # 收藏
        self.assertEqual(self.c.post("/api/vocab", json={"language": "ja", "lemma": "食べる",
                                                         "context_sentence": "食べた"}).status_code, 200)
        self.c.post("/api/vocab", json={"language": "ja", "lemma": "食べる", "context_sentence": "again"})  # 重复不算
        self.assertEqual(self.c.post("/api/patterns", json={"language": "ja", "pattern_name": "〜てしまう"}).status_code, 200)
        # 阅读判分 + 错题复习
        ident = "r2-" + "a" * 64
        self.sql("INSERT INTO reading_exercises VALUES (?, 'ja', '猫の本', '', ?)",
                 (ident, json.dumps({"items": [{"question": "q", "options": ["a", "b"], "answer": 0}]})))
        self.assertEqual(self.c.post(f"/api/reader/exercises/{ident}/submit", json={"choices": [1]}).status_code, 200)
        r = self.c.post("/api/review/attempt", json={"kind": "reading", "item_id": ident, "item_index": 0, "selection": 0,
                                                     "mode": "independent", "attempt_id": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 200, r.text)
        # 听力第一次判分（判分本身需要合成好的练习，这里直接走判分后的那一步）
        from app.routers import listening
        self.sql("INSERT INTO listening_sessions (id, language, version, metadata_json, payload_json, audio, "
                 "reserved_bytes, created_at) VALUES ('p1', 'ja', 1, '{}', '{}', x'00', 1, '2026-11-12')")
        listening._finished("p1", 2, 3)
        # 口语课桥读到新课
        with tempfile.TemporaryDirectory() as folder:
            bridge = Path(folder) / "langpal.json"
            bridge.write_text(json.dumps({"version": 1, "langs": {"ja": {"lastLesson": {
                "id": "lesson-9", "date": datetime.now().astimezone().isoformat()}}}}), encoding="utf-8")
            self.sql("UPDATE settings SET value = '1' WHERE key = 'coach_bridge'")
            with patch.dict(os.environ, {"COACH_BRIDGE_FILE": str(bridge)}):
                self.c.get("/api/hooks/pending")
                hooks.flush()
                self.c.get("/api/hooks/pending")  # 同一节课只发一次
                hooks.flush()
            self.sql("UPDATE settings SET value = '0' WHERE key = 'coach_bridge'")
        # A unit completes after each point has one success.
        directory = base.ROOT / 'tests' / 'fixtures' / 'lessons'
        outline = course.lessons.Course.model_validate_json((directory / 'toefl-2026' / 'course.json').read_text('utf-8'))
        section = outline.sections[0].model_copy(update={'lessons': outline.sections[0].lessons[:1]})
        outline = outline.model_copy(update={'language': 'ja', 'sections': [section]})
        unit = course.lessons.Lesson.model_validate_json((directory / outline.id / (section.lessons[0] + '.json')).read_text('utf-8'))
        now = datetime(2026, 11, 1, 10)
        with patch.object(course.content, 'presets', return_value={outline.id: outline}), \
                patch.object(course.lessons, 'load', return_value=unit), closing(hook_engine.connect()) as conn, conn:
            course.save_language_settings(conn, 'ja', course.Teaching(mode='ambient', preset=outline.id))
            for point in unit.points:
                course.ledger.write(conn, outline, [{'unit_id': unit.id, 'point_id': point.id,
                    'channel': 'lesson', 'ref': point.id, 'result': 'success',
                    'context': point.id, 'at': clock.stamp(now)}], now=now)
        # 复习会话结束：学习模块（services/learning.end_session）用 hooks.emit_soon 发，这里照它的发法
        hooks.emit_soon("study.review_session_done", None, {"count": 5, "forgot": 1, "language": "ja"})
        # 上完一节课：课程内核（services/course/lesson）交卷后同样用 emit_soon 发
        hooks.emit_soon("course.lesson_finished", None, {"unit_id": "u", "title": "t", "language": "ja", "passed": 1})
        hooks.flush()
        counts = {event: self.var("n_" + event) for event in hooks.EVENTS}
        self.assertEqual(counts, {event: 1 for event in hooks.EVENTS})
        units = [e for e in self.log() if e["event"] == "course.unit_completed"]
        self.assertEqual(len(units), 1)

    def test_language_events_land_on_the_native_speaker_or_the_primary(self):
        self.quiet_builtins()
        self.sql("INSERT INTO personas (id, name, language, profile_json) VALUES (7, 'Mio', 'ja', '{}')")
        self.assertEqual(self.c.put("/api/chat/main", json={"primary_id": 5, "guests": [
            {"persona_id": 6, "rule": {"type": "always"}}, {"persona_id": 7}]}).status_code, 200)
        self.rule("study.pattern_saved", [{"type": "inc_var", "name": "who"}])
        self.rule("study.pattern_saved", [{"type": "inc_var", "name": "pinned"}], persona_ids=[7])
        self.rule("study.pattern_saved", [{"type": "inc_var", "name": "english"}], persona_ids=[6])
        self.c.post("/api/patterns", json={"language": "ja", "pattern_name": "〜ながら"})
        hooks.flush()
        self.assertEqual((self.var("who", 5), self.var("who", 7)), (1, None))  # 日语是主人设的母语
        self.assertEqual(self.var("pinned", 7), 1)
        self.assertIsNone(self.var("english", 6))  # 限定的联系人语言对不上就不落
        self.c.post("/api/patterns", json={"language": "en", "pattern_name": "used to"})
        hooks.flush()
        self.assertEqual(self.var("who", 6), 1)  # 英语是副人设 Emma 的母语
        self.c.post("/api/patterns", json={"language": "fr", "pattern_name": "x"})
        hooks.flush()
        self.assertEqual(self.var("who", 5), 2)  # 谁的母语都不是 → 主人设

class ActionTests(HookBase):
    def test_inject_say_vars_and_remember(self):
        self.quiet_builtins()
        rule_id = self.rule("chat.open", [
            {"type": "inject", "text": "INJECT-{{char}}", "turns": 2},
            {"type": "set_var", "name": "mood", "value": "happy"},
            {"type": "inc_var", "name": "count", "by": 2, "scope": "global"},
            {"type": "remember", "content": "MEM {{char}}", "category": "promise"},
            {"type": "say", "directive": "SAY {{char}}"},
        ])
        result = self.fire("chat.open")
        self.assertEqual(result["fired"], [rule_id])
        self.assertEqual(result["pending"], [{"persona_id": 5, "count": 1}])
        self.assertEqual((self.var("mood", 5), self.var("count")), ("happy", 2))
        self.assertEqual([tuple(r) for r in self.sql("SELECT category, content FROM memory_items WHERE persona_id = 5")],
                         [("promise", "MEM Tester")])
        self.fire("chat.open")  # 同样内容的记忆不重复写
        self.assertEqual(self.sql("SELECT count(*) FROM memory_items")[0][0], 1)
        self.assertEqual(self.var("count"), 4)
        self.sql("DELETE FROM hook_queue WHERE kind = 'inject' AND id > 1")
        for _ in range(3):
            self.run_turn("やあ")
        users = [call["user"] for call in self.claude.calls]
        self.assertEqual(["INJECT-Tester" in u for u in users], [True, True, False])
        self.assertEqual(self.sql("SELECT count(*) FROM hook_queue WHERE kind = 'inject' AND consumed_at IS NULL")[0][0], 0)
        vars_api = self.c.get("/api/hooks/vars?persona_id=5").json()["items"]
        self.assertIn({"name": "mood", "value": "happy", "scope": "persona", "persona_id": 5}, vars_api)
        self.assertIn({"name": "count", "value": 4, "scope": "global", "persona_id": None}, vars_api)

    def test_activate_and_deactivate_entries(self):
        self.quiet_builtins()
        book_id = self.book([{"uid": 1, "keys": ["never-matches"], "content": "FORCED-ENTRY"},
                             {"uid": 2, "keys": ["猫"], "content": "SUPPRESSED-ENTRY"}])
        self.rule("chat.user_message", [{"type": "activate_entry", "book_id": book_id, "uid": 1, "turns": 1},
                                        {"type": "deactivate_entry", "book_id": book_id, "uid": 2, "turns": 1}],
                  conditions=[{"field": "event.text", "op": "contains", "value": "魔法"}])
        self.run_turn("魔法の猫")
        self.assertIn("FORCED-ENTRY", self.claude.calls[0]["user"])
        self.assertNotIn("SUPPRESSED-ENTRY", self.claude.calls[0]["user"])
        self.run_turn("猫だよ")
        self.assertIn("SUPPRESSED-ENTRY", self.claude.calls[1]["user"])
        self.assertNotIn("FORCED-ENTRY", self.claude.calls[1]["user"])

    def test_macros_expand_and_unknown_ones_stay(self):
        self.quiet_builtins()
        self.sql("INSERT INTO hook_vars (scope, persona_id, name, value) VALUES ('global', 0, 'v', '7')")
        self.rule("chat.open", [{"type": "inject", "text": "{{user}}|{{char}}|{{weekday}}|{{date}}|{{getvar::v}}|"
                                                          "{{event.first_today}}|{{random::a::b}}|{{roll::6}}|{{unknown}}|{{event.nope}}"}])
        with patch.object(clock, "now", lambda: THURSDAY):
            self.fire("chat.open")
        text = json.loads(self.sql("SELECT payload_json FROM hook_queue")[0][0])["text"]
        parts = text.split("|")
        self.assertEqual(parts[:6], ["对方", "Tester", "周四", "2026-11-12", "7", "True"])
        self.assertIn(parts[6], ("a", "b"))
        self.assertIn(int(parts[7]), range(1, 7))
        self.assertEqual(parts[8:], ["{{unknown}}", "{{event.nope}}"])

    def test_due_vocab_picks_by_meaning_and_voids_the_action_when_empty(self):
        self.quiet_builtins()
        self.rule("chat.user_message", [{"type": "inject", "text": "復習：{{due_vocab::1}}"}])
        hooks.emit("chat.user_message", 5, {"text": "うちのねこ"})
        self.assertEqual(self.log()[0]["skipped_reason"], "no_due_vocab")
        self.assertEqual(self.sql("SELECT count(*) FROM hook_queue")[0][0], 0)
        self.sql("INSERT INTO vocab_entries (language, lemma, reading, meaning, context_sentence, created_at) "
                 "VALUES ('ja', '食べる', 'たべる', '吃', 'x', '2026-01-01 00:00:00')")
        self.sql("INSERT INTO vocab_entries (language, lemma, reading, meaning, context_sentence, created_at) "
                 "VALUES ('ja', '猫', 'ねこ', '猫咪', 'x', '2026-02-01 00:00:00')")
        self.due_cards()
        before = [tuple(r) for r in self.sql("SELECT id, due_at FROM review_cards ORDER BY id")]
        semantic.set_embedder(lambda texts: [np.array([1.0, 0.0]) if ("猫" in t or "ねこ" in t) else np.array([0.0, 1.0])
                                             for t in texts], tag="fake")
        hooks.emit("chat.user_message", 5, {"text": "うちのねこ"})
        text = json.loads(self.sql("SELECT payload_json FROM hook_queue")[0][0])["text"]
        self.assertEqual(text, "復習：猫（ねこ）：猫咪")
        # 挑中不改排期（她真在回复里用到、这一轮发完才算碰见，见 chat.py）
        self.assertEqual([tuple(r) for r in self.sql("SELECT id, due_at FROM review_cards ORDER BY id")], before)
        semantic.set_embedder(None)  # 模型不可用：按到期时间
        hooks.emit("chat.user_message", 5, {"text": "うちのねこ"})
        text = json.loads(self.sql("SELECT payload_json FROM hook_queue ORDER BY id DESC")[0][0])["text"]
        self.assertEqual(text, "復習：食べる（たべる）：吃")

    def test_builtin_vocab_review_respects_turn_cooldown(self):
        self.sql("INSERT INTO vocab_entries (language, lemma, meaning, context_sentence) VALUES ('ja', '猫', '猫咪', 'x')")
        self.sql("INSERT INTO vocab_entries (language, lemma, meaning, context_sentence) VALUES ('ja', '犬', '狗', 'x')")
        self.sql("INSERT INTO vocab_entries (language, lemma, meaning, context_sentence) VALUES ('ja', '鳥', '鸟', 'x')")
        self.due_cards()
        for _ in range(9):
            self.run_turn("やあ")
        hits = ["对方该复习这个词了" in call["user"] for call in self.claude.calls]
        # one word at a time, then eight quiet turns
        self.assertEqual(hits, [True] + [False] * 7 + [True])
        first = next(call["user"] for call in self.claude.calls if "对方该复习这个词了" in call["user"])
        self.assertEqual(sum(word in first for word in ("猫咪", "狗", "鸟")), 1)


class LearningLinkTests(HookBase):
    def test_review_session_done_event_reaches_rules(self):
        self.quiet_builtins()
        self.rule("study.review_session_done", conditions=[{"field": "event.forgot", "op": ">=", "value": 2}])
        hooks.emit_soon("study.review_session_done", None, {"count": 10, "forgot": 3, "language": "ja"})
        hooks.emit_soon("study.review_session_done", None, {"count": 10, "forgot": 0, "language": "ja"})
        hooks.flush()
        self.assertEqual(self.var("n_study.review_session_done"), 1)
        meta = self.c.get("/api/hooks/meta").json()
        event = next(e for e in meta["events"] if e["id"] == "study.review_session_done")
        self.assertEqual([f["key"] for f in event["fields"]], ["count", "forgot", "language"])

    def test_due_counts_come_from_review_cards(self):
        from app.services.situation import Situation
        self.sql("INSERT INTO vocab_entries (language, lemma, meaning, context_sentence, due_at) "
                 "VALUES ('ja', '猫', '猫咪', 'x', '2000-01-01 00:00:00')")  # 旧字段到期了也不算
        self.sql("INSERT INTO pattern_entries (language, pattern_name) VALUES ('ja', '〜ながら')")
        with closing(self.connect()) as conn:
            sit = Situation(conn, self.persona(5), 19)
            self.assertEqual((sit.get("vocab_due"), sit.get("reviews_due")), (0, 0))
        self.due_cards(kinds=("vocab", "pattern"))
        with closing(self.connect()) as conn:
            sit = Situation(conn, self.persona(5), 19)
            self.assertEqual((sit.get("vocab_due"), sit.get("reviews_due")), (1, 2))

    def test_due_vocab_macro_goes_through_learning(self):
        self.quiet_builtins()
        self.rule("chat.user_message", [{"type": "inject", "text": "{{due_vocab::2}}"}])
        fake = [{"id": 1, "lemma": "雨", "reading": "あめ", "meaning": "雨", "card_id": 9}]
        with patch("app.services.learning.due_vocab", return_value=fake) as due:
            hooks.emit("chat.user_message", 5, {"text": "今日は雨", "language": "ja"})
        self.assertEqual(due.call_args.args[1:], ("ja", 2, "今日は雨"))
        self.assertEqual(json.loads(self.sql("SELECT payload_json FROM hook_queue")[0][0])["text"], "雨（あめ）：雨")


class ThrottleTests(HookBase):
    def setUp(self):
        super().setUp()
        self.quiet_builtins()

    def test_once_per_day_and_session(self):
        daily = self.rule("chat.open", once_per="day")
        session = self.rule("chat.idle", once_per="session")
        self.assertEqual(self.fire("chat.open")["fired"], [daily])
        self.assertEqual(self.fire("chat.open")["fired"], [])
        with patch.object(clock, "now", lambda: datetime.now() + timedelta(days=1)):
            self.assertEqual(self.fire("chat.open")["fired"], [daily])
        self.assertEqual(self.fire("chat.idle")["fired"], [session])
        self.assertEqual(self.fire("chat.idle")["fired"], [])
        with patch.object(hook_engine, "BOOT", "restarted"):
            self.assertEqual(self.fire("chat.idle")["fired"], [session])

    def test_cooldown_minutes_and_turns(self):
        minutes = self.rule("chat.open", cooldown_minutes=30)
        self.assertEqual(self.fire("chat.open")["fired"], [minutes])
        self.assertEqual(self.fire("chat.open")["fired"], [])
        with patch.object(clock, "now", lambda: datetime.now() + timedelta(minutes=31)):
            self.assertEqual(self.fire("chat.open")["fired"], [minutes])
        self.rule("chat.user_message", [{"type": "inc_var", "name": "turns_hit", "scope": "global"}], cooldown_turns=2)
        for _ in range(5):
            self.run_turn("やあ")
        self.assertEqual(self.var("turns_hit"), 3)  # 第 1、3、5 轮

    def test_probability_and_master_switch(self):
        never = self.rule("chat.open", probability=0)
        self.assertEqual(self.fire("chat.open")["fired"], [])
        self.assertEqual(self.log()[0]["skipped_reason"], "probability")
        self.c.put(f"/api/hooks/rules/{never}", json={"probability": 50})

        class Roll:
            def __init__(self, value):
                self.value = value

            def random(self):
                return self.value

        with patch.object(clock, "rng", Roll(0.9)):
            self.assertEqual(self.fire("chat.open")["fired"], [])
        with patch.object(clock, "rng", Roll(0.1)):
            self.assertEqual(self.fire("chat.open")["fired"], [never])
        self.assertEqual(self.c.put("/api/settings", json={"hooks_enabled": False}).status_code, 200)
        with patch.object(clock, "rng", Roll(0.1)):
            self.assertEqual(self.fire("chat.open")["fired"], [])


class BuiltinTests(HookBase):
    def test_builtins_are_seeded_editable_not_deletable_and_survive_upgrade(self):
        items = self.c.get("/api/hooks/rules").json()["items"]
        by_key = {r["builtin"]: r for r in items}
        self.assertEqual(set(by_key), {"reunion", "late_night", "study_reading", "study_listening", "vocab_review",
                                       "lesson_done", "unit_done"})
        self.assertFalse(by_key["lesson_done"]["enabled"])
        self.assertTrue(by_key["reunion"]["enabled"])
        self.assertEqual(by_key["vocab_review"]["cooldown_turns"], 8)
        self.assertEqual(self.c.delete(f"/api/hooks/rules/{by_key['reunion']['id']}").status_code, 409)
        r = self.c.put(f"/api/hooks/rules/{by_key['late_night']['id']}", json={"enabled": False})
        self.assertEqual((r.status_code, r.json()["enabled"], r.json()["builtin"]), (200, False, "late_night"))
        upgraded = [dict(spec, name=spec["name"] + " v2") for spec in hook_builtin.BUILTINS]
        with patch.object(hook_store, "BUILTINS", upgraded):
            with closing(hook_engine.connect()) as conn:
                hook_engine.ensure_builtins(conn)
                conn.commit()
        names = {r["builtin"]: r["name"] for r in self.c.get("/api/hooks/rules").json()["items"]}
        self.assertEqual(names["reunion"], "久别重逢 v2")  # 没改过的跟着新版走
        self.assertEqual(names["late_night"], "深夜")  # 用户改过的不动
        self.assertEqual(len(self.c.get("/api/hooks/rules").json()["items"]), 7)
        user_rule = self.rule("chat.open")
        self.assertEqual(self.c.delete(f"/api/hooks/rules/{user_rule}").status_code, 200)


class ProactiveTests(HookBase):
    def queue_reunion(self):
        self.old_message(days=3)
        result = self.fire("chat.open")
        self.assertEqual(result["pending"], [{"persona_id": 5, "count": 1}])

    def test_full_round_from_queue_to_messages(self):
        self.queue_reunion()
        self.assertEqual(self.c.get("/api/hooks/pending").json(), {"items": [{"persona_id": 5, "count": 1}]})
        before = self.sql("SELECT count(*) FROM messages WHERE role = 'user'")[0][0]
        r = self.c.post("/api/chat/proactive", json={"persona_id": 5})
        events = sse(r.text)
        names = [name for name, _ in events]
        self.assertEqual(names[:2], ["speaker", "guard"])  # 主动消息没有 read
        self.assertIn("bubble_done", names)
        self.assertEqual(names[-1], "done")
        self.assertTrue(all(data.get("proactive") is True for _, data in events))
        done = events[-1][1]
        self.assertEqual((done["session_id"], done["persona_id"]), (19, 5))
        self.assertEqual(self.sql("SELECT count(*) FROM messages WHERE role = 'user'")[0][0], before)
        stored = [r[0] for r in self.sql("SELECT role FROM messages WHERE id IN (%s)" % ",".join(map(str, done["message_ids"])))]
        self.assertEqual(stored, ["assistant"] * len(done["message_ids"]))
        call = self.claude.calls[0]
        self.assertEqual(call["key"], "p5s19")
        self.assertIn("对方已经 3 天没来找你了", call["user"])
        self.assertIn("不要提到这条提示", call["user"])
        all_text = " ".join(r[0] for r in self.sql("SELECT content FROM messages"))
        self.assertNotIn("没来找你", all_text)
        self.assertEqual(self.c.get("/api/hooks/pending").json(), {"items": []})
        again = sse(self.c.post("/api/chat/proactive", json={"persona_id": 5}).text)
        self.assertEqual(again, [("done", {"session_id": 19, "persona_id": 5, "persona_name": None, "language": None,
                                           "empty": True, "proactive": True})])
        hooks.flush()
        replies = [e for e in self.log() if e["event"] == "chat.reply"]
        self.assertEqual(replies, [])  # 没有 chat.reply 规则时不记日志
        self.assertEqual(self.sql("SELECT last_mood FROM chat_turns WHERE session_id = 19 AND persona_id = 5")[0][0], "happy")

    def test_absent_guest_enters_with_a_capsule(self):
        self.quiet_builtins()
        self.c.put("/api/chat/main", json={"guests": [{"persona_id": 6, "rule": {"type": "keyword", "keywords": ["tea"]}}]})
        self.rule("chat.open", [{"type": "say", "directive": "hi"}], persona_ids=[6])
        self.fire("chat.open")  # 不带 persona_id = 主人设打开；规则限定了 Emma
        events = sse(self.c.post("/api/chat/proactive", json={}).text)
        names = [name for name, _ in events]
        self.assertEqual(names[:3], ["system", "speaker", "guard"])
        self.assertEqual(events[0][1]["kind"], "enter")
        self.assertEqual((events[1][1]["persona_id"], events[1][1]["language"]), (6, "en"))
        self.assertEqual(names[-1], "done")
        self.assertEqual(events[-1][1]["session_id"], 19)
        self.assertEqual(self.claude.calls[0]["key"], "p6s19")
        items = self.c.get("/api/chat/main/messages").json()["items"]
        self.assertEqual(items[0]["role"], "system")
        self.assertEqual(items[0]["content"], "Emma 来了")

    def test_daily_cap_min_gap_and_expiry(self):
        self.quiet_builtins()
        self.rule("chat.idle", [{"type": "say", "directive": "ping"}])
        self.assertEqual(self.c.put("/api/settings", json={"hooks_say_daily_cap": 1}).status_code, 200)
        self.fire("chat.idle")
        self.fire("chat.idle")
        self.assertEqual(self.log()[0]["skipped_reason"], "say_daily_cap")
        self.c.put("/api/settings", json={"hooks_say_daily_cap": 5, "hooks_say_min_gap_minutes": 30})
        self.fire("chat.idle")
        self.assertEqual(self.log()[0]["skipped_reason"], "say_min_gap")
        self.assertEqual(self.sql("SELECT count(*) FROM hook_queue WHERE kind = 'say'")[0][0], 1)
        with patch.object(clock, "now", lambda: datetime.now() + timedelta(hours=7)):
            self.assertEqual(self.c.get("/api/hooks/pending").json(), {"items": []})
            events = sse(self.c.post("/api/chat/proactive", json={"persona_id": 5}).text)
        self.assertTrue(events[-1][1]["empty"])
        self.assertEqual(self.claude.calls, [])

    def test_no_concurrent_proactive_while_replying_to_the_user(self):
        self.queue_reunion()

        async def scenario():
            with patch.object(chat_service, "first_pause_seconds", lambda: 0.4):
                user = asyncio.create_task(self._collect(chat_service.run_chat_turn("ねえ")))
                await asyncio.sleep(0.1)
                proactive = [e async for e in chat_service.run_proactive_turn(5)]
                return await user, proactive

        user, proactive = asyncio.run(scenario())
        self.assertEqual(user[-1][0], "done")
        self.assertEqual([name for name, _ in proactive], ["done"])
        self.assertTrue(proactive[0][1]["empty"])
        self.assertEqual(self.c.get("/api/hooks/pending").json()["items"], [{"persona_id": 5, "count": 1}])

    def test_user_message_interrupts_a_proactive_message(self):
        self.queue_reunion()
        self.claude.replies = ["一つ目だよ\n---\n二つ目だよ\n⟦mood:normal⟧", base.JA_REPLY]

        async def scenario():
            with patch.object(chat_service, "first_pause_seconds", lambda: 0.4):
                proactive = asyncio.create_task(self._collect(chat_service.run_proactive_turn(5)))
                await asyncio.sleep(0.1)
                user = await self._collect(chat_service.run_chat_turn("ちょっと待って、別の話"))
                return await proactive, user

        proactive, user = asyncio.run(scenario())
        self.assertEqual(proactive[-1][0], "interrupted")
        self.assertTrue(proactive[-1][1]["proactive"])
        self.assertEqual(user[-1][0], "done")
        self.assertIn("二つ目だよ", self.claude.calls[1]["user"])  # 她没说完的话交接给下一轮

    def test_engine_failure_puts_the_message_back(self):
        self.queue_reunion()
        self.sql("INSERT OR REPLACE INTO settings (key, value) VALUES ('chat_fallback', 'none')")

        async def broken(*args, **kwargs):
            raise RuntimeError("engine down")
            yield  # noqa: unreachable

        self.claude.stream_chat = broken
        events = sse(self.c.post("/api/chat/proactive", json={"persona_id": 5}).text)
        self.assertEqual(events[-1][0], "error")
        self.assertTrue(events[-1][1]["proactive"])
        self.assertEqual(self.c.get("/api/hooks/pending").json()["items"], [{"persona_id": 5, "count": 1}])

    async def _collect(self, generator):
        return [item async for item in generator]


class ApiTests(HookBase):
    def test_meta_describes_everything_the_editor_needs(self):
        meta = self.c.get("/api/hooks/meta").json()
        self.assertEqual({e["id"] for e in meta["events"]}, set(hooks.EVENTS))
        reading = next(e for e in meta["events"] if e["id"] == "study.reading_finished")
        self.assertEqual([f["key"] for f in reading["fields"]], ["title", "correct", "total", "language"])
        fields = {f["key"]: f for f in meta["condition_fields"]}
        self.assertIn("between", fields["hour"]["ops"])
        self.assertIn("var.*", fields)
        self.assertEqual([a["type"] for a in meta["actions"]],
                         ["inject", "say", "set_var", "inc_var", "activate_entry", "deactivate_entry", "remember"])
        self.assertIn("{{due_vocab::2}}", [m["name"] for m in meta["macros"]])

    def test_rule_validation_and_partial_update(self):
        bad = [
            {"name": "x", "event": "chat.reply_typo", "actions": [{"type": "say", "directive": "x"}]},
            {"name": "x", "event": "chat.open", "actions": [{"type": "explode"}]},
            {"name": "x", "event": "chat.open", "actions": []},
            {"name": "x", "event": "chat.open", "actions": [{"type": "say", "directive": "x"}] * 11},
            {"name": "x", "event": "chat.open", "conditions": [{"field": "moon", "op": "==", "value": 1}],
             "actions": [{"type": "say", "directive": "x"}]},
            {"name": "x", "event": "chat.open", "actions": [{"type": "say", "directive": "x" * 2001}]},
        ]
        for body in bad:
            self.assertEqual(self.c.post("/api/hooks/rules", json=body).status_code, 422, body)
        rule_id = self.rule("chat.open", id=999, builtin="sneaky")
        r = self.c.put(f"/api/hooks/rules/{rule_id}", json={"enabled": False, "once_per": "day"})
        self.assertEqual((r.json()["enabled"], r.json()["once_per"], r.json()["builtin"]), (False, "day", None))
        self.assertEqual(self.c.put(f"/api/hooks/rules/{rule_id}", json={"once_per": "week"}).status_code, 422)
        self.assertEqual(self.c.put("/api/hooks/rules/12345", json={"enabled": False}).status_code, 404)
        with patch.object(hook_store, "MAX_RULES", 8):
            self.assertEqual(self.c.post("/api/hooks/rules", json={
                "name": "y", "event": "chat.open", "actions": [{"type": "say", "directive": "x"}]}).status_code, 409)

    def test_vars_log_and_fire_endpoints(self):
        self.assertEqual(self.c.put("/api/hooks/vars", json={"name": "x", "value": 3, "scope": "persona"}).status_code, 422)
        self.assertEqual(self.c.put("/api/hooks/vars", json={"name": "x", "value": 3, "scope": "persona",
                                                             "persona_id": 5}).status_code, 200)
        self.assertEqual(self.c.put("/api/hooks/vars", json={"name": "bad name!", "value": 1}).status_code, 422)
        self.assertEqual(self.c.get("/api/hooks/vars?persona_id=5").json()["items"],
                         [{"name": "x", "value": 3, "scope": "persona", "persona_id": 5}])
        self.c.put("/api/hooks/vars", json={"name": "x", "value": None, "scope": "persona", "persona_id": 5})
        self.assertEqual(self.c.get("/api/hooks/vars").json()["items"], [])
        self.assertEqual(self.c.post("/api/hooks/fire", json={"event": "chat.reply", "persona_id": 5}).status_code, 422)
        self.assertEqual(self.c.post("/api/hooks/fire", json={"event": "chat.open", "persona_id": 99}).status_code, 404)
        self.assertEqual(self.c.post("/api/hooks/fire", json={"event": "chat.open", "persona_id": 5,
                                                              "payload": {"deep": {"x": 1}}}).status_code, 422)
        with closing(hook_engine.connect()) as conn:
            for i in range(520):
                hook_store.log(conn, "chat.open", None, 5, {"actions": [], "skipped_reason": f"r{i}"})
            conn.commit()
        self.assertEqual(self.sql("SELECT count(*) FROM hook_log")[0][0], 500)
        items = self.c.get("/api/hooks/log?limit=3").json()["items"]
        self.assertEqual([i["skipped_reason"] for i in items], ["r519", "r518", "r517"])
        self.assertEqual(set(items[0]), {"at", "rule_id", "rule_name", "event", "persona_id", "actions", "skipped_reason"})
        self.assertEqual(self.c.get("/api/hooks/log?limit=501").status_code, 422)

    def test_settings_defaults_and_validation(self):
        settings = self.c.get("/api/settings").json()
        self.assertEqual((settings["hooks_enabled"], settings["hooks_say_daily_cap"], settings["hooks_say_min_gap_minutes"]),
                         (True, 4, 30))
        for body in ({"hooks_say_daily_cap": -1}, {"hooks_say_daily_cap": "lots"}, {"hooks_say_min_gap_minutes": 99999},
                     {"hooks_enabled": "maybe"}, {"hooks_say_daily_cap": True}):
            self.assertEqual(self.c.put("/api/settings", json=body).status_code, 422, body)
        settings = self.c.put("/api/settings", json={"hooks_enabled": False, "hooks_say_daily_cap": 2,
                                                     "hooks_say_min_gap_minutes": "15"}).json()
        self.assertEqual((settings["hooks_enabled"], settings["hooks_say_daily_cap"], settings["hooks_say_min_gap_minutes"]),
                         (False, 2, 15))
        self.sql("INSERT OR REPLACE INTO settings (key, value) VALUES ('hooks_lesson_seen:ja', 'x')")
        self.assertNotIn("hooks_lesson_seen:ja", self.c.get("/api/settings").json())

    def test_cross_site_requests_are_refused(self):
        evil = {"Origin": "https://evil.example"}
        cross = {"Sec-Fetch-Site": "cross-site"}
        for method, path, body in (("get", "/api/hooks/meta", None), ("get", "/api/hooks/rules", None),
                                   ("post", "/api/hooks/rules", {}), ("put", "/api/hooks/rules/1", {}),
                                   ("delete", "/api/hooks/rules/1", None), ("get", "/api/hooks/pending", None),
                                   ("post", "/api/hooks/fire", {"event": "chat.open", "persona_id": 5}),
                                   ("get", "/api/hooks/log", None), ("get", "/api/hooks/vars", None),
                                   ("put", "/api/hooks/vars", {}), ("post", "/api/chat/proactive", {"persona_id": 5})):
            for headers in (evil, cross):
                kwargs = {"headers": headers} if body is None else {"headers": headers, "json": body}
                self.assertEqual(getattr(self.c, method)(path, **kwargs).status_code, 403, (method, path))

    def test_broken_rules_never_break_chat(self):
        self.sql("INSERT INTO hook_rules (name, enabled, rule_json, created_at, updated_at) "
                 "VALUES ('broken', 1, '{nope', 'x', 'x')")
        self.rule("chat.user_message", [{"type": "say", "directive": "x"}])
        with patch.object(hook_engine, "_act", side_effect=RuntimeError("boom")):
            self.assertEqual(self.run_turn("やあ")[-1][0], "done")
        self.assertTrue(any((e["skipped_reason"] or "").startswith("error") for e in self.log()))
        self.assertEqual(self.c.get("/api/hooks/rules").status_code, 200)
        with patch.object(hooks, "emit", side_effect=RuntimeError("boom")):
            self.assertEqual(self.run_turn("やあ")[-1][0], "done")


if __name__ == "__main__":
    unittest.main()
