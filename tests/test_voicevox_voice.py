"""日语朗读走 VOICEVOX：她的声音默认就是作者调好的那一组；设置能存能读、越界的值不收；
引擎不在时日语退回 Kokoro；聊天里日语朗读用存下来的声音。"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, main  # noqa: E402
from app.routers import chat  # noqa: E402
from app.services import character_voice, listening_settings, listening_tts, voicevox  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8765"}


class VoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "voice.db"
        conn = sqlite3.connect(path)
        conn.executescript((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        patcher = mock.patch.object(db, "DB_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_the_owners_voice(self):
        voice = character_voice.load()
        self.assertEqual((voice.ja.style, voice.ja.speaker, voice.ja.style_name), (49, "ナースロボ＿タイプＴ", "恐怖"))
        p = voice.ja.params
        self.assertEqual((p.speedScale, p.pitchScale, p.intonationScale, p.pauseLengthScale), (1.10, 0.04, 1.45, 1.0))
        self.assertEqual((voice.en.base, voice.en.rate, voice.en.pitch), ("af_nicole", 1.34, 5.5))

    def test_saved_voice_comes_back(self):
        voice = character_voice.DEFAULTS.model_copy(deep=True)
        voice.ja.style, voice.ja.speaker, voice.ja.style_name = 91, "ぞん子", "低血圧"
        voice.ja.params.speedScale = 0.9
        character_voice.save(voice)
        again = character_voice.load()
        self.assertEqual((again.ja.style, again.ja.params.speedScale), (91, 0.9))

    def test_api_round_trip_and_rejects_out_of_range(self):
        client = TestClient(main.app, base_url="http://127.0.0.1:8765")
        body = client.get("/api/voice/character", headers=ORIGIN).json()
        self.assertEqual(body["saved"]["ja"]["style"], 49)
        bad = body["saved"]
        bad["ja"]["params"]["speedScale"] = 3
        self.assertEqual(client.put("/api/voice/character", json=bad, headers=ORIGIN).status_code, 422)
        good = client.get("/api/voice/character", headers=ORIGIN).json()["saved"]
        good["en"]["rate"] = 1.1
        self.assertEqual(client.put("/api/voice/character", json=good, headers=ORIGIN).status_code, 200)
        self.assertEqual(character_voice.load().en.rate, 1.1)

    def test_japanese_listening_uses_voicevox_only_when_the_engine_is_there(self):
        settings, key = listening_settings.load()
        with mock.patch.object(voicevox, "available", return_value=True):
            self.assertIsInstance(listening_tts.configured_synthesis("ja", settings, key), listening_tts.VoicevoxConfig)
            self.assertNotIsInstance(listening_tts.configured_synthesis("en", settings, key), listening_tts.VoicevoxConfig)
        with mock.patch.object(voicevox, "available", return_value=False):
            self.assertNotIsInstance(listening_tts.configured_synthesis("ja", settings, key), listening_tts.VoicevoxConfig)

    def test_japanese_read_aloud_uses_the_saved_voice(self):
        voice = character_voice.DEFAULTS.model_copy(deep=True)
        voice.ja.style = 91
        character_voice.save(voice)
        with mock.patch.object(voicevox, "available", return_value=True):
            config, speaker, timbre = chat._speech_profile("ja", "糖糖（あめ）")
        self.assertIsInstance(config, listening_tts.VoicevoxConfig)
        self.assertEqual(config.styles[speaker], 91)
        self.assertIsNone(timbre)

    def test_no_engine_path_means_unavailable(self):
        with mock.patch.dict("os.environ", {"LANGPAL_VOICEVOX_ENGINE": ""}):
            self.assertFalse(voicevox.available())
        with mock.patch.dict("os.environ", {"LANGPAL_VOICEVOX_ENGINE": str(Path(self.temp.name) / "missing.exe")}):
            self.assertFalse(voicevox.available())


if __name__ == "__main__":
    unittest.main()
