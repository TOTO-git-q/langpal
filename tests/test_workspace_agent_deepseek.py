"""Offline official DSH contracts; no real settings, credentials or requests."""
import asyncio
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from app.providers import dsh
from app.services import workspace_agent_deepseek as runtime
CONFIG=('https://api.deepseek.com','test-placeholder','deepseek-chat')
CONTEXT={'inspect':{'example':'sanitized'},'read_skill':{'skill':'local guidance'}}
FINAL={'reply':'OK','operations':[{'tool':'source.save','args_json':'{"name":"example"}'}],'test_source_id':None}

class Harness:
    result=json.dumps(FINAL)
    finish='completed'
    def __init__(self,config):
        self.config=config
        self.patch=json.loads(Path(config.patches[0]).read_text(encoding='utf8'))
        self.closed=False
    def start(self):pass
    def run(self,prompt):
        self.prompt=prompt
        return SimpleNamespace(final_response=self.result,finish_reason=self.finish)
    def close(self):self.closed=True

class HarnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        p=patch.object(runtime,'_deepseek_config',return_value=CONFIG)
        self.reader=p.start();self.addCleanup(p.stop)
        settings=patch('app.services.model_reasoning.get_setting',side_effect=lambda key,default='':default)
        settings.start();self.addCleanup(settings.stop)
        self.instances=[]
    def factory(self,config):
        h=Harness(config);self.instances.append(h);return h
    async def generate(self,**kwargs):
        return await runtime.generate('User request',CONTEXT,{'source.save':None},harness_factory=self.factory,**kwargs)
    async def test_snapshot_proposals_and_cleanup(self):
        value=await self.generate()
        self.assertEqual(value['operations'][0]['args'],{'name':'example'})
        h=self.instances[0]
        self.assertEqual(json.loads(h.prompt)['snapshots'],CONTEXT)
        self.assertTrue(h.closed)
        self.assertFalse(Path(h.config.cwd).exists())
        self.assertEqual(h.config.profile,'sdk-minimal')
        self.assertEqual(h.config.base_url,dsh.MESSAGES_BASE)
        self.assertEqual({r['id'] for r in h.patch if r.get('disabled')},set(dsh.DISABLED_ROWS))
        self.assertNotIn(CONFIG[1],json.dumps(h.patch))
    async def test_invalid_and_nonfinite_proposals(self):
        for result in ({}, {**FINAL,'operations':[{'tool':'Bash','args':{}}]}, {**FINAL,'operations':[{'tool':'source.save','args_json':'{"x":NaN}'}]}):
            with self.subTest(result=result),patch.object(Harness,'result',json.dumps(result)),self.assertRaises(runtime.DeepSeekFailure):
                await self.generate()
    async def test_truncated_and_oversize_response(self):
        with patch.object(Harness,'finish','max-tokens'),self.assertRaises(runtime.DeepSeekFailure):await self.generate()
        with patch.object(Harness,'result','x'*(dsh.MAX_OUTPUT_BYTES+1)),self.assertRaises(runtime.DeepSeekFailure):await self.generate()
    async def test_oversize_input(self):
        with self.assertRaises(runtime.DeepSeekFailure) as caught:
            await runtime.generate('x'*dsh.MAX_INPUT_BYTES,CONTEXT,{},harness_factory=self.factory)
        self.assertEqual(caught.exception.code,'size')
        self.assertEqual(self.instances,[])
    async def test_images_rejected_before_configuration(self):
        with self.assertRaises(runtime.DeepSeekFailure) as caught:await self.generate(images=['fake'])
        self.assertEqual(caught.exception.code,'vision');self.reader.assert_not_called()
    async def test_config_and_passive_capabilities(self):
        with patch.object(dsh,'installed',return_value=True):self.assertTrue(runtime.configured())
        with patch.object(dsh,'installed',return_value=False):self.assertEqual(runtime.capabilities()['configuration_state'],'sdk_missing')
        for config in (None,('https://evil.example','test','deepseek-chat'),(CONFIG[0],'test','invalid/model')):
            self.reader.return_value=config
            with self.assertRaises(runtime.DeepSeekFailure):await self.generate()
        self.assertEqual(self.instances,[])
    async def test_error_redaction(self):
        with patch.object(Harness,'run',side_effect=RuntimeError('secret diagnostics')),self.assertRaises(runtime.DeepSeekFailure) as caught:await self.generate()
        self.assertNotIn('secret',str(caught.exception))
        self.assertTrue(self.instances[0].closed)
    async def test_environment_scrub(self):
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'secret','NODE_OPTIONS':'inject','HTTPS_PROXY':'bad','DSH_HOME':'old'}):
            env=dsh.isolated_env('temporary')
        for key in ('ANTHROPIC_API_KEY','NODE_OPTIONS','HTTPS_PROXY','DSH_HOME'):self.assertEqual(env[key],'')
    async def test_cancel_closes_only_owned_runtime(self):
        started=threading.Event();closed=threading.Event()
        class Blocking(Harness):
            def run(self,prompt):started.set();closed.wait(5);raise RuntimeError('closed')
            def close(self):closed.set();super().close()
        task=asyncio.create_task(dsh.complete('system','request',config=CONFIG,harness_factory=Blocking))
        self.assertTrue(await asyncio.to_thread(started.wait,2))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(closed.is_set())
    async def test_timeout_closes_runtime(self):
        closed=threading.Event()
        class Blocking(Harness):
            def run(self,prompt):closed.wait(5);raise RuntimeError('closed')
            def close(self):closed.set();super().close()
        with self.assertRaises(dsh.DSHFailure) as caught:
            await dsh.complete('system','request',config=CONFIG,harness_factory=Blocking,timeout=.05)
        self.assertEqual(caught.exception.code,'timeout');self.assertTrue(closed.is_set())
    async def test_dsh_is_agent_only_and_chat_deepseek_is_direct_http(self):
        from app.providers import deepseek, registry
        self.assertFalse(hasattr(dsh,'DSHProvider'))
        self.assertIs(registry.DeepSeekProvider, deepseek.DeepSeekProvider)
        self.assertIsInstance(registry._provider_for('deepseek'), deepseek.OpenAICompatProvider)

if __name__=='__main__':unittest.main()
