"""主聊天（docs/MAIN-CHAT.md）离线测试：临时 SQLite、假 provider，不连模型。

覆盖：主讲判定（点名 / @名字 / 关键词 / 默认）；语言判定（拨片 / 趣味随机且不连抽同一门 / 副人设母语）；
每个人设各自的常驻 key、各自的记忆抽取和语义回忆；补课块只含没见过的消息且有上限；切语言不改系统提示词；
【JINE 私聊】段在提示词里；口吻样本确定性抽样、换轮换批、语言不匹配不注入、校验上限；种子迁移幂等且不覆盖；
插话的概率 / 只插一个 / 被打断作废；read 和 speaker 事件顺序；节奏公式和贴图排最后；用户发贴图；
旧对话只读；GET/PUT /api/chat/main；会话指针模块和迁移；跨站请求被拒。
"""
import asyncio
import json
import random
import sys
import unittest
from contextlib import closing
from unittest.mock import AsyncMock, patch

import numpy as np

try:
    import test_lore as base
except ImportError:  # python -m unittest tests.test_main_chat
    from tests import test_lore as base

from app.services import (chat as chat_service, chat_room, clock, hooks, memoryx, prompts, recall,  # noqa: E402
                          session_pointers)

ORIGINAL_RECALL = recall.recall  # chat_setup 会把这几个换成假的，测真东西时用原来的
ORIGINAL_EXTRACT = memoryx.maybe_extract
ORIGINAL_BUBBLE_PAUSE = chat_service.bubble_pause_seconds
ORIGINAL_FIRST_PAUSE = chat_service.first_pause_seconds


class Fixed:
    """固定的随机源：random() 依次吐给定的值，choice/shuffle 按 random.Random(0)。"""

    def __init__(self, *values):
        self.values = list(values)
        self._r = random.Random(0)

    def random(self):
        return self.values.pop(0) if self.values else 0.99

    def choice(self, seq):
        return self._r.choice(seq)

    def shuffle(self, seq):
        self._r.shuffle(seq)


class MainBase(base.Base):
    def setUp(self):
        super().setUp()
        self.chat_setup()
        self.c = self.client()
        self.sql("INSERT INTO personas (id, name, language, profile_json) VALUES (7, 'Lena', 'de', '{}')")
        self.configure(primary_id=5)

    def configure(self, **patch_body):
        r = self.c.put("/api/chat/main", json=patch_body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def speakers(self, events):
        return [(d["persona_id"], d["role"], d["language"]) for n, d in events if n == "speaker"]

    def keys(self):
        return [c["key"] for c in self.claude.calls]


class DecisionTests(MainBase):
    def test_lead_naming_keyword_and_default(self):
        self.configure(guests=[{"persona_id": 6, "rule": {"type": "always"}},
                               {"persona_id": 7, "rule": {"type": "keyword", "keywords": ["Bier"]}}])
        with closing(self.connect()) as conn:
            config = chat_room.settings(conn)
            self.assertEqual(chat_room.choose_lead(conn, config, "hallo", None), 5)
            self.assertEqual(chat_room.choose_lead(conn, config, "hallo", 6), 6)
            self.assertEqual(chat_room.choose_lead(conn, config, "@Emma how are you", None), 6)
            self.assertEqual(chat_room.choose_lead(conn, config, "＠lena na?", None), 7)
            self.assertEqual(chat_room.choose_lead(conn, config, "ein Bier bitte", None), 7)
            self.assertEqual(chat_room.choose_lead(conn, config, "ein Bier, @Emma", None), 7)
            with self.assertRaises(ValueError):
                chat_room.choose_lead(conn, config, "x", 99)
            self.assertEqual(chat_room.present_guest_ids(conn, config, "nothing"), [6])
            self.assertEqual(chat_room.present_guest_ids(conn, config, "Bier!"), [6, 7])

    def test_time_rule_wraps_midnight(self):
        guest = chat_room.Guest(persona_id=6, rule={"type": "time", "start": "22:00", "end": "02:00"})
        self.assertTrue(chat_room.is_present(guest, "", "23:10"))
        self.assertTrue(chat_room.is_present(guest, "", "01:59"))
        self.assertFalse(chat_room.is_present(guest, "", "12:00"))

    def test_language_dial_fun_mode_and_native_guests(self):
        self.configure(language="en", guests=[{"persona_id": 6}])
        with closing(self.connect()) as conn:
            config = chat_room.settings(conn)
            primary, guest = self.persona(5), self.persona(6)
            self.assertEqual(chat_room.choose_language(conn, config, primary, 19), "en")  # 主人设：拨片
            self.assertEqual(chat_room.choose_language(conn, config, guest, 19), "en")  # 副人设：母语（英语）
            self.assertEqual(chat_room.choose_language(conn, self._with(conn, fun=True), self.persona(7), 19,
                                                       previous="ja") in ("en", "de"), True)
        fun = chat_room.MainSettings(primary_id=5, language="ja", fun=True, fun_languages=["ja", "en", "de"])
        previous, seen = None, []
        for _ in range(60):
            language = chat_room.fun_language(fun, previous)
            self.assertNotEqual(language, previous)  # 不连着两轮同一门
            seen.append(language)
            previous = language
        self.assertEqual(set(seen), {"ja", "en", "de"})
        single = chat_room.MainSettings(primary_id=5, language="ja", fun=True, fun_languages=["ja"])
        self.assertEqual(chat_room.fun_language(single, "ja"), "ja")

    def _with(self, conn, **changes):
        return chat_room.MainSettings.model_validate({**chat_room.settings(conn).model_dump(), **changes})

    def test_fun_mode_turns_use_the_dice_and_never_repeat(self):
        self.configure(fun=True, fun_languages=["ja", "en"])
        with patch.object(clock, "rng", random.Random(3)):
            for text in ("a", "b", "c", "d"):
                self.run_turn(text)
        languages = [r[0] for r in self.sql("SELECT language FROM messages WHERE role = 'assistant' ORDER BY id")]
        self.assertEqual(len(languages), 4)
        self.assertTrue(all(a != b for a, b in zip(languages, languages[1:])))

    def test_main_settings_api(self):
        body = self.c.get("/api/chat/main").json()
        self.assertEqual((body["primary_id"], body["language"], body["fun"], body["session_id"], body["pending"]),
                         (5, "ja", False, 19, 0))
        self.assertEqual({item["tag"] for item in body["languages"]}, {"ja", "en", "de"})
        self.assertEqual(body["present_guest_ids"], [])
        body = self.configure(language="de")  # 拨片只发一个字段
        self.assertEqual(body["language"], "de")
        for bad in ({"language": "fr"}, {"primary_id": 99}, {"guests": [{"persona_id": 5}]},
                    {"guests": [{"persona_id": 6, "chime": 101}]}, {"fun_languages": ["ja", "ja"]},
                    {"guests": [{"persona_id": 6, "rule": {"type": "time", "start": "22:00", "end": "22:00"}}]},
                    {"nonsense": 1}):
            self.assertEqual(self.c.put("/api/chat/main", json=bad).status_code, 422, bad)
        body = self.configure(primary_id=6)
        self.assertEqual((body["primary_id"], body["session_id"]), (6, 19))  # 主人设换人不换时间线


class BrainTests(MainBase):
    def setUp(self):
        super().setUp()
        self.configure(primary_chime=0, guests=[{"persona_id": 6, "chime": 0}, {"persona_id": 7, "chime": 0}])

    def test_each_persona_has_its_own_key_memory_and_recall(self):
        extract = AsyncMock()
        with patch("app.services.memoryx.maybe_extract", extract):
            self.claude.replies = [base.JA_REPLY, "Sure thing!\n⟦mood:happy⟧", base.JA_REPLY]
            self.run_turn("やあ")
            self.run_turn("hi Emma", to=6)
            self.run_turn("またね")
        self.assertEqual(self.keys(), ["p5s19", "p6s19", "p5s19"])
        self.assertEqual([c.args for c in extract.await_args_list], [(19, 5), (19, 6), (19, 5)])
        self.assertEqual([c.args[0] for c in self.recall.await_args_list], [5, 6, 5])
        self.assertEqual([c.kwargs["main_session_id"] for c in self.recall.await_args_list], [19, 19, 19])
        rows = self.sql("SELECT persona_id, language FROM messages WHERE role = 'assistant' ORDER BY id")
        self.assertEqual([tuple(r) for r in rows], [(5, "ja"), (6, "en"), (5, "ja")])

    def test_real_memory_extraction_only_reads_her_own_lines(self):
        for role, pid, text in (("user", None, "I love cats"), ("assistant", 5, "猫いいよね"),
                                ("assistant", 6, "Cats are great"), ("user", None, "my cat is Tama")):
            self.sql("INSERT INTO messages (session_id, role, persona_id, content) VALUES (19, ?, ?, ?)", (role, pid, text))
        provider = AsyncMock()
        provider.generate_json = AsyncMock(return_value={"items": [{"category": "fact", "content": "养了一只叫 Tama 的猫"}]})
        with patch.object(memoryx, "_BATCH_SIZE", 3), patch.object(memoryx, "get_utility_provider", return_value=provider):
            asyncio.run(ORIGINAL_EXTRACT(19, 6))
        prompt = provider.generate_json.await_args.args[0]
        self.assertIn("Cats are great", prompt)
        self.assertNotIn("猫いいよね", prompt)
        self.assertEqual([tuple(r) for r in self.sql("SELECT persona_id, content FROM memory_items")],
                         [(6, "养了一只叫 Tama 的猫")])
        with patch.object(memoryx, "_BATCH_SIZE", 3), patch.object(memoryx, "get_utility_provider", return_value=provider):
            asyncio.run(ORIGINAL_EXTRACT(19, 6))  # 水位记住了，不重复抽
        self.assertEqual(provider.generate_json.await_count, 1)

    def test_real_recall_keeps_other_personas_out_of_her_memory(self):
        self.sql("INSERT INTO sessions (id, persona_id, language) VALUES (21, 6, 'en')")
        rows = [(19, "user", None, "cats please"), (19, "assistant", 5, "猫の話だね"),
                (19, "assistant", 6, "cats cats cats"), (21, "assistant", None, "old cat memory")]
        for sid, role, pid, text in rows:
            self.sql("INSERT INTO messages (session_id, role, persona_id, content) VALUES (?, ?, ?, ?)",
                     (sid, role, pid, text))
        vec = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        for row in self.sql("SELECT id FROM messages"):
            self.sql("INSERT INTO message_embeddings (message_id, model, dim, vector) VALUES (?, 'fake', 2, ?)",
                     (row[0], vec))

        async def fake_embed(texts):
            return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]

        with patch.object(recall, "_embed_batch", fake_embed), patch.object(recall, "RECALL_THRESHOLD", 0.5):
            emma = asyncio.run(ORIGINAL_RECALL(6, "cats", set(), k=3, main_session_id=19))
            tester = asyncio.run(ORIGINAL_RECALL(5, "cats", set(), k=3, main_session_id=19))
        emma_text = "\n".join(h["text"] for h in emma)
        self.assertIn("你：old cat memory", emma_text)  # 她自己的旧对话
        self.assertIn("你：cats cats cats", emma_text)
        self.assertIn("Tester：猫の話だね", emma_text)  # 别人的话标名字，不当成「你」
        tester_text = "\n".join(h["text"] for h in tester)
        self.assertNotIn("old cat memory", tester_text)  # 别人的旧对话不是她的回忆
        self.assertIn("你：猫の話だね", tester_text)
        self.assertIn("Emma：cats cats cats", tester_text)
    def test_catch_up_only_unseen_and_capped(self):
        self.claude.replies = [base.JA_REPLY, "Hello!\n⟦mood:normal⟧", "Ok!\n⟦mood:normal⟧", "Bye!\n⟦mood:normal⟧"]
        self.run_turn("最初のメッセージ")  # 主人设开口
        self.run_turn("@Emma hi")
        first = self.claude.calls[1]["user"]
        self.assertIn("【你上次开口之后", first)
        self.assertIn("对方：最初のメッセージ", first)  # Emma 没见过的用户消息
        self.assertIn("Tester：うん、いいね", first)  # 主人设刚才的回复
        self.assertNotIn("对方：@Emma hi", first)  # 这一批本身不进补课块（在最后单独给）
        for i in range(20):
            self.sql("INSERT INTO messages (session_id, role, persona_id, content) VALUES (19, 'assistant', 7, ?)",
                     (f"Lena sagt {i} " + "x" * 40,))
        self.run_turn("@Emma what did Lena say?")
        block = self.claude.calls[2]["user"].split("【对方本轮消息】", 1)[0]
        lines = [line for line in block.splitlines() if line.startswith("Lena：")]
        self.assertEqual(len(lines), 12)  # 最多 12 条
        self.assertLessEqual(sum(len(line) for line in lines), 1500)
        self.assertIn("Lena sagt 19", block)  # 补的是最近的
        self.assertNotIn("Lena sagt 7 ", block)
        self.assertNotIn("最初のメッセージ", block)  # 看过的不再补
        self.run_turn("@Emma bye")
        self.assertNotIn("【你上次开口之后", self.claude.calls[3]["user"])
    def test_switching_language_keeps_the_system_prompt(self):
        self.claude.replies = [base.JA_REPLY, "Alles gut!\n⟦mood:normal⟧", "Sure!\n⟦mood:normal⟧"]
        self.run_turn("やあ")
        self.configure(language="de")
        self.run_turn("und jetzt?")
        self.configure(language="en")
        self.run_turn("and now?")
        systems = {c["system"] for c in self.claude.calls}
        self.assertEqual(len(systems), 1)
        self.assertEqual(self.claude.forgot, [])  # 切语言不触发重连
        self.assertTrue(self.claude.calls[1]["user"].startswith("【本轮语言：德语（de）】"))
        self.assertTrue(self.claude.calls[2]["user"].startswith("【本轮语言：英语（en）】"))
        self.assertEqual([r[0] for r in self.sql("SELECT language FROM messages WHERE role = 'assistant' ORDER BY id")],
                         ["ja", "de", "en"])

    def test_jine_block_and_iron_rule_in_the_system_prompt(self):
        with closing(self.connect()) as conn:
            system = prompts.compile_system_prompt(conn, self.persona(5))
        self.assertIn(prompts.JINE_PRIVATE_CHAT, system)
        self.assertIn("人设卡里写的和上面这段冲突时，听人设卡的。", system)
        self.assertLess(system.index("【关于对方，长期记住的事】"), system.index("【JINE 私聊】"))
        self.assertLess(system.index("【JINE 私聊】"), system.index("【铁律：只用【本轮语言】】"))
        self.assertIn("母语：日语", system)
        self.assertIn("口吻、性格、说话习惯都不变", system)
        self.assertNotIn("只说日语", system)
        spec = (base.ROOT / "docs/MAIN-CHAT.md").read_text(encoding="utf-8")
        self.assertIn(prompts.JINE_PRIVATE_CHAT, spec)  # 和规格逐字一致


class VoiceTests(MainBase):
    def samples(self, n=40):
        return [f"サンプル{i}だよ" for i in range(n)]

    def test_voice_samples_are_deterministic_rotate_and_match_language(self):
        persona = {**self.persona(5), "profile_json": json.dumps({"voice_samples": {"ja": self.samples()}})}
        a = chat_room.voice_block(persona, "ja", 19, 3)
        self.assertEqual(a, chat_room.voice_block(persona, "ja", 19, 3))  # 同一轮重试同一批
        self.assertNotEqual(a, chat_room.voice_block(persona, "ja", 19, 4))  # 下一轮换一批
        self.assertEqual(a.count("\n- "), 12)
        self.assertTrue(a.startswith("【口吻参考：只学说法，不把里面的事当成发生过】"))
        self.assertEqual(chat_room.voice_block(persona, "en", 19, 3), "")  # 本轮语言没有样本 → 不放

    def test_voice_samples_reach_the_turn_and_validate(self):
        r = self.c.put("/api/personas/5", json={"name": "Tester", "language": "ja",
                                                 "profile": {"voice_samples": {"ja": self.samples(20), "en": []}}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(set(r.json()["profile"]["voice_samples"]), {"ja"})
        self.run_turn("やあ")
        self.assertIn("【口吻参考", self.claude.calls[0]["user"])
        self.configure(language="en")
        self.claude.replies = ["ok!\n⟦mood:normal⟧"]
        self.run_turn("hi")
        self.assertNotIn("【口吻参考", self.claude.calls[1]["user"])
        for bad in ({"ja": ["x" * 61]}, {"ja": [f"s{i}xx" for i in range(601)]}, {"ja": "not a list"}):
            r = self.c.put("/api/personas/5", json={"name": "Tester", "language": "ja", "profile": {"voice_samples": bad}})
            self.assertEqual(r.status_code, 422, bad)

    def test_ame_seed_is_written_once_and_never_overwritten(self):
        self.sql("INSERT INTO personas (id, name, language, profile_json) VALUES (8, '糖糖', 'ja', '{}')")
        self.sql("INSERT INTO personas (id, name, language, profile_json) VALUES (9, '糖糖（英语）', 'en', '{}')")
        self.sql("INSERT INTO personas (id, name, language, profile_json) VALUES (10, '糖糖2', 'ja', ?)",
                 (json.dumps({"voice_samples": {"ja": ["自分の口癖だよ"]}}),))
        seed = json.loads((chat_room.VOICE_DIR / "ame.ja.json").read_text(encoding="utf-8"))["samples"]
        self.assertTrue(200 <= len(seed) <= 600)
        self.assertTrue(all(2 <= len(s) <= 60 and "\n" not in s for s in seed))
        self.assertEqual(len(set(seed)), len(seed))

        def run():
            with closing(self.connect()) as conn:
                chat_room.migrate(conn)
                conn.commit()

        run()
        profile = lambda pid: json.loads(self.sql("SELECT profile_json FROM personas WHERE id = ?", (pid,))[0][0])
        self.assertEqual(profile(8)["voice_samples"]["ja"], seed)
        self.assertNotIn("voice_samples", profile(9))  # 不是日语人设
        self.assertEqual(profile(10)["voice_samples"]["ja"], ["自分の口癖だよ"])  # 用户写过的不碰
        self.sql("UPDATE personas SET profile_json = ? WHERE id = 8", (json.dumps({"voice_samples": {"ja": ["改过"]}}),))
        run()
        self.assertEqual(profile(8)["voice_samples"]["ja"], ["改过"])
        self.sql("UPDATE personas SET profile_json = '{}' WHERE id = 8")  # 删光了也不再写回来
        run()
        self.assertNotIn("voice_samples", profile(8))


class ChimeAndEventTests(MainBase):
    def test_read_and_speaker_order_with_a_chime(self):
        self.configure(guests=[{"persona_id": 6, "chime": 100}])
        self.claude.replies = ["一つ目\n---\n二つ目\n⟦mood:happy⟧", "Me!\n---\nAnd more\n⟦mood:normal⟧"]
        events = self.run_turn("ねえねえ")
        names = [n for n, _ in events]
        self.assertEqual(names, ["read", "speaker", "guard", "delta", "bubble_done", "delta", "bubble_done",
                                 "speaker", "guard", "delta", "bubble_done", "done"])
        self.assertEqual(self.speakers(events), [(5, "lead", "ja"), (6, "chime", "en")])
        read = dict(events)["read"]
        user_id = self.sql("SELECT id FROM messages WHERE role = 'user'")[0][0]
        self.assertEqual(read["message_ids"], [user_id])
        done = events[-1][1]
        self.assertEqual(done["persona_id"], 5)
        self.assertEqual(len(done["message_ids"]), 3)  # 插话只要一条
        for name, data in events:
            self.assertTrue({"session_id", "persona_id", "persona_name", "language"} <= set(data), name)
        self.assertEqual(self.keys(), ["p5s19", "p6s19"])
        self.assertIn("现在不是轮到你主讲", self.claude.calls[1]["user"])
        self.assertIn("对方：ねえねえ", self.claude.calls[1]["user"])
        self.assertIn("Tester：一つ目", self.claude.calls[1]["user"])
        listed = self.c.get("/api/chat/main/messages").json()["items"]
        self.assertEqual([(m["role"], m["persona_id"], m["read"]) for m in listed],
                         [("user", None, True), ("assistant", 5, None), ("assistant", 5, None), ("assistant", 6, None)])
        self.assertEqual(listed[3]["persona_name"], "Emma")

    def test_chime_probability_and_at_most_one(self):
        self.configure(guests=[{"persona_id": 6, "chime": 0}, {"persona_id": 7, "chime": 0}])
        self.run_turn("a")
        self.assertEqual(self.keys(), ["p5s19"])
        self.configure(guests=[{"persona_id": 6, "chime": 100}, {"persona_id": 7, "chime": 100}])
        self.claude.replies = [base.JA_REPLY, "Yo!\n⟦mood:normal⟧"]
        events = self.run_turn("b")
        self.assertEqual(len([e for e in events if e[0] == "speaker"]), 2)
        self.configure(guests=[{"persona_id": 6, "chime": 50}])
        with patch.object(clock, "rng", Fixed(0.6)):
            events = self.run_turn("c")
        self.assertEqual(len([e for e in events if e[0] == "speaker"]), 1)  # 0.6×100 ≥ 50：没掷中
        with patch.object(clock, "rng", Fixed(0.3)):
            self.claude.replies = [base.JA_REPLY, "Hey!\n⟦mood:normal⟧"]
            events = self.run_turn("d")
        self.assertEqual(len([e for e in events if e[0] == "speaker"]), 2)
        self.configure(guests=[{"persona_id": 6, "chime": 100, "enabled": False}])
        self.assertEqual(len([e for e in self.run_turn("e") if e[0] == "speaker"]), 1)

    def test_guest_lead_lets_the_primary_chime(self):
        self.configure(primary_chime=100, guests=[{"persona_id": 6, "chime": 0}])
        self.claude.replies = ["Hi!\n⟦mood:normal⟧", base.JA_REPLY]
        events = self.run_turn("hi", to=6)
        self.assertEqual(self.speakers(events), [(6, "lead", "en"), (5, "chime", "ja")])

    def test_user_message_cancels_a_chime(self):
        self.configure(guests=[{"persona_id": 6, "chime": 100}])
        self.claude.replies = [base.JA_REPLY, "Wait, I also--\n---\nmore\n⟦mood:normal⟧", base.JA_REPLY]
        first_pause = {"n": 0}

        def pause():
            first_pause["n"] += 1
            return 0.4 if first_pause["n"] == 2 else 0  # 第二次说话（插话）开口前停久一点

        async def scenario():
            with patch.object(chat_service, "first_pause_seconds", pause):
                first = asyncio.create_task(self._collect("ねえ"))
                for _ in range(100):
                    await asyncio.sleep(0.01)
                    if len(self.claude.calls) >= 2:
                        break
                await asyncio.sleep(0.05)
                second = await self._collect("ちょっと聞いて")
                return await first, second

        first, second = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual(first[-1][0], "done")  # 主讲这一轮照常完成
        self.assertNotIn("interrupted", [n for n, _ in first])
        self.assertEqual([d["persona_id"] for n, d in first if n == "bubble_done"], [5])  # 插话一条都没落
        self.assertEqual(second[-1][0], "done")
        self.assertNotIn("Wait, I also", self.claude.calls[2]["user"])  # 插话作废，不交接
        second_user = self.sql("SELECT max(id) FROM messages WHERE role = 'user'")[0][0]
        self.assertEqual(self.sql("SELECT count(*) FROM messages WHERE persona_id = 6 AND id < ?", (second_user,))[0][0], 0)

    async def _collect(self, text):
        return [item async for item in chat_service.run_chat_turn(text)]

    def test_rhythm_formula_and_stickers_last(self):
        self.assertEqual(ORIGINAL_FIRST_PAUSE(), 0.25)
        self.assertAlmostEqual(ORIGINAL_BUBBLE_PAUSE("あ" * 10), 0.43)
        self.assertEqual(ORIGINAL_BUBBLE_PAUSE("あ" * 500), 1.7)
        self.assertEqual(ORIGINAL_BUBBLE_PAUSE(""), 0.25)
        self.claude.replies = ["⟦sticker:cho_peace⟧\nやったね\n---\nすごい\n⟦mood:happy⟧"]
        events = self.run_turn("合格した！")
        bubbles_done = [d for n, d in events if n == "bubble_done"]
        self.assertEqual([(d["sticker"], d["text"]) for d in bubbles_done],
                         [(None, "やったね"), (None, "すごい"), ("cho_peace", "")])

    def test_user_sticker_reaches_the_model_as_its_meaning(self):
        meaning = chat_room.sticker_meanings()["cho_peace"]
        events = self.run_turn("", sticker="cho_peace")
        self.assertEqual(events[-1][0], "done")
        self.assertIn(f"（发了一张贴图：{meaning}）", self.claude.calls[0]["user"])
        self.assertEqual(self.sql("SELECT content FROM messages WHERE role = 'user'")[0][0], "[sticker:cho_peace]")
        item = self.c.get("/api/chat/main/messages").json()["items"][0]
        self.assertEqual((item["sticker"], item["role"]), ("cho_peace", "user"))
        self.assertEqual(self.run_turn("", sticker="no-such-sticker")[-1][0], "error")
        stickers = self.c.get("/api/stickers").json()["items"]
        self.assertIn({"id": "cho_peace", "url": "/assets/stickers/cho_peace.png", "meaning": meaning}, stickers)


class LearningAfterTurnTests(MainBase):
    """一轮完整发完之后：chat_success（用户用到到期词）、encounter_lemmas（双方出现的收藏词）、record_event。"""

    def setUp(self):
        super().setUp()
        self.calls = []
        patches = [patch("app.services.learning.chat_success", side_effect=lambda c, l, x: self.calls.append(("success", l, list(x)))),
                   patch("app.services.learning.encounter_lemmas", side_effect=lambda c, l, x: self.calls.append(("encounter", l, list(x)))),
                   patch("app.services.learning.record_event", side_effect=lambda c, k, l, r, d: self.calls.append(("event", k, l, r, d)))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_calls_after_a_complete_turn(self):
        self.claude.replies = ["ねこかわいい\n⟦fix:行くます=>行きます⟧\n⟦mood:happy⟧"]
        self.configure(language="ja")
        self.run_turn("うちのねこ")
        hooks.flush()
        self.assertEqual(self.calls[0], ("success", "ja", ["うちのねこ"]))  # 测试里分词器是"整句一个词"
        self.assertEqual(self.calls[1], ("encounter", "ja", ["うちのねこ", "ねこかわいい"]))
        self.assertEqual(self.calls[2], ("event", "chat", "ja", "19", {"turns": 1, "fixes": 1}))

    def test_interrupted_turn_records_nothing(self):
        self.claude.replies = ["一つ目\n---\n二つ目\n⟦mood:normal⟧", base.JA_REPLY]

        async def scenario():
            with patch.object(chat_service, "first_pause_seconds", lambda: 0.4):
                first = asyncio.create_task(self._collect("長い話して"))
                await asyncio.sleep(0.1)
                second = await self._collect("ちょっと待って、やっぱり別の話")
                return await first, second

        first, second = asyncio.run(scenario())
        hooks.flush()
        self.assertEqual(first[-1][0], "interrupted")
        self.assertEqual([c for c in self.calls if c[0] == "event"], [("event", "chat", "ja", "19", {"turns": 1, "fixes": 0})])
        self.assertNotIn("長い話して", [w for c in self.calls if c[0] != "event" for w in c[2]])

    async def _collect(self, text):
        return [item async for item in chat_service.run_chat_turn(text)]

    def test_learning_failure_does_not_touch_chat(self):
        with patch("app.services.learning.encounter_lemmas", side_effect=RuntimeError("boom")):
            events = self.run_turn("やあ")
            hooks.flush()
        self.assertEqual(events[-1][0], "done")


class RealLearningTests(MainBase):
    def test_saved_words_are_encountered_and_due_ones_count_as_success(self):
        from app.services import learning
        self.sql("INSERT INTO vocab_entries (language, lemma, meaning, context_sentence) VALUES ('ja', 'ねこ', '猫', 'x')")
        self.due_cards()
        self.claude.replies = ["ねこ\n⟦mood:happy⟧"]
        self.run_turn("ねこ")
        hooks.flush()
        self.assertEqual(self.sql("SELECT encounters FROM vocab_entries")[0][0], 1)  # 一轮记一次（去重后的词）
        card = self.sql("SELECT reps, due_at FROM review_cards WHERE kind = 'vocab'")[0]
        self.assertGreater(card[1], "2000-01-01 00:00:00")  # 记得了一次，排期往后挪
        self.assertEqual(self.sql("SELECT kind, language, ref FROM study_events")[0][:], ("chat", "ja", "19"))


class ArchiveAndApiTests(MainBase):
    def test_archives_are_read_only(self):
        self.sql("INSERT INTO sessions (id, persona_id, language) VALUES (21, 6, 'en')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (21, 'user', 'old talk')")
        self.run_turn("やあ")
        items = self.c.get("/api/chat/archives").json()["items"]
        self.assertEqual([(a["session_id"], a["persona_name"], a["count"]) for a in items], [(21, "Emma", 1)])
        detail = self.c.get("/api/chat/archives/21").json()
        self.assertEqual((detail["read_only"], detail["items"][0]["content"]), (True, "old talk"))
        self.assertEqual(self.c.get("/api/chat/archives/19").status_code, 404)  # 主聊天不是旧对话
        r = self.c.post("/api/chat", json={"persona_id": 6, "session_id": 21, "text": "続き"})
        self.assertEqual(sse_names(r.text)[-1], "done")
        self.assertEqual(self.sql("SELECT count(*) FROM messages WHERE session_id = 21")[0][0], 1)  # 旧对话没被续

    def test_implicit_primary_is_the_most_recent_contact_and_gets_pinned(self):
        self.sql("DELETE FROM settings WHERE key IN ('chat_main', 'chat_main_session')")
        self.sql("INSERT INTO sessions (id, persona_id, language) VALUES (21, 6, 'en')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', 'older')")
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (21, 'user', 'newest')")
        body = self.c.get("/api/chat/main").json()
        self.assertEqual((body["primary_id"], body["session_id"], body["language"]), (6, 21, "en"))
        self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', 'even newer')")
        body = self.c.get("/api/chat/main").json()
        self.assertEqual((body["primary_id"], body["session_id"]), (6, 21))  # 钉住了，不再跟着变
    def test_messages_paging(self):
        for i in range(5):
            self.sql("INSERT INTO messages (session_id, role, content) VALUES (19, 'user', ?)", (f"m{i}",))
        ids = [r[0] for r in self.sql("SELECT id FROM messages ORDER BY id")]
        page = self.c.get("/api/chat/main/messages?limit=2").json()["items"]
        self.assertEqual([m["content"] for m in page], ["m3", "m4"])
        older = self.c.get(f"/api/chat/main/messages?limit=2&before={ids[3]}").json()["items"]
        self.assertEqual([m["content"] for m in older], ["m1", "m2"])

    def test_chat_open_without_persona_is_the_primary(self):
        rule = self.c.post("/api/hooks/rules", json={"name": "x", "event": "chat.open",
                                                     "actions": [{"type": "inc_var", "name": "opened"}]}).json()["id"]
        r = self.c.post("/api/hooks/fire", json={"event": "chat.open"})
        self.assertEqual(r.json()["fired"], [rule])
        self.assertEqual(json.loads(self.sql("SELECT value FROM hook_vars WHERE name = 'opened'")[0][0]), 1)
        self.assertEqual(self.sql("SELECT persona_id FROM hook_vars WHERE name = 'opened'")[0][0], 5)

    def test_cross_site_requests_are_refused(self):
        evil = {"Origin": "https://evil.example"}
        for method, path, body in (("get", "/api/chat/main", None), ("put", "/api/chat/main", {"fun": True}),
                                   ("get", "/api/chat/main/messages", None), ("get", "/api/chat/archives", None),
                                   ("get", "/api/chat/archives/19", None), ("get", "/api/stickers", None),
                                   ("post", "/api/chat", {"text": "x"}), ("post", "/api/chat/proactive", {})):
            kwargs = {"headers": evil} if body is None else {"headers": evil, "json": body}
            self.assertEqual(getattr(self.c, method)(path, **kwargs).status_code, 403, path)


class PointerTests(MainBase):
    def test_get_set_clear_and_migration(self):
        self.sql("UPDATE sessions SET claude_session_id = 'cli-primary' WHERE id = 19")
        with closing(self.connect()) as conn:
            session_pointers.migrate(conn)
            session_pointers.migrate(conn)
            conn.commit()
        self.assertEqual(session_pointers.get("p5s19"), "cli-primary")
        self.assertIsNone(session_pointers.get("p6s19"))  # 副人设不会拿到主人设的指针
        session_pointers.set("p6s19", "cli-emma")
        session_pointers.set("p6s19", "gpt-thread", engine="chatgpt")
        self.assertEqual((session_pointers.get("p6s19"), session_pointers.get("p6s19", "chatgpt")),
                         ("cli-emma", "gpt-thread"))
        self.assertEqual(session_pointers.clear("p6s19", engine="claude"), 1)
        self.assertIsNone(session_pointers.get("p6s19"))
        self.assertEqual(session_pointers.clear(persona_id=6), 1)
        session_pointers.set("p6s19", "again")
        self.assertEqual(session_pointers.clear(session_id=19), 2)
        session_pointers.set("p5s19", None)
        self.assertIsNone(session_pointers.parse("main"))
        self.assertIsNone(session_pointers.get("garbage"))

    def test_seed_history_for_providers_is_per_persona(self):
        for role, pid, text in (("user", None, "hi all"), ("assistant", 5, "やあ"), ("assistant", 6, "Hello!"),
                                ("user", None, "pending")):
            self.sql("INSERT INTO messages (session_id, role, persona_id, content) VALUES (19, ?, ?, ?)", (role, pid, text))
        self.assertEqual(chat_room.seed_history("p6s19"), [
            {"role": "user", "content": "hi all"}, {"role": "user", "content": "（Tester说）やあ"},
            {"role": "assistant", "content": "Hello!"}])
        recap = prompts.current_session_recap("p6s19")
        self.assertIn("你：Hello!", recap)
        self.assertIn("Tester：やあ", recap)


def sse_names(text):
    return [line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("event: ")]


if __name__ == "__main__":
    unittest.main()
