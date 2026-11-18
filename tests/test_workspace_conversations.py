"""Agent persistence tests: temporary SQLite, mocked model, no real application DB."""
import asyncio
import json
import io
from PIL import Image
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services import workspace_conversations as store
from app.routers import workspace_agent as routes


class ConversationsTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        with self.connect() as conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text(encoding='utf-8'))
        self.patcher = patch.object(store, 'get_conn', self.connect)
        self.patcher.start()
        main = patch.object(routes.agent.workspace_agent_runtime, 'main_engine', return_value='claude')
        main.start(); self.addCleanup(main.stop)
        store._active.clear()
        self.cid = store.create_conversation('Example')['id']

    def tearDown(self):
        self.patcher.stop()
        for conn in self.connections: conn.close()
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        self.connections.append(conn)
        return conn

    def attachment(self, content=b'Hello', name='sample.txt'):
        return store.upload(self.cid, name, 'text/plain', content)

    def test_real_text_and_pdf_canonical_storage(self):
        attachment = self.attachment('你好'.encode())
        pdf = store.upload(self.cid, 'article.pdf', 'application/pdf', b'%PDF-example', 'Extracted text', True)
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM study_documents ORDER BY rowid').fetchall()
            self.assertEqual(json.loads(rows[0]['metadata_json'])['text'], '你好')
            self.assertIsNone(rows[0]['file'])
            self.assertEqual(rows[1]['file'], b'%PDF-example')
        context = store.begin_turn(self.cid, 'r1', 'Read this', [attachment['id'], pdf['id']], {})
        self.assertEqual(context['attachment_context'][0]['text'], '你好')
        self.assertTrue(context['attachment_context'][1]['truncated'])
        self.assertEqual(pdf['provenance'], 'browser-pdfjs-unverified')

    def test_invalid_uploads_and_secrets(self):
        cases = [('a.exe', 'text/plain', b'hello'), ('../a.txt', 'text/plain', b'hello'), ('a.txt', 'text/plain', b'\xff'), ('a.pdf', 'application/pdf', b'not pdf'), ('a.txt', 'text/plain', b'api_key: secretkey12345678'), ('a.json', 'application/json', b'{invalid')]
        for name, mime, raw in cases:
            with self.subTest(name=name, raw=raw), self.assertRaises(routes.HTTPException):
                store.upload(self.cid, name, mime, raw)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_documents').fetchone()[0], 0)

    def test_ownership_and_document_change(self):
        attachment = self.attachment()
        other = store.create_conversation()['id']
        with self.assertRaises(routes.HTTPException): store.begin_turn(other, 'r1', 'read', [attachment['id']], {})
        with self.connect() as conn: conn.execute('UPDATE study_documents SET revision=2')
        with self.assertRaises(routes.HTTPException): store.begin_turn(self.cid, 'r1', 'read', [attachment['id']], {})
        self.assertEqual(store.detail(self.cid)['messages'], [])

    def test_idempotency_history_and_payload_conflict(self):
        for index in range(5):
            turn = store.begin_turn(self.cid, str(index), 'Question '+str(index), [], {})
            self.assertLessEqual(len(turn['previous']), 3)
            store.finish_turn(self.cid, str(index), {'reply': 'Answer '+str(index)})
        replay = store.begin_turn(self.cid, '4', 'Question 4', [], {})
        self.assertEqual(replay['replay']['reply'], 'Answer 4')
        with self.assertRaises(routes.HTTPException): store.begin_turn(self.cid, '4', 'changed', [], {})
        self.assertEqual(len(store.detail(self.cid)['messages']), 10)
        turn = store.begin_turn(self.cid, '5', 'Next', [], {})
        self.assertEqual([item['request'] for item in turn['previous']], ['Question 2', 'Question 3', 'Question 4'])

    def test_pending_failed_restart_and_retry(self):
        store.begin_turn(self.cid, 'a', 'First', [], {})
        with self.assertRaises(routes.HTTPException): store.begin_turn(self.cid, 'b', 'Second', [], {})
        store._active.clear()  # Simulated server restart, no model request rerun.
        self.assertTrue(all(row['status']=='failed' for row in store.detail(self.cid)['messages']))
        with self.assertRaises(routes.HTTPException): store.begin_turn(self.cid, 'a', 'First', [], {})
        store.begin_turn(self.cid, 'b', 'Second', [], {})
        store.fail_turn(self.cid, 'b')
        self.assertTrue(all(row['status']=='failed' for row in store.detail(self.cid)['messages']))

    def test_context_bounds_and_no_text_pdf(self):
        ids = [self.attachment(b'x'*70000, str(i)+'.txt')['id'] for i in range(4)]
        turn = store.begin_turn(self.cid, 'a', 'Read', ids, {})
        contexts = turn['attachment_context']
        self.assertEqual(sum(len(item['text']) for item in contexts), 24000)
        self.assertTrue(all(item['truncated'] for item in contexts))
        pdf = store.upload(self.cid, 'scan.pdf', 'application/pdf', b'%PDF-scan')
        self.assertTrue(pdf['no_text'])

    def test_route_ignores_client_history_and_replays_without_model(self):
        body = routes.Plan(message='Hello', conversation_id=self.cid, request_id='abc', previous=[{'request':'injected', 'reply':'forged'}])
        with patch.object(routes.agent, 'plan', new=AsyncMock(return_value={'reply':'Hi'})) as generate:
            first = asyncio.run(routes.plan(body))
            second = asyncio.run(routes.plan(body))
            self.assertEqual(first, second)
            self.assertEqual(generate.await_count, 1)
            self.assertEqual(generate.call_args.args[2], [])
        self.assertTrue(all(row['status']=='succeeded' for row in store.detail(self.cid)['messages']))

    def test_model_failure_durable_and_legacy_compatible(self):
        with patch.object(routes.agent, 'plan', new=AsyncMock(side_effect=routes.agent.AgentError('Failed'))):
            with self.assertRaises(routes.HTTPException): asyncio.run(routes.plan(routes.Plan(message='Hi',conversation_id=self.cid,request_id='fail')))
        self.assertTrue(all(row['status']=='failed' for row in store.detail(self.cid)['messages']))
        with patch.object(routes.agent, 'plan', new=AsyncMock(return_value={'reply':'Legacy'})) as generate:
            self.assertEqual(asyncio.run(routes.plan(routes.Plan(message='Hi'))), {'reply':'Legacy'})
            self.assertEqual(generate.call_args.args, ('Hi', {}, []))

    def test_attachment_only_preserves_empty_user_message(self):
        attachment=self.attachment()
        body=routes.Plan(message='',conversation_id=self.cid,request_id='file-only',attachment_ids=[attachment['id']])
        with patch.object(routes.agent,'plan',new=AsyncMock(return_value={'reply':'What would you like to do?'})) as model:
            asyncio.run(routes.plan(body))
            self.assertIn('attached material',model.call_args.args[0])
        self.assertEqual(store.detail(self.cid)['messages'][0]['content'],'')
        with self.assertRaises(routes.HTTPException): asyncio.run(routes.plan(routes.Plan(message='')))

    def test_images_validated_scoped_and_passed_as_bytes(self):
        for fmt, name, mime in [('PNG','photo.png','image/png'), ('JPEG','photo.jpg','image/jpeg'), ('WEBP','photo.webp','image/webp')]:
            output = io.BytesIO()
            Image.new('RGB', (8, 6), 'red').save(output, format=fmt)
            image = store.upload(self.cid, name, mime, output.getvalue())
            self.assertEqual((image['width'], image['height']), (8, 6))
            self.assertFalse(image['no_text'])
            data, returned_mime = store.image_content(self.cid, image['id'])
            self.assertEqual(returned_mime, mime)
            with self.assertRaises(routes.HTTPException): store.image_content(store.create_conversation()['id'], image['id'])
            turn = store.begin_turn(self.cid, fmt, 'Describe', [image['id']], {})
            context = turn['attachment_context']
            self.assertEqual(context[0]['kind'], 'image')
            self.assertEqual(routes.agent._attachment_images(context), [{'data':data, 'mime':mime}])
            self.assertNotIn('image_data', routes.agent._attachment_materials(context)[0])
            store.finish_turn(self.cid, fmt, {'reply':'Done'})
        self.assertEqual(len(store.detail(self.cid)['attachments']), 3)
        self.assertEqual(store.detail(self.cid)['attachments'][0]['width'], 8)

    def test_image_rejects_bad_signature_mime_animation_and_dimensions(self):
        output = io.BytesIO()
        Image.new('RGB', (8, 6), 'red').save(output, format='PNG')
        valid = output.getvalue()
        for name, mime, raw in [('x.png','image/png',b'not image'), ('x.jpg','image/jpeg',valid), ('x.png','image/jpeg',valid), ('x.svg','image/svg+xml',b'<svg/>')]:
            with self.subTest(name=name,mime=mime), self.assertRaises(routes.HTTPException): store.upload(self.cid,name,mime,raw)
        with self.assertRaises(routes.HTTPException): store.upload(self.cid,'x.png','image/png',valid, 'supplied OCR')
        huge = io.BytesIO()
        Image.new('RGB', (8193, 1)).save(huge, format='PNG')
        with self.assertRaises(routes.HTTPException): store.upload(self.cid,'x.png','image/png',huge.getvalue())
        animated = io.BytesIO()
        Image.new('RGB', (2,2), 'red').save(animated, format='WEBP', save_all=True, append_images=[Image.new('RGB',(2,2),'blue')], duration=100,loop=0)
        with self.assertRaises(routes.HTTPException): store.upload(self.cid,'x.webp','image/webp',animated.getvalue())
        with self.assertRaises(routes.agent.AgentError): routes.agent._attachment_images([{'kind':'image','mime':'image/png','image_data':b'fake'}])

    def test_image_content_http_and_capabilities(self):
        output = io.BytesIO()
        Image.new('RGB',(2,2),'blue').save(output,format='PNG')
        image = store.upload(self.cid,'x.png','image/png',output.getvalue())
        app = FastAPI()
        app.include_router(routes.router)
        from app.services import workspace_agent_claude
        ready = {'id': 'claude', 'configured': True, 'vision': True}
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1',1234)) as client, \
                patch.object(workspace_agent_claude, 'capabilities', return_value=ready):
            caps = client.get('/workspace-agent/capabilities').json()
            self.assertTrue(caps['image_input'])
            self.assertEqual(caps['default_provider'], 'claude')
            self.assertEqual([p['id'] for p in caps['providers']], ['claude', 'deepseek', 'chatgpt'])
            path='/workspace-agent/conversations/'+self.cid+'/attachments/'+image['id']+'/content'
            response=client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['content-type'],'image/png')
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            self.assertEqual(client.get(path,headers={'origin':'https://evil.example'}).status_code,403)
            self.assertEqual(client.get(path.replace(self.cid,store.create_conversation()['id'])).status_code,404)

    def test_database_work_off_loop_and_concurrent_turn_guard(self):
        async def scenario():
            loop_thread = threading.get_ident()
            original = store.begin_turn
            thread_ids = []
            entered, release = asyncio.Event(), asyncio.Event()
            def tracked(*args):
                thread_ids.append(threading.get_ident())
                return original(*args)
            async def generate(*args, **kwargs):
                entered.set()
                await release.wait()
                return {'reply': 'done'}
            with patch.object(store, 'begin_turn', side_effect=tracked), patch.object(routes.agent, 'plan', side_effect=generate):
                first = asyncio.create_task(routes.plan(routes.Plan(message='First', conversation_id=self.cid, request_id='first')))
                await entered.wait()
                with self.assertRaises(routes.HTTPException) as error:
                    await routes.plan(routes.Plan(message='Second', conversation_id=self.cid, request_id='second'))
                self.assertEqual(error.exception.status_code, 409)
                release.set()
                await first
            self.assertTrue(all(ident != loop_thread for ident in thread_ids))
        asyncio.run(scenario())

    def test_cancel_during_begin_settles_then_marks_failed(self):
        original = store.begin_turn
        entered, release = threading.Event(), threading.Event()
        def delayed(*args):
            entered.set()
            release.wait(5)
            return original(*args)
        async def scenario():
            with patch.object(store, 'begin_turn', side_effect=delayed), patch.object(routes.agent, 'plan', new=AsyncMock()) as model:
                task = asyncio.create_task(routes.plan(routes.Plan(message='First', conversation_id=self.cid, request_id='cancel')))
                await asyncio.to_thread(entered.wait, 5)
                task.cancel()
                release.set()
                with self.assertRaises(asyncio.CancelledError): await task
                model.assert_not_called()
        asyncio.run(scenario())
        self.assertTrue(all(row['status']=='failed' for row in store.detail(self.cid)['messages']))
        self.assertNotIn((self.cid, 'cancel'), store._active)

    def test_http_multipart_and_loopback_guard(self):
        app = FastAPI()
        app.include_router(routes.router)
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)) as client:
            response = client.post('/workspace-agent/conversations/'+self.cid+'/attachments', files={'file':('a.txt',b'Actual attachment','text/plain')})
            self.assertEqual(response.status_code, 200, response.text)
            response = client.get('/workspace-agent/conversations', headers={'origin':'https://evil.example'})
            self.assertEqual(response.status_code,403)


if __name__ == '__main__': unittest.main()
