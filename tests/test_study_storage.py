"""Isolated temporary SQLite tests: never import the application startup."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services import study_storage as store
from app.routers.study_storage import router


class StudyStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'study.sqlite'
        def connect():
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.connect = connect
        with closing(connect()) as conn:
            # A pre-existing unrelated record survives additive and repeated schema.
            conn.execute('CREATE TABLE old_data (value TEXT)')
            conn.execute("INSERT INTO old_data VALUES ('keep')")
            conn.commit()
            schema = (ROOT / 'backend/db/schema.sql').read_text('utf-8')
            conn.executescript(schema)
            conn.executescript(schema)
        self.patch = patch.object(store, 'get_conn', connect)
        self.patch.start()
        self.app = FastAPI()
        self.app.include_router(router, prefix='/api')
        self.client = TestClient(self.app)
        self.prefix = '/api/study-storage'
        self.doc = {'id': 'https://example.org/paper/a?x=1#scope/test', 'title': 'Test', 'text': 'Reading text', 'page': 1}

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.tmp.cleanup()

    def put_doc(self, metadata=None, rev=0, blob=b'%PDF-1.7\ntest', imp=False):
        return self.client.post(self.prefix+'/document', data={'metadata': json.dumps(metadata or self.doc), 'revision': str(rev), 'importOnly': str(imp).lower()}, files={'file': ('paper.pdf', blob, 'application/pdf')} if blob is not None else None)

    def put_note(self, id='n1', text='Note', rev=0, imp=False):
        return self.client.put(self.prefix+'/annotation', json={'documentId': self.doc['id'], 'annotation': {'id': id, 'text': text, 'page': 1}, 'revision': rev, 'importOnly': imp})

    def test_roundtrip_reopen_pdf_annotations_notes_drafts(self):
        self.assertEqual(self.put_doc().status_code, 200)
        self.assertEqual(self.put_note().status_code, 200)
        self.assertEqual(self.client.put(self.prefix+'/listening-notes', json={'text': 'Listen', 'revision': 0}).status_code, 200)
        draft = {'answers': [['q0', '1']], 'time': 3.5, 'phase': 2}
        self.assertEqual(self.client.put(self.prefix+'/listening-draft', json={'id': 'practice#1', 'draft': draft}).status_code, 200)
        # New client and fresh connection each call simulate a reopened process.
        self.client.close()
        self.client = TestClient(self.app)
        self.assertEqual(self.client.get(self.prefix+'/document', params={'id': self.doc['id']}).json()['metadata'], self.doc)
        self.assertEqual(self.client.get(self.prefix+'/document/file', params={'id': self.doc['id']}).content, b'%PDF-1.7\ntest')
        self.assertEqual(self.client.get(self.prefix+'/annotations', params={'documentId': self.doc['id']}).json()['annotations'][0]['text'], 'Note')
        self.assertEqual(self.client.get(self.prefix+'/listening-notes').json()['text'], 'Listen')
        self.assertEqual(self.client.get(self.prefix+'/listening-draft', params={'id': 'practice#1'}).json()['draft'], draft)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT value FROM old_data').fetchone()[0], 'keep')

    def test_revisions_import_idempotency_and_tombstones(self):
        self.assertEqual(self.put_doc().json()['revision'], 1)
        self.assertEqual(self.put_doc(rev=0).status_code, 409)
        same = self.put_doc(imp=True).json()
        self.assertFalse(same['imported']); self.assertFalse(same['conflict'])
        changed = self.put_doc(metadata={**self.doc, 'title': 'Old'}, imp=True).json()
        self.assertTrue(changed['conflict']); self.assertEqual(changed['metadata']['title'], 'Test')
        self.put_note()
        self.assertEqual(self.put_note(text='New', rev=1).json()['revision'], 2)
        self.assertEqual(self.put_note(text='Stale', rev=1).status_code, 409)
        self.assertEqual(self.client.delete(self.prefix+'/annotation', params={'documentId': self.doc['id'], 'id': 'n1', 'revision': 2}).status_code, 200)
        imported = self.put_note(imp=True).json()
        self.assertTrue(imported['deleted']); self.assertTrue(imported['conflict'])
        self.assertEqual(self.client.get(self.prefix+'/annotations', params={'documentId': self.doc['id']}).json()['annotations'], [])

    def test_atomic_distinct_annotations_and_same_revision_race(self):
        store.save_document(self.doc)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: store.save_annotation(self.doc['id'], {'id': str(i), 'text': 'text'}), range(20)))
        self.assertEqual(len(store.list_annotations(self.doc['id'])), 20)
        def write(text):
            try:
                store.save_state('listening-notes', 'global', text)
                return 200
            except Exception as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ['one', 'two']))
        self.assertEqual(sorted(results), [200, 409])

    def test_input_limits_and_missing_ids(self):
        self.assertEqual(self.client.get(self.prefix+'/document', params={'id': 'missing'}).status_code, 404)
        self.assertEqual(self.put_note().status_code, 404)
        self.assertEqual(self.put_doc(blob=b'not a pdf').status_code, 422)
        self.assertEqual(self.put_doc(metadata={'id': 'x'*2049}).status_code, 422)
        self.assertEqual(self.client.put(self.prefix+'/listening-notes', json={'text': 'x'*20001}).status_code, 422)
        self.assertEqual(self.client.put(self.prefix+'/listening-notes', json={'text': '', 'revision': True}).status_code, 422)
        self.assertEqual(self.client.put(self.prefix+'/listening-draft', json={'id': 'x', 'draft': {'phase': 5}}).status_code, 422)
        self.assertEqual(self.client.put(self.prefix+'/listening-notes', content=b'{}', headers={'content-length': str(store.MAX_JSON+1)}).status_code, 413)
        with patch.object(store, 'MAX_JSON', 64):
            self.assertEqual(self.client.put(self.prefix+'/listening-notes', content=b'x'*65).status_code, 413)
        with patch.object(store, 'MAX_PDF', 10):
            self.assertEqual(self.put_doc(blob=b'%PDF-'+b'a'*20).status_code, 413)

    def test_metadata_update_preserves_pdf_and_state_import_never_overwrites(self):
        self.put_doc()
        result = self.put_doc(metadata={**self.doc, 'page': 2}, rev=1, blob=None)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['hasFile'])
        self.assertEqual(store.get_file(self.doc['id']), b'%PDF-1.7\ntest')
        for kind, id, original, old in [('listening-notes', 'global', 'Newer', 'Older'), ('listening-draft', 'practice', {'phase': 3}, {'phase': 1})]:
            store.save_state(kind, id, original)
            imported = store.save_state(kind, id, old, import_only=True)
            self.assertFalse(imported['imported']); self.assertTrue(imported['conflict'])
            same = store.save_state(kind, id, original, import_only=True)
            self.assertFalse(same['conflict'])
            self.assertEqual(imported['revision'], 1)

    def test_storage_failure_never_reports_saved(self):
        with patch.object(store, 'get_conn', side_effect=PermissionError('database directory is read-only')):
            with TestClient(self.app, raise_server_exceptions=False) as client:
                response = client.put(self.prefix+'/listening-notes', json={'text': 'unsaved'})
                self.assertEqual(response.status_code, 500)
        self.assertEqual(store.get_state('listening-notes', 'global')['revision'], 0)

    def test_all_routes_reject_cross_origin_before_parsing(self):
        for method, path in [('get','/capabilities'),('get','/documents'),('get','/document?id=x'),('get','/document/file?id=x'),('post','/document'),('get','/annotations?documentId=x'),('put','/annotation'),('delete','/annotation?documentId=x&id=n&revision=1'),('get','/listening-notes'),('put','/listening-notes'),('get','/listening-draft?id=x'),('put','/listening-draft'),('get','/export'),('post','/restore'),
                             ('delete','/document?id=x&revision=1'),('delete','/listening-draft?id=x')]:
            response = getattr(self.client, method)(self.prefix+path, headers={'origin': 'https://evil.example'})
            self.assertEqual(response.status_code, 403, path)
        self.assertEqual(self.client.get(self.prefix+'/capabilities', headers={'sec-fetch-site': 'same-site'}).status_code, 403)
        self.assertEqual(self.client.get(self.prefix+'/capabilities', headers={'origin': 'http://testserver'}).status_code, 200)

    def test_delete_document_removes_pdf_and_annotations(self):
        self.put_doc(); self.put_note('n1'); self.put_note('n2')
        self.client.delete(self.prefix+'/annotation', params={'documentId': self.doc['id'], 'id': 'n2', 'revision': 1})
        other = {**self.doc, 'id': 'other'}
        self.put_doc(other)
        url = self.prefix+'/document'
        self.assertEqual(self.client.delete(url, params={'id': self.doc['id'], 'revision': 7}).status_code, 409)
        response = self.client.delete(url, params={'id': self.doc['id'], 'revision': 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['annotations'], 2)  # the tombstone goes too
        self.assertEqual(self.client.get(url, params={'id': self.doc['id']}).status_code, 404)
        self.assertEqual(self.client.get(url+'/file', params={'id': self.doc['id']}).status_code, 404)
        self.assertEqual([row['metadata']['id'] for row in store.list_documents()], ['other'])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_annotations').fetchone()[0], 0)
        self.assertEqual(self.client.delete(url, params={'id': self.doc['id'], 'revision': 1}).status_code, 404)
        # Re-importing the same ID afterwards starts a fresh record.
        self.assertEqual(self.put_doc().json()['revision'], 1)

    def test_delete_document_refuses_agent_attachment(self):
        self.put_doc()
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO workspace_conversations VALUES ('c','t','now','now')")
            conn.execute("INSERT INTO workspace_attachments VALUES ('a','c',?,'n','application/pdf',1,'p',0,0,0,'d','now')", (self.doc['id'],))
        response = self.client.delete(self.prefix+'/document', params={'id': self.doc['id'], 'revision': 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(store.list_documents()), 1)

    def test_delete_listening_draft(self):
        self.client.put(self.prefix+'/listening-draft', json={'id': 'p', 'draft': {'phase': 1}})
        self.assertEqual(self.client.delete(self.prefix+'/listening-draft', params={'id': 'p'}).status_code, 200)
        self.assertIsNone(self.client.get(self.prefix+'/listening-draft', params={'id': 'p'}).json()['draft'])
        self.assertEqual(self.client.delete(self.prefix+'/listening-draft', params={'id': 'p'}).status_code, 404)

    def test_export_restore_portable_insert_only(self):
        self.put_doc(); self.put_note()
        store.save_state('listening-notes', 'global', 'Notes')
        archive = self.client.get(self.prefix+'/export')
        self.assertEqual(archive.status_code, 200)
        first = store.restore_archive(archive.content)
        self.assertEqual(first, {'imported': 0, 'skipped': 3, 'conflicts': 0})
        store.save_state('listening-notes', 'global', 'Newer', 1)
        second = store.restore_archive(archive.content)
        self.assertEqual(second['conflicts'], 1)
        self.assertEqual(store.get_state('listening-notes', 'global')['text'], 'Newer')
        self.path = Path(self.tmp.name)/'restored.sqlite'
        with closing(self.connect()) as conn:
            conn.executescript((ROOT/'backend/db/schema.sql').read_text('utf-8'))
        self.assertEqual(store.restore_archive(archive.content)['imported'], 3)
        self.assertEqual(store.get_file(self.doc['id']), b'%PDF-1.7\ntest')
        self.assertEqual(store.list_annotations(self.doc['id'])[0]['text'], 'Note')

    def archive(self, manifest, extras=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            for name, data in (extras or {}).items(): archive.writestr(name, data)
        return output.getvalue()

    def test_restore_rejects_paths_corruption_duplicates_and_rolls_back(self):
        manifest = {'format':'langpal-study', 'version':1, 'documents':[], 'annotations':[], 'state':[]}
        for raw in [b'not zip', self.archive(manifest, {'../escape.pdf': b'bad'}), self.archive([])]:
            self.assertEqual(self.client.post(self.prefix+'/restore', content=raw).status_code, 422)
        bad = {**manifest, 'documents':[{'id':'one','metadata_json':'{"id":"one"}'}], 'annotations':[{'document_id':'missing','id':'n','payload_json':'{"id":"n"}','deleted':0}]}
        self.assertEqual(self.client.post(self.prefix+'/restore', content=self.archive(bad)).status_code, 422)
        self.assertEqual(store.list_documents(), [])
        blob = b'%PDF-file'; digest = hashlib.sha256(blob).hexdigest()
        bad = {**manifest, 'documents':[{'id':'one','metadata_json':'{"id":"one"}', 'file': {'name':'pdf/'+digest+'.pdf', 'sha256':digest}}]}
        self.assertEqual(self.client.post(self.prefix+'/restore', content=self.archive(bad, {'pdf/'+digest+'.pdf':b'%PDF-corrupt'})).status_code, 422)
        with patch.object(store, 'MAX_ARCHIVE', 20):
            self.assertEqual(self.client.post(self.prefix+'/restore', content=self.archive(manifest)).status_code, 413)

    def test_archive_duplicate_members_and_expansion_limit(self):
        import warnings
        manifest = {'format':'langpal-study', 'version':1, 'documents':[], 'annotations':[], 'state':[]}
        output = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(output, 'w') as archive:
                archive.writestr('manifest.json', json.dumps(manifest))
                archive.writestr('manifest.json', json.dumps(manifest))
        self.assertEqual(self.client.post(self.prefix+'/restore', content=output.getvalue()).status_code, 413)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', b' '*10000)
        self.assertLess(len(output.getvalue()), 2000)
        with patch.object(store, 'MAX_ARCHIVE', 2000):
            self.assertEqual(self.client.post(self.prefix+'/restore', content=output.getvalue()).status_code, 413)


if __name__ == '__main__':
    unittest.main()
