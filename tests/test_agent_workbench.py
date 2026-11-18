"""Offline tests: staged modules, temporary SQLite only, no network/model use."""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
SOURCE = Path(os.environ.get('LANGPAL_SOURCE_ROOT', ROOT.parent))
MODULES = ROOT if (ROOT/'backend/app/services/workspace_agent.py').exists() else SOURCE
sys.path.insert(0, str(SOURCE/'backend'))
from app.services import workspace_agent as existing
import app.services
spec = importlib.util.spec_from_file_location('app.services.workspace_agent', MODULES/'backend/app/services/workspace_agent.py')
agent = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = agent
spec.loader.exec_module(agent)
app.services.workspace_agent = agent
spec = importlib.util.spec_from_file_location('app.routers.workspace_agent', MODULES/'backend/app/routers/workspace_agent.py')
router = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = router
spec.loader.exec_module(router)

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.connections=[]
        self.folder = tempfile.TemporaryDirectory()
        self.db = Path(self.folder.name)/'test.db'
        with self.connect() as conn: conn.executescript((SOURCE/'backend/db/schema.sql').read_text(encoding='utf-8'))
        self.patch = patch.object(agent,'get_conn',self.connect)
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        for conn in self.connections: conn.close()
        self.folder.cleanup()
    def connect(self):
        conn=sqlite3.connect(self.db); conn.row_factory=sqlite3.Row; self.connections.append(conn); return conn
    def value(self):
        with self.connect() as conn:
            row=conn.execute('SELECT value FROM settings WHERE key=?',(agent.reading_style.STYLE_KEY,)).fetchone()
            return json.loads(row[0]) if row else None
    def preview(self, args):
        return router.preview(router.Preview(operations=[{'tool':'reading.style','args':args}]))['proposal']
    def test_preview_apply_idempotency_and_undo(self):
        with patch.object(agent.workspace_agent_runtime,'generate',side_effect=AssertionError('model called')):
            proposal=self.preview({'size':20,'theme':'paper'})
        self.assertIsNone(self.value())
        result=agent.commit(proposal['id'],False,{})
        self.assertEqual(result['status'],'applied'); self.assertEqual(self.value()['size'],20)
        agent.commit(proposal['id'],False,{})
        agent.commit(proposal['id'],True,{})
        self.assertIsNone(self.value())
    def test_conflict_preserves_external_change(self):
        proposal=self.preview({'size':20})
        with self.connect() as conn:
            conn.execute('INSERT INTO settings VALUES (?,?)',(agent.reading_style.STYLE_KEY,'{"size":22}'))
        with self.assertRaises(agent.Conflict): agent.commit(proposal['id'],False,{})
        self.assertEqual(self.value(),{'size':22})
    def test_invalid_and_unknown_operations_leave_no_writes(self):
        for op in [{'tool':'reading.style','args':{'size':99}}, {'tool':'shell.exec','args':{}}, {'tool':'reading.style','args':{'invented':True}}]:
            with self.assertRaises(router.HTTPException): router.preview(router.Preview(operations=[op]))
            self.assertIsNone(self.value())
    def test_batch_failure_rolls_back_earlier_change(self):
        with self.assertRaises(router.HTTPException):
            router.preview(router.Preview(operations=[{'tool':'reading.style','args':{'size':20}},{'tool':'invalid','args':{}}]))
        self.assertIsNone(self.value())
    def test_secret_and_oversized_payload_rejected(self):
        with self.assertRaises(router.HTTPException):
            router.preview(router.Preview(operations=[{'tool':'persona.edit','args':{'id':1,'free_text':'api_key: secretkey12345678'}}]))
        with self.assertRaises(router.HTTPException) as error:
            router.preview(router.Preview(operations=[{'tool':'world.save','args':{'name':'x'*64000}}]))
        self.assertEqual(error.exception.status_code,413)
    def test_inspect_redacts_and_never_runs_model(self):
        with patch.object(agent,'_snapshot',return_value={'name':'api_key: secretkey12345678'}) as snap:
            result=router.inspect_workspace()
        self.assertEqual(result,{'name':'[已隐藏]'})
        self.assertEqual(set(snap.call_args.args[1]),set(agent._routes))
    def test_catalog_has_every_registered_schema(self):
        self.assertEqual({row['id'] for row in router.catalog()['tools']},set(agent.TOOLS))
    def test_operation_count_bounded(self):
        for operations in [[],[{'tool':'reading.style','args':{}}]*5]:
            with self.assertRaises(ValueError): router.Preview(operations=operations)
    def test_explicit_course_clear_does_not_restore_previous_preset(self):
        previous=agent.course.Teaching(mode='off',preset='old-course')
        with patch.object(agent.languages,'registered',return_value={'en':'English'}), patch.object(agent.course,'language_settings',return_value=previous), patch.object(agent.course,'resolve'), patch.object(agent.course,'save_language_settings'):
            result=router.preview(router.Preview(operations=[{'tool':'course.set','args':{'language':'en','mode':'off','preset':None}}]))
        self.assertEqual(result['proposal']['changes'][0]['after'],{'mode':'off'})
    def test_omitted_course_selection_retains_previous_preset(self):
        previous=agent.course.Teaching(mode='off',preset='old-course')
        with patch.object(agent.languages,'registered',return_value={'en':'English'}), patch.object(agent.course,'language_settings',return_value=previous), patch.object(agent.course,'resolve'):
            result=router.preview(router.Preview(operations=[{'tool':'course.set','args':{'language':'en','mode':'off'}}]))
        self.assertIsNone(result['proposal'])

if __name__=='__main__': unittest.main()
