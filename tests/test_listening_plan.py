"""Concierge plans and the listening screen share database records."""
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services import workspace_agent as agent, listening_preferences as plans, course
from app.routers import listening


class ListeningPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.connections = []
        with self.connect() as conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
            conn.execute("INSERT INTO settings(key,value) VALUES('teaching_language:ja','{\"mode\":\"off\"}')")
        for module in [agent, plans, listening]:
            mock = patch.object(module, 'get_conn', self.connect); mock.start(); self.addCleanup(mock.stop)

    def tearDown(self):
        for conn in self.connections:
            conn.close()
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False); conn.row_factory = sqlite3.Row
        self.connections.append(conn)
        return conn

    def preview(self, tool, args):
        return agent.preview_operations([agent.Operation(tool=tool, args=args)], {})['proposal']

    def test_listening_plan_preview_apply_and_undo(self):
        proposal = self.preview('listening.plan', {'language':'ja','format':'ja_gist','difficulty':'foundation','topic':'书店'})
        self.assertEqual(plans.catalog()['ja']['format'], 'auto')
        agent.commit(proposal['id'], False, {})
        self.assertEqual(plans.catalog()['ja']['format'], 'ja_gist')
        self.assertEqual(plans.catalog()['ja']['difficulty'], 'foundation')
        agent.commit(proposal['id'], True, {})
        self.assertEqual(plans.catalog()['ja']['format'], 'auto')

    def test_invalid_language_format_does_not_write(self):
        with self.assertRaises((ValueError, agent.AgentError)):
            self.preview('listening.plan', {'language':'en','format':'ja_gist'})
        with self.connect() as conn:
            self.assertIsNone(conn.execute('SELECT value FROM settings WHERE key=?', (plans.PREFIX+'en',)).fetchone())


    def test_manual_plan_uses_same_record_and_validates_format(self):
        with self.connect() as conn, conn:
            plans.save(conn,'en',plans.Plan(format='en_talk',difficulty='challenge'))
        self.assertEqual(plans.catalog()['en']['format'], 'en_talk')
        with self.connect() as conn, self.assertRaises(ValueError):
            plans.save(conn,'en',plans.Plan(format='ja_gist'))


    def test_draft_uses_active_course_and_explicit_difficulty_wins(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        generate = AsyncMock(return_value={})
        exercise = SimpleNamespace(model_json_schema=lambda: {}, model_validate=lambda value: value)
        profile = SimpleNamespace(description='听主旨', speakers=1, questions=1, choices=4)
        with patch.object(listening.listening_subscription,'generate',generate), \
                patch.object(listening,'Exercise',exercise), patch.object(listening,'validate_exercise'):
            asyncio.run(listening._draft(listening.PrepareRequest(language='ja',difficulty='foundation'),profile))
            self.assertIn('使用高频词和短句',generate.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
