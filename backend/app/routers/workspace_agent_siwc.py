"""ChatGPT 账号登录（SIWC）路由：显式同意、只收本机同源请求、响应里不带任何凭据。

整个路由挂 security.local_request（本机 + 同源，status 会返回账号邮箱）；会改状态的 POST 另外要求
Origin（GET 退而看 Referer）和 Host 完全对上。登录本身不在这里完成：POST /login 返回一个
http://127.0.0.1:<随机端口>/begin?ticket=… 的本机链接，由桌面壳或前端用系统浏览器打开；那个端口由
授权运行时自己起的小 HTTP 服务应答，不经过 FastAPI，也就不受全局访问守卫影响。
"""
from urllib.parse import urlsplit
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel
from ..services import workspace_agent_siwc_auth as auth
from ..services.workspace_agent_siwc_live import SIWCFailure
from ..security import local_request as _local_same_origin

router = APIRouter(prefix='/workspace-agent/siwc', tags=['workspace-agent-siwc'],
                   dependencies=[Depends(_local_same_origin)])


def local_request(request):
    peer = request.client.host if request.client else ''
    host = request.headers.get('host', '')
    origin = request.headers.get('origin', '')
    if not origin and request.method == 'GET':
        referer = urlsplit(request.headers.get('referer', ''))
        origin = referer.scheme + '://' + referer.netloc
    try:
        parsed = urlsplit('http://' + host)
        valid = peer in ('127.0.0.1', '::1') and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
        valid = valid and origin == 'http://' + host and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(403, 'A local same-origin request is required.')


@router.get('/status')
@router.get('/disclosure')
def status(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {**auth.disclosure(), **auth.safe_metadata(), 'live_enabled': auth.runtime().enabled}


class Consent(BaseModel):
    approved: bool = False


@router.post('/login')
def login(request: Request, body: Consent, response: Response):
    local_request(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        if body.approved is not True:
            raise auth.AuthorizationRequired()
        auth.enable_after_user_approval(approved=True)
        from ..db import get_conn
        with closing(get_conn()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('chatgpt_enabled','1')")
        return auth.runtime().start(approved=body.approved)
    except auth.AuthorizationRequired:
        raise HTTPException(409, detail={'code': 'siwc_authorization_required',
            'message': 'Live authorization is not enabled or explicit approval was not supplied.'},
            headers={'Cache-Control': 'no-store'}) from None
    except SIWCFailure as exc:
        raise HTTPException(409, str(exc), headers={'Cache-Control': 'no-store'}) from None


@router.post('/test')
async def test_connection(request: Request, response: Response):
    local_request(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        from ..services.chatgpt_sdk import complete
        from ..services.workspace_agent_siwc import SiwcFailure
        model = await auth.get_selected_model()
        result = await complete({'model': model, 'input': 'Reply with exactly OK.'})
        if not result.strip():
            raise ValueError()
        return {'ok': True, 'model': model, 'sdk': 'openai', 'reply': result[:100]}
    except auth.AuthorizationRequired:
        raise HTTPException(409, '请先连接 ChatGPT 并选择模型。') from None
    except SiwcFailure as error:
        raise HTTPException(409, str(error)) from None
    except ValueError:
        raise HTTPException(502, 'ChatGPT 返回了空回复。') from None


@router.post('/cancel')
def cancel(request: Request):
    local_request(request)
    auth.runtime().cancel()
    return {'cancelled': True}


@router.post('/logout')
async def logout(request: Request, response: Response):
    local_request(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        return await auth.runtime().sign_out()
    except auth.AuthorizationRequired:
        raise HTTPException(409, 'ChatGPT authorization is not enabled.') from None
    except SIWCFailure as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/models')
async def models(request: Request, response: Response):
    local_request(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        from ..services.workspace_agent_siwc import list_models, SiwcFailure
        from ..services.model_catalog import chatgpt_models
        return {'models': await chatgpt_models()}
    except auth.AuthorizationRequired:
        raise HTTPException(409, '请先连接 ChatGPT。') from None
    except SiwcFailure as error:
        message = 'ChatGPT 授权已失效，请重新连接。' if error.code == 'authentication' else '暂时无法读取 ChatGPT 模型列表，请重试。'
        raise HTTPException(409 if error.code == 'authentication' else 502, message) from None
    except Exception:
        raise HTTPException(502, '暂时无法读取 ChatGPT 模型列表，请重试。') from None


class ModelChoice(BaseModel):
    model: str
    effort: str | None = None


@router.post('/model')
async def select_model(request: Request, body: ModelChoice, response: Response):
    local_request(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        from ..services.model_reasoning import save_chatgpt
        await save_chatgpt(body.model, body.effort)
        return auth.safe_metadata()
    except Exception:
        raise HTTPException(409, '请从当前账号返回的模型和思考档位中选择。') from None
