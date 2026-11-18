import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.routers import memory


class MemoryCreateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'memory.db'
        self.connections = []
        with self.connect() as conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
            conn.execute("INSERT OR REPLACE INTO personas(id,name,language) VALUES(1,'Test','ja')")
            conn.execute("INSERT OR REPLACE INTO personas(id,name,language,archived_at) VALUES(2,'Archive','ja','2020-01-01')")
        self.guard = patch.object(memory, 'get_conn', self.connect)
        self.guard.start()
        app = FastAPI(); app.include_router(memory.router, prefix='/api')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8787', headers={'Origin':'http://127.0.0.1:8787'})

    def connect(self):
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row; self.connections.append(conn); return conn

    async def asyncTearDown(self):
        await self.client.aclose(); self.guard.stop()
        for conn in self.connections: conn.close()
        self.temp.cleanup()

    async def test_create_and_reload_real_record(self):
        response = await self.client.post('/api/memory', json={'persona_id':1,'category':'preference','content':'  雨の日はコーヒーが好き。  ','active':True})
        self.assertEqual(response.status_code,201)
        item = response.json(); self.assertEqual(item['content'],'雨の日はコーヒーが好き。')
        self.assertTrue(item['active']); self.assertIsNone(item['source_session_id'])
        listing = (await self.client.get('/api/memory?persona_id=1')).json()['items']
        self.assertEqual(listing,[item])

    async def test_invalid_content_and_category_never_write(self):
        for extra in [{'content':' \n '},{'category':'made-up'},{'content':'x'*4001},{'source_session_id':123}]:
            response = await self.client.post('/api/memory',json={'persona_id':1,'content':'test',**extra})
            self.assertEqual(response.status_code,422)
        self.assertEqual((await self.client.get('/api/memory')).json()['items'],[])

    async def test_missing_or_archived_persona_rejected(self):
        for ident in [2,999]:
            response = await self.client.post('/api/memory',json={'persona_id':ident,'content':'test'})
            self.assertEqual(response.status_code,404)

    async def test_cross_site_create_rejected(self):
        response = await self.client.post('/api/memory',json={'persona_id':1,'content':'test'},headers={'Origin':'https://unrelated.test'})
        self.assertEqual(response.status_code,403)
        self.assertEqual((await self.client.get('/api/memory')).json()['items'],[])


if __name__ == '__main__': unittest.main()
