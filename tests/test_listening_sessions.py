"""Offline persistence tests: temporary SQLite only; no app lifespan/providers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'backend/app').exists():
    ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.routers import listening
from app.services import listening_sessions as store
from app.services.listening_formats import Exercise, FORMATS


class ListeningSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sessions.sqlite'
        def connect():
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.connect = connect
        self.schema = (ROOT / 'backend/db/schema.sql').read_text('utf-8')
        with closing(connect()) as conn:
            conn.executescript(self.schema)
        self.patcher = patch.object(store, 'get_conn', connect)
        self.patcher.start()
        notebook = patch.object(listening.listening_errors, 'get_conn', connect)
        notebook.start()
        self.addCleanup(notebook.stop)
        listening._prepared.clear()
        self.exercise = Exercise.model_validate({
            'title': 'Secret title', 'script': [{'speaker': 'A', 'text': 'Secret transcript.'}],
            'questions': [{'prompt': 'Choose a response', 'choices': ['Yes indeed', 'No thanks', 'Not now', 'Tomorrow morning'],
                           'answer': 1, 'evidence': [1], 'explanation': 'Secret explanation'}]})
        self.profile = FORMATS['en_response']
        self.meta = dict(id='one', language='en', format=self.profile.label, count=1, preview=None,
                         difficulty='foundation', difficulty_label='Foundation')
        app = FastAPI()
        app.include_router(listening.router, prefix='/api')
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        listening._prepared.clear()
        self.patcher.stop()
        self.tmp.cleanup()

    def seed(self, identifier='one', audio=b'RIFF-test-audio'):
        store.create(identifier, self.exercise, self.profile, audio, [{'start': 0, 'end': 1}],
                     {**self.meta, 'id': identifier})

    def submit(self, selection=1):
        response = self.client.post('/api/listening/practice/one/grade', json={'selections': [selection]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_restart_safe_metadata_audio_and_no_early_answers(self):
        self.seed()
        listing = self.client.get('/api/listening/practices').json()['items']
        self.assertEqual(listing[0]['status'], 'ready')
        detail = self.client.get('/api/listening/practice/one').json()
        self.assertIsNone(detail['receipt'])
        self.assertEqual(detail['difficulty'], 'foundation')
        for secret in ['Secret', 'answer', 'explanation', 'script']:
            self.assertNotIn(secret, json.dumps(listing + [detail]))
        self.assertNotIn('marks', listing[0])
        shape = self.client.get('/api/listening/practice/one/shape').json()
        self.assertEqual(shape, {'segments': [{'start': 0, 'end': 1, 'speaker': 'A', 'female': True}], 'duration': 1})
        self.assertEqual(self.client.get('/api/listening/practice/one/audio').content, b'RIFF-test-audio')
        listening._prepared.clear()
        questions = self.client.get('/api/listening/practice/one/questions').json()
        self.assertNotIn('answer', json.dumps(questions))
        self.assertEqual(questions['questions'][0]['prompt'], 'Choose a response')

    def test_all_correct_receipt_is_immutable_and_recovered(self):
        self.seed()
        first = self.submit()
        self.assertEqual(first['score'], 1)
        self.assertEqual(first['saved_errors'], 0)
        self.assertEqual(first['receipt_kind'], 'first_submission')
        listening._prepared.clear()
        self.assertEqual(self.submit(0), first)
        self.assertEqual(self.client.get('/api/listening/practice/one').json()['receipt'], first)
        recent = self.client.get('/api/listening/practices').json()['items'][0]
        self.assertEqual((recent['status'], recent['score'], recent['marks']), ('graded', 1, [True]))
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM listening_errors').fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE listening_sessions SET receipt_json='{}' WHERE id='one'")

    def test_wrong_first_answer_and_notebook_survive_repeat_and_schema(self):
        self.seed()
        first = self.submit(0)
        self.assertEqual(first['saved_errors'], 1)
        self.assertEqual(self.submit(1), first)
        with closing(self.connect()) as conn:
            before = tuple(conn.execute('SELECT * FROM listening_errors').fetchone())
            conn.executescript(self.schema)
            self.assertEqual(tuple(conn.execute('SELECT * FROM listening_errors').fetchone()), before)
            self.assertEqual(conn.execute('SELECT audio FROM listening_error_sets').fetchone()[0], b'RIFF-test-audio')

    def test_concurrent_first_grade_returns_same_receipt(self):
        self.seed()
        def submit(choice):
            with TestClient(self.client.app) as client:
                response = client.post('/api/listening/practice/one/grade', json={'selections': [choice]})
                self.assertEqual(response.status_code, 200, response.text)
                return response.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(submit, [0, 1]))
        self.assertEqual(receipts[0], receipts[1])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM listening_errors').fetchone()[0], receipts[0]['saved_errors'])

    def test_notebook_failure_rolls_back_receipt(self):
        self.seed()
        with closing(self.connect()) as conn:
            conn.executescript("""CREATE TRIGGER fail_notebook BEFORE INSERT ON listening_errors
                                BEGIN SELECT RAISE(ABORT, 'injected failure'); END;""")
        response = self.client.post('/api/listening/practice/one/grade', json={'selections': [0]})
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(store.metadata('one')['receipt'])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM listening_error_sets').fetchone()[0], 0)
            conn.executescript('DROP TRIGGER fail_notebook;')
        self.assertEqual(self.submit(0)['saved_errors'], 1)

    def test_ungraded_practice_is_never_evicted_and_error_says_where_to_clean(self):
        self.seed()
        with patch.object(store, 'MAX_SESSIONS', 1):
            with self.assertRaises(store.CapacityError): store.check_capacity()
            with self.assertRaises(store.CapacityError) as caught: self.seed('two')
            self.assertIn('删除', str(caught.exception))
        with patch.object(store, 'MAX_STORAGE_BYTES', 1):
            with self.assertRaises(store.CapacityError): self.seed('three')
        with patch.object(store, 'MAX_SESSION_BYTES', 1):
            with self.assertRaises(store.CapacityError): self.seed('huge')
        self.assertEqual([item['id'] for item in store.recent()], ['one'])
        self.assertEqual(store.load('one')[2], b'RIFF-test-audio')

    def test_full_storage_evicts_oldest_graded_and_keeps_notebook_audio(self):
        self.seed()
        self.submit(0)  # wrong: notebook keeps its own copy of the audio
        self.seed('two')  # ungraded, may still be in progress
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO study_state VALUES ('listening-draft','one','{}',1)")
        with patch.object(store, 'MAX_SESSIONS', 2):
            store.check_capacity()
            self.assertEqual(store.create('three', self.exercise, self.profile, b'new', [], {**self.meta, 'id': 'three'}), ['one'])
            with self.assertRaises(store.CapacityError): self.seed('four')  # only ungraded work left
        self.assertEqual({item['id'] for item in store.recent()}, {'two', 'three'})
        self.assertEqual(self.client.get('/api/listening/errors/one/audio').content, b'RIFF-test-audio')
        self.assertEqual(len(self.client.get('/api/listening/errors').json()['items']), 1)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_state').fetchone()[0], 0)

    def test_byte_limit_evicts_by_actual_size_not_double(self):
        audio = 100_000
        self.seed('one', b'x' * audio)
        self.submit(1)  # all correct: no notebook copy
        listing = self.client.get('/api/listening/practices').json()
        size = listing['items'][0]['size_bytes']
        self.assertGreater(size, audio)
        self.assertLess(size, audio * 1.1)
        self.assertEqual(listing['storage']['used_bytes'], size)
        self.assertEqual(listing['storage']['count'], 1)
        with closing(self.connect()) as conn:
            self.assertLess(conn.execute('SELECT reserved_bytes FROM listening_sessions').fetchone()[0], audio * 1.1)
        # The new row needs itself, a possible notebook copy and the receipt; the old one must go.
        with patch.object(store, 'MAX_STORAGE_BYTES', size + 2 * audio + store.GRADE_RESERVE):
            self.assertEqual(store.create('two', self.exercise, self.profile, b'y' * audio, [], {**self.meta, 'id': 'two'}), ['one'])
        self.assertEqual([item['id'] for item in store.recent()], ['two'])

    def test_delete_practice_keeps_mistakes_and_frees_cache(self):
        self.seed()
        self.submit(0)
        self.assertIn('one', listening._prepared)
        self.assertEqual(self.client.delete('/api/listening/practice/one', headers={'origin': 'https://evil.example'}).status_code, 403)
        response = self.client.delete('/api/listening/practice/one')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['storage']['count'], 0)
        self.assertNotIn('one', listening._prepared)
        self.assertEqual(self.client.get('/api/listening/practice/one').status_code, 404)
        self.assertEqual(self.client.get('/api/listening/practice/one/audio').status_code, 404)
        self.assertEqual(self.client.delete('/api/listening/practice/one').status_code, 404)
        self.assertEqual(self.client.get('/api/listening/errors/one/audio').content, b'RIFF-test-audio')

    def test_unreadable_practice_is_listed_and_can_be_deleted(self):
        self.seed()
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE listening_sessions SET version=99 WHERE id='one'")
        item, = self.client.get('/api/listening/practices').json()['items']
        self.assertEqual((item['id'], item['status']), ('one', 'unreadable'))
        self.assertEqual(self.client.delete('/api/listening/practice/one').status_code, 200)

    def test_delete_mistake_set_removes_audio_and_review_history(self):
        self.seed()
        self.submit(0)
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO review_states(kind,item_id,item_index) VALUES ('listening','one',0)")
        self.assertEqual(self.client.delete('/api/listening/errors/one', headers={'origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.delete('/api/listening/errors/one').status_code, 200)
        self.assertEqual(self.client.get('/api/listening/errors').json()['items'], [])
        self.assertEqual(self.client.get('/api/listening/errors/one/audio').status_code, 404)
        self.assertEqual(self.client.delete('/api/listening/errors/one').status_code, 404)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM review_states').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM listening_error_sets').fetchone()[0], 0)
        self.assertEqual(store.metadata('one')['status'], 'graded')  # the practice itself stays

    def test_preflight_capacity_stops_generation(self):
        self.seed()
        draft = AsyncMock(return_value=self.exercise)
        with patch.object(store, 'MAX_SESSIONS', 1), patch.object(listening.languages, 'catalog', return_value=['en']), \
             patch.object(listening.listening_settings, 'load', return_value=(None, None)), \
             patch.object(listening.listening_tts, 'configured_synthesis', return_value=object()), \
             patch.object(listening, '_draft', draft):
            response = self.client.post('/api/listening/practice', json={'language': 'en', 'format': 'en_response'})
        self.assertEqual(response.status_code, 507)
        draft.assert_not_awaited()

    def test_prepare_commits_snapshot_before_response(self):
        with patch.object(listening.languages, 'catalog', return_value=['en']), \
             patch.object(listening.listening_settings, 'load', return_value=(None, None)), \
             patch.object(listening.listening_tts, 'configured_synthesis', return_value=object()), \
             patch.object(listening.listening_tts, 'synthesize', return_value=b'audio'), \
             patch.object(listening, '_draft', AsyncMock(return_value=self.exercise)):
            response = self.client.post('/api/listening/practice', json={'language': 'en', 'format': 'en_response', 'difficulty': 'challenge'})
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()['id']
        self.assertEqual(store.metadata(identifier)['difficulty'], 'challenge')
        listening._prepared.clear()
        self.assertEqual(self.client.get(f'/api/listening/practice/{identifier}/audio').content, b'audio')

    def test_oversize_generation_does_not_return_or_cache_unsaved_session(self):
        with patch.object(listening.languages, 'catalog', return_value=['en']), \
             patch.object(listening.listening_settings, 'load', return_value=(None, None)), \
             patch.object(listening.listening_tts, 'configured_synthesis', return_value=object()), \
             patch.object(listening.listening_tts, 'synthesize', return_value=b'audio'), \
             patch.object(listening, '_draft', AsyncMock(return_value=self.exercise)), \
             patch.object(store, 'MAX_SESSION_BYTES', 1):
            response = self.client.post('/api/listening/practice', json={'language': 'en', 'format': 'en_response'})
        self.assertEqual(response.status_code, 507)
        self.assertEqual(store.recent(), [])
        self.assertEqual(len(listening._prepared), 0)

    def test_concurrent_capacity_checks_cannot_overfill(self):
        def create(identifier):
            try:
                self.seed(identifier)
                return True
            except store.CapacityError:
                return False
        with patch.object(store, 'MAX_SESSIONS', 1), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ['one', 'two']))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(store.recent()), 1)

    def test_cache_eviction_and_expiry_do_not_delete_sessions(self):
        for index in range(8):
            self.seed(str(index))
            self.assertEqual(self.client.get(f'/api/listening/practice/{index}/audio').status_code, 200)
        self.assertLessEqual(len(listening._prepared), listening._max_cached)
        for prepared in listening._prepared.values():
            prepared.expires_at = 0
        self.assertEqual(self.client.get('/api/listening/practice/0/audio').status_code, 200)
        self.assertEqual(len(store.recent()), 8)
        self.assertEqual(len(store.recent('ja')), 0)
        self.assertEqual(len(store.recent('en', 2)), 2)

    def test_unknown_version_and_bad_snapshot_preserve_records(self):
        self.seed()
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE listening_sessions SET version=99 WHERE id='one'")
        self.assertEqual(self.client.get('/api/listening/practice/one').status_code, 409)
        self.assertEqual(self.client.get('/api/listening/practice/one/audio').status_code, 409)
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE listening_sessions SET version=1, payload_json='{' WHERE id='one'")
        self.assertEqual(self.client.get('/api/listening/practice/one/audio').status_code, 409)
        self.assertEqual(len(store.recent()), 1)

    def test_cross_origin_rejected_before_storage(self):
        with patch.object(store, 'get_conn', side_effect=AssertionError('must not touch storage')):
            for path in ['/practices', '/practice/one', '/practice/one/audio', '/practice/one/questions']:
                self.assertEqual(self.client.get('/api/listening' + path, headers={'origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/listening/practices?limit=51').status_code, 422)
        self.assertEqual(self.client.get('/api/listening/practice/missing').status_code, 404)

    def test_invalid_selections_do_not_create_receipt(self):
        self.seed()
        for selections in [[True], [9], [], [1, 2]]:
            self.assertEqual(self.client.post('/api/listening/practice/one/grade', json={'selections': selections}).status_code, 422)
        self.assertIsNone(store.metadata('one')['receipt'])


if __name__ == '__main__':
    unittest.main()
