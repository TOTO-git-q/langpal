"""Reader sources (built-in + custom), Zotero and the reader MCP bridge.

Temporary SQLite only. No internet: built-in readers are fakes, and the transport
tests talk to a throwaway HTTP server on 127.0.0.1.
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.routers import reader_bridge, reader_zotero, reading as reading_routes, reading_sources as source_routes
from app.services import reading_sources as sources

SECRET = 'synthetic-source-key-123'
CUSTOM = {'name': 'My feed', 'kind': 'article', 'lang': 'en', 'format': 'rss', 'url': 'https://feeds.example.org/rss'}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / 'sources.sqlite'

        def connect():
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        self.connect = connect
        with closing(connect()) as conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
        for module in (sources, reader_zotero, reading_routes.reading_format_settings):
            patcher = patch.object(module, 'get_conn', connect)
            patcher.start()
            self.addCleanup(patcher.stop)
        reader_bridge.active = None
        self.app = FastAPI()
        for router in (source_routes.router, reading_routes.router, reader_zotero.router, reader_bridge.router):
            self.app.include_router(router, prefix='/api')

    def tearDown(self):
        reader_bridge.active = None
        self.tmp.cleanup()

    def call(self, method, path, client='127.0.0.1', host='127.0.0.1', **options):
        async def run():
            transport = httpx.ASGITransport(app=self.app, client=(client, 5000))
            async with httpx.AsyncClient(transport=transport, base_url=f'http://{host}') as http:
                return await http.request(method, '/api' + path, **options)
        return asyncio.run(run())


class Registry(Fixture):
    def test_custom_source_lifecycle_and_unified_list(self):
        created = self.call('POST', '/reader/sources', json=CUSTOM)
        self.assertEqual(created.status_code, 201, created.text)
        ident = created.json()['id']
        self.assertEqual(created.json()['connector'], 'spec')
        listed = self.call('GET', '/reader/sources').json()['items']
        self.assertEqual(listed[-1]['id'], ident)
        self.assertEqual({row['connector'] for row in listed if row['builtin'] and row['kind'] == 'article'},
                         {'feed', 'textbooks'})
        edited = self.call('PATCH', f'/reader/sources/{ident}', json={'name': 'Renamed'})
        self.assertEqual(edited.json()['name'], 'Renamed')
        order = [ident] + [row['id'] for row in listed if row['id'] != ident]
        self.assertEqual(self.call('PUT', '/reader/sources/order', json={'ids': order}).json()['items'][0]['id'], ident)
        self.assertFalse(self.call('PATCH', '/reader/sources/builtin-nasa', json={'enabled': False}).json()['enabled'])
        self.assertNotIn('builtin-nasa', [row['id'] for row in self.call('GET', '/reader/options').json()['sources']])
        self.assertEqual(self.call('PATCH', '/reader/sources/builtin-nasa', json={'url': 'https://x.example'}).status_code, 422)
        self.assertEqual(self.call('DELETE', '/reader/sources/builtin-nasa').status_code, 422)
        self.assertEqual(self.call('DELETE', f'/reader/sources/{ident}').status_code, 200)
        self.assertEqual(self.call('DELETE', f'/reader/sources/{ident}').status_code, 404)

    def test_key_is_sealed_and_only_masked(self):
        body = {**CUSTOM, 'auth': {'mode': 'header', 'name': 'X-Api-Key', 'key': SECRET}}
        created = self.call('POST', '/reader/sources', json=body)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['auth']['key_mask'], sources.KEY_MASK)
        self.assertTrue(created.json()['auth']['configured'])
        for response in (created, self.call('GET', '/reader/sources'), self.call('GET', '/reader/options')):
            self.assertNotIn(SECRET, response.text)
        with closing(self.connect()) as conn:
            self.assertNotIn(SECRET, conn.execute('SELECT value FROM reader_source_registry').fetchone()[0])
        row = sources._state()['custom'][created.json()['id']]
        self.assertEqual(sources._open(row['_secret']), SECRET)
        # Moving the source to another host drops the saved key.
        moved = self.call('PATCH', f"/reader/sources/{created.json()['id']}", json={'url': 'https://other.example/rss'})
        self.assertFalse(moved.json()['auth']['configured'])
        # Keys never travel in the URL.
        bad = {**CUSTOM, 'url': 'https://feeds.example.org/rss?api_key=abc'}
        self.assertEqual(self.call('POST', '/reader/sources', json=bad).status_code, 422)

    def test_private_network_switch_is_local_only(self):
        private = {**CUSTOM, 'url': 'http://192.168.1.20/rss', 'allow_private': True}
        with self.assertRaises(sources.SourceError):
            sources.create_source(private)  # e.g. the course concierge
        ident = sources.create_source(CUSTOM)['id']
        with self.assertRaises(sources.SourceError):
            sources.edit_source(ident, {'allow_private': True})
        sources.edit_source(ident, {'name': 'Still public'})
        with patch.dict(os.environ, {'LANGPAL_READER_REMOTE_ADMIN': '1'}):
            remote = dict(client='192.168.1.5', host='jine.lan')
            self.assertEqual(self.call('POST', '/reader/sources', json=CUSTOM, **remote).status_code, 201)
            self.assertEqual(self.call('POST', '/reader/sources', json=private, **remote).status_code, 422)
            self.assertEqual(self.call('POST', '/reader/sources/test', json={'source': private}, **remote).status_code, 422)
        self.assertEqual(self.call('POST', '/reader/sources', json=private, client='192.168.1.5', host='jine.lan').status_code, 403)
        self.assertEqual(self.call('POST', '/reader/sources', json=private).status_code, 201)
        self.assertEqual(self.call('POST', '/reader/sources', json=CUSTOM, headers={'origin': 'https://evil.example'}).status_code, 403)

    def test_remote_readers_skip_private_and_keyed_sources(self):
        private = sources.create_source({**CUSTOM, 'url': 'http://192.168.1.20/rss', 'allow_private': True}, trusted=True)
        public = sources.create_source({**CUSTOM, 'name': 'Public'})
        reached = []

        async def run(spec, query, key):
            reached.append(spec.name)
            return [{'title': spec.name, 'url': 'https://example.org/' + spec.name, 'source': spec.name, 'text': ''}]
        rows = [row for row in sources._filtered('article', 'en') if not row['builtin']]
        with patch.object(sources, '_run', run):
            result = asyncio.run(sources.collect('article', rows=rows, lang='en', include_private=False))
        self.assertEqual(reached, ['Public'])
        self.assertEqual(result['unavailable'], ['My feed'])
        self.assertEqual([item['source_id'] for item in result['items']], [public['id']])
        self.assertTrue(private['allow_private'])


class OneFetchLine(Fixture):
    def test_builtins_and_custom_go_through_collect(self):
        custom = sources.create_source({'name': 'Lab API', 'kind': 'paper', 'url': 'https://api.example.org/search',
                                        'query_param': 'q', 'fields': {'items': 'hits', 'title': 'name', 'url': 'link'}})
        news = AsyncMock(return_value={'items': [], 'unavailable': []})
        papers = AsyncMock(return_value={'items': [{'title': 'A', 'url': 'https://a', 'source': 'Crossref', 'doi': '10.1/a'}], 'unavailable': []})

        def load(spec, query, key):
            if spec.name == 'HAL':
                raise sources.SourceError('down')
            return [{'title': spec.name, 'url': 'https://example.org/' + spec.name, 'source': spec.name}]
        with patch.object(sources.reading, 'papers', papers), patch.object(sources.reading, 'news', news), \
             patch.object(sources, '_load', load):
            result = self.call('GET', '/reader/papers', params={'q': 'memory'}).json()
            self.assertEqual({item['title'] for item in result['items']}, {'A', 'DataCite', 'Lab API'})
            self.assertEqual(result['unavailable'], ['HAL'])
            self.assertEqual(sorted(papers.await_args.args[2]), ['Crossref', 'Europe PMC', 'arXiv'])
            one = self.call('GET', '/reader/papers', params={'q': 'memory', 'source': custom['id']}).json()
            self.assertEqual([item['title'] for item in one['items']], ['Lab API'])
            self.assertEqual(self.call('GET', '/reader/papers', params={'q': 'memory', 'source': 'custom-nope'}).status_code, 422)
            tested = asyncio.run(sources.test_source('builtin-crossref', None, 'x'))
            self.assertEqual(tested['count'], 1)

    def test_old_names_keep_working(self):
        with patch.object(sources, '_load', lambda spec, query, key: [{'title': 'T', 'url': 'https://t', 'source': spec.name}]):
            extra = asyncio.run(sources.collect_extra_papers('memory'))
        self.assertEqual(sorted(item['source_id'] for item in extra['items']), ['builtin-datacite', 'builtin-hal'])
        for name in ['list_sources', 'get_source', 'enabled_builtins', 'create_source', 'edit_source', 'delete_source',
                     'reorder_sources', 'collect_custom', 'collect_extra_papers', 'test_source', 'collect']:
            self.assertTrue(callable(getattr(sources, name)), name)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/redirect'):
            self.send_response(302)
            self.send_header('Location', 'http://169.254.169.254/latest/meta-data')
            self.end_headers()
        elif self.path.startswith('/huge'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'[' + b'0,' * (sources.MAX_RESPONSE // 2 + 10) + b'0]')
        else:
            body = json.dumps({'hits': [{'name': 'Local item', 'link': 'http://127.0.0.1/item'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class Transport(Fixture):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def draft(self, path, allow_private=True):
        return {'source': {'name': 'Local', 'kind': 'paper', 'url': self.base + path, 'query_param': 'q',
                           'allow_private': allow_private, 'fields': {'items': 'hits', 'title': 'name', 'url': 'link'}}}

    def test_private_addresses_blocked_without_the_switch(self):
        for url in [self.base + '/ok', 'http://10.0.0.1/', 'http://169.254.169.254/', 'http://[::1]/', 'http://0.0.0.0/']:
            draft = {'source': {**self.draft('/ok', False)['source'], 'url': url}}
            response = self.call('POST', '/reader/sources/test', json=draft)
            self.assertEqual(response.status_code, 422, url)
        self.assertIn('私有网络', self.call('POST', '/reader/sources/test', json=self.draft('/ok', False)).json()['detail'])

    def test_unsaved_draft_reaches_local_server_only_when_allowed(self):
        response = self.call('POST', '/reader/sources/test', json=self.draft('/ok'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['items'][0]['title'], 'Local item')
        self.assertTrue(all(row['builtin'] for row in sources.list_sources()))  # nothing was saved

    def test_redirects_are_not_followed_and_huge_responses_stop(self):
        redirect = self.call('POST', '/reader/sources/test', json=self.draft('/redirect'))
        self.assertEqual(redirect.status_code, 422)
        self.assertIn('302', redirect.json()['detail'])
        huge = self.call('POST', '/reader/sources/test', json=self.draft('/huge'))
        self.assertEqual(huge.status_code, 422)
        self.assertIn('过大', huge.json()['detail'])


class LocalOnlyRoutes(Fixture):
    def test_zotero_and_bridge_need_loopback_on_both_ends(self):
        for method, path in [('GET', '/reader/zotero/connection'), ('PUT', '/reader/zotero/connection'),
                             ('POST', '/reader/zotero/connection/test'), ('GET', '/reader/zotero/items'),
                             ('GET', '/reader/zotero/items/ABCD1234/pdf'), ('POST', '/reader/bridge/claim'),
                             ('POST', '/reader/bridge/poll'), ('POST', '/reader/bridge/result'),
                             ('POST', '/reader/bridge/release'), ('GET', '/reader/bridge/state'), ('POST', '/reader/bridge/call')]:
            self.assertEqual(self.call(method, path, client='192.168.1.5', host='jine.lan').status_code, 403, path)
            self.assertEqual(self.call(method, path, host='evil.example').status_code, 403, path)  # DNS rebinding
            self.assertEqual(self.call(method, path, headers={'origin': 'https://evil.example'}).status_code, 403, path)
        self.assertEqual(self.call('GET', '/reader/zotero/connection').json(), {'port': 23119, 'library': 'users/0'})
        self.assertEqual(self.call('PUT', '/reader/zotero/connection', json={'port': 23120, 'library': 'groups/7'}).status_code, 200)
        self.assertEqual(self.call('GET', '/reader/zotero/connection').json()['port'], 23120)

    def test_bridge_round_trip_like_the_mcp_process(self):
        token = self.call('POST', '/reader/bridge/claim', json={}).json()['token']
        self.assertEqual(self.call('GET', '/reader/bridge/state').status_code, 200)

        async def run():
            transport = httpx.ASGITransport(app=self.app, client=('127.0.0.1', 5000))
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1') as http:
                call = asyncio.create_task(http.post('/api/reader/bridge/call', json={'tool': 'list_shelf'}))
                commands = []
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    commands = (await http.post('/api/reader/bridge/poll', json={'token': token, 'title': 'Paper', 'page': 3})).json()['commands']
                    if commands:
                        break
                await http.post('/api/reader/bridge/result', json={'token': token, 'command': commands[0]['id'], 'result': '[]'})
                return (await call).json(), (await http.get('/api/reader/bridge/state')).json()
        result, state = asyncio.run(run())
        self.assertEqual(result, {'result': '[]'})
        self.assertEqual((state['title'], state['page'], state['writable']), ('Paper', 3, False))

    def test_main_app_guard_lets_the_local_mcp_through(self):
        import app.main as main

        async def run():
            transport = httpx.ASGITransport(app=main.app, client=('127.0.0.1', 5000))
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8787') as http:
                ok = await http.post('/api/reader/bridge/claim', json={})  # no Origin, like reader_mcp.py
                reader_bridge.active = None
                cross = await http.post('/api/reader/bridge/claim', json={}, headers={'origin': 'https://evil.example'})
                zotero = await http.get('/api/reader/zotero/connection', headers={'origin': 'http://127.0.0.1:8787'})
                return ok.status_code, cross.status_code, zotero.status_code
        self.assertEqual(asyncio.run(run()), (200, 403, 200))


if __name__ == '__main__':
    unittest.main()
