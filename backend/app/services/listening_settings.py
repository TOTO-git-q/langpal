"""Stored listening-voice preferences, separate from text authoring settings."""
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from ..db import get_conn
from .languages import LanguageTag
from .provider_urls import service_url
from .voice_secrets import seal, open_secret

CONFIG_KEY = "listening_synthesis"
API_KEY = "listening_synthesis_api_key"


class Voices(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    a: str = Field(min_length=1, max_length=100)
    b: str = Field(min_length=1, max_length=100)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    speed_b: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch_b: float | None = Field(default=None, ge=-6, le=6)


class VoicevoxVoices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int = Field(default=49, ge=0, le=2147483647, strict=True)
    b: int = Field(default=2, ge=0, le=2147483647, strict=True)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    speed_b: float | None = Field(default=None, ge=0.5, le=2.0)


class SynthesisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Literal["kokoro", "compatible"] = "kokoro"
    kokoro_en: Voices = Field(default_factory=lambda: Voices(a="af_heart", b="af_nicole"))
    kokoro_ja: Voices = Field(default_factory=lambda: Voices(a="jf_alpha", b="jf_alpha", pitch_b=-2.5))
    voicevox_ja: VoicevoxVoices | None = None
    api_en: Voices = Field(default_factory=lambda: Voices(a="alloy", b="echo"))
    api_ja: Voices = Field(default_factory=lambda: Voices(a="alloy", b="echo"))
    api_languages: dict[LanguageTag, Voices] = Field(default_factory=dict, max_length=28)
    base_url: str = Field(default="", max_length=300)
    model: str = Field(default="", max_length=256)
    pause_ms: int = Field(default=300, ge=0, le=1500)
    volume: float = Field(default=1.0, ge=0.25, le=1.5)

    def japanese_voicevox(self) -> VoicevoxVoices:
        if self.voicevox_ja is not None:
            return self.voicevox_ja
        previous = self.kokoro_ja if self.provider == "kokoro" else self.api_ja
        return VoicevoxVoices(speed=previous.speed, speed_b=previous.speed_b)

    @field_validator("base_url")
    @classmethod
    def normalize_base(cls, value: str) -> str:
        return service_url(value) if value else value

    @model_validator(mode="after")
    def validate_provider(self):
        if self.provider == "compatible" and (not self.base_url or not self.model):
            raise ValueError("请填写合成服务地址和模型")
        return self


class SynthesisUpdate(SynthesisSettings):
    api_key: SecretStr | None = Field(default=None, max_length=1024)


def _load(conn, *, ignore_key_errors=True) -> tuple[SynthesisSettings, str]:
    rows = dict(conn.execute("SELECT key, value FROM settings WHERE key IN (?, ?)", (CONFIG_KEY, API_KEY)))
    try:
        config = SynthesisSettings.model_validate_json(rows.get(CONFIG_KEY, "{}"))
    except ValueError:
        return SynthesisSettings(), ""
    if config.kokoro_en.b == "am_michael":
        config.kokoro_en.b = "af_nicole"
    if config.kokoro_ja.b == "jm_kumo":
        config.kokoro_ja.b = "jf_alpha"
        if config.kokoro_ja.pitch_b is None:
            config.kokoro_ja.pitch_b = -2.5
    try:
        key = open_secret(rows.get(API_KEY, ""))
    except ValueError:
        if not ignore_key_errors:
            raise
        key = ''
    return config, key


def load() -> tuple[SynthesisSettings, str]:
    with closing(get_conn()) as conn:
        return _load(conn)


def save(update: SynthesisUpdate) -> tuple[SynthesisSettings, str]:
    config = SynthesisSettings.model_validate(update.model_dump(exclude={"api_key"}))
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        old, old_key = _load(conn, ignore_key_errors=update.api_key is not None)
        if update.api_key is None:
            key = old_key if config.base_url == old.base_url else ""
        else:
            key = update.api_key.get_secret_value().strip()
            if any(not 32 < ord(char) < 127 for char in key):
                raise ValueError("密钥格式无效")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (CONFIG_KEY, config.model_dump_json()))
        if key:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (API_KEY, seal(key)))
        else:
            conn.execute("DELETE FROM settings WHERE key = ?", (API_KEY,))
    return config, key
