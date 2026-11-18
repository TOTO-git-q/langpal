"""糖糖朗读的音色：characters.json 的 voice 按语言覆盖、底子音色（base）只在本机有这个文件时才换。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.routers import chat  # noqa: E402
from app.services import listening_tts as tts  # noqa: E402


class CharacterVoiceTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="lp-voice-"))
        self.characters = self.dir / "characters.json"
        self.characters.write_text(json.dumps({"ame": {"match": ["糖糖"], "voice": {
            "pitch": 1.8, "breath": -22, "en": {"base": "af_nicole", "pitch": 1.0}}}}), encoding="utf-8")
        patcher = mock.patch.object(chat, "_CHARACTERS", self.characters)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.dir / "voices").mkdir()
        self.config = tts.KokoroConfig(Path("python"), self.dir, {"A": "af_heart", "B": "am_michael"}, 1.0)

    def test_language_entry_overrides_the_shared_one(self):
        self.assertEqual(chat._character_voice("糖糖", "en"), {"pitch": 1.0, "breath": -22, "base": "af_nicole"})
        self.assertEqual(chat._character_voice("糖糖", "ja"), {"pitch": 1.8, "breath": -22})
        self.assertIsNone(chat._character_voice("Emma", "en"))

    def test_base_voice_is_used_only_when_the_file_is_there(self):
        timbre = chat._character_voice("糖糖", "en")
        self.assertEqual(chat._with_base(self.config, "en", "A", timbre).voices["A"], "af_heart")
        (self.dir / "voices" / "af_nicole.pt").write_bytes(b"x")
        config = chat._with_base(self.config, "en", "A", timbre)
        self.assertEqual(config.voices, {"A": "af_nicole", "B": "am_michael"})

    def test_base_voice_must_fit_the_language_and_provider(self):
        (self.dir / "voices" / "af_nicole.pt").write_bytes(b"x")
        timbre = {"base": "af_nicole"}
        self.assertIs(chat._with_base(self.config, "ja", "A", timbre), self.config)
        compatible = tts.CompatibleConfig("https://speech.example/v1", "k", "m", {"A": "a", "B": "b"}, 1.0)
        self.assertIs(chat._with_base(compatible, "en", "A", timbre), compatible)
        self.assertIs(chat._with_base(self.config, "en", "A", {"base": "../evil"}), self.config)

    def test_rate_multiplies_the_synthesis_speed(self):
        from app.services import voice_timbre
        self.assertAlmostEqual(voice_timbre.speed_factor({"pitch": 12, "rate": 1.3}), 0.65)
        self.assertAlmostEqual(voice_timbre.speed_factor({}), 1.0)


if __name__ == "__main__":
    unittest.main()
