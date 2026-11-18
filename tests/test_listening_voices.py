"""Offline voice defaults, pitch arithmetic and listening metadata."""
from contextlib import closing, nullcontext
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.routers import listening
from app.services import listening_settings as settings, listening_tts as tts, listening_kokoro as worker
from app.services.listening_formats import Exercise, FORMATS, Line


class ListeningVoices(unittest.TestCase):
    def test_fresh_defaults_and_pitch_bounds(self):
        config = settings.SynthesisSettings()
        self.assertEqual((config.kokoro_en.a, config.kokoro_en.b, config.kokoro_en.pitch_b),
                         ('af_heart', 'af_nicole', None))
        self.assertEqual((config.kokoro_ja.a, config.kokoro_ja.b, config.kokoro_ja.pitch_b),
                         ('jf_alpha', 'jf_alpha', -2.5))
        self.assertEqual(tts.KOKORO_VOICES, {'en': {'A': 'af_heart', 'B': 'af_nicole'},
                                             'ja': {'A': 'jf_alpha', 'B': 'jf_alpha'}})
        for pitch in (-6, 0, 6, None):
            self.assertEqual(settings.Voices(a='jf_alpha', b='jf_alpha', pitch_b=pitch).pitch_b, pitch)
        for pitch in (-6.01, 6.01):
            with self.assertRaises(ValueError):
                settings.Voices(a='jf_alpha', b='jf_alpha', pitch_b=pitch)

    def test_load_upgrades_only_old_defaults_without_writing(self):
        cases = [
            ({}, ('af_nicole', 'jf_alpha', -2.5)),
            ({'kokoro_en': {'a': 'af_heart', 'b': 'am_michael'},
              'kokoro_ja': {'a': 'jf_alpha', 'b': 'jm_kumo'}}, ('af_nicole', 'jf_alpha', -2.5)),
            ({'kokoro_en': {'a': 'af_nicole', 'b': 'af_heart', 'pitch_b': 2},
              'kokoro_ja': {'a': 'jf_alpha', 'b': 'jf_custom'}}, ('af_heart', 'jf_custom', None)),
            ({'kokoro_ja': {'a': 'jf_alpha', 'b': 'jm_kumo', 'pitch_b': 1}}, ('af_nicole', 'jf_alpha', 1)),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'settings.sqlite'
                def connect():
                    return sqlite3.connect(path)
                stored = json.dumps(raw)
                with closing(connect()) as conn, conn:
                    conn.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)')
                    conn.execute('INSERT INTO settings VALUES (?, ?)', (settings.CONFIG_KEY, stored))
                with patch.object(settings, 'get_conn', connect):
                    config, _ = settings.load()
                self.assertEqual((config.kokoro_en.b, config.kokoro_ja.b, config.kokoro_ja.pitch_b), expected)
                if 'pitch_b' in raw.get('kokoro_en', {}):
                    self.assertEqual(config.kokoro_en.pitch_b, raw['kokoro_en']['pitch_b'])
                with closing(connect()) as conn:
                    self.assertEqual(conn.execute('SELECT value FROM settings').fetchone()[0], stored)

    def test_default_configuration_and_settings_pitch_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            for name in ['python.exe', 'config.json', 'kokoro-v1_0.pth', 'voices/af_heart.pt',
                         'voices/af_nicole.pt', 'voices/jf_alpha.pt', tts.JAPANESE_DICTIONARY + '/sys.dic']:
                path = assets / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with patch.dict('os.environ', {'LANGPAL_LISTENING_TTS_PYTHON': str(assets / 'python.exe'),
                                          'LANGPAL_LISTENING_TTS_ASSETS': str(assets)}):
                self.assertEqual(tts.configured('ja').pitch_b, -2.5)
                self.assertIsNone(tts.configured('en').pitch_b)
                config = settings.SynthesisSettings()
                config.kokoro_ja.pitch_b = 3
                local = tts.configured_synthesis('ja', config, '')
                self.assertEqual(local.pitch_b, 3)
                config.provider = 'compatible'
                config.base_url = 'https://speech.example/v1'
                config.model = 'fixture'
                self.assertIsInstance(tts.configured_synthesis('ja', config, ''), tts.CompatibleConfig)

    def test_worker_payload_carries_pitch(self):
        config = tts.KokoroConfig(Path('python'), Path('assets'), tts.KOKORO_VOICES['ja'], 1, pitch_b=-2.5)
        def request(_, body):
            self.assertEqual(body['exercise']['pitch_b'], -2.5)
            self.assertIn('speed_b', body['exercise'])
            with wave.open(body['output'], 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(48))
        with patch.object(tts.worker, 'request', request):
            tts.synthesize(config, 'ja', [Line(speaker='B', text='はい。')])

    def test_two_female_speaker_note_uses_roles(self):
        for language, voices in tts.KOKORO_VOICES.items():
            note = listening._speaker_note(language, voices)
            self.assertIn('身份', note)
            self.assertNotIn('the woman', note)
            self.assertNotIn('女の人', note)

    def test_lines_and_shape_female_flags_follow_current_config(self):
        exercise = Exercise.model_validate({
            'title': 'Fixture', 'script': [{'speaker': 'A', 'text': 'First.'}, {'speaker': 'B', 'text': 'Second.'}],
            'questions': [{'prompt': 'Which?', 'choices': ['One', 'Two', 'Three', 'Four'],
                           'answer': 0, 'evidence': [1], 'explanation': 'Fixture'}]})
        timings = [{'start': 0, 'end': 1}, {'start': 1.3, 'end': 2.3}]
        receipt = {'script': [line.model_dump() for line in exercise.script], 'clips': timings, 'results': []}
        prepared = listening.Prepared(0, exercise, FORMATS['en_conversation'], b'', timings)
        configs = [
            (tts.KokoroConfig(Path('python'), Path('assets'), {'A': 'af_heart', 'B': 'af_nicole'}, 1), [True, True]),
            (tts.KokoroConfig(Path('python'), Path('assets'), {'A': 'af_heart', 'B': 'am_michael'}, 1), [True, False]),
            (tts.CompatibleConfig('https://speech.example/v1', '', 'fixture', {'A': 'af_heart', 'B': 'am_michael'}, 1), [True, True]),
            (None, [True, True]),
        ]
        app = FastAPI()
        app.include_router(listening.router, prefix='/api')
        with TestClient(app) as client, patch.object(listening, '_find', return_value=prepared), \
                patch.object(listening, 'get_conn', side_effect=lambda: sqlite3.connect(':memory:')), \
                patch.object(listening, '_graded_receipt', return_value=('en', receipt)), \
                patch.object(settings, 'load', return_value=(settings.SynthesisSettings(), '')):
            for config, expected in configs:
                with self.subTest(config=config), patch.object(tts, 'configured_synthesis', return_value=config):
                    for endpoint, key in [('lines', 'lines'), ('shape', 'segments')]:
                        response = client.get('/api/listening/practice/fixture/' + endpoint)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual([row['female'] for row in response.json()[key]], expected)


class PitchResampling(unittest.TestCase):
    def test_exact_lengths_and_sample_timing_arithmetic(self):
        audio = np.linspace(-.5, .5, 24001, dtype=np.float32)
        for pitch in (-6, -2.5, 0, 6):
            ratio = 2 ** (pitch / 12)
            shifted = worker._resample_pitch(audio, ratio)
            self.assertEqual(len(shifted), round(len(audio) / ratio))
            frames = 7200 + len(shifted)
            self.assertAlmostEqual(frames / 24000 - 7200 / 24000, len(shifted) / 24000)
            self.assertTrue(np.isfinite(shifted).all())
        self.assertIs(worker._resample_pitch(audio, 1), audio)
        self.assertEqual(len(worker._resample_pitch(audio[:0], 2)), 0)

    def test_render_counts_resampled_frames_for_lines_and_sentences(self):
        # Stand in for tensors and the model; execute the real render bookkeeping.
        class Tensor(np.ndarray):
            def numel(self): return self.size
            def cpu(self): return self
            def numpy(self): return np.asarray(self)
            def clamp(self, low, high): return np.clip(self, low, high).view(Tensor)
            def to(self, dtype): return self.astype(dtype).view(Tensor)
        def tensor(audio): return np.asarray(audio).view(Tensor)
        torch = SimpleNamespace(inference_mode=nullcontext, isfinite=np.isfinite, from_numpy=tensor, int16=np.int16)
        for pitch in (None, 0, -2.5, 6):
            with self.subTest(pitch=pitch), tempfile.TemporaryDirectory() as directory:
                calls = []
                def pipeline(text, **kwargs):
                    calls.append(kwargs['speed'])
                    return [SimpleNamespace(audio=tensor(np.ones(2400, dtype=np.float32) * .1))]
                state = {'model': None, 'pipelines': {'j': pipeline}}
                output = Path(directory) / 'fixture.wav'
                exercise = {'language': 'ja', 'voices': {'A': 'jf_alpha', 'B': 'jf_alpha'},
                            'speed': .9, 'speed_b': 1.1, 'pitch_b': pitch, 'timestamps': True,
                            'lines': [{'speaker': 'A', 'text': 'はい。'}, {'speaker': 'B', 'text': 'はい。次。'}]}
                pipeline.g2p = lambda text: ('fixture', None)
                with patch.dict(sys.modules, {'torch': torch, 'kokoro': SimpleNamespace(KPipeline=None)}), \
                        patch.object(worker, '_model', return_value=state):
                    worker.render(Path(directory), output, exercise)
                ratio = 2 ** ((pitch or 0) / 12)
                count = round(2400 / ratio)
                self.assertEqual(calls, [.9, 1.1 / ratio, 1.1 / ratio])
                timings = json.loads(output.with_suffix('.json').read_text('utf-8'))
                self.assertEqual(timings[0]['end'], .1)
                self.assertEqual(timings[1]['start'], .4)
                self.assertEqual(timings[1]['end'], (9600 + 2 * count) / 24000)
                self.assertEqual(timings[1]['parts'][0]['end'], (9600 + count) / 24000)
                with wave.open(str(output)) as wav:
                    self.assertEqual(wav.getnframes(), 9600 + 2 * count)


if __name__ == '__main__':
    unittest.main()
