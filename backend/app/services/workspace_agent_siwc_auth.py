"""SIWC protocol primitives and access to the app-owned authorization runtime.

Live authorization starts after an explicit local sign-in action.
Official contract: developers.openai.com/siwc/token-sharing-open-source/sign-in
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit

ISSUER = 'https://auth.openai.com'
AUTHORIZE_ENDPOINT = ISSUER + '/api/accounts/authorize'
TOKEN_ENDPOINT = ISSUER + '/api/accounts/oauth/token'
JWKS_ENDPOINT = ISSUER + '/.well-known/jwks.json'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = ('openid', 'profile', 'email', 'offline_access', 'resource.invoke', 'chatgpt.tokens.use.direct')
CALLBACK_PATH = '/auth/langpal/siwc/callback'


class AuthorizationRequired(RuntimeError):
    def __init__(self):
        super().__init__('SIWC authorization requires explicit user approval; live sign-in is not enabled.')


class InvalidAuthorization(ValueError):
    def __init__(self):
        super().__init__('Invalid or expired authorization transaction.')


def disclosure() -> dict:
    return {
        'status': 'authorization_required', 'live_enabled': False,
        'scopes': list(SCOPES), 'authorization_host': ISSUER,
        'resource': RESOURCE, 'application_name': 'LangPal',
        'registration': 'OpenAI dynamic registration after explicit consent; no API key or client secret.',
        'data': ['OpenAI account identifier, name and email', 'LangPal host identifier',
                 'access, refresh and ID tokens', 'user-selected prompts and materials for future inference'],
        'storage': 'Windows current-user DPAPI protected LangPal bundle; never business SQLite or browser storage.',
        'retention': 'Pending state: 5 minutes in memory. Tokens: until sign-out, revocation, or expiry; registration and host mapping retained for reauthorization.',
        'notice': 'Creates persistent access to eligible ChatGPT plan usage. No access to ChatGPT conversation history. No authorization has been initiated.',
    }


async def get_access_token() -> str:
    return await runtime().get_access_token()


def _redirect(uri: str) -> None:
    try:
        p = urlsplit(uri)
        if (p.scheme != 'http' or p.hostname != '127.0.0.1' or not p.port
                or p.username or p.password or p.path != CALLBACK_PATH or p.query or p.fragment):
            raise InvalidAuthorization()
    except ValueError:
        raise InvalidAuthorization() from None


def _issued(value: str) -> bool:
    return bool(re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,240}', value))


@dataclass(repr=False)
class ExchangePlan:
    """Sensitive in-memory data; never serialize into API responses or diagnostics."""
    client_id: str
    code: str = field(repr=False)
    verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    redirect_uri: str
    expected_subject: str | None = None

    def form(self) -> dict:
        return {'grant_type': 'authorization_code', 'client_id': self.client_id,
                'code': self.code, 'code_verifier': self.verifier,
                'redirect_uri': self.redirect_uri, 'resource': RESOURCE}


@dataclass(repr=False)
class _Pending:
    session_hash: str
    verifier: str
    nonce: str
    redirect_uri: str
    client_id: str
    expires_at: float
    expected_subject: str | None


class OfflineAuthorization:
    """Pure protocol preparation used by mock tests, not mounted as a live login API."""
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._pending = {}
        self._lock = threading.Lock()

    def prepare(self, *, local_session: str, host_id: str, redirect_uri: str,
                client_id: str = 'dynamic_agent_client', expected_subject: str | None = None) -> str:
        _redirect(redirect_uri)
        if len(local_session) < 32 or not host_id or len(host_id) > 200:
            raise InvalidAuthorization()
        if client_id != 'dynamic_agent_client' and (not _issued(client_id) or not expected_subject):
            raise InvalidAuthorization()
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v.expires_at > self._clock()}
            if len(self._pending) >= 32:
                raise InvalidAuthorization()
            self._pending[state] = _Pending(hashlib.sha256(local_session.encode()).hexdigest(),
                verifier, nonce, redirect_uri, client_id, self._clock() + 300, expected_subject)
        params = dict(client_id=client_id, ext_agent_host_id=host_id, response_type='code',
                      redirect_uri=redirect_uri, scope=' '.join(SCOPES), resource=RESOURCE,
                      state=state, nonce=nonce, code_challenge_method='S256', code_challenge=challenge)
        if client_id == 'dynamic_agent_client':
            params['agent_name_hint'] = 'LangPal'
        return AUTHORIZE_ENDPOINT + '?' + urlencode(params)

    def consume(self, callback_url: str, *, local_session: str) -> ExchangePlan:
        if len(callback_url) > 16384:
            raise InvalidAuthorization()
        p = urlsplit(callback_url)
        if p.fragment:
            raise InvalidAuthorization()
        q = parse_qs(p.query, keep_blank_values=True)
        if any(len(v) != 1 for v in q.values()):
            raise InvalidAuthorization()
        state = q.get('state', [''])[0]
        with self._lock:
            pending = self._pending.get(state)
            if not pending or not secrets.compare_digest(pending.session_hash, hashlib.sha256(local_session.encode()).hexdigest()):
                raise InvalidAuthorization()
            # Atomic one-time consumption, including rejected/denied callbacks.
            del self._pending[state]
        actual = p._replace(query='', fragment='').geturl()
        if pending.expires_at <= self._clock() or actual != pending.redirect_uri or 'error' in q:
            raise InvalidAuthorization()
        issued = q.get('client_id', [pending.client_id])[0]
        if not _issued(issued) or (pending.client_id != 'dynamic_agent_client' and issued != pending.client_id):
            raise InvalidAuthorization()
        code = q.get('code', [''])[0]
        if not code or len(code) > 8192:
            raise InvalidAuthorization()
        return ExchangePlan(issued, code, pending.verifier, pending.nonce,
                            pending.redirect_uri, pending.expected_subject)


def validate_id_token(id_token: str, jwks: dict, plan: ExchangePlan) -> dict:
    """Validate against trusted JWKS supplied by a future fixed-host fetcher, offline here."""
    import jwt
    try:
        header = jwt.get_unverified_header(id_token)
        keys = [key for key in jwks.get('keys', []) if key.get('kid') == header.get('kid')]
        if header.get('alg') != 'RS256' or len(keys) != 1:
            raise InvalidAuthorization()
        key = jwt.PyJWK.from_dict(keys[0], algorithm='RS256').key
        claims = jwt.decode(id_token, key, algorithms=['RS256'], audience=plan.client_id,
                            issuer=ISSUER, options={'require': ['iss', 'aud', 'exp', 'sub', 'nonce']})
        if not secrets.compare_digest(str(claims['nonce']), plan.nonce) or not claims['sub']:
            raise InvalidAuthorization()
        if plan.expected_subject and claims['sub'] != plan.expected_subject:
            raise InvalidAuthorization()
        if isinstance(claims['aud'], list) and len(claims['aud']) > 1 and claims.get('azp') != plan.client_id:
            raise InvalidAuthorization()
        return claims
    except Exception:
        raise InvalidAuthorization() from None


_runtime = None
_runtime_lock = threading.RLock()


def runtime():
    global _runtime
    if _runtime is None:
        from .workspace_agent_siwc_live import SIWCRuntime
        _runtime = SIWCRuntime(enabled=False)
    return _runtime


def install_runtime(value, *, approved=False):
    """Explicit integration hook; startup may call it only under the approved opt-in flag."""
    if approved is not True:
        raise AuthorizationRequired()
    global _runtime
    _runtime = value


def safe_metadata() -> dict:
    return runtime().metadata()


async def get_selected_model() -> str:
    value = safe_metadata()
    if not value['configured'] or not value['selected_model']:
        raise AuthorizationRequired()
    return value['selected_model']


def enable_after_user_approval(*, approved=False):
    """Call only after documented action-time consent. No network or storage I/O here.

    The later same-origin POST /login must separately carry approved=true. This
    explicit hook enables this process only; approved opt-in startup wiring may invoke it.
    """
    if approved is not True:
        raise AuthorizationRequired()
    from .workspace_agent_siwc_live import SIWCRuntime
    with _runtime_lock:
        if _runtime is None or not _runtime.enabled:
            install_runtime(SIWCRuntime(enabled=True), approved=True)
