"""Exercise the real bundled runtime against loopback, never DeepSeek's API."""
import asyncio
import json
import sys
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.providers import dsh

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(dsh.installed(),'Pinned DSH runtime not installed')
    async def test_real_runtime_exposes_no_tools(self):
        from deepseek_harness import DeepSeekHarness
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path,body))
                events=[
                    {'type':'message_start','message':{'id':'mock-1','type':'message','role':'assistant','model':'deepseek-chat','content':[],'usage':{'input_tokens':3,'output_tokens':0}}},
                    {'type':'content_block_start','index':0,'content_block':{'type':'text','text':'MOCK_OK'}},
                    {'type':'content_block_stop','index':0},
                    {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':1}},
                    {'type':'message_stop'}]
                data=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        homes=[]
        def factory(config):
            self.assertEqual(config.reasoning_effort, 'max')
            # Only this explicit test factory can override the production fixed URL.
            config.base_url=f'http://127.0.0.1:{server.server_port}/anthropic'
            homes.append(Path(config.cwd))
            return DeepSeekHarness(config)
        try:
            with patch('app.services.model_reasoning.get_effort', return_value='max'):
                result=await dsh.complete('Reply MOCK_OK.','Synthetic offline test.',config=('https://api.deepseek.com','offline-placeholder','deepseek-chat'),harness_factory=factory,timeout=20)
            self.assertEqual(result,'MOCK_OK');self.assertEqual(len(requests),1)
            path,body=requests[0]
            self.assertEqual(path,'/anthropic/v1/messages')
            self.assertFalse(body.get('tools'))
            self.assertEqual(body['output_config']['effort'], 'max')
            self.assertEqual(set(body),{'max_tokens','messages','model','output_config','stream','system','thinking'})
            self.assertTrue(all(not home.exists() for home in homes))
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
