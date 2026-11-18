"""课程管家：对话、附件、提案的预览/应用/撤销。模型可选 Claude / DeepSeek（DSH）/ ChatGPT，默认跟随主聊天引擎。仅本机访问。"""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.datastructures import UploadFile
from pydantic import Field

from ..services import reading_sources, workspace_agent as agent, workspace_conversations as conversations
from .study_storage import bounded_body
from ..security import local_request, same_origin


router = APIRouter(prefix='/workspace-agent', tags=['workspace-agent'], dependencies=[Depends(local_request)])


class Turn(agent.Strict):
    request: str = Field(min_length=1, max_length=2000)
    reply: str = Field(min_length=1, max_length=2400)


class Conversation(agent.Strict):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class Plan(agent.Strict):
    # 不传或 'main' = 跟随主聊天引擎；也可以每轮单独选一家。不会自动换到别家。
    provider: Literal['main', 'claude', 'deepseek', 'chatgpt'] | None = None
    message: str = Field(default="", max_length=2000)
    preferences: dict[str, str] = Field(default_factory=dict, max_length=2)
    previous: list[Turn] = Field(default_factory=list, max_length=3)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=80)
    request_id: str | None = Field(default=None, min_length=1, max_length=80)
    attachment_ids: list[str] = Field(default_factory=list, max_length=4)


class Decision(agent.Strict):
    id: str = Field(min_length=20, max_length=80)
    preferences: dict[str, str] = Field(default_factory=dict, max_length=2)


class TestSource(agent.Strict):
    id: str = Field(min_length=1, max_length=80)
    query: str = Field(default='', max_length=220)


class Preview(agent.Strict):
    operations: list[agent.Operation] = Field(min_length=1, max_length=4)
    preferences: dict[str, str] = Field(default_factory=dict, max_length=2)


@router.get('/catalog')
def catalog():
    return agent.catalog()


@router.get('/inspect')
def inspect_workspace():
    return agent.inspect_workspace()


@router.post('/preview')
def preview(body: Preview):
    if len(agent.encoded(body.model_dump()).encode('utf-8')) > 64_000:
        raise HTTPException(413, '配置内容过大，请拆分修改')
    try:
        return agent.preview_operations(body.operations, _preferences(body.preferences))
    except agent.AgentError as error:
        raise HTTPException(422, str(error)) from None


def _preferences(values):
    return {key: value for key, value in values.items()
            if key in {'reviewKind', 'reviewLanguage'} and len(value) <= 25}


@router.get('/capabilities')
def capabilities():
    return {'version': 1, 'conversations': True, 'attachments': True,
            'max_file_bytes': conversations.MAX_FILE, 'max_text_file_bytes': conversations.MAX_TEXT_FILE,
            'max_attachments': 4, 'history_turns': 3, 'images': True,
            'max_image_pixels': 16000000, 'proposals': True,
            **agent.workspace_agent_runtime.capabilities()}


@router.get('/proposals')
def proposal_history():
    return {'proposals': agent.proposal_history()}


@router.get('/proposals/{proposal_id}')
def proposal_state(proposal_id: str):
    try:
        return agent.proposal_state(proposal_id)
    except agent.Missing as error:
        raise HTTPException(404, str(error)) from None


@router.get('/conversations')
def list_conversations():
    return {'conversations': conversations.list_conversations()}


@router.post('/conversations')
def create_conversation(body: Conversation):
    return conversations.create_conversation(body.title)


@router.get('/conversations/{conversation_id}')
def conversation_detail(conversation_id: str):
    return conversations.detail(conversation_id)


@router.delete('/conversations/{conversation_id}', dependencies=[Depends(same_origin)])
def delete_conversation(conversation_id: str):
    return conversations.delete_conversation(conversation_id)


@router.get('/conversations/{conversation_id}/attachments/{attachment_id}/content')
def attachment_content(conversation_id: str, attachment_id: str):
    data, mime = conversations.image_content(conversation_id, attachment_id)
    return Response(data, media_type=mime, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'"})


@router.post('/conversations/{conversation_id}/attachments')
async def upload_attachment(conversation_id: str, request: Request):
    request._body = await bounded_body(request, conversations.MAX_FILE + 300000)
    async with request.form(max_files=1, max_fields=2, max_part_size=256000) as form:
        file = form.get('file')
        text = form.get('extracted_text', '')
        truncated = form.get('extraction_truncated', 'false')
        if not isinstance(file, UploadFile) or not isinstance(text, str) or truncated not in ('true', 'false'):
            raise HTTPException(422, 'Invalid attachment fields')
        raw = await file.read(conversations.MAX_FILE + 1)
        return await _database_call(conversations.upload, conversation_id, file.filename, file.content_type or '', raw, text, truncated == 'true')


async def _database_call(function, *args):
    # SQLite work must leave the event loop. Cancellation cannot stop a worker
    # thread, so settle its transaction before any follow-up state transition.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


@router.post('/plan')
async def plan(body: Plan):
    try:
        provider = agent.workspace_agent_runtime.resolve_provider(body.provider)
    except agent.workspace_agent_runtime.RuntimeFailure as error:
        raise HTTPException(422, str(error)) from None
    started = False
    begin_task = None
    try:
        preferences = _preferences(body.preferences)
        if not body.message and not body.attachment_ids:
            raise HTTPException(422, 'Enter a message or attach a file')
        if body.conversation_id is None:
            if body.request_id is not None or body.attachment_ids:
                raise HTTPException(422, 'Attachments and request_id require conversation_id')
            return await agent.plan(body.message, preferences, [row.model_dump() for row in body.previous], provider=provider)
        if not body.request_id:
            raise HTTPException(422, 'Conversation messages require request_id')
        if len(set(body.attachment_ids)) != len(body.attachment_ids) or any(not value or len(value) > 80 for value in body.attachment_ids):
            raise HTTPException(422, 'Invalid attachment IDs')
        if agent._secret.search(body.message):
            raise HTTPException(422, 'Remove credentials before sending')
        begin_task = asyncio.create_task(asyncio.to_thread(conversations.begin_turn, body.conversation_id, body.request_id, body.message, body.attachment_ids, {**preferences, '_provider': provider}))
        turn = await asyncio.shield(begin_task)
        if 'replay' in turn:
            return turn['replay']
        started = True
        prompt_message = body.message or 'Please examine the attached material and ask what I would like to do with it; do not propose changes without an explicit request.'
        result = await agent.plan(prompt_message, preferences, turn['previous'], attachment_context=turn['attachment_context'], provider=provider)
        return await _database_call(conversations.finish_turn, body.conversation_id, body.request_id, result)
    except agent.AgentError as error:
        if started: await _database_call(conversations.fail_turn, body.conversation_id, body.request_id)
        raise HTTPException(422, str(error)) from None
    except asyncio.CancelledError:
        if not started and begin_task is not None:
            try:
                turn = await begin_task
                started = 'replay' not in turn
            except Exception:
                pass
        if started: await _database_call(conversations.fail_turn, body.conversation_id, body.request_id)
        raise
    except Exception:
        if started: await _database_call(conversations.fail_turn, body.conversation_id, body.request_id)
        raise


def _commit(body, undo):
    try:
        return agent.commit(body.id, undo, _preferences(body.preferences))
    except agent.Missing as error:
        raise HTTPException(404, str(error)) from None
    except agent.Conflict as error:
        raise HTTPException(409, str(error)) from None


@router.post('/apply')
def apply(body: Decision):
    return _commit(body, False)


@router.post('/undo')
def undo(body: Decision):
    return _commit(body, True)


@router.post('/test-source')
async def test_source(body: TestSource):
    """只读：用户点按钮测试一个已保存的阅读来源能不能取到内容，不改任何设置。"""
    try:
        result = await reading_sources.test_source(body.id, query=body.query)
    except KeyError:
        raise HTTPException(404, '这个来源已删除') from None
    except reading_sources.SourceError as error:
        raise HTTPException(422, str(error)) from None
    return {'ok': True, 'count': result['count']}
