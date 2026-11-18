"""课程管家三种模型：默认跟随主引擎、可以每轮单独选、选中的不可用就报错不换；所有模型调用都是假的。"""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import pydantic
from app.services import workspace_agent_runtime as runtime
from app.routers import workspace_agent as routes


class Failure(RuntimeError):
    code = 'test_error'


def adapter(name, *, vision, configured=True):
    return SimpleNamespace(capabilities=lambda: {'id': name, 'label': name, 'vision': vision, 'configured': configured},
                           generate=AsyncMock(return_value={'reply': name}), ProviderFailure=Failure)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.adapters = {'claude': adapter('claude', vision=True), 'deepseek': adapter('deepseek', vision=False),
                         'chatgpt': adapter('chatgpt', vision=False)}
        self.main = 'claude'
        for p in (patch.object(runtime, '_adapters', lambda: self.adapters),
                  patch.object(runtime, 'main_engine', lambda: self.main)):
            p.start(); self.addCleanup(p.stop)

    def test_default_follows_main_engine(self):
        for main in ('claude', 'deepseek', 'chatgpt'):
            self.main = main
            self.assertEqual(asyncio.run(runtime.generate('x', {}, {})), {'reply': main})
            self.assertEqual(runtime.capabilities()['default_provider'], main)
        self.main = 'custom'
        with self.assertRaises(runtime.RuntimeFailure) as error:
            asyncio.run(runtime.generate('x', {}, {}))
        self.assertEqual(error.exception.code, 'provider_required')
        self.assertIsNone(runtime.capabilities()['default_provider'])

    def test_per_turn_choice_overrides_main(self):
        self.assertEqual(asyncio.run(runtime.generate('x', {}, {}, provider='chatgpt')), {'reply': 'chatgpt'})
        self.assertEqual(asyncio.run(runtime.generate('x', {}, {}, provider='main')), {'reply': 'claude'})
        self.adapters['claude'].generate.assert_awaited_once()

    def test_failure_and_unavailable_never_switch(self):
        self.adapters['deepseek'].generate.side_effect = Failure('safe failure')
        with self.assertRaises(runtime.RuntimeFailure) as error:
            asyncio.run(runtime.generate('x', {}, {}, provider='deepseek'))
        self.assertEqual(error.exception.code, 'test_error')
        self.adapters['chatgpt'] = adapter('chatgpt', vision=False, configured=False)
        with self.assertRaises(runtime.RuntimeFailure) as error:
            asyncio.run(runtime.generate('x', {}, {}, provider='chatgpt'))
        self.assertEqual(error.exception.code, 'provider_unavailable')
        self.adapters['claude'].generate.assert_not_called()

    def test_images_need_a_vision_provider(self):
        with self.assertRaises(runtime.RuntimeFailure) as error:
            asyncio.run(runtime.generate('x', {}, {}, images=[{'data': b'x'}], provider='deepseek'))
        self.assertEqual(error.exception.code, 'images_unsupported')

    def test_capabilities_report_each_provider(self):
        caps = runtime.capabilities()
        self.assertEqual([p['id'] for p in caps['providers']], ['claude', 'deepseek', 'chatgpt'])
        self.assertTrue(caps['available'])
        self.assertTrue(caps['image_input'])
        self.main = 'deepseek'
        self.assertFalse(runtime.capabilities()['image_input'])

    def test_api_accepts_three_providers_and_main(self):
        for provider in ('codex', 'custom', 'other'):
            with self.assertRaises(pydantic.ValidationError):
                routes.Plan(message='synthetic', provider=provider)
        for provider in ('claude', 'deepseek', 'chatgpt', 'main', None):
            self.assertEqual(routes.Plan(message='synthetic', provider=provider).provider, provider)


if __name__ == '__main__':
    unittest.main()
