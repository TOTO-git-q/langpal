"""API contract and backend consumers; SQLite and fake JSON only."""
import unittest
from contextlib import closing
from datetime import timedelta
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
try:
    from .course_support import START, DatabaseFixture, course, clock, event
except ImportError:
    from course_support import START, DatabaseFixture, course, clock, event
from app.routers import teaching as routes
from app.services.learning import insights, store


class CourseAPI(DatabaseFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(routes.router, prefix='/api')
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_settings_bundle_schema_saved_library_and_progress_overview(self):
        response = self.client.get('/api/teaching/settings/ja')
        self.assertEqual(response.status_code, 200)
        bundle = response.json()
        with closing(self.connect()) as conn:
            self.assertEqual(bundle['progress'], course.planner.overview(conn, 'ja', START))
        self.assertEqual(set(bundle['teaching']), {'mode', 'preset_id'})
        saved = self.client.put('/api/teaching/settings/ja', json={'mode': 'off', 'preset': self.outline.id})
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.json()['progress']['active'])
        self.assertTrue(saved.json()['progress']['units'])




    def test_removed_routes_are_absent_and_remaining_routes_check_origin(self):
        for method, path in [('get','/progress/1'), ('get','/lesson/ja/first'), ('post','/import-outline'),
                             ('post','/workshop'), ('post','/workshop/lesson')]:
            self.assertIn(getattr(self.client, method)('/api/teaching'+path).status_code, (404,405))
        for method, path in [('get','/presets'), ('get','/settings/ja'),
                             ('put','/settings/ja'), 
                             ('get','/plan/ja'), ('post','/observe'), ('get','/lesson'), ('post','/lesson/start'),
                             ('post','/lesson/answer'), ('post','/lesson/submit'), ('post','/lesson/stop')]:
            response = getattr(self.client, method)('/api/teaching'+path, headers={'origin':'https://evil.example'})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/api/teaching/settings/ja', headers={'sec-fetch-site':'cross-site'}).status_code, 403)

    def test_today_output_lists_due_points_and_next_lesson(self):
        self.write(event(self.outline), event(self.outline, 2, context='b'))
        self.now += timedelta(days=3)
        with closing(self.connect()) as conn, conn:
            store.migrate(conn)
            target = insights.today(conn, 'ja')['steps'][-1]['target']
            self.assertEqual(target['lesson'], course.planner.overview(conn, 'ja', self.now)['next'])
