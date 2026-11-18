# LangPal ChatGPT integration

> **现状（2026-11-12）**：ChatGPT 账号是第四个聊天引擎（providers/chatgpt.py），也是课程管家的可选模型和杂活/听力的可选引擎。
> - 上下文：按常驻会话 key `p{persona}s{session}` 在内存里维护多轮历史，首次出现从库里补种（和 DeepSeek 一样），不每轮冷启动；不再按会话建锁。
> - 降级：主引擎是 chatgpt 时出错 → Claude（可用时）→ DeepSeek；半开重试照常。
> - 登录：`POST /api/workspace-agent/siwc/login {approved:true}` 返回 `browser_url`（`http://127.0.0.1:<随机端口>/begin?ticket=…`），由桌面壳 IPC `chatgpt:open-sign-in` 或前端用系统浏览器打开；该端口由授权运行时自己的小服务应答，不经过 8787 的全局访问守卫。整个 `/api/workspace-agent/siwc/*` 要求本机 + 同源，POST 还要求 Origin 与 Host 完全对上。
> - 启动时只要 `settings.chatgpt_enabled=1`（或 `LANGPAL_SIWC_ENABLED=1`）就从 `%LOCALAPPDATA%\LangPal\siwc\session.dpapi` 读回授权，不刷新令牌、不开浏览器。
> - 模型和思考档位：`GET /api/engines/chatgpt/models` 读账号模型目录；`POST /api/engines/chatgpt/reasoning`（或 `/siwc/model`）保存，档位只能从接口读到的列表（读不到时为标了 default 的保守列表）里选。

The Models and accounts page includes ChatGPT in the main-engine selector. Its sign-in button, authorized model selector and connection test appear directly below that selection. Inference uses the official OpenAI Python SDK with the app-owned OAuth access token.

## Official contract and required consent

Verified sources:
- https://developers.openai.com/siwc/quickstart
- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions

The OSS flow uses official `dynamic_agent_client` only to begin initial registration. OpenAI returns the issued client ID in the callback; code exchange and subsequent sign-ins use that issued ID. No client secret/API key is needed. This is independent of Codex/TangTang and never imports their credentials. App and account eligibility remain subject to OpenAI's official consent flow.

Before enabling, obtain explicit action-time approval for LangPal to create persistent access with scopes `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`. Data includes verified account identity/name/email, a stable opaque LangPal host ID and renewable access/refresh/ID tokens. Later inference sends only the prompts/materials selected for the user's request. Identity scopes do not expose ChatGPT conversation history.

Recipients: `auth.openai.com` for authorization, token exchange and renewal; `api.openai.com` for models and inference. Resource: `https://api.openai.com/v1`. Authorization: `https://auth.openai.com/api/accounts/authorize`. Token: `https://auth.openai.com/api/accounts/oauth/token`.

Storage: a current-Windows-user DPAPI-encrypted bundle under `%LOCALAPPDATA%/LangPal/siwc/session.dpapi`, atomic replacement, never plaintext or business SQLite. The backend declares the OpenAI SDK, PyJWT and Windows pywin32 dependencies. This avoids Windows generic Credential Manager's small single-blob size limit for multiple JWTs. DPAPI protects at rest but not against malware running as the same Windows user. Pending authorization data expires after five minutes in memory. Tokens remain until expiry, sign-out or revocation; renewable access can continue until revoked. Account/client mapping and host ID remain after sign-out for reauthorization. Official server controls token lifetime.

## Enablement after explicit user approval

Clicking Continue with ChatGPT sends the local same-origin login request with approved=true and persists chatgpt_enabled=1. The login handler enables the runtime and prepares its one-time browser handoff. The desktop bridge opens that handoff in the system browser. Startup restores only the app's protected credential record after this opt-in, or when LANGPAL_SIWC_ENABLED=1 was explicitly configured. Startup does not begin a new authorization. Resume restores the saved model and safe account label without a network request.

1. Read `GET /api/workspace-agent/siwc/disclosure`; show scopes, destinations, persistence and purpose before asking for confirmation.
2. After the user clicks the sign-in button, a same-origin local `POST /api/workspace-agent/siwc/login` with `{"approved":true}` starts the listener and returns a short-lived local browser handoff URL. Open it in the system browser only in response to that user action. Do not put the handoff URL in analytics/logs.
3. The local `/begin` consumes a one-time handoff ticket, sets an HttpOnly SameSite=Lax cookie in the system browser and redirects to OpenAI. This avoids relying on Electron's separate cookie jar.
4. OpenAI returns to `http://127.0.0.1:<ephemeral-port>/auth/langpal/siwc/callback`. HTTP loopback is required; do not substitute localhost. Scheme/host/path stay fixed across sign-ins and the exact URI including port is retained during code exchange.
5. The dedicated loopback listener verifies Host, peer, cookie, state, nonce, PKCE, expiry and issued client ID. It does not use a same-origin Referer rule on callback because legitimate top-level navigation comes from OpenAI. Logging is disabled on that listener. Success redirects to clean `/complete`, without code or tokens; responses are no-store/no-referrer. Main uvicorn never receives OAuth callback parameters.
6. JWT signature, issuer, audience, expiry, nonce and returning identity are checked before saving credentials. Granted token scopes must include plan invocation. The active status then becomes `authorized`, with no model guessed.
7. `GET /api/workspace-agent/siwc/models` loads the official authorized model list. `POST /api/workspace-agent/siwc/model` with `{"model":"<listed slug>"}` re-fetches the list and validates the choice. Both require local same-origin requests. Model selection is stored in the same protected bundle and restored on an explicitly enabled restart. Re-fetch the official list to change it.
8. Chat, explanations, listening authoring and Agent call `get_selected_model()` and `get_access_token()`. The official OpenAI SDK sends store=false and stream=true, and the response is accepted only after response.completed. The connection-test action runs a short request through that same SDK. Metadata is memory-only, never refreshes or reads credentials. Token renewal is serialized with a Windows cross-process lock and atomically replaces rotating credentials. `POST /logout` attempts official discovery-supplied revocation and clears tokens. If remote revocation fails, it explicitly says remote revocation was not confirmed and directs the user to ChatGPT Settings. `POST /cancel` stops the pending listener.

This initial implementation supports one active/saved registration. Signing out retains its mapping, and returning sign-in reuses it. A multi-account picker and account removal workflow are not implemented; do not imply they are.

## Verification and remaining limits

Run `python -m unittest discover -s tests -p 'test_workspace_agent_siwc_*.py' -v`.

The 22 authorization/runtime tests cover S256, one-time state, TTL, cookie-session protocol binding, duplicate parameters, denied callback, issued client and callback allowlists, returning identity, signed JWT checks, disabled I/O, provider host restrictions/no redirects, sanitized errors, save-after-validation, granted scopes, refresh rotation, revocation failure, model validation and mocked listener cancellation. Transport has its own mock suite.

Live authorization and inference depend on the user's completed official sign-in. Offline tests use generated identities, mock HTTP and isolated data. Report live connection results separately from those checks.
