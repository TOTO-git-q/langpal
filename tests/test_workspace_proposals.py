"""Durable proposal tests: isolated SQLite and fresh Python processes; no models."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.services import workspace_agent as agent

class ProposalTests(unittest.TestCase):

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'proposals.db'
        self.connections=[]
        with self.connect() as c:
            c.executescript((ROOT/'backend/db/schema.sql').read_text(encoding='utf-8'))
            c.execute("INSERT OR REPLACE INTO personas(id,name,language,profile_json) VALUES(1,'One','en',?)",(json.dumps({'tone':'warm','world_book_ids':[]}),))
        self.patch=patch.object(agent,'get_conn',self.connect)
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        for c in self.connections:c.close()
        self.temp.cleanup()
    def connect(self):
        c=sqlite3.connect(self.path,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');self.connections.append(c);return c
    def preview(self,tool,args,client=None):
        return agent.preview_operations([agent.Operation(tool=tool,args=args)],client or {})['proposal']
    def payload(self,p):
        with self.connect() as c:return json.loads(c.execute('SELECT payload_json FROM workspace_proposals WHERE id=?',(p['id'],)).fetchone()[0])
    def child_commit(self,p,undo=False):
        code="import sys,sqlite3,json;sys.path.insert(0,sys.argv[1]);from app.services import workspace_agent as a\ndef connect():\n c=sqlite3.connect(sys.argv[2]);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c\na.get_conn=connect\nprint(json.dumps(a.commit(sys.argv[3],sys.argv[4]=='1',{})))"
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        result=subprocess.run([sys.executable,'-c',code,str(ROOT/'backend'),str(self.path),p['id'],'1' if undo else '0'],capture_output=True,text=True,encoding='utf-8',timeout=30,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},**flags)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)
    def test_fresh_process_apply_undo_and_repeat(self):
        p=self.preview('reading.style',{'size':20,'theme':'paper'})
        self.assertEqual(p['status'],'pending')
        self.assertEqual(self.child_commit(p)['status'],'applied')
        first=agent.proposal_state(p['id'])
        self.assertEqual(self.child_commit(p)['proposal']['expires_at'],first['expires_at'])
        self.assertEqual(self.child_commit(p,True)['status'],'undone')
        self.assertEqual(self.child_commit(p,True)['status'],'undone')
        with self.connect() as c:self.assertIsNone(c.execute('SELECT value FROM settings WHERE key=?',(agent.reading_style.STYLE_KEY,)).fetchone())
    def test_expiry_is_durable_and_blocks_apply_or_undo(self):
        for applied in (False,True):
            p=self.preview('reading.style',{'size':20})
            if applied: agent.commit(p['id'],False,{})
            with self.connect() as c:c.execute('UPDATE workspace_proposals SET expires_at=0 WHERE id=?',(p['id'],))
            with self.assertRaises(agent.Missing):agent.commit(p['id'],applied,{})
            saved=agent.proposal_state(p['id'])
            self.assertEqual(saved['status'],'expired');self.assertEqual(saved['last_status'],'applied' if applied else 'pending')
    def test_status_write_failure_rolls_back_settings(self):
        p=self.preview('reading.style',{'size':20})
        with self.connect() as c:c.execute("CREATE TRIGGER reject_status BEFORE UPDATE OF status ON workspace_proposals BEGIN SELECT RAISE(ABORT,'simulated'); END")
        with self.assertRaises(sqlite3.IntegrityError):agent.commit(p['id'],False,{})
        with self.connect() as c:
            self.assertIsNone(c.execute('SELECT value FROM settings WHERE key=?',(agent.reading_style.STYLE_KEY,)).fetchone())
            self.assertEqual(c.execute('SELECT status FROM workspace_proposals').fetchone()[0],'pending')
    def test_conflict_never_overwrites_and_same_resource_order_preserved(self):
        p=agent.preview_operations([agent.Operation(tool='reading.style',args={'size':20}),agent.Operation(tool='reading.style',args={'theme':'paper'})],{})['proposal']
        self.assertEqual(len(self.payload(p)['changes']),2)
        self.child_commit(p);self.child_commit(p,True)
        p=self.preview('reading.style',{'size':20})
        with self.connect() as c:c.execute('INSERT INTO settings VALUES (?,?)',(agent.reading_style.STYLE_KEY,'{"size":23}'))
        with self.assertRaises(agent.Conflict):agent.commit(p['id'],False,{})
        self.assertEqual(agent.proposal_state(p['id'])['status'],'pending')
        with self.connect() as c:self.assertEqual(c.execute('SELECT value FROM settings WHERE key=?',(agent.reading_style.STYLE_KEY,)).fetchone()[0],'{"size":23}')
    def test_all_resource_kinds_restore_and_roundtrip(self):
        cases=[
          ('reading.style',{'size':21}),
          ('source.save',{'changes':{'name':'News','kind':'article','lang':'en','format':'rss','url':'https://example.org/feed'},'make_default':True}),
          ('language.add',{'tag':'fr','label':'French'}),
          ('persona.edit',{'id':1,'name':'Updated'}),
          ('course.set',{'language':'en','mode':'ambient','preset':'toefl-2026'}),
          ('world.save',{'name':'World','book':{'entries':[{'title':'Rule','content':'Content','keywords':[]}]}}),
          ('coach.preferences',{'url':'http://127.0.0.1:19010','languages':['en']}),
          ('voice.listening',{'api_en':{'a':'alloy','b':'echo','speed':1.1}}),
          ('reading.format',{'format':{'name':'Format','language':'en','min_length':300,'target_length':400,'max_length':500,'question_count':3,'skills':'Reading facts'},'make_default':True}),
        ]
        kinds=set()
        for tool,args in cases:
            with self.subTest(tool=tool):
                p=self.preview(tool,args)
                self.assertIsNotNone(p)
                kinds.update(d['resource']['kind'] for d in self.payload(p)['changes'])
                self.child_commit(p);self.child_commit(p,True)
        self.assertEqual(kinds,{'setting','sources','defaults','language','persona','course','world','coach_service','coach_languages'})
    def test_reference_guards_survive_restore(self):
        p=self.preview('language.add',{'tag':'fr','label':'French'});agent.commit(p['id'],False,{})
        with self.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(agent.COACH_LANGUAGES_KEY,json.dumps(['fr'])))
        with self.assertRaises(agent.Conflict):agent.commit(p['id'],True,{})
        self.assertEqual(agent.proposal_state(p['id'])['status'],'applied')
        world=self.preview('world.save',{'name':'World','book':{'entries':[]}});agent.commit(world['id'],False,{})
        ident=self.payload(world)['changes'][0]['after']['id']
        with self.connect() as c:c.execute('UPDATE personas SET profile_json=? WHERE id=1',(json.dumps({'world_book_ids':[ident]}),))
        with self.assertRaises(agent.Conflict):agent.commit(world['id'],True,{})
    def test_apply_dependency_guards_and_concurrent_replay(self):
        world=self.preview('world.save',{'name':'Reference','book':{'entries':[]}})
        agent.commit(world['id'],False,{})
        ident=self.payload(world)['changes'][0]['after']['id']
        persona=self.preview('persona.edit',{'id':1,'world_book_ids':[ident]})
        agent.commit(world['id'],True,{})
        with self.assertRaises(agent.Conflict):agent.commit(persona['id'],False,{})
        self.assertEqual(agent.proposal_state(persona['id'])['status'],'pending')
        coach=self.preview('coach.preferences',{'languages':['en','ja']})
        with self.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(agent.coach_bridge.SERVICE_KEY,'http://127.0.0.1:19011'))
        with self.assertRaises(agent.Conflict):agent.commit(coach['id'],False,{})
        style=self.preview('reading.style',{'size':20})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:agent.commit(style['id'],False,{}),range(2)))
        self.assertTrue(all(item['status']=='applied' for item in results))
        self.assertEqual(results[0]['proposal']['expires_at'],results[1]['proposal']['expires_at'])

    def test_retired_chat_room_proposals_cannot_apply(self):
        for kind in ('chat','chat_v2'):
            with self.assertRaises(agent.Conflict):agent._restore_resource({'kind':kind,'result':{}})
        payload={'version':1,'browser':None,'changes':[{'resource':{'kind':'chat_v2','result':{}},'before':None,'after':None,'view':{'tool':'chat.room'}}]}
        with self.connect() as c:c.execute("INSERT INTO workspace_proposals(id,status,payload_json,created_at,updated_at,expires_at) VALUES ('old','pending',?,0,0,9e12)",(json.dumps(payload),))
        with self.assertRaises(agent.Conflict):agent.commit('old',False,{})
        self.assertEqual(agent.proposal_state('old')['status'],'pending')

    def test_source_enable_and_defaults_check_registry(self):
        p=self.preview('source.enable',{'id':'builtin-nasa','enabled':False})
        self.assertEqual(self.payload(p)['changes'][0]['resource']['kind'],'sources')
        self.child_commit(p)
        with self.assertRaises(agent.AgentError):self.preview('reading.defaults',{'article_en':'builtin-nasa'})
        self.child_commit(p,True)
        q=self.preview('reading.defaults',{'article_en':'builtin-nasa'});self.child_commit(q);self.child_commit(q,True)
        with self.assertRaises(agent.AgentError):self.preview('reading.defaults',{'article_en':'builtin-unknown'})
    def test_world_approved_id_does_not_reallocate(self):
        p=self.preview('world.save',{'name':'Approved','book':{'entries':[]}})
        q=self.preview('world.save',{'name':'Other','book':{'entries':[]}})
        agent.commit(q['id'],False,{})
        with self.assertRaises(agent.Conflict):agent.commit(p['id'],False,{})
        with self.connect() as c:self.assertEqual([w['name'] for w in agent.lore.world_books(c)],['Other'])
    def test_browser_state_is_explicit_and_client_conflicts_preserved(self):
        p=self.preview('review.preference',{'key':'reviewKind','value':'reading'},{'reviewKind':'all'})
        self.assertTrue(p['browser_only'])
        with self.assertRaises(agent.Conflict):agent.commit(p['id'],False,{'reviewKind':'listening'})
        result=agent.commit(p['id'],False,{'reviewKind':'all'})
        self.assertEqual(result['browser'],{'key':'reviewKind','value':'reading'})
        self.assertEqual(agent.commit(p['id'],True,{'reviewKind':'reading'})['status'],'undone')
        self.assertTrue(any(row['id']==p['id'] for row in agent.proposal_history()))

if __name__=='__main__':unittest.main()
