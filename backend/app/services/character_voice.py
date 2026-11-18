"""Saved read-aloud voices and their shared synthesis configurations."""
from contextlib import closing

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..db import get_conn
from . import listening_tts

KEY = "character_voice"


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class JapaneseParams(VoiceSettings):
    speedScale: float = Field(ge=0.5, le=2)
    pitchScale: float = Field(ge=-0.15, le=0.15)
    intonationScale: float = Field(ge=0, le=2)
    volumeScale: float = Field(ge=0, le=2)
    pauseLengthScale: float = Field(ge=0, le=2)
    prePhonemeLength: float = Field(ge=0, le=1)
    postPhonemeLength: float = Field(ge=0, le=1)


class JapaneseVoice(VoiceSettings):
    style: int = Field(ge=0, le=2147483647)
    speaker: str = Field(min_length=1, max_length=100)
    style_name: str = Field(min_length=1, max_length=100)
    params: JapaneseParams


class EnglishVoice(VoiceSettings):
    base: str
    rate: float = Field(ge=0.6, le=1.8)
    pitch: float = Field(ge=-12, le=12)
    breath: float = Field(ge=-40, le=0)
    nasal: float = Field(ge=0, le=6)
    close: float = Field(ge=0, le=4)

    @field_validator("base")
    @classmethod
    def validate_base(cls, value):
        if not listening_tts.valid_kokoro_voice("en", value):
            raise ValueError("Invalid Kokoro English voice")
        return value


class CharacterVoice(VoiceSettings):
    ja: JapaneseVoice
    en: EnglishVoice


DEFAULTS = CharacterVoice(
    ja=JapaneseVoice(
        style=49, speaker="ナースロボ＿タイプＴ", style_name="恐怖",
        params=JapaneseParams(speedScale=1.10, pitchScale=0.04, intonationScale=1.45, volumeScale=1.0,
                              pauseLengthScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1),
    ),
    en=EnglishVoice(base="af_nicole", rate=1.34, pitch=5.5, breath=-28, nasal=2, close=1.5),
)


def load() -> CharacterVoice:
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
    if row:
        try:
            return CharacterVoice.model_validate_json(row[0])
        except ValueError:
            pass
    return DEFAULTS


def save(voice: CharacterVoice) -> None:
    with closing(get_conn()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (KEY, voice.model_dump_json()))


def japanese_config(voice: JapaneseVoice) -> listening_tts.VoicevoxConfig:
    return listening_tts.VoicevoxConfig({"A": voice.style}, voice.params.model_dump())


def english_config(voice: EnglishVoice) -> listening_tts.KokoroConfig | None:
    return listening_tts.configured("en", {"A": voice.base})
