"""Mock-only Claude tests: no CLI process, credential reads or model calls."""
import asyncio
import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import BaseModel, ConfigDict
from claude_agent_sdk import ResultMessage
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import workspace_agent_claude as adapter

ANSWER = {'reply': 'Review this proposal.', 'operations': [], 'test_source_id': None}
PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic'
class Args(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool

def result(value=ANSWER, error=False):
    return ResultMessage(subtype='success', duration_ms=1, duration_api_ms=1,
        is_error=error, num_turns=1, session_id='mock-only', structured_output=value)

class FakeClient:
    instances = []
    response = ANSWER
    mode = 'ok'
    def __init__(self, options):
        self.options = options
        self.disconnected = False
        self.blocks = None
        self.instances.append(self)
    async def connect(self):
        self.connect_task = asyncio.current_task()
        assert Path(self.options.cwd).is_dir()
        assert not list(Path(self.options.cwd).iterdir())
        if self.mode == 'connect_error':
            raise RuntimeError('SECRET_PROVIDER_DETAIL')
    async def query(self, messages):
        self.blocks = [message async for message in messages]
    async def receive_response(self):
        if self.mode == 'wait':
            await asyncio.sleep(100)
        yield result(self.response, self.mode == 'error')
    async def disconnect(self):
        self.disconnected = True
        assert asyncio.current_task() is self.connect_task

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeClient.instances = []
        FakeClient.response = ANSWER
        FakeClient.mode = 'ok'
        self.patches = [patch('claude_agent_sdk.ClaudeSDKClient', FakeClient),
                        patch.object(adapter, '_cli_path', return_value='mock-claude.exe'),
                        patch.object(adapter, '_credential_present', return_value=True),
                        patch('app.providers.agent_sdk.get_setting', side_effect=lambda key, default='': {'chat_model_claude':'opus', 'chat_reasoning_claude':'high'}.get(key,default))]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
    async def test_isolated_options_images_and_proposal_only(self):
        handler = unittest.mock.Mock(side_effect=AssertionError('must not execute'))
        tools = {'toggle': ('Toggle', Args, handler)}
        FakeClient.response = {**ANSWER, 'operations': [{'tool': 'toggle', 'args': {'enabled': True}}]}
        value = await adapter.generate('request', {'inspect': {'value': 'safe'},
            'read_skill': {'skill': 'data only'}, 'unselected': 'private'}, tools,
            images=[{'mime': 'image/png', 'data': PNG}])
        self.assertEqual(value, FakeClient.response)
        handler.assert_not_called()
        client = FakeClient.instances[0]
        opt = client.options
        self.assertEqual(opt.model, 'opus')
        self.assertIsNone(opt.max_thinking_tokens)
        self.assertEqual(opt.effort, 'high')
        for name in ('tools', 'allowed_tools', 'setting_sources', 'skills', 'plugins'):
            self.assertEqual(getattr(opt, name), [])
        self.assertEqual(opt.mcp_servers, {})
        self.assertTrue(opt.strict_mcp_config)
        self.assertIsNone(opt.resume)
        self.assertFalse(opt.continue_conversation)
        self.assertEqual(opt.permission_mode, 'dontAsk')
        self.assertEqual(json.loads(opt.settings), {'disableAllHooks': True})
        self.assertEqual(opt.extra_args, {'no-session-persistence': None})
        self.assertEqual(opt.system_prompt, adapter.SYSTEM_PROMPT)
        blocks = client.blocks[0]['message']['content']
        self.assertNotIn('unselected', blocks[0]['text'])
        self.assertEqual(base64.b64decode(blocks[1]['source']['data']), PNG)
        self.assertTrue(client.disconnected)
        self.assertFalse(Path(opt.cwd).exists())
    async def test_timeout_and_cancel_cleanup(self):
        FakeClient.mode = 'wait'
        with patch.object(adapter, 'TIMEOUT_SECONDS', .01):
            with self.assertRaises(adapter.ClaudeFailure) as caught:
                await adapter.generate('request', {}, {})
        self.assertEqual(caught.exception.code, 'timeout')
        self.assertTrue(FakeClient.instances[-1].disconnected)
        self.assertFalse(Path(FakeClient.instances[-1].options.cwd).exists())
        task = asyncio.create_task(adapter.generate('request', {}, {}))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(FakeClient.instances[-1].disconnected)
        self.assertFalse(Path(FakeClient.instances[-1].options.cwd).exists())
    async def test_fixed_failure_and_connect_cleanup(self):
        for mode in ('connect_error', 'error'):
            FakeClient.mode = mode
            with self.assertRaises(adapter.ClaudeFailure) as caught:
                await adapter.generate('request', {}, {})
            self.assertEqual(caught.exception.code, 'provider_error')
            self.assertNotIn('SECRET', str(caught.exception))
            self.assertTrue(FakeClient.instances[-1].disconnected)
    async def test_invalid_outputs_never_execute(self):
        for response in (None, 'raw text', {**ANSWER, 'operations': [{'tool': 'unknown', 'args': {}}]},
                         {**ANSWER, 'reply': 'x' * 2401}):
            FakeClient.response = response
            with self.assertRaises(adapter.ClaudeFailure) as caught:
                await adapter.generate('request', {}, {})
            self.assertEqual(caught.exception.code, 'invalid_output')
            self.assertTrue(FakeClient.instances[-1].disconnected)
    async def test_reject_input_before_start(self):
        cases = [('x' * (adapter.MAX_INPUT_BYTES + 1), ()),
                 ('request', [{'mime': 'image/svg+xml', 'data': PNG}]),
                 ('request', [{'mime': 'image/jpeg', 'data': PNG}]),
                 ('request', [{'mime': 'image/png', 'data': b'bad'}]),
                 ('request', [{'mime': 'image/png', 'data': PNG}] * 5)]
        for prompt, images in cases:
            with self.assertRaises(adapter.ClaudeFailure) as caught:
                await adapter.generate(prompt, {}, {}, images=images)
            self.assertEqual(caught.exception.code, 'invalid_input')
        self.assertEqual(FakeClient.instances, [])
    async def test_capabilities_do_not_claim_login(self):
        self.assertEqual(adapter.capabilities()['auth_status'], 'credential_present_unverified')
        self.assertTrue(adapter.capabilities()['configured'])
        self.assertIs(adapter.ProviderFailure, adapter.ClaudeFailure)
        with patch.object(adapter, '_credential_present', return_value=False):
            self.assertFalse(adapter.capabilities()['configured'])
            self.assertEqual(adapter.capabilities()['auth_status'], 'missing')

if __name__ == '__main__': unittest.main()
