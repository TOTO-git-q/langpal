"""Runtime tests with memory storage, mock HTTP and generated keys only."""
import asyncio
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch, MagicMock
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import workspace_agent_siwc_auth as auth
from app.services import workspace_agent_siwc_live as live


class MemoryStore:
    def __init__(self, value=None): self.value = value; self.writes = 0
    @contextmanager
    def transaction(self): yield
    def load(self): return copy.deepcopy(self.value)
    def save(self, value): self.value = copy.deepcopy(value); self.writes += 1


class LiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = {'host_id': 'mock-host', 'registration': None}
        self.store = MemoryStore(self.saved)
        self.calls = []
        self.payload = None
        async def handler(request):
            self.calls.append(request)
            return httpx.Response(200, json=self.payload)
        self.client = live.OfficialClient(enabled=True, transport=httpx.MockTransport(handler))
        self.runtime = live.SIWCRuntime(enabled=True, store=self.store, client=self.client)

    async def test_default_disabled_no_io(self):
        with patch.object(live.DPAPIStore, 'load', side_effect=AssertionError('must not read')):
            runtime = live.SIWCRuntime()
            self.assertFalse(runtime.metadata()['configured'])
            for operation in [runtime.get_access_token(), runtime.sign_out()]:
                with self.assertRaises(auth.AuthorizationRequired): await operation
            with self.assertRaises(auth.AuthorizationRequired): runtime.start(approved=True)
        with self.assertRaises(auth.AuthorizationRequired):
            await live.OfficialClient().token({})
        self.assertEqual(self.calls, [])

    async def test_host_redirect_fail_closed(self):
        for url in ['https://evil.test/token', 'http://auth.openai.com/token',
                    'https://auth.openai.com.evil/token', 'https://user@auth.openai.com/token',
                    'https://auth.openai.com/token?token=bad']:
            with self.assertRaises(live.SIWCFailure): await self.client.request('GET', url)
        self.assertEqual(self.calls, [])
        async def redirect(request): return httpx.Response(302, headers={'Location': 'https://evil.test'})
        self.client.transport = httpx.MockTransport(redirect)
        with self.assertRaises(live.SIWCFailure): await self.client.jwks()

    async def test_token_error_sanitized(self):
        async def handler(request): return httpx.Response(400, json={'secret': 'never-print-this'})
        self.client.transport = httpx.MockTransport(handler)
        with self.assertRaises(live.SIWCFailure) as error: await self.client.token({'code': 'mock'})
        self.assertNotIn('never-print-this', str(error.exception))

    async def test_finish_verifies_then_saves(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())); jwk['kid']='test'
        plan = auth.ExchangePlan('oaiapp_test', 'mock-code', 'mock-verifier', 'nonce',
                                 'http://127.0.0.1:12345' + auth.CALLBACK_PATH)
        identity = jwt.encode(dict(iss=auth.ISSUER, aud=plan.client_id, sub='subject', nonce='nonce',
            exp=int(time.time())+600), key, algorithm='RS256', headers={'kid':'test'})
        response = dict(access_token='mock-access', refresh_token='mock-refresh', id_token=identity,
                        expires_in=3600, token_type='Bearer', scope=' '.join(auth.SCOPES))
        async def handler(request):
            self.calls.append(request)
            return httpx.Response(200, json={'keys':[jwk]} if request.method=='GET' else response)
        self.client.transport=httpx.MockTransport(handler)
        await self.runtime.finish(plan, self.saved)
        self.assertEqual(self.store.writes, 1)
        self.assertEqual(self.runtime.metadata()['authorization_state'], 'authorized')
        self.assertEqual(await self.runtime.get_access_token(), 'mock-access')
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('mock-access', str(self.runtime.metadata()))
        self.runtime.select_model('listed-model', ['listed-model'])
        with self.assertRaises(live.SIWCFailure): self.runtime.select_model('guessed-model', ['listed-model'])

    async def test_missing_scopes_never_persist(self):
        with self.assertRaises(live.SIWCFailure):
            self.runtime._token_record(dict(scope='openid', token_type='Bearer'))
        self.assertEqual(self.store.writes, 0)

    async def test_refresh_rotation_and_no_scope_sent(self):
        old = dict(client_id='oaiapp_test',subject='s',issuer=auth.ISSUER,
            access_token='old-access',refresh_token='old-refresh',id_token='old-id',
            scopes=list(auth.SCOPES), expires_at=1)
        self.store.value={**self.saved,'registration':old}
        self.payload=dict(access_token='new-access',refresh_token='new-refresh',expires_in=3600,token_type='Bearer')
        self.assertEqual(await self.runtime.get_access_token(), 'new-access')
        self.assertEqual(self.store.value['registration']['refresh_token'], 'new-refresh')
        self.assertNotIn(b'scope=', self.calls[0].content)
        self.assertIn(b'client_id=oaiapp_test', self.calls[0].content)

    async def test_logout_failure_clears_tokens_keeps_mapping(self):
        self.store.value={**self.saved,'registration':dict(client_id='oaiapp_test',subject='s',issuer=auth.ISSUER,
            access_token='mock-access',refresh_token='mock-refresh',id_token='mock-id')}
        self.payload={'issuer':auth.ISSUER,'revocation_endpoint':'https://evil.test/revoke'}
        result=await self.runtime.sign_out()
        self.assertFalse(result['remote_revocation_confirmed'])
        self.assertEqual(set(self.store.value['registration']), {'client_id','subject','issuer'})
        self.assertEqual(len(self.calls),1)

    async def test_dpapi_disabled(self):
        with self.assertRaises(auth.AuthorizationRequired): live.DPAPIStore().load()
        with self.assertRaises(auth.AuthorizationRequired): live.DPAPIStore().save({'mock':'value'})

    async def test_login_requires_approval(self):
        with self.assertRaises(auth.AuthorizationRequired): self.runtime.start()
        self.assertEqual(self.store.writes,0)

    async def test_start_mock_listener_and_cancel(self):
        server=MagicMock(); server.server_address=('127.0.0.1',43210)
        with patch.object(live,'ThreadingHTTPServer',return_value=server), patch.object(live.threading,'Thread'), patch.object(live.threading,'Timer'):
            result=self.runtime.start(approved=True)
            self.assertTrue(result['browser_url'].startswith('http://127.0.0.1:43210/begin?ticket='))
            self.assertNotIn('code_verifier',str(result))
            self.runtime.cancel()
            server.shutdown.assert_called_once()

if __name__=='__main__': unittest.main()
