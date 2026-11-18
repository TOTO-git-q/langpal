"""Offline SIWC protocol tests; never reads credentials or sends network requests."""
import asyncio
import base64
import hashlib
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import workspace_agent_siwc_auth as auth
from app.routers.workspace_agent_siwc import router


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.service = auth.OfflineAuthorization(lambda: self.now)
        self.session = 's' * 43
        self.uri = 'http://127.0.0.1:43123' + auth.CALLBACK_PATH
        self.query = parse_qs(urlsplit(self.service.prepare(local_session=self.session,
             host_id='urn:uuid:test-host', redirect_uri=self.uri)).query)

    def callback(self, **changes):
        q = dict(state=self.query['state'][0], code='mock-code', client_id='oaiapp_test')
        q.update(changes)
        return self.uri + '?' + urlencode(q)

    def consume(self, **changes):
        return self.service.consume(self.callback(**changes), local_session=self.session)

    def test_pkce_and_exact_exchange(self):
        plan = self.consume()
        self.assertEqual(self.query['client_id'], ['dynamic_agent_client'])
        self.assertEqual(self.query['agent_name_hint'], ['LangPal'])
        expected = base64.urlsafe_b64encode(hashlib.sha256(plan.verifier.encode()).digest()).decode().rstrip('=')
        self.assertEqual(self.query['code_challenge'], [expected])
        self.assertEqual(plan.form()['client_id'], 'oaiapp_test')
        self.assertEqual(plan.form()['redirect_uri'], self.uri)
        self.assertNotIn('mock-code', repr(plan))
        with self.assertRaises(auth.InvalidAuthorization): self.consume()

    def test_expiry(self):
        self.now += 300
        with self.assertRaises(auth.InvalidAuthorization): self.consume()

    def test_session_binding(self):
        with self.assertRaises(auth.InvalidAuthorization):
            self.service.consume(self.callback(), local_session='other-session')
        self.consume()

    def test_duplicate_state(self):
        with self.assertRaises(auth.InvalidAuthorization):
            self.service.consume(self.callback() + '&state=bad', local_session=self.session)

    def test_denial_consumed(self):
        with self.assertRaises(auth.InvalidAuthorization): self.consume(error='access_denied')
        with self.assertRaises(auth.InvalidAuthorization): self.consume()

    def test_unissued_client_rejected(self):
        with self.assertRaises(auth.InvalidAuthorization): self.consume(client_id='dynamic_agent_client')

    def test_wrong_callback(self):
        with self.assertRaises(auth.InvalidAuthorization):
            self.service.consume(self.callback().replace(':43123', ':43124'), local_session=self.session)

    def test_redirect_allowlist(self):
        for uri in ['http://localhost:43123' + auth.CALLBACK_PATH,
                    'https://example.com' + auth.CALLBACK_PATH,
                    self.uri + '?next=evil', self.uri.replace('/auth/', '/wrong/')]:
            with self.subTest(uri=uri), self.assertRaises(auth.InvalidAuthorization):
                self.service.prepare(local_session=self.session, host_id='host', redirect_uri=uri)

    def test_reauthorization_client_binding(self):
        url = self.service.prepare(local_session=self.session, host_id='host', redirect_uri=self.uri,
                                  client_id='oaiapp_original', expected_subject='subject')
        query = parse_qs(urlsplit(url).query)
        self.assertNotIn('agent_name_hint', query)
        callback = self.uri + '?' + urlencode(dict(state=query['state'][0], code='mock', client_id='oaiapp_other'))
        with self.assertRaises(auth.InvalidAuthorization):
            self.service.consume(callback, local_session=self.session)

    def test_signed_identity_validation(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        import json
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk['kid'] = 'test'
        plan = self.consume()
        claims = dict(iss=auth.ISSUER, sub='subject', aud=plan.client_id,
                      exp=int(time.time()) + 60, nonce=plan.nonce)
        def token(c): return jwt.encode(c, key, algorithm='RS256', headers={'kid': 'test'})
        self.assertEqual(auth.validate_id_token(token(claims), {'keys': [jwk]}, plan)['sub'], 'subject')
        for changes in [dict(nonce='wrong'), dict(aud='other'), dict(iss='https://evil.test'), dict(exp=1)]:
            with self.assertRaises(auth.InvalidAuthorization):
                auth.validate_id_token(token({**claims, **changes}), {'keys': [jwk]}, plan)

    def test_live_and_storage_hard_disabled(self):
        with self.assertRaises(auth.AuthorizationRequired): asyncio.run(auth.get_access_token())
        self.assertFalse(auth.disclosure()['live_enabled'])

    def test_routes_never_redirect_or_return_credentials(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, client=('127.0.0.1', 1234), base_url='http://127.0.0.1:8787') as client:
            response = client.get('/workspace-agent/siwc/status')
            self.assertFalse(response.json()['live_enabled'])
            self.assertEqual(response.headers['cache-control'], 'no-store')
            response = client.post('/workspace-agent/siwc/login', json={'approved': False}, headers={'Origin': 'http://127.0.0.1:8787'})
            self.assertEqual(response.status_code, 409)
            self.assertNotIn('location', response.headers)

if __name__ == '__main__': unittest.main()
