import asyncio
import io
import json
import sqlite3
import struct
import tempfile
import unittest
import wave
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import sys

from fastapi import FastAPI, HTTPException
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import listening_settings as settings, listening_tts as tts
from app.services.listening_formats import Line
from app.routers import voice_settings, speaking


def audio(samples=(100, -100), frames=1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(struct.pack('<' + 'h' * len(samples), *samples) * frames)
    return out.getvalue()


class VoiceSettings(unittest.TestCase):
    def test_voice_api_key_is_sealed_and_legacy_migrates_only_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.db'
            def conn():
                return sqlite3.connect(path)
            with closing(conn()) as db, db:
                db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)')
                db.execute('INSERT INTO settings VALUES (?,?)', (settings.API_KEY, 'synthetic-legacy-token'))
            with patch.object(settings, 'get_conn', conn):
                self.assertEqual(settings.load()[1], 'synthetic-legacy-token')
                with closing(conn()) as db:
                    self.assertEqual(db.execute('SELECT value FROM settings WHERE key=?', (settings.API_KEY,)).fetchone()[0], 'synthetic-legacy-token')
                config, key = settings.save(settings.SynthesisUpdate(pause_ms=650, volume=.7))
                self.assertEqual(key, 'synthetic-legacy-token')
                with closing(conn()) as db:
                    stored = db.execute('SELECT value FROM settings WHERE key=?', (settings.API_KEY,)).fetchone()[0]
                    self.assertTrue(stored.startswith('dpapi:'))
                    self.assertNotIn(key, stored)
                self.assertEqual(settings.load()[1], key)
                settings.save(settings.SynthesisUpdate(provider='compatible', base_url='https://speech.example/v1', model='any-model'))
                self.assertEqual(settings.load()[1], '')

    def test_pcm_gain_clips_and_does_not_change_length(self):
        pcm = struct.pack('<hhhh', 30000, -30000, 100, -100)
        self.assertEqual(struct.unpack('<hhhh', tts._scale_pcm(pcm, 1.5)), (32767, -32768, 150, -150))
        self.assertEqual(tts._scale_pcm(pcm, 1), pcm)

    def test_compatible_speech_receives_distinct_speeds_and_audio_pause_gain(self):
        requests = []
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def raise_for_status(self): pass
            def iter_bytes(self, **_): yield audio(frames=1200)
        class Client:
            def __init__(self, **options): self.options = options
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def stream(self, method, url, **options):
                requests.append((method, url, options)); return Stream()
        config = tts.CompatibleConfig('https://speech.example/v1', 'synthetic-token', 'future-model', {'A':'voice-a','B':'voice-b'}, .8, 500, 1.5, 1.2)
        timings = []
        with patch.object(tts.httpx, 'Client', Client):
            result = tts.synthesize(config, 'en', [Line(speaker='A', text='Hello.'), Line(speaker='B', text='Hi.')], timings=timings)
        self.assertEqual([r[2]['json']['speed'] for r in requests], [.8, 1.2])
        self.assertTrue(all(r[1] == 'https://speech.example/v1/audio/speech' for r in requests))
        with wave.open(io.BytesIO(result), 'rb') as wav:
            self.assertEqual(wav.getnframes(), 2400 * 2 + 12000)
            pcm = wav.readframes(wav.getnframes())
        self.assertEqual(struct.unpack('<hh', pcm[:4]), (150,-150))
        self.assertEqual(pcm[4800:4800+24000], bytes(24000))
        self.assertEqual(timings, [{'start':0.,'end':.1},{'start':.6,'end':.7}])

    def test_session_options_reject_fake_or_out_of_range_controls(self):
        for data in [{'pause_ms':-1}, {'volume':2}, {'kokoro_en':{'a':'af_heart','b':'am_michael','speed':3}}, {'pitch':1}]:
            with self.assertRaises(ValueError): settings.SynthesisUpdate(**data)


class VoiceRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(voice_settings.router, prefix='/api')
        self.app.include_router(speaking.router, prefix='/api')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('127.0.0.1',1234)), base_url='http://127.0.0.1')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_origin_guard_blocks_cross_origin_config(self):
        result = await self.client.put('/api/speaking/connection', headers={'Origin':'https://evil.example'}, json={'baseUrl':'https://api.openai.com/v1'})
        self.assertEqual(result.status_code, 403)

    async def test_config_proxy_is_fixed_and_key_is_secret_in_validation(self):
        body = speaking.ConnectionWrite(baseUrl='https://speech.example/v1', apiKey='synthetic-token')
        self.assertNotIn('synthetic-token', repr(body))
        with patch.object(speaking, 'get_conn', lambda: sqlite3.connect(':memory:')), patch.object(speaking, 'coach_service', lambda _: 'https://remote.example'):
            with self.assertRaises(HTTPException) as error: speaking._managed_url()
            self.assertEqual(error.exception.status_code,409)

    async def test_speaking_model_probe_has_no_persisting_call_when_upstream_fails(self):
        calls = []
        async def configuration(method, path, body=None):
            calls.append((method,path,body))
            raise HTTPException(422,'Probe failed')
        with patch.object(speaking,'_configuration',configuration):
            result = await self.client.post('/api/speaking/models',json={'provider':'compatible','baseUrl':'https://draft.example/v1','apiKey':'synthetic-draft-token'})
        self.assertEqual(result.status_code,422)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][:2],('POST','/api/connection/models'))
        self.assertNotIn('synthetic-draft-token',result.text)

    async def test_preview_returns_wav_using_saved_voice_settings(self):
        config = settings.SynthesisSettings()
        with patch.object(voice_settings, 'get_conn', lambda: sqlite3.connect(':memory:')), patch.object(voice_settings.languages, 'registered', lambda _: {'ja':'日本語'}), patch.object(voice_settings.listening_settings, 'load', lambda: (config,'')), patch.object(tts,'configured_synthesis',lambda *args: 'fixture-config'), patch.object(tts,'synthesize',lambda config, lang, lines: audio()):
            result = await self.client.post('/api/voice-settings/listening/preview', json={'language':'ja','speaker':'B'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers['content-type'],'audio/wav')
        self.assertEqual(result.headers['cache-control'],'no-store')
        self.assertTrue(result.content.startswith(b'RIFF'))

    async def test_catalog_can_load_before_a_model_is_chosen_without_cross_endpoint_key_reuse(self):
        config = settings.SynthesisSettings(provider='compatible', base_url='https://saved.example/v1', model='saved-model')
        calls = []
        async def models(base, key):
            calls.append((base,key))
            return {'models':[{'id':'future-model','label':'Future'}]}
        with patch.object(settings,'load',lambda:(config,'synthetic-saved-token')), patch.object(voice_settings,'_models',models):
            for base in ['https://saved.example/v1','https://different.example/v1']:
                result = await self.client.post('/api/voice-settings/listening/models',json={'base_url':base})
                self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(calls,[('https://saved.example/v1','synthetic-saved-token'),('https://different.example/v1','')])

    async def test_authoring_uses_main_text_provider_and_rejects_remote_refs(self):
        schema = {'type':'object','properties':{'unit':{'type':'string'}},'required':['unit']}
        class Provider:
            async def generate_json(self, prompt, shape):
                self.assert_prompt = prompt
                return {'unit':'A sourced lesson'}
        with patch('app.providers.registry.get_feature_provider', lambda feature: Provider() if feature=='chat' else None):
            result = await self.client.post('/api/speaking/authoring', json={'name':'LessonCard','prompt':'Make a card.','schema':schema})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['value']['unit'],'A sourced lesson')
        result = await self.client.post('/api/speaking/authoring', json={'name':'LessonCard','prompt':'x','schema':{'$ref':'https://external.example/schema'}})
        self.assertEqual(result.status_code,422)


if __name__ == '__main__':
    unittest.main()
