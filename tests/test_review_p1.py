"""The four P1 findings of the 2026-11-18 review, as the lead's acceptance checks:
1. a course whose files are gone never breaks the lesson view or course settings;
2. deleting a course removes its rows, and new course ids never repeat;
3. a stale or missing run id cannot submit into the current run;
4. LAN access needs the access code; loopback is unchanged."""
import os
import re
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tests'))

from app import db  # noqa: E402
from app.services import course  # noqa: E402
from test_course_lessons import Base, ESSAY  # noqa: E402


class GoneCourse(Base):
    def test_missing_course_files_mean_no_current_lesson(self):
        self.start()
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with patch.object(course.lessons, 'DIRECTORY', Path(empty.name)):
            course.lessons.reload()
            response = self.client.get('/api/teaching/lesson')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(response.json()['lesson'])
            self.assertEqual(self.client.get('/api/teaching/settings/en').status_code, 200)


class DeleteCourse(Base):
    def test_delete_removes_the_course_rows_and_closes_its_runs(self):
        dead, other = 'my-course-' + 'a' * 32, 'toefl-2026'
        self.start()                                        # a real run of the other course, copied below as one of the dead course
        with closing(db.get_conn()) as conn, conn:
            conn.row_factory = __import__('sqlite3').Row
            row = dict(conn.execute('SELECT * FROM course_lessons ORDER BY id DESC LIMIT 1').fetchone())
            for table, extra in (('course_lessons', None), ('course_generated', None), ('course_events', None)):
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
                self.assertIn('course_id', cols, table)
            before = {t: conn.execute(f'SELECT COUNT(*) FROM {t} WHERE course_id=?', (other,)).fetchone()[0]
                      for t in ('course_lessons', 'course_generated', 'course_events')}
            row.pop('id')
            row['course_id'] = dead
            conn.execute(f"INSERT INTO course_lessons ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        with patch.object(course.builder, 'delete', lambda course_id: None):
            response = self.client.delete('/api/teaching/build/' + dead)
        self.assertEqual(response.status_code, 200, response.text)
        with closing(db.get_conn()) as conn:
            for table in ('course_lessons', 'course_generated', 'course_events'):
                self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE course_id=?', (dead,)).fetchone()[0], 0, table)
                self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE course_id=?', (other,)).fetchone()[0], before[table], table)

    def test_new_course_ids_are_unique_and_never_the_old_numbered_ones(self):
        seen = set()
        source = (ROOT / 'backend/app/services/course/builder.py').read_text('utf-8')
        self.assertIn("'my-course-' + uuid4().hex", source)
        from uuid import uuid4
        for _ in range(50):
            ident = 'my-course-' + uuid4().hex
            self.assertRegex(ident, r'^my-course-[0-9a-f]{32}$')
            seen.add(ident)
        self.assertEqual(len(seen), 50)


class StaleRun(Base):
    def test_wrong_or_missing_run_id_is_refused_and_changes_nothing(self):
        lesson = self.start()
        good = self.run_id
        before = self.view()
        self.model()
        for body in ({'run_id': good + 99, 'text': ESSAY, 'seconds': 300}, {'text': ESSAY, 'seconds': 300}):
            response = self.client.post('/api/teaching/lesson/submit', json=body)
            self.assertIn(response.status_code, (409, 422), response.text)
            if response.status_code == 409:
                self.assertEqual(response.json()['detail'], '这节课已经换了，刷新一下再交')
        self.assertEqual(self.view(), before)
        self.assertEqual(lesson['id'], good)


class LanAccess(unittest.TestCase):
    TOKEN = 'k' * 20

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        guard = patch.object(db, 'DB_PATH', Path(self.tmp.name) / 'lan.db')
        guard.start()
        self.addCleanup(guard.stop)
        with closing(db.get_conn()) as conn, conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
        from app import main
        self.main = main

    def client(self, host, token=TOKEN):
        env = {'LANGPAL_ALLOWED_HOSTS': '192.168.1.5', 'LANGPAL_ACCESS_TOKEN': token}
        guard = patch.dict(os.environ, env)
        guard.start()
        self.addCleanup(guard.stop)
        client = TestClient(self.main.app, base_url=f'http://{host}:8787', follow_redirects=False)
        self.addCleanup(client.close)
        return client

    def test_loopback_needs_no_code(self):
        self.assertEqual(self.client('127.0.0.1').get('/api/personas').status_code, 200)

    def test_lan_without_code_is_refused(self):
        response = self.client('192.168.1.5').get('/api/personas')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], '需要访问码')

    def test_unlock_sets_the_cookie_and_then_lan_works(self):
        client = self.client('192.168.1.5')
        self.assertEqual(client.get('/unlock', params={'code': 'wrong-code-wrong-code'}).status_code, 403)
        response = client.get('/unlock', params={'code': self.TOKEN})
        self.assertEqual(response.status_code, 303)
        cookie = response.headers['set-cookie']
        for part in ('lp_access=', 'HttpOnly', 'SameSite=strict', 'Path=/', 'Max-Age=2592000'):
            self.assertIn(part.lower(), cookie.lower())
        self.assertEqual(client.get('/api/personas', cookies={'lp_access': self.TOKEN}).status_code, 200)

    def test_a_short_code_never_opens_lan(self):
        client = self.client('192.168.1.5', token='short')
        self.assertEqual(client.get('/unlock', params={'code': 'short'}).status_code, 403)
        self.assertEqual(client.get('/api/personas', cookies={'lp_access': 'short'}).status_code, 403)

    def test_hosts_not_on_the_list_stay_refused(self):
        self.assertEqual(self.client('10.0.0.9').get('/api/personas', cookies={'lp_access': self.TOKEN}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
