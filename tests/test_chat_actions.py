"""Offline coverage for transient scenes, action replies and stage speech warm-up."""
import asyncio
import unittest
from unittest.mock import patch

try:
    import test_lore as base
except ImportError:
    from tests import test_lore as base

from pydantic import ValidationError
from app.routers.chat import ChatIn
from app.routers import chat as router
from app.services import actions, scene, chat as service, chat_room, listening_tts


class ActionTests(unittest.TestCase):
    def extract(self, text):
        return actions.extract(text, languages={'ja', 'en'}, formats={'en_talk'})

    def test_valid_actions(self):
        for line, name, arg in [
            ('open workspace-agent', 'open', 'workspace-agent'), ('listen', 'listen', None),
            ('listen en_talk', 'listen', 'en_talk'), ('review', 'review', None),
            ('language ja', 'language', 'ja'), ('fun on', 'fun', 'on'), ('voice off', 'voice', 'off'),
            ('save 猫', 'save', '猫'), ('manage 改课程', 'manage', '改课程'),
        ]:
            with self.subTest(line=line):
                self.assertEqual(self.extract('[do:' + line + ']'), ('', [{'name': name, 'arg': arg}]))

    def test_invalid_name_and_args_are_removed(self):
        for line in ['unknown hi', 'open nowhere', 'review now', 'language fr',
                     'fun yes', 'voice', 'save', 'save ' + 'x' * 61, 'manage x', 'manage ' + 'x' * 301]:
            with self.subTest(line=line):
                self.assertEqual(self.extract('[do:' + line + ']'), ('', []))

    def test_names_she_sees_are_accepted(self):
        formats, languages = {'ja_task': '課題理解', 'ja_response': '即時応答'}, {'ja': '日本語', 'en': 'English'}
        for line, name, arg in [
            ('open 听力', 'open', 'listening'), ('open 「复习」', 'open', 'drill'),
            ('listen 課題理解', 'listen', 'ja_task'), ('listen 会話', 'listen', None),   # a type she made up = whatever is set
            ('language English', 'language', 'en'),
        ]:
            with self.subTest(line=line):
                self.assertEqual(actions.extract('[do:' + line + ']', languages=languages, formats=formats),
                                 ('', [{'name': name, 'arg': arg}]))

    def test_first_two_valid_and_action_only(self):
        self.assertEqual(self.extract('[do:bad]\n[do:review]\n[do:listen]\n[do:voice off]'),
                         ('', [{'name': 'review', 'arg': None}, {'name': 'listen', 'arg': None}]))

    def test_other_lines_and_line_endings_are_unchanged(self):
        self.assertEqual(self.extract('  Hello\r\n  [do:review]  \r\n\r\nBye\n')[0], '  Hello\r\n\r\nBye\n')
        self.assertEqual(self.extract('before\n[do:bad]\nafter')[0], 'before\nafter')
        self.assertEqual(self.extract('inline [do:review]')[0], 'inline [do:review]')

    def test_prompt_exact(self):
        expected = '''【你可以替他动手】这个软件你也能操作。要动手就在回复里单独写一行（这一行他看不到）：
[do:open 页面] 打开一页：talk 聊天、today 今天、reading 阅读、listening 听力、coach 口语、drill 复习、review 错题本、notebook 单词本、settings 设置
[do:listen 题型] 马上开一组听力，题型可以不写；现在能选：en_conversation 校园对话、en_talk 学术讲解
[do:review] 开始复习
[do:lesson] 开始上下一课（他说「上课吧」「来一课」这类才用）
[do:open course] 打开课程页
[do:language 语言代码] 把聊天语言拨过去；现在有：en English、ja 日本語
[do:fun on] / [do:fun off] 趣味模式
[do:voice on] / [do:voice off] 开关你的声音
[do:save 单词] 把这个词收进他的单词本
[do:manage 一句话说清要改什么] 改设置：课程、世界书、阅读来源、题型、听力安排、角色卡
绝大多数时候不用动手。只有他明明白白让你做（「打开…」「帮我…」「…して」「…にして」）才写，一次最多两行；拿不准就不写，问他一句。他只是问你话、跟你聊天的时候，绝不替他换页面。动手的同时照常跟他说话，别把这些写法念出来。
'''
        self.assertEqual(actions.prompt_block('en', {'en': 'English', 'ja': '日本語'},
                                              {'en_conversation': '校园对话', 'en_talk': '学术讲解'}), expected)


class SceneTests(unittest.TestCase):
    def test_talk(self):
        self.assertEqual(scene.scene_block({'tab': 'talk', 'text': 'ignored'}, 'English'), '')

    def test_no_text_and_fallback_title(self):
        self.assertEqual(scene.scene_block({'tab': 'reading', 'title': '阅读', 'text': '  '}, 'English'),
                         '【他现在在哪】他开着「阅读」页（English）。\n')
        self.assertEqual(scene.scene_block({'tab': 'reading'}, None), '【他现在在哪】他开着「reading」页。\n')

    def test_long_text_and_actions(self):
        text = 'a' * 3000 + 'middle' * 200 + 'z' * 1000
        self.assertEqual(scene.scene_block({'tab': 'reading', 'text': ' ' + text + ' ', 'actions': ['▶ 阅读', '♪ ON']}, None),
                         '【他现在在哪】他开着「reading」页。屏幕上现在是这些（只是让你知道他在看什么，不是他说的话；别整段复述）：\n'
                         + 'a' * 3000 + '\n……\n' + 'z' * 1000 + '\n【你刚才替他做的】\n- ▶ 阅读\n- ♪ ON\n')
        self.assertEqual(scene.scene_block({'tab': 'talk', 'actions': ['▶ 阅读']}, None), '【你刚才替他做的】\n- ▶ 阅读\n')

    def test_stage_line_exact(self):
        self.assertEqual(scene.STAGE_LINE, '【这句是弹幕】他没切回聊天页，是在你的小窗底下打了这一句，像直播间里刷过来的一条弹幕。像主播念到弹幕那样回：只回一两条，每条一两句，是能说出口的话——这几条会用你的声音念出来，所以不要颜文字，也不要括号里的动作。\n')

    def test_request_validation(self):
        body = ChatIn(text='hi', via='stage', scene={'tab': 'reading'})
        self.assertEqual(body.scene.text, '')
        for patch_body in [dict(via='other'), dict(scene={'tab': 'reading', 'unknown': True}),
                           dict(scene={'tab': ''}), dict(scene={'tab': 'x' * 33}),
                           dict(scene={'tab': 'reading', 'text': 'x' * 8001}),
                           dict(scene={'tab': 'reading', 'title': 'x' * 121}),
                           dict(scene={'tab': 'reading', 'language': 'x' * 17}),
                           dict(scene={'tab': 'reading', 'actions': ['x'] * 4}),
                           dict(scene={'tab': 'reading', 'actions': ['x' * 161]})]:
            with self.subTest(body=patch_body), self.assertRaises(ValidationError):
                ChatIn(**patch_body)


class TurnTests(base.Base):
    def setUp(self):
        super().setUp()
        self.chat_setup()
        self.c = self.client()
        self.assertEqual(self.c.put('/api/chat/main', json={'primary_id': 5, 'language': 'ja', 'primary_chime': 0}).status_code, 200)

    def test_scene_language_and_talk_dial(self):
        self.claude.replies = ['Sure thing!', base.JA_REPLY, base.JA_REPLY]
        for tab, tag, expected in [('reading', 'en', 'en'), ('talk', 'en', 'ja'), ('reading', 'xx', 'ja')]:
            events = self.run_turn('hi', scene={'tab': tab, 'language': tag})
            self.assertEqual(events[-1][0], 'done', events)
            self.assertEqual(next(data['language'] for name, data in events if name == 'speaker'), expected)
        self.assertEqual(self.c.get('/api/chat/main').json()['language'], 'ja')

    def test_background_order_actions_meta_and_no_scene_storage(self):
        self.claude.replies = [base.JA_REPLY + '\n[do:open reading]\n[do:voice on]']
        page = {'tab': 'reading', 'title': '阅读', 'language': 'ja', 'text': 'SCREEN-ONLY', 'actions': ['▶ 阅读']}
        events = self.run_turn('hi', via='stage', scene=page)
        names = [name for name, _ in events]
        self.assertEqual(names[-1], 'done', events)
        self.assertEqual(names.count('action'), 2)
        self.assertLess(max(i for i, n in enumerate(names) if n == 'bubble_done'), names.index('action'))
        action = next(data for name, data in events if name == 'action')
        self.assertEqual(action, {'name': 'open', 'arg': 'reading', 'session_id': 19, 'persona_id': 5,
                                  'persona_name': 'Tester', 'language': 'ja'})
        prompt = self.claude.calls[0]['user']
        self.assertIn(actions.prompt_block('ja', {'ja': '日本語', 'en': 'English', 'de': 'Deutsch'},
                                           {k: v.label for k, v in service.profiles_for('ja').items()}), prompt)
        self.assertLess(prompt.index('【你可以替他动手】'), prompt.index('【他现在在哪】'))
        self.assertLess(prompt.index('【你刚才替他做的】'), prompt.index(scene.STAGE_LINE))
        self.assertLess(prompt.index(scene.STAGE_LINE), prompt.index('【对方本轮消息】'))
        self.assertFalse(any('SCREEN-ONLY' in r[0] or '[do:' in r[0] for r in self.sql('SELECT content FROM messages')))

    def test_action_only_reply(self):
        self.claude.replies = ['[do:review]']
        events = self.run_turn('review')
        self.assertEqual([n for n, _ in events if n in {'action', 'bubble_done', 'done'}], ['action', 'done'])

    def test_guard_retry_strips_actions(self):
        self.claude.replies = ['Wrong\n[do:voice on]', base.JA_REPLY + '\n[do:review]']
        with patch.object(service.guard, 'check', side_effect=[False, True]) as check:
            events = self.run_turn('hi')
        self.assertTrue(all('[do:' not in call.args[0] for call in check.call_args_list))
        self.assertEqual([d['name'] for n, d in events if n == 'action'], ['review'])

    def test_chime_and_proactive_strip_but_do_not_act(self):
        async def collect(role, directive=None):
            outcome = {}
            events = [item async for item in service._speak(self.persona(5), 19, service._state_for(19), role=role,
                      language='ja', joined_text='', batch_images=[], batch_ids=[], outcome=outcome, directive=directive)]
            await asyncio.sleep(0.05)
            return events, outcome
        for role, directive in [('chime', None), ('lead', 'hi')]:
            self.claude.replies = ['[do:review]']
            events, outcome = asyncio.run(collect(role, directive))
            self.assertEqual(outcome['status'], 'done', events)
            self.assertFalse(any(n in {'action', 'bubble_done'} for n, _ in events))

    def test_interrupted_reply_never_acts(self):
        async def collect():
            events = []
            async for name, data in service.run_chat_turn('hi'):
                events.append((name, data))
                if name == 'guard':
                    service._state_for(19).delivery_event.set()
            return events
        self.claude.replies = [base.JA_REPLY + '\n[do:review]']
        events = asyncio.run(collect())
        self.assertTrue(any(n == 'interrupted' for n, _ in events), events)
        self.assertFalse(any(n == 'action' for n, _ in events))

    def test_latest_batch_scene_and_via_win_and_clear(self):
        async def collect():
            first = asyncio.create_task(self._turn('one', via='stage', scene={'tab': 'reading', 'language': 'en'}))
            await asyncio.sleep(0.005)
            second = asyncio.create_task(self._turn('two', scene={'tab': 'talk', 'language': 'en'}))
            return await asyncio.gather(first, second)
        self.claude.replies = [base.JA_REPLY]
        with patch.object(service, '_get_batch_debounce_sec', return_value=0.03):
            first, second = asyncio.run(collect())
        self.assertEqual(first[-1][0], 'queued')
        self.assertEqual(second[-1][0], 'done', second)
        self.assertNotIn(scene.STAGE_LINE, self.claude.calls[0]['user'])
        self.assertEqual(next(d['language'] for n, d in second if n == 'speaker'), 'ja')
        self.assertIsNone(service._state_for(19).batch_via)
        self.assertIsNone(service._state_for(19).batch_scene)

    async def _turn(self, text, **kwargs):
        return [item async for item in service.run_chat_turn(text, **kwargs)]

    def test_chat_route_forwards_scene_and_rejects_bad_fields(self):
        response = self.c.post('/api/chat', json={'text': 'hi', 'via': 'stage', 'scene': {'tab': 'reading', 'text': 'SCREEN'}})
        self.assertEqual(response.status_code, 200)
        self.assertIn(scene.STAGE_LINE, self.claude.calls[0]['user'])
        for body in [{'via': 'other'}, {'scene': {'tab': 'talk', 'unknown': 1}}]:
            self.assertEqual(self.c.post('/api/chat', json=body).status_code, 422)

    def test_warm_without_message_and_same_origin(self):
        async def collect(config):
            with patch.object(router, '_primary_speech_config', return_value=config) as source, \
                    patch.object(listening_tts, 'warm') as warm:
                response = await router.warm_speech(router.SpeechWarmIn(language='en'))
                await asyncio.gather(*list(router._warming))
                source.assert_called_once_with('en')
                self.assertEqual(warm.call_count, int(config is not None))
                if config is not None:
                    warm.assert_called_once_with(config)
                return response
        self.assertEqual(asyncio.run(collect(None)), {'ok': False})
        self.assertEqual(asyncio.run(collect(object())), {'ok': True})
        with patch.object(router, '_primary_speech_config', return_value=None):
            self.assertEqual(self.c.post('/api/chat/speech/warm', json={'language': 'en'}).status_code, 202)
            self.assertEqual(self.c.post('/api/chat/speech/warm', json={'language': 'en'}, headers={'Origin': 'https://evil.test'}).status_code, 403)

    def test_warm_uses_primary_character_base_and_language_synthesis(self):
        from types import SimpleNamespace
        from app.services import listening_settings
        config = SimpleNamespace(voices={'A': 'am_voice', 'B': 'af_voice'})
        timbre = {'base': 'af_base'}
        expected = object()
        with patch.object(listening_settings, 'load', return_value=({'settings': True}, 'key')), \
                patch.object(listening_tts, 'configured_synthesis', return_value=config) as synthesis, \
                patch.object(router, '_character_voice', return_value=timbre) as character, \
                patch.object(router, '_with_base', return_value=expected) as with_base:
            self.assertIs(router._primary_speech_config('en'), expected)
        synthesis.assert_called_once_with('en', {'settings': True}, 'key')
        character.assert_called_once_with('Tester', 'en')
        with_base.assert_called_once_with(config, 'en', 'B', timbre)


if __name__ == '__main__':
    unittest.main()
