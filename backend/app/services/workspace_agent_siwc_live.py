"""Opt-in SIWC runtime. Disabled by default; imports perform no credential/network I/O.

Only construct with enabled=True after the user's explicit action-time authorization.
Never use third-party application credentials. All errors are deliberately sanitized.
"""
from __future__ import annotations
import asyncio
import json
import os
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import httpx
from . import workspace_agent_siwc_auth as protocol


class SIWCFailure(RuntimeError):
    def __init__(self, message='ChatGPT authorization failed. Please start a new sign-in.'):
        super().__init__(message)


class DPAPIStore:
    """Current-user DPAPI ciphertext, atomic replace, never business SQLite.

    No path or OS APIs are accessed until an explicitly enabled operation. The caller
    serializes read/refresh/write using transaction(), including across processes.
    """
    def __init__(self, *, enabled=False, root=None, protector=None):
        self.enabled = enabled
        self._root = root
        self._protector = protector
        self._thread_lock = threading.RLock()

    def _check(self):
        if not self.enabled:
            raise protocol.AuthorizationRequired()

    @property
    def root(self):
        self._check()
        if self._root is not None:
            return Path(self._root)
        return Path(os.environ['LOCALAPPDATA']) / 'LangPal' / 'siwc'

    def _crypto(self):
        if self._protector is not None:
            return self._protector
        import win32crypt
        return win32crypt

    @contextmanager
    def transaction(self):
        self._check()
        with self._thread_lock:
            root = self.root
            root.mkdir(parents=True, exist_ok=True)
            # Windows byte-range locks protect rotation against another LangPal process.
            import msvcrt
            with (root / 'session.lock').open('a+b') as handle:
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise SIWCFailure('Another LangPal process is updating ChatGPT authorization. Retry shortly.') from None
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def load(self):
        self._check()
        path = self.root / 'session.dpapi'
        if not path.exists():
            return None
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError()
            with path.open('rb') as handle:
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError()
            plain = self._crypto().CryptUnprotectData(raw, None, None, None, 1)[1]
            return json.loads(plain.decode('utf-8'))
        except Exception:
            raise SIWCFailure('The protected LangPal authorization record could not be opened.') from None

    def save(self, record):
        self._check()
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / ('session-' + secrets.token_hex(12) + '.tmp')
        try:
            plain = json.dumps(record, separators=(',', ':')).encode('utf-8')
            cipher = self._crypto().CryptProtectData(plain, 'LangPal SIWC', None, None, None, 1)
            with temporary.open('xb') as handle:
                handle.write(cipher)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, root / 'session.dpapi')
        except Exception:
            raise SIWCFailure('The protected LangPal authorization record could not be saved.') from None
        finally:
            if temporary.exists():
                temporary.unlink()


class OfficialClient:
    def __init__(self, *, enabled=False, transport=None):
        self.enabled = enabled
        self.transport = transport

    async def request(self, method, url, *, data=None):
        if not self.enabled:
            raise protocol.AuthorizationRequired()
        p = urlsplit(url)
        # Discovery-supplied revocation paths are accepted only on the exact issuer.
        if (p.scheme != 'https' or p.hostname != 'auth.openai.com' or p.port not in (None, 443)
                or p.username or p.password or p.query or p.fragment):
            raise SIWCFailure()
        try:
            async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                    follow_redirects=False, timeout=20) as client:
                async with client.stream(method, url, data=data, headers={'Accept': 'application/json'}) as response:
                    if response.status_code != 200:
                        raise SIWCFailure()
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 1024 * 1024:
                            raise SIWCFailure()
                    return json.loads(chunks) if chunks else {}
        except Exception:
            raise SIWCFailure() from None

    async def token(self, form):
        return await self.request('POST', protocol.TOKEN_ENDPOINT, data=form)

    async def jwks(self):
        return await self.request('GET', protocol.JWKS_ENDPOINT)

    async def revoke(self, client_id, refresh_token):
        discovery = await self.request('GET', protocol.ISSUER + '/.well-known/openid-configuration')
        if discovery.get('issuer') != protocol.ISSUER:
            raise SIWCFailure()
        endpoint = discovery.get('revocation_endpoint')
        if not isinstance(endpoint, str):
            raise SIWCFailure()
        await self.request('POST', endpoint, data={'client_id': client_id, 'token': refresh_token,
                                                  'token_type_hint': 'refresh_token'})


class SIWCRuntime:
    def __init__(self, *, enabled=False, store=None, client=None):
        self.enabled = enabled
        self.store = store if store is not None else DPAPIStore(enabled=enabled)
        self.client = client if client is not None else OfficialClient(enabled=enabled)
        self.protocol = protocol.OfflineAuthorization()
        self._pending = None
        self._server = None
        self._state_lock = threading.Lock()
        self._last_result = 'disabled' if not enabled else 'required'
        self._selected_model = None
        self._reasoning_effort = None
        self._reasoning_levels = []
        self._account_label = None
        self._completed = False

    def _check(self):
        if not self.enabled:
            raise protocol.AuthorizationRequired()

    def metadata(self):
        # Metadata performs no persistent credential reads and does not renew tokens.
        return {'configured': self._last_result == 'authorized',
                'authorization_state': self._last_result, 'selected_model': self._selected_model,
                'account_label': self._account_label,
                'reasoning_effort': self._reasoning_effort,
                'reasoning_levels': self._reasoning_levels,
                'sdk': 'openai',
                'availability_note': 'Select an explicitly authorized model after sign-in.'}

    def start(self, *, approved=False):
        self._check()
        if approved is not True:
            raise protocol.AuthorizationRequired()
        with self._state_lock:
            if self._pending is not None:
                raise SIWCFailure('A ChatGPT sign-in is already pending.')
            # Host metadata is persisted only after explicit consent. No tokens yet.
            with self.store.transaction():
                saved = self.store.load() or {'host_id': 'urn:uuid:' + str(uuid.uuid4()), 'registration': None}
                saved['consent_version'] = 'siwc-v1'
                self.store.save(saved)
            self._completed = False
            host_id = saved['host_id']
            selected = saved.get('registration')
            local_session = secrets.token_urlsafe(32)
            ticket = secrets.token_urlsafe(32)
            runtime = self

            class CallbackHandler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass  # OAuth codes and browser tickets must not reach access logs.

                def do_GET(self):
                    runtime._handle_browser(self)

            server = ThreadingHTTPServer(('127.0.0.1', 0), CallbackHandler)
            self._server = server
            port = server.server_address[1]
            uri = f'http://127.0.0.1:{port}' + protocol.CALLBACK_PATH
            authorization_url = self.protocol.prepare(local_session=local_session,
                host_id=host_id, redirect_uri=uri,
                client_id=selected['client_id'] if selected else 'dynamic_agent_client',
                expected_subject=selected['subject'] if selected else None)
            self._pending = {'ticket': ticket, 'session': local_session, 'uri': uri,
                             'url': authorization_url, 'expires': time.monotonic() + 300,
                             'saved': saved, 'processing': False}
            self._last_result = 'pending'
            threading.Thread(target=server.serve_forever, daemon=True).start()
            timer = threading.Timer(300, self.cancel)
            timer.daemon = True
            timer.start()
            self._pending['timer'] = timer
            # Open this local URL in the user's system browser only on explicit click.
            return {'browser_url': f'http://127.0.0.1:{port}/begin?ticket={ticket}', 'expires_in': 300}

    def _handle_browser(self, handler):
        def reply(code, message, headers=None):
            handler.send_response(code)
            handler.send_header('Cache-Control', 'no-store')
            handler.send_header('Referrer-Policy', 'no-referrer')
            handler.send_header('Content-Type', 'text/plain; charset=utf-8')
            handler.send_header('X-Content-Type-Options', 'nosniff')
            for k, v in (headers or {}).items(): handler.send_header(k, v)
            handler.end_headers()
            handler.wfile.write(message.encode('utf-8'))
        try:
            parsed = urlsplit(handler.path)
            with self._state_lock:
                if parsed.path == '/complete' and self._completed:
                    reply(200, 'ChatGPT is connected to LangPal. You can close this window.')
                    threading.Thread(target=self.cancel, daemon=True).start()
                    return
                pending = self._pending
                if not pending or pending['expires'] <= time.monotonic() or pending['processing']:
                    reply(400, 'Sign-in expired. Start again in LangPal.')
                    return
                expected_host = urlsplit(pending['uri']).netloc
                if handler.headers.get('Host') != expected_host or handler.client_address[0] != '127.0.0.1':
                    reply(400, 'Invalid callback.')
                    return
                if parsed.path == '/begin':
                    query = parse_qs(parsed.query)
                    values = query.get('ticket', [])
                    if not pending['ticket'] or len(values) != 1 or not secrets.compare_digest(values[0], pending['ticket']):
                        reply(400, 'Invalid sign-in handoff.')
                        return
                    pending['ticket'] = None
                    reply(302, 'Continue in the official OpenAI sign-in page.', {
                        'Location': pending['url'],
                        'Set-Cookie': 'langpal_siwc=' + pending['session'] + '; HttpOnly; SameSite=Lax; Path=' + protocol.CALLBACK_PATH + '; Max-Age=300'})
                    return
                if parsed.path != protocol.CALLBACK_PATH:
                    reply(404, 'Not found.')
                    return
                cookie = SimpleCookie()
                cookie.load(handler.headers.get('Cookie', ''))
                value = cookie.get('langpal_siwc')
                if value is None or not secrets.compare_digest(value.value, pending['session']):
                    reply(400, 'Sign-in session mismatch. Start again in LangPal.')
                    return
                pending['processing'] = True
            # Do not use Referer as authority: this is navigation from auth.openai.com.
            try:
                plan = self.protocol.consume('http://' + expected_host + handler.path,
                                             local_session=pending['session'])
                asyncio.run(self.finish(plan, pending['saved']))
                self._completed = True
                reply(302, 'Sign-in complete.',
                      {'Location': '/complete', 'Set-Cookie': 'langpal_siwc=; HttpOnly; SameSite=Lax; Path=' + protocol.CALLBACK_PATH + '; Max-Age=0'})
            except Exception:
                self._last_result = 'required'
                reply(400, 'ChatGPT sign-in did not complete. Return to LangPal and try again.')
            finally:
                if not self._completed:
                    self.cancel()
        except Exception:
            reply(400, 'Invalid sign-in request.')

    def cancel(self):
        with self._state_lock:
            pending, self._pending = self._pending, None
            server, self._server = self._server, None
            if pending and 'timer' in pending: pending['timer'].cancel()
            if self._last_result == 'pending': self._last_result = 'required'
        if server:
            server.shutdown()
            server.server_close()

    async def finish(self, plan, saved):
        self._check()
        response = await self.client.token(plan.form())
        claims = protocol.validate_id_token(response.get('id_token', ''), await self.client.jwks(), plan)
        record = self._token_record(response)
        record.update(client_id=plan.client_id, subject=claims['sub'], issuer=protocol.ISSUER,
                      account_label=claims.get('email') or claims.get('name'))
        # Identity is validated before activation or credential persistence.
        with self.store.transaction():
            current = self.store.load()
            if current != saved:
                raise SIWCFailure('Authorization changed in another process. Start again.')
            self.store.save({**saved, 'registration': record})
        self._last_result = 'authorized'
        self._selected_model = saved.get('selected_model')
        reasoning = saved.get('selected_reasoning') or {}
        self._reasoning_levels = reasoning.get('levels') or []
        self._reasoning_effort = reasoning.get('effort') if reasoning.get('effort') in self._reasoning_levels else None
        self._account_label = record.get('account_label')

    def _token_record(self, response):
        try:
            scopes = response['scope'].split()
            if not {'resource.invoke', 'chatgpt.tokens.use.direct'}.issubset(scopes):
                raise ValueError()
            if response.get('token_type', '').lower() != 'bearer':
                raise ValueError()
            if not all(isinstance(response.get(k), str) and response[k] for k in ('access_token', 'refresh_token', 'id_token')):
                raise ValueError()
            expiry = float(response['expires_in'])
            if not 0 < expiry <= 365 * 86400:
                raise ValueError()
            return {k: response[k] for k in ('access_token', 'refresh_token', 'id_token')} | {
                'scopes': scopes, 'expires_at': time.time() + expiry, 'token_type': 'Bearer'}
        except Exception:
            raise SIWCFailure('ChatGPT plan access was not granted. Please review the requested permissions.') from None

    async def get_access_token(self):
        self._check()
        # Process lock remains held across the request to serialize rotating refresh.
        with self.store.transaction():
            saved = self.store.load()
            old = (saved or {}).get('registration')
            if not old or not old.get('refresh_token'):
                raise protocol.AuthorizationRequired()
            if old['expires_at'] > time.time() + 60:
                return old['access_token']
            result = await self.client.token({'grant_type': 'refresh_token', 'client_id': old['client_id'],
                'refresh_token': old['refresh_token'], 'resource': protocol.RESOURCE})
            # Refresh can omit unchanged scopes/ID token; preserve only within this registration.
            merged = {**result, 'scope': result.get('scope', ' '.join(old['scopes'])),
                      'id_token': result.get('id_token', old['id_token']),
                      'refresh_token': result.get('refresh_token', old['refresh_token'])}
            if 'id_token' in result:
                # A fresh ID token must still bind to the original issuer/client/subject.
                import jwt
                try:
                    keys = await self.client.jwks()
                    header = jwt.get_unverified_header(result['id_token'])
                    matching = [k for k in keys['keys'] if k.get('kid') == header.get('kid')]
                    if header.get('alg') != 'RS256' or len(matching) != 1: raise ValueError()
                    claims = jwt.decode(result['id_token'], jwt.PyJWK.from_dict(matching[0], algorithm='RS256').key,
                        algorithms=['RS256'], audience=old['client_id'], issuer=protocol.ISSUER,
                        options={'require': ['iss', 'aud', 'exp', 'sub']})
                    if claims['sub'] != old['subject']: raise ValueError()
                    if isinstance(claims['aud'], list) and len(claims['aud']) > 1 and claims.get('azp') != old['client_id']: raise ValueError()
                except Exception:
                    raise SIWCFailure() from None
            updated = {**old, **self._token_record(merged)}
            self.store.save({**saved, 'registration': updated})
            return updated['access_token']

    async def sign_out(self):
        self._check()
        self.cancel()
        confirmed = False
        with self.store.transaction():
            saved = self.store.load()
            old = (saved or {}).get('registration')
            if old and old.get('refresh_token'):
                try:
                    await self.client.revoke(old['client_id'], old['refresh_token'])
                    confirmed = True
                except Exception:
                    pass
                mapping = {k: old[k] for k in ('client_id', 'subject', 'issuer')}
                self.store.save({**saved, 'registration': mapping})
        self._last_result = 'required'
        self._selected_model = None
        self._reasoning_effort = None
        self._reasoning_levels = []
        self._account_label = None
        return {'signed_out': True, 'remote_revocation_confirmed': confirmed,
                'message': 'Disconnected.' if confirmed else 'Local tokens cleared; remote revocation unconfirmed. Disconnect LangPal in ChatGPT Settings.'}


    def select_model(self, model, authorized_models, *, effort=None, reasoning=None):
        """Only pass model IDs freshly obtained from the authenticated models endpoint."""
        self._check()
        if self._last_result != 'authorized' or not isinstance(model, str) or model not in authorized_models:
            raise SIWCFailure('Choose a model from the authorized ChatGPT model list.')
        levels = [item['id'] for item in (reasoning or {}).get('levels', [])]
        if effort is not None and effort not in levels:
            raise SIWCFailure('请从当前模型支持的思考档位中选择。')
        with self.store.transaction():
            saved = self.store.load()
            if not saved or not saved.get('registration', {}).get('refresh_token'):
                raise protocol.AuthorizationRequired()
            self.store.save({**saved, 'selected_model': model,
                             'selected_reasoning': {'effort': effort, 'levels': levels}})
        self._selected_model = model
        self._reasoning_effort = effort
        self._reasoning_levels = levels


    def resume(self):
        """Explicit opt-in startup restore; never called by metadata/capabilities."""
        self._check()
        with self.store.transaction():
            saved = self.store.load()
        registration = (saved or {}).get('registration')
        if saved and saved.get('consent_version') == 'siwc-v1' and registration and registration.get('refresh_token'):
            self._last_result = 'authorized'
            self._selected_model = saved.get('selected_model')
            reasoning = saved.get('selected_reasoning') or {}
            self._reasoning_levels = reasoning.get('levels') or []
            self._reasoning_effort = reasoning.get('effort') if reasoning.get('effort') in self._reasoning_levels else None
            self._account_label = registration.get('account_label')
        else:
            self._last_result = 'required'
        return self.metadata()
