import asyncio
import json
import sqlite3
import sys
import unittest
import httpx
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.providers import chatgpt, registry
from app.services import chatgpt_sdk, workspace_agent_siwc as siwc, workspace_agent_siwc_auth as auth


class ChatGPTTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_text_is_normalized_for_the_chatgpt_plan_endpoint(self):
        def respond(request):
            body=json.loads(request.content)
            self.assertEqual(body['input'], [{'role':'user','content':'Reply OK'}])
            self.assertIsInstance(body['instructions'], str)
            self.assertFalse(body['store'])
            self.assertTrue(body['stream'])
            event={'type':'response.completed','response':{'status':'completed','output':[{
                'type':'message','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':'OK'}]}]}}
            return httpx.Response(200,headers={'content-type':'text/event-stream'},
                                  content=('data: '+json.dumps(event)+'\n\n').encode())
        result=await chatgpt_sdk.complete({'model':'account-model','input':'Reply OK'},
            token_provider=AsyncMock(return_value='test-oauth-token'),
            transport=httpx.MockTransport(respond))
        self.assertEqual(result,'OK')

    async def test_chat_uses_history_and_commits_only_completed_turns(self):
        provider = chatgpt.ChatGPTProvider()
        with (patch.object(auth, 'get_selected_model', AsyncMock(return_value='account-model')),
              patch.object(chatgpt, '_seed_history_from_db', return_value=[{'role':'assistant','content':'Earlier.'}]),
              patch.object(chatgpt_sdk, 'complete', AsyncMock(side_effect=['Hello.', siwc.SiwcFailure('timeout', 'Timed out'), 'Again.'])) as complete):
            self.assertEqual([part async for part in provider.stream_chat('test', 'Stay in role.', 'First')], ['Hello.'])
            with self.assertRaises(siwc.SiwcFailure):
                _ = [part async for part in provider.stream_chat('test', 'New instruction', 'Failed turn')]
            self.assertEqual([part async for part in provider.stream_chat('test', 'New instruction', 'Next')], ['Again.'])
            payload = complete.call_args.args[0]
            self.assertEqual(payload['model'], 'account-model')
            self.assertEqual(payload['instructions'], 'Stay in role.')
            self.assertNotIn('Failed turn', json.dumps(payload))
            self.assertEqual(payload['input'][-2:], [{'role':'assistant','content':'Hello.'},{'role':'user','content':'Next'}])

    async def test_valid_completed_stream_can_omit_content_type(self):
        event={'type':'response.completed','response':{'status':'completed','output':[{
            'type':'message','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':'OK'}]}]}}
        def respond(_):
            return httpx.Response(200,content=('data: '+json.dumps(event)+'\n\n').encode())
        result=await chatgpt_sdk.complete({'model':'account-model','input':'Reply OK'},
            token_provider=AsyncMock(return_value='test-oauth-token'),
            transport=httpx.MockTransport(respond))
        self.assertEqual(result,'OK')

    async def test_json_is_validated_for_explanations_and_questions(self):
        provider = chatgpt.ChatGPTProvider()
        schema = {'type':'object','properties':{'meaning':{'type':'string'}},'required':['meaning']}
        with (patch.object(auth, 'get_selected_model', AsyncMock(return_value='account-model')),
              patch.object(chatgpt_sdk, 'complete', AsyncMock(side_effect=['{"meaning":"例"}', '{"meaning":3}']))):
            self.assertEqual(await provider.generate_json('Explain', schema), {'meaning':'例'})
            with self.assertRaises(siwc.SiwcFailure): await provider.generate_json('Explain', schema)

    async def test_shared_routing_for_chat_utility_and_listening(self):
        settings={'chat_engine':'chatgpt','utility_engine':'chatgpt','listening_subscription':''}
        expected = object()
        with (patch.object(registry, 'get_setting', side_effect=lambda key, default='': settings.get(key,default)),
              patch.object(registry, '_get_chatgpt', return_value=expected)):
            for feature in ('chat','utility','listening'):
                self.assertIs(registry.get_feature_provider(feature), expected)
            from app.services import workspace_agent_runtime
            self.assertEqual(workspace_agent_runtime.resolve_provider(), 'chatgpt')

    async def test_history_is_resident_and_seeded_once(self):
        provider = chatgpt.ChatGPTProvider()
        seed = patch.object(chatgpt, '_seed_history_from_db', return_value=[{'role':'user','content':'昨日の話'},{'role':'assistant','content':'覚えてるよ'}])
        with (patch.object(auth, 'get_selected_model', AsyncMock(return_value='account-model')), seed as seeded,
              patch.object(chatgpt_sdk, 'complete', AsyncMock(side_effect=[f'reply {i}' for i in range(40)])) as complete):
            for i in range(20):
                _ = [part async for part in provider.stream_chat('p5s19', 'system', f'turn {i}')]
            seeded.assert_called_once_with('p5s19')
            first = complete.call_args_list[0].args[0]
            self.assertEqual(first['input'][:2], [{'role':'user','content':'昨日の話'},{'role':'assistant','content':'覚えてるよ'}])
            last = complete.call_args_list[-1].args[0]
            self.assertEqual(last['instructions'], 'system')
            self.assertLessEqual(len(last['input']), 31)  # 最多 30 条历史 + 本轮
            self.assertEqual(last['input'][-3:], [{'role':'user','content':'turn 18'},{'role':'assistant','content':'reply 18'},{'role':'user','content':'turn 19'}])
            self.assertFalse(hasattr(provider, '_locks'))
            provider.forget_session('p5s19')
            _ = [part async for part in provider.stream_chat('p5s19', 'system', 'again')]
            self.assertEqual(seeded.call_count, 2)
        self.assertFalse(provider.supports_vision())

    async def test_sdk_requires_login_before_network(self):
        with patch.object(auth, 'get_access_token', AsyncMock(side_effect=auth.AuthorizationRequired())):
            with self.assertRaises(siwc.SiwcFailure) as error:
                await chatgpt_sdk.complete({'model':'test','input':'Hello'})
            self.assertEqual(error.exception.code, 'authentication')


class LoginRouteTests(unittest.TestCase):
    def test_explicit_local_login_enables_and_persists_configuration(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.workspace_agent_siwc import router
        app=FastAPI(); app.include_router(router)
        opened=[]
        def connection():
            conn=sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
            opened.append(conn)
            return conn
        runtime=SimpleNamespace(start=lambda **kw: {'browser_url':'http://127.0.0.1:12345/begin?ticket='+'x'*43,'expires_in':300})
        with (patch.object(auth, 'runtime', return_value=runtime),
              patch.object(auth, 'enable_after_user_approval') as enable,
              patch('app.db.get_conn', side_effect=connection),
              TestClient(app, client=('127.0.0.1',32123),base_url='http://127.0.0.1:8787') as client):
            path='/workspace-agent/siwc/login'
            response=client.post(path,json={'approved':False},headers={'Origin':'http://127.0.0.1:8787'})
            self.assertEqual(response.status_code,409)
            enable.assert_not_called(); self.assertEqual(opened,[])
            response=client.post(path,json={'approved':True},headers={'Origin':'https://other.test'})
            self.assertEqual(response.status_code,403)
            enable.assert_not_called()
            response=client.post(path,json={'approved':True},headers={'Origin':'http://127.0.0.1:8787'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertNotIn('access_token',response.text)
            enable.assert_called_once_with(approved=True)

if __name__ == '__main__': unittest.main()
