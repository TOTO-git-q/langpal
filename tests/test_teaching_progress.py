"""Planner, event persistence, completion hooks and retained settings."""
import json
import unittest
from contextlib import closing
from datetime import timedelta
from unittest.mock import patch
try:
    from .course_support import START, DatabaseFixture, course, clock, event
except ImportError:
    from course_support import START, DatabaseFixture, course, clock, event


class PlannerTests(DatabaseFixture, unittest.TestCase):
    def overview(self):
        with closing(self.connect()) as conn:
            return course.planner.overview(conn, 'ja', self.now)





    def test_paused_course_has_units_zero_counts_no_next_and_v1_is_inactive(self):
        with closing(self.connect()) as conn, conn:
            course.save_language_settings(conn, 'ja', course.Teaching(mode='off', preset=self.outline.id))
        paused = self.overview()
        self.assertFalse(paused['active'])
        self.assertTrue(paused['units'])
        self.assertEqual(sum(paused['counts'].values()), 0)
        self.assertIsNone(paused['next'])

    def test_missing_language_setting_does_not_use_persona_course(self):
        with closing(self.connect()) as conn, conn:
            conn.execute('DELETE FROM settings WHERE key=?', ('teaching_language:ja',))
            conn.execute('UPDATE personas SET profile_json=? WHERE id=1',
                         (json.dumps({'teaching': {'mode': 'ambient', 'outline': self.outline.model_dump()}}),))
            self.assertEqual(course.language_settings(conn, 'ja'), course.Teaching())
        self.assertIsNone(self.overview()['course'])

    def test_ledger_is_lazy_idempotent_and_promotes_offer_to_verified_result(self):
        row = event(self.outline, ref='run42')
        self.assertEqual(self.write(row), 1)
        self.assertEqual(self.write(row), 0)
        self.assertEqual(self.write({**row, 'result': 'success'}), 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['result'], 'success')
        with closing(self.connect()) as conn:
            course.ledger.ensure(conn)
            self.assertTrue(conn.execute("SELECT 1 FROM sqlite_master WHERE name='course_events'").fetchone())

    def test_unit_completion_hook_only_on_transition(self):
        with patch('app.services.hooks.emit_soon') as emit:
            for p in range(len(self.units[0].points)):
                self.write(event(self.outline, p*4+1, point=p), event(self.outline, p*4+2, point=p, context='b'),
                           event(self.outline, p*4+3, point=p, context='c', at=START+timedelta(days=3)),
                           event(self.outline, p*4+4, point=p, context='d', at=START+timedelta(days=1000)))
            emit.assert_called_once_with('course.unit_completed', None, {
                'unit_id': self.units[0].id, 'title': self.units[0].title, 'language': 'ja'})
            self.write(event(self.outline, 99, context='d', at=START+timedelta(days=4)))
            self.assertEqual(emit.call_count, 1)

