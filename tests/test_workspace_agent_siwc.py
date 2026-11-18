"""Offline SIWC transport contracts; never reads auth files or uses live network."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import workspace_agent_siwc as runtime

CONTEXT = {'inspect': {'safe': True}, 'read_skill': {'skill': 'sanitized snapshot'}}
class SourceArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str


TOOLS = {'source.save': ('Save source', SourceArgs)}
FINAL = {'reply': 'Ready', 'operations': [{'tool': 'source.save', 'args': {'name': 'example'}}], 'test_source_id': None}


def event(value, newline='\n'):
    return ('data: ' + json.dumps(value, ensure_ascii=False) + newline * 2).encode()


def completed(value=FINAL):
    return {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
        {'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [
            {'type': 'output_text', 'text': json.dumps(value, ensure_ascii=False)}]}]}}


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.token = AsyncMock(return_value='mock-token-not-a-credential')
        self.requests = []

    async def run_response(self, body=None, response=None, **kwargs):
        def handler(request):
            self.requests.append(request)
            self.assertEqual(str(request.url), runtime.BASE + '/responses')
            self.assertEqual(request.headers['authorization'], 'Bearer mock-token-not-a-credential')
            return response if response is not None else httpx.Response(200,
                headers={'content-type': 'text/event-stream; charset=utf-8'},
                stream=Chunks([event(completed()) if body is None else body]))
        return await runtime.generate('User request', CONTEXT, TOOLS,
            token_provider=self.token, model='account-model', transport=httpx.MockTransport(handler), **kwargs)

    async def test_contract(self):
        self.assertEqual(await self.run_response(), FINAL)
        self.assertEqual(len(self.requests), 1)
        payload = json.loads(self.requests[0].content)
        self.assertEqual(set(payload), {'model', 'store', 'stream', 'instructions', 'input'})
        self.assertIs(payload['store'], False)
        self.assertIs(payload['stream'], True)
        self.assertIsInstance(payload['input'], list)
        content = json.loads(payload['input'][0]['content'])
        self.assertEqual(content['reference_data'], CONTEXT)
        self.assertEqual(content['tool_catalog'][0]['id'], 'source.save')
        self.assertIn('schema', content['tool_catalog'][0])

    async def test_account_catalog_filters_and_preserves_order(self):
        def handler(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(str(request.url), runtime.BASE + '/models')
            self.assertEqual(request.headers['authorization'], 'Bearer mock-token-not-a-credential')
            return httpx.Response(200, json={'models': [
                {'slug': 'z', 'display_name': 'Z', 'visibility': 'list'},
                {'slug': 'hidden', 'visibility': 'hidden'},
                {'slug': 'a', 'display_name': 'A', 'visibility': 'list'}]})
        result = await runtime.list_models(token_provider=self.token, transport=httpx.MockTransport(handler))
        self.assertEqual(result, [{'slug': 'z', 'display_name': 'Z'}, {'slug': 'a', 'display_name': 'A'}])

    async def test_catalog_invalid_and_bounded(self):
        for body in ({'data': []}, {'models': [{'slug': 'a', 'visibility': 'list'}]},
                     {'models': [{'slug': 'a', 'display_name': 'A', 'visibility': 'list'}] * 2}):
            with self.assertRaises(runtime.SiwcFailure):
                await runtime.list_models(token_provider=self.token,
                    transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
        with patch.object(runtime, 'MAX_MODEL_BYTES', 5), self.assertRaises(runtime.SiwcFailure) as caught:
            await runtime.list_models(token_provider=self.token,
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'x' * 6)))
        self.assertEqual(caught.exception.code, 'size')

    async def test_catalog_metadata_can_exceed_inference_response_budget(self):
        value = {'models': [{'slug': 'listed', 'display_name': 'Listed', 'visibility': 'list',
                             'base_instructions': 'x' * 600_000}]}
        result = await runtime.list_models(token_provider=self.token,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value)))
        self.assertEqual(result, [{'slug': 'listed', 'display_name': 'Listed'}])

    async def test_default_authorization_is_closed_and_caps_have_no_io(self):
        from app.services import workspace_agent_siwc_auth as auth
        with patch.object(auth, 'get_access_token', new_callable=AsyncMock) as token:
            caps = runtime.capabilities()
            self.assertFalse(caps['configured'])
            self.assertFalse(caps['authenticated'])
            self.assertIsNone(caps['model'])
            token.assert_not_called()
            token.side_effect = auth.AuthorizationRequired()
            with self.assertRaises(runtime.SiwcFailure) as caught:
                await runtime.generate('request', CONTEXT, TOOLS)
            self.assertEqual(caught.exception.code, 'authorization_required')
            token.assert_not_called()

    async def test_app_owned_authorized_path_uses_selected_model(self):
        from app.services import workspace_agent_siwc_auth as auth
        def handler(request):
            self.requests.append(request)
            self.assertEqual(json.loads(request.content)['model'], 'selected-model')
            self.assertEqual(request.headers['authorization'], 'Bearer mock-app-token')
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=event(completed()))
        metadata = {'configured': True, 'authorization_state': 'authorized', 'selected_model': 'selected-model'}
        with patch.object(auth, 'safe_metadata', return_value=metadata), \
                patch.object(auth, 'get_selected_model', new_callable=AsyncMock, return_value='selected-model') as model, \
                patch.object(auth, 'get_access_token', new_callable=AsyncMock, return_value='mock-app-token') as token:
            self.assertTrue(runtime.capabilities()['configured'])
            token.assert_not_called()
            result = await runtime.generate('request', CONTEXT, TOOLS, transport=httpx.MockTransport(handler))
            self.assertEqual(result, FINAL)
            model.assert_awaited_once()
            token.assert_awaited_once()

    async def test_app_path_requires_both_authorization_and_model(self):
        from app.services import workspace_agent_siwc_auth as auth
        for metadata in ({'configured': True, 'authorization_state': 'disabled', 'selected_model': 'model'},
                         {'configured': True, 'authorization_state': 'authorized', 'selected_model': None},
                         {'configured': False, 'authorization_state': 'authorized', 'selected_model': 'model'}):
            with patch.object(auth, 'safe_metadata', return_value=metadata), \
                    patch.object(auth, 'get_access_token', new_callable=AsyncMock) as token:
                with self.assertRaises(runtime.SiwcFailure) as caught:
                    await runtime.generate('request', CONTEXT, TOOLS)
                self.assertEqual(caught.exception.code, 'authorization_required')
                token.assert_not_called()

    async def test_invalid_model_and_token_never_send(self):
        with self.assertRaises(runtime.SiwcFailure) as caught:
            await runtime.generate('request', CONTEXT, TOOLS, token_provider=self.token,
                                   model='bad\nmodel', transport=httpx.MockTransport(lambda _: self.fail('network')))
        self.assertEqual(caught.exception.code, 'model')
        self.token.assert_not_called()
        self.token.return_value = 'invalid\r\nheader'
        with self.assertRaises(runtime.SiwcFailure) as caught:
            await self.run_response()
        self.assertEqual(caught.exception.code, 'authentication')
        self.assertEqual(self.requests, [])

    async def test_utf8_byte_splits_and_newline_types(self):
        value = {**FINAL, 'reply': '\u4f60\u597d'}
        for newline in ('\n', '\r\n', '\r'):
            data = b'\xef\xbb\xbf: ping' + newline.encode() * 2 + event(completed(value), newline)
            stream = Chunks([bytes([byte]) for byte in data])
            result = await self.run_response(response=httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=stream))
            self.assertEqual(result, value)
            self.assertTrue(stream.closed)

    async def test_multiline_and_named_event(self):
        raw = json.dumps(completed(), indent=2)
        data = ('event: response.completed\n' + '\n'.join('data: ' + line for line in raw.splitlines()) + '\n\n').encode()
        self.assertEqual(await self.run_response(data), FINAL)

    async def test_missing_terminal_and_done_not_success(self):
        for body in (b'', b'data: [DONE]\n\n', event({'type': 'response.output_text.delta', 'delta': 'partial'}), event(completed()).rstrip(b'\n')):
            with self.subTest(body=body), self.assertRaises(runtime.SiwcFailure) as caught:
                await self.run_response(body)
            self.assertEqual(caught.exception.code, 'interrupted')

    async def test_terminal_failures_even_after_partial_or_completed(self):
        for kind in ('response.failed', 'response.incomplete', 'error', 'response.error'):
            failure = event({'type': kind, 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded', 'message': 'private details'}}})
            for prefix in (event({'type': 'response.output_text.delta', 'delta': 'partial'}), event(completed())):
                with self.assertRaises(runtime.SiwcFailure) as caught:
                    await self.run_response(prefix + failure)
                self.assertEqual(caught.exception.code, 'subscription_sharing_usage_limit_exceeded')
                self.assertNotIn('private', str(caught.exception))

    async def test_completed_done(self):
        self.assertEqual(await self.run_response(event(completed()) + b'data: [DONE]\n\n'), FINAL)

    async def test_bad_sse(self):
        bodies = [b'data: nope\n\n', b'data: []\n\n', b'data: {"type":"a","type":"b"}\n\n',
                  b'data: \xff\n\n', b'event: error\n' + event(completed()), event(completed()) * 2]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(runtime.SiwcFailure):
                await self.run_response(body)

    async def test_invalid_proposals(self):
        for value in ({}, {**FINAL, 'extra': True}, {**FINAL, 'operations': [{'tool': 'source.save', 'args': {'extra': 2}}]}, {**FINAL, 'reply': ' '},
                      {**FINAL, 'operations': [{'tool': 'shell', 'args': {}}]},
                      {**FINAL, 'operations': [{'tool': 'source.save', 'args': []}]},
                      {**FINAL, 'operations': [{'tool': 'source.save', 'args_json': '{}'}]},
                      {**FINAL, 'operations': FINAL['operations'] * 5},
                      {**FINAL, 'test_source_id': 1}):
            with self.subTest(value=value), self.assertRaises(runtime.SiwcFailure):
                await self.run_response(event(completed(value)))

    async def test_completed_shape_and_no_external_tools(self):
        for output in ([{'type': 'function_call', 'name': 'shell'}], [{'type': 'message', 'role': 'user'}],
                       [{'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'refusal', 'refusal': 'No'}]}], []):
            value = completed()
            value['response']['output'] = output
            with self.assertRaises(runtime.SiwcFailure):
                await self.run_response(event(value))

    async def test_status_redaction_no_redirect(self):
        for status, code in [(401, 'authentication'), (403, 'authentication'), (429, 'rate_limit'), (500, 'service'), (302, 'service')]:
            before = len(self.requests)
            with self.assertRaises(runtime.SiwcFailure) as caught:
                await self.run_response(response=httpx.Response(status, text='private upstream', headers={'location': 'https://example.com'}))
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('private', str(caught.exception))
            self.assertEqual(len(self.requests), before + 1)

    async def test_invalid_content_type(self):
        with self.assertRaises(runtime.SiwcFailure):
            await self.run_response(response=httpx.Response(200, json=completed()))

    async def test_limits(self):
        for limit in ('MAX_RESPONSE_BYTES', 'MAX_EVENT_BYTES', 'MAX_OUTPUT_BYTES'):
            with patch.object(runtime, limit, 10), self.assertRaises(runtime.SiwcFailure) as caught:
                await self.run_response()
            self.assertEqual(caught.exception.code, 'size')
        with patch.object(runtime, 'MAX_INPUT_BYTES', 10), self.assertRaises(runtime.SiwcFailure):
            await self.run_response()
        self.assertEqual(self.token.await_count, 3)

    async def test_images_rejected_before_token(self):
        with self.assertRaises(runtime.SiwcFailure) as caught:
            await self.run_response(images=[{'data': b'fake'}])
        self.assertEqual(caught.exception.code, 'vision')
        self.token.assert_not_called()
        self.assertEqual(self.requests, [])

    async def test_network_timeout_and_cancel(self):
        for exception, code in [(httpx.ConnectError('private'), 'network'), (httpx.ReadTimeout('private'), 'timeout')]:
            def handler(_):
                raise exception
            with self.assertRaises(runtime.SiwcFailure) as caught:
                await runtime.generate('request', CONTEXT, {}, model='model', token_provider=self.token, transport=httpx.MockTransport(handler))
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('private', str(caught.exception))
        class Blocking(Chunks):
            async def __aiter__(self):
                yield b': started\n\n'
                await asyncio.Event().wait()
        stream = Blocking([])
        task = asyncio.create_task(self.run_response(response=httpx.Response(200,
            headers={'content-type': 'text/event-stream'}, stream=stream)))
        await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stream.closed)

    async def test_nonfinite_and_duplicate_proposal(self):
        value = completed()
        for text in ('{"reply":"a","reply":"b","operations":[],"test_source_id":null}',
                     '{"reply":"a","operations":[{"tool":"source.save","args":{"v":NaN}}],"test_source_id":null}'):
            value['response']['output'][0]['content'][0]['text'] = text
            with self.assertRaises(runtime.SiwcFailure):
                await self.run_response(event(value))


if __name__ == '__main__':
    unittest.main()
