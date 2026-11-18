import asyncio
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing,contextmanager
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services import model_reasoning as reasoning,model_catalog,chatgpt_sdk,workspace_agent_siwc_auth as auth
from app.services.workspace_agent_siwc_live import SIWCRuntime,SIWCFailure

class MemoryStore:
    def __init__(self):self.value={'consent_version':'siwc-v1','registration':{'refresh_token':'mock-only'}}
    @contextmanager
    def transaction(self):yield
    def load(self):return copy.deepcopy(self.value)
    def save(self,value):self.value=copy.deepcopy(value)

class ReasoningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'settings.db'
        with closing(sqlite3.connect(self.path))as conn,conn:conn.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
        def connect():
            conn=sqlite3.connect(self.path);conn.row_factory=sqlite3.Row;return conn
        def setting(key,default=''):
            conn=connect()
            try:
                value=conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
                return value['value'] if value else default
            finally:conn.close()
        for target,value in [('get_conn',connect),('get_setting',setting)]:
            p=patch.object(reasoning,target,side_effect=value);p.start();self.addCleanup(p.stop)
        reasoning._observed.clear();self.addCleanup(reasoning._observed.clear);self.addCleanup(self.temp.cleanup)

    async def test_catalog_driven_options_accept_new_ids_and_filter_invalid_values(self):
        result=reasoning.options({'supported_reasoning_levels':[{'effort':'low'},{'effort':'future-tier','display_name':'Future'},'low',None], 'default_reasoning_level':'future-tier'})
        self.assertEqual(result,{'levels':[{'id':'low','label':'low'},{'id':'future-tier','label':'Future'}],'default':'future-tier'})
        self.assertEqual(reasoning.options({'effort':{'supported_levels':['server-a','server-b'],'default_level':'server-b'}})['default'],'server-b')
        self.assertEqual(reasoning.options({'supportedEffortLevels':['sdk-only']})['levels'][0]['id'],'sdk-only')
        self.assertEqual(reasoning.options({}),{'levels':[],'default':None})

    async def test_preference_is_bound_to_model_and_connection(self):
        with closing(sqlite3.connect(self.path))as conn,conn:conn.execute("INSERT INTO settings VALUES('custom_base_url','https://one.example/v1')")
        options=reasoning.options({'effort':{'supported_levels':['future']}})
        reasoning.save('custom','vendor/model','future',options)
        self.assertEqual(reasoning.get_effort('custom','vendor/model'),'future')
        self.assertIsNone(reasoning.get_effort('custom','different-model'))
        with closing(sqlite3.connect(self.path))as conn,conn:conn.execute("UPDATE settings SET value='https://two.example/v1' WHERE key='custom_base_url'")
        self.assertIsNone(reasoning.get_effort('custom','vendor/model'))
        with self.assertRaises(ValueError):reasoning.save('custom','vendor/model','guessed',options)

    async def test_refresh_stops_sending_a_removed_level(self):
        options=reasoning.options({'effort':{'supported_levels':['old','new']}})
        reasoning.save('deepseek','model','old',options)
        rows=[{'id':'model','reasoning':reasoning.options({'effort':{'supported_levels':['new']}})}]
        self.assertIsNone(reasoning.decorate('deepseek',rows)[0]['reasoning']['selected'])
        self.assertIsNone(reasoning.get_effort('deepseek','model'))
        reasoning.save('deepseek','model','future',reasoning.options({'effort':{'supported_levels':['future']}}))
        self.assertEqual(reasoning.get_effort('deepseek','model'),'future')

    async def test_chatgpt_choice_survives_restart_and_resets_when_model_changes(self):
        store=MemoryStore();runtime=SIWCRuntime(enabled=True,store=store);runtime._last_result='authorized'
        options=reasoning.options({'supported_reasoning_levels':['provider-tier']})
        runtime.select_model('a',['a','b'],effort='provider-tier',reasoning=options)
        restored=SIWCRuntime(enabled=True,store=store);restored.resume()
        self.assertEqual(restored.metadata()['reasoning_effort'],'provider-tier')
        with self.assertRaises(SIWCFailure):restored.select_model('b',['a','b'],effort='provider-tier',reasoning={'levels':[]})
        restored.select_model('b',['a','b'],reasoning={'levels':[]})
        self.assertIsNone(restored.metadata()['reasoning_effort'])

    async def test_official_sdk_receives_selected_reasoning_effort(self):
        seen=[]
        def respond(request):
            seen.append(json.loads(request.content))
            event={'type':'response.completed','response':{'status':'completed','output':[{'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'OK'}]}]}}
            return httpx.Response(200,content=('data: '+json.dumps(event)+'\n\n').encode())
        with patch.object(auth,'safe_metadata',return_value={'selected_model':'m','reasoning_effort':'declared-tier','reasoning_levels':['declared-tier']}):
            result=await chatgpt_sdk.complete({'model':'m','input':'test'},token_provider=AsyncMock(return_value='synthetic-oauth'),transport=httpx.MockTransport(respond))
        self.assertEqual(result,'OK');self.assertEqual(seen[0]['reasoning'],{'effort':'declared-tier'})

    async def test_api_catalog_preserves_effort_metadata(self):
        result=model_catalog.parse({'data':[{'id':'model','effort':{'supported_levels':['provider-1','provider-2'],'default_level':'provider-1'}}]})
        self.assertEqual([x['id']for x in result[0]['reasoning']['levels']],['provider-1','provider-2'])

    async def test_custom_requests_include_only_an_explicit_supported_effort(self):
        from app.providers import deepseek
        client_type=httpx.AsyncClient
        seen=[]
        def respond(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
        def client(**kwargs):return client_type(**kwargs,transport=httpx.MockTransport(respond))
        provider=deepseek.OpenAICompatProvider('custom',lambda:('https://custom.test/v1','synthetic','model'))
        reasoning.save('custom','model','future',reasoning.options({'effort':{'supported_levels':['future']}}))
        with patch.object(deepseek.httpx,'AsyncClient',side_effect=client):
            self.assertEqual(await provider.generate_json('request',{}),{'ok':True})
            reasoning.save('custom','model',None,reasoning.options({}))
            await provider.generate_json('request',{})
        self.assertEqual(seen[0]['reasoning_effort'],'future')
        self.assertNotIn('reasoning_effort',seen[1])

    async def test_save_route_validates_against_fresh_catalog(self):
        from app.routers import config
        from fastapi import HTTPException
        rows=[{'id':'model','reasoning':reasoning.options({'effort':{'supported_levels':['fresh']}})}]
        with patch.object(model_catalog,'discover',AsyncMock(return_value=rows)):
            result=await config.select_reasoning('deepseek',config.ReasoningChoice(model='model',effort='fresh'))
            self.assertEqual(result['reasoning']['selected'],'fresh')
            with self.assertRaises(HTTPException)as caught:
                await config.select_reasoning('deepseek',config.ReasoningChoice(model='model',effort='guessed'))
        self.assertEqual(caught.exception.status_code,422)
        self.assertEqual(reasoning.get_effort('deepseek','model'),'fresh')

if __name__=='__main__':unittest.main()
