"""The resident Kokoro worker: reuse, queueing, crash recovery, idle stop. A fake worker stands in for Kokoro."""
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services import listening_tts as tts
from app.services.listening_formats import Line

FAKE = textwrap.dedent('''
    import json, os, sys, time, wave
    REPLY = "@@LANGPAL-TTS@@ "
    print("noise from a library", flush=True)
    print(REPLY + json.dumps({"ready": True}), flush=True)
    for raw in sys.stdin:
        request = json.loads(raw)
        if request.get("warm"):
            print(REPLY + json.dumps({"ok": True}), flush=True); continue
        lines = request["exercise"]["lines"]
        if lines[0]["text"] == "crash":
            os._exit(3)
        if lines[0]["text"] == "slow":
            time.sleep(0.3)
        with wave.open(request["output"], "wb") as w:
            w.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            w.writeframes(b"\\x01\\x00" * 2400 * len(lines))
        json.dump([{"start": i * 0.1, "end": i * 0.1 + 0.1, "parts": [{"start": i * 0.1, "end": i * 0.1 + 0.1,
                    "text": line["text"]}]} for i, line in enumerate(lines)],
                  open(request["output"][:-4] + ".json", "w"))
        print(REPLY + json.dumps({"ok": True, "pid": os.getpid()}), flush=True)
''')


class ResidentWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        script = Path(self.tmp.name) / 'fake_worker.py'
        script.write_text(FAKE, encoding='utf-8')
        self.config = tts.KokoroConfig(Path(sys.executable), Path(self.tmp.name), {'A': 'af_heart', 'B': 'am_michael'}, 1.0)
        self.worker = tts.KokoroWorker()
        self.patches = [patch.object(tts, 'WORKER', script), patch.object(tts, 'worker', self.worker)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        self.worker.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def say(self, *texts):
        timings = []
        audio = tts.synthesize(self.config, 'en', [Line(speaker='A', text=t) for t in texts], timings=timings)
        return audio, timings

    def test_reused_and_timings_come_back(self):
        tts.warm(self.config)
        pid = self.worker.pid
        self.assertIsNotNone(pid)
        audio, timings = self.say('Hello there.', 'Fine.')
        self.assertTrue(audio.startswith(b'RIFF'))
        self.assertEqual(timings[1]['parts'][0]['text'], 'Fine.')
        self.say('Again.')
        self.assertEqual(self.worker.pid, pid)

    def test_requests_queue_one_at_a_time(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.say('slow')[1])) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertEqual(len(results), 3)

    def test_crash_is_reported_and_next_request_restarts(self):
        self.say('first')
        old = self.worker.pid
        with self.assertRaises(RuntimeError):
            self.say('crash')
        self.assertIsNone(self.worker.pid)
        self.say('after')
        self.assertNotEqual(self.worker.pid, old)

    def test_idle_worker_stops(self):
        self.say('one')
        self.assertIsNotNone(self.worker.pid)
        with patch.object(tts, 'IDLE_SECONDS', 0):
            self.worker._idle_check()
        self.assertIsNone(self.worker.pid)


if __name__ == '__main__':
    unittest.main()
