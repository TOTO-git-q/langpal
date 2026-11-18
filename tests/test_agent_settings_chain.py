"""Agent settings integration: synthetic SQLite, no live providers or user data."""
import asyncio
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services import workspace_agent as agent

class SettingsChainTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'settings.db'
        with self.connect() as conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
            conn.execute("INSERT OR REPLACE INTO personas(id,name,language,profile_json) VALUES(1,'Test','en',?)", (json.dumps({'tone':'warm', 'interests':['books'], 'world_book_ids':[]}),))
        self.db_patch = patch.object(agent, 'get_conn', self.connect)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        for conn in self.connections: conn.close()
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        self.connections.append(conn)
        return conn

    def preview(self, tool, args):
        return agent.preview_operations([agent.Operation(tool=tool, args=args)], {})['proposal']

    def inspect(self):
        return agent.inspect_workspace()

    def test_world_natural_language_plan_preserves_other_entries_and_undo(self):
        book = {'entries':[{'title':'First','content':'Original','keywords':[]}, {'title':'Second','content':'Must survive','keywords':['keep']}]}
        p = self.preview('world.save', {'name':'Test world','book':book})
        self.assertEqual(self.inspect()['world_books'], [])
        agent.commit(p['id'], False, {})
        original = self.inspect()['world_books'][0]
        async def model(prompt, context, tools):
            current = context['inspect']['world_books'][0]
            self.assertTrue(current['content_available'])
            changed = copy.deepcopy(current['book'])
            changed['entries'][0]['content'] = 'Changed'
            return {'reply':'Please confirm the proposed change.', 'operations':[{'tool':'world.save','args':{'id':current['id'],'name':current['name'],'book':changed}}]}
        with patch.object(agent.workspace_agent_runtime, 'generate', side_effect=model):
            result = asyncio.run(agent.plan('修改世界书的第一项', {}))
        self.assertEqual(self.inspect()['world_books'][0], original)
        agent.commit(result['proposal']['id'], False, {})
        saved = self.inspect()['world_books'][0]
        self.assertEqual(saved['book']['entries'][0]['content'], 'Changed')
        self.assertEqual(saved['book']['entries'][1], original['book']['entries'][1])
        agent.commit(result['proposal']['id'], True, {})
        self.assertEqual(self.inspect()['world_books'][0], original)

    def test_language_course_batch_is_atomic_and_reversible(self):
        outline = agent.course.lessons.Course(version=3, id='french-basic', title='French basic', language='fr', sections=[])
        guard = patch.object(agent.course.content, 'presets', return_value={outline.id: outline})
        guard.start(); self.addCleanup(guard.stop)
        proposal = agent.preview_operations([agent.Operation(tool='language.add',args={'tag':'fr','label':'Français'}),agent.Operation(tool='course.set',args={'language':'fr','preset':outline.id})], {})['proposal']
        self.assertNotIn('fr', self.inspect()['languages'])
        agent.commit(proposal['id'], False, {})
        self.assertEqual(self.inspect()['courses']['fr']['preset'], outline.id)
        agent.commit(proposal['id'], True, {})
        self.assertNotIn('fr', self.inspect()['languages'])

    def test_source_create_edit_default_readback_undo(self):
        tools = {item['id'] for item in agent.catalog()['tools']}
        self.assertTrue({'source.save', 'source.enable', 'chat.room'} <= tools)
        self.assertIn('source.test', {item['id'] for item in agent.catalog()['read_tools']})
        args = {'changes':{'name':'Public news','kind':'article','lang':'en','format':'rss','url':'https://example.org/news.xml'},'make_default':True}
        proposal = self.preview('source.save', args)
        self.assertFalse(any(s['name']=='Public news' for s in self.inspect()['sources']))
        agent.commit(proposal['id'], False, {})
        row = next(s for s in self.inspect()['sources'] if s['name']=='Public news')
        self.assertEqual(row['url'],args['changes']['url'])
        edit = self.preview('source.save',{'id':row['id'],'changes':{'name':'Renamed'}})
        agent.commit(edit['id'], False, {})
        saved = next(s for s in self.inspect()['sources'] if s['id']==row['id'])
        self.assertEqual(saved['name'],'Renamed')
        self.assertEqual(saved['url'],row['url'])
        agent.commit(edit['id'], True, {})
        agent.commit(proposal['id'], True, {})
        self.assertFalse(any(s['id']==row['id'] for s in self.inspect()['sources']))

    def test_snapshot_bounds_full_content_and_redacts_secrets(self):
        large = {'entries':[{'title':str(i),'content':'x'*1400} for i in range(20)]}
        p = self.preview('world.save', {'name':'Large','book':large})
        agent.commit(p['id'], False, {})
        row = self.inspect()['world_books'][0]
        self.assertFalse(row['content_available'])
        self.assertNotIn('book',row)
        with self.connect() as conn:
            conn.execute("UPDATE personas SET profile_json=? WHERE id=1", (json.dumps({'tone':'warm','free_text':'api_key: secretkey12345678'}),))
        profile = self.inspect()['personas'][0]['profile']
        self.assertEqual(profile['tone'],'warm')
        self.assertNotIn('secretkey12345678',profile['free_text'])

    def test_model_cannot_replace_omitted_world_book(self):
        large = {'entries':[{'title':str(i),'content':'x'*1400} for i in range(20)]}
        proposal = self.preview('world.save', {'name':'Large','book':large})
        agent.commit(proposal['id'], False, {})
        row = self.inspect()['world_books'][0]
        async def model(*args):
            return {'reply':'Replace', 'operations':[{'tool':'world.save','args':{'id':row['id'],'name':'Large','book':{'entries':[]}}}]}
        with patch.object(agent.workspace_agent_runtime, 'generate', side_effect=model):
            with self.assertRaises(agent.AgentError):
                asyncio.run(agent.plan('修改世界书', {}))
        with self.connect() as conn:
            self.assertEqual(len(agent.lore.world_books(conn)[0]['book']['entries']),20)

    def test_common_course_language_requests_route_to_curriculum(self):
        for message in ['把日语改成 N2','英语学 B2','German A1','French lessons']:
            self.assertIn('curriculum',agent.route_message(message))

if __name__ == '__main__':
    unittest.main()
