"""Listening synthesis through local VOICEVOX, Kokoro or an explicit compatible endpoint."""
import atexit
import io
import os
import queue
import re
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from json import dumps, loads
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx

from . import voicevox
from .listening_formats import Language, Line
from .listening_settings import SynthesisSettings

KOKORO_VOICES = {
    "en": {"A": "af_heart", "B": "af_nicole"},
    "ja": {"A": "jf_alpha", "B": "jf_alpha"},
}
SAMPLE_RATE = 24000
MAX_AUDIO_BYTES = 12_000_000
JAPANESE_DICTIONARY = "open_jtalk_dic_utf_8-1.11"


@dataclass(frozen=True)
class KokoroConfig:
    python: Path
    assets: Path
    voices: dict[str, str]
    speed: float
    pause_ms: int = 300
    volume: float = 1.0
    speed_b: float | None = None
    pitch_b: float | None = None


@dataclass(frozen=True, repr=False)
class CompatibleConfig:
    base_url: str
    key: str
    model: str
    voices: dict[str, str]
    speed: float
    pause_ms: int = 300
    volume: float = 1.0
    speed_b: float | None = None


@dataclass(frozen=True)
class VoicevoxConfig:
    styles: dict[str, int]
    params: dict
    pause_ms: int = 300
    speed_b: float | None = None


def valid_kokoro_voice(language: Language, voice: str) -> bool:
    if language not in KOKORO_VOICES:
        return False
    prefix = "[ab]" if language == "en" else "j"
    return bool(re.fullmatch(prefix + r"[fm]_[a-z][a-z0-9_]{0,40}", voice))


def kokoro_voices(language: Language) -> list[str]:
    assets = Path(os.environ.get("LANGPAL_LISTENING_TTS_ASSETS", ""))
    if not assets.is_absolute():
        return []
    return sorted(file.stem for file in (assets / "voices").glob("*.pt")
                  if valid_kokoro_voice(language, file.stem) and file.is_file())


def configured(language: Language, voices=None, speed=1.0, *, pause_ms=300, volume=1.0, speed_b=None, pitch_b=None) -> KokoroConfig | None:
    python = Path(os.environ.get("LANGPAL_LISTENING_TTS_PYTHON", ""))
    assets = Path(os.environ.get("LANGPAL_LISTENING_TTS_ASSETS", ""))
    if not python.is_absolute() or not assets.is_absolute() or not python.is_file():
        return None
    if voices is None:
        voices = KOKORO_VOICES[language]
        if language == "ja" and pitch_b is None:
            pitch_b = -2.5
    if not all(valid_kokoro_voice(language, voice) for voice in voices.values()):
        return None
    files = [assets / "config.json", assets / "kokoro-v1_0.pth"]
    files.extend(assets / "voices" / f"{voice}.pt" for voice in voices.values())
    if language == "ja":
        files.append(assets / JAPANESE_DICTIONARY / "sys.dic")
    return KokoroConfig(python, assets, voices, speed, pause_ms, volume, speed_b, pitch_b) if all(file.is_file() for file in files) else None


def configured_voicevox(language: Language, settings: SynthesisSettings) -> VoicevoxConfig | None:
    if language != "ja" or not voicevox.available():
        return None
    voice = settings.japanese_voicevox()
    return VoicevoxConfig(
        {"A": voice.a, "B": voice.b, "C": 8, "D": 14, "E": 20, "F": 10},
        {"speedScale": voice.speed, "volumeScale": settings.volume}, settings.pause_ms, voice.speed_b,
    )


def configured_synthesis(language: Language, settings: SynthesisSettings, key: str):
    if config := configured_voicevox(language, settings):
        return config
    if settings.provider == "kokoro":
        if language not in KOKORO_VOICES:
            return None
        voice = getattr(settings, f"kokoro_{language}")
        return configured(language, {"A": voice.a, "B": voice.b}, voice.speed,
                          pause_ms=settings.pause_ms, volume=settings.volume, speed_b=voice.speed_b, pitch_b=voice.pitch_b)
    voice = getattr(settings, f"api_{language}", None) or settings.api_languages.get(language)
    if voice is None:
        return None
    if urlsplit(settings.base_url).hostname == "api.openai.com" and not key:
        return None
    return CompatibleConfig(settings.base_url, key, settings.model, {"A": voice.a, "B": voice.b}, voice.speed,
                            settings.pause_ms, settings.volume, voice.speed_b)


def _worker_environment():
    # A synthesis worker doesn't need Claude, OpenAI, proxy or provider settings.
    environment = {
        key: os.environ[key]
        for key in (
            "SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "TMPDIR",
            "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
            "ESPEAK_DATA_PATH", "PHONEMIZER_ESPEAK_LIBRARY",
        )
        if key in os.environ
    }
    environment.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "2",
    })
    return environment


def _wav_pcm(audio: bytes) -> bytes:
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("WAV file exceeds permitted size")
    with wave.open(io.BytesIO(audio), "rb") as stream:
        frames = stream.getnframes()
        if (stream.getnchannels() != 1 or stream.getsampwidth() != 2
                or stream.getframerate() != SAMPLE_RATE or not 0 < frames <= SAMPLE_RATE * 240):
            raise ValueError("Invalid or truncated listening WAV")
        pcm = stream.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError("Invalid or truncated listening WAV")
        return pcm


def validate_wav(audio: bytes) -> None:
    _wav_pcm(audio)


def _scale_pcm(pcm: bytes, volume: float) -> bytes:
    if volume == 1:
        return pcm
    from array import array
    from sys import byteorder
    values = array('h', pcm)
    if byteorder != 'little':
        values.byteswap()
    for index, value in enumerate(values):
        values[index] = max(-32768, min(32767, round(value * volume)))
    if byteorder != 'little':
        values.byteswap()
    return values.tobytes()


def _synthesize_compatible(config: CompatibleConfig, lines: list[Line], timings: list | None = None) -> bytes:
    official = urlsplit(config.base_url).hostname == "api.openai.com"
    headers = {"Authorization": f"Bearer {config.key}"} if config.key else {}
    deadline = monotonic() + 150
    pcm = bytearray()
    max_pcm = SAMPLE_RATE * 240 * 2
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        for line in lines:
            if monotonic() >= deadline:
                raise TimeoutError("Listening synthesis timed out")
            voice = config.voices[line.speaker]
            payload = {"input": line.text, "model": config.model,
                       "voice": {"id": voice} if official and voice.startswith("voice_") else voice,
                       "speed": config.speed_b if line.speaker == 'B' and config.speed_b is not None else config.speed,
                       "response_format": "pcm" if official else "wav"}
            with client.stream("POST", f"{config.base_url}/audio/speech", headers=headers, json=payload) as response:
                response.raise_for_status()
                audio = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    audio.extend(chunk)
                    if len(audio) > MAX_AUDIO_BYTES or monotonic() >= deadline:
                        raise ValueError("Listening synthesis exceeded its output or time limit")
            segment = bytes(audio) if official else _wav_pcm(bytes(audio))
            if not segment or len(segment) % 2:
                raise ValueError("Invalid listening audio")
            if pcm:
                pcm.extend(bytes(SAMPLE_RATE * config.pause_ms // 1000 * 2))
            start = len(pcm) // 2 / SAMPLE_RATE
            pcm.extend(_scale_pcm(segment, config.volume))
            if len(pcm) > max_pcm:
                raise ValueError("Audio exceeds duration limit")
            if timings is not None:
                timings.append({"start": start, "end": len(pcm) // 2 / SAMPLE_RATE})
    return _pcm_wav(pcm)


def _pcm_wav(pcm: bytes | bytearray) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        stream.writeframes(pcm)
    audio = output.getvalue()
    validate_wav(audio)
    return audio


def _synthesize_voicevox(config: VoicevoxConfig, lines: list[Line], timings: list | None) -> bytes:
    pcm = bytearray()
    segments = []
    for line in lines:
        params = config.params
        if line.speaker == "B" and config.speed_b is not None:
            params = {**params, "speedScale": config.speed_b}
        segment = _wav_pcm(voicevox.synthesize(line.text, config.styles[line.speaker], params))
        if pcm:
            pcm.extend(bytes(SAMPLE_RATE * config.pause_ms // 1000 * 2))
        start = len(pcm) // 2 / SAMPLE_RATE
        pcm.extend(segment)
        if len(pcm) > SAMPLE_RATE * 240 * 2:
            raise ValueError("Audio exceeds duration limit")
        segments.append({"start": start, "end": len(pcm) // 2 / SAMPLE_RATE})
    audio = _pcm_wav(pcm)
    if timings is not None:
        timings.extend(segments)
    return audio


WORKER = Path(__file__).with_name("listening_kokoro.py")
REPLY = "@@LANGPAL-TTS@@ "
IDLE_SECONDS = 600
REQUEST_SECONDS = 150


class KokoroWorker:
    """One resident Kokoro process: started on first use, reused, stopped after 10 idle minutes.

    Loading the model costs 20-40 s, so keeping it saves that on every practice. Requests are
    serialized (one synthesis at a time; others wait on the lock). A crash, a timeout or a
    garbled reply kills the process; the next request starts a fresh one.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.key = None
        self.replies: queue.Queue = queue.Queue()
        self.last_used = 0.0
        self.timer = None

    def _start(self, config: KokoroConfig):
        self._stop()
        environment = _worker_environment()
        environment["OPEN_JTALK_DICT_DIR"] = str(config.assets / JAPANESE_DICTIONARY)
        self.process = subprocess.Popen(
            [str(config.python), "-I", "-X", "utf8", str(WORKER), "--serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.key = (str(config.python), str(config.assets))
        self.replies = replies = queue.Queue()
        stdout = self.process.stdout

        def pump():
            for line in stdout:
                if line.startswith(REPLY):
                    replies.put(line[len(REPLY):])
            replies.put(None)
        threading.Thread(target=pump, daemon=True, name="kokoro-replies").start()
        self._reply(60, "Kokoro worker did not start")

    def _reply(self, timeout, message):
        try:
            raw = self.replies.get(timeout=timeout)
        except queue.Empty:
            raw = None
        if raw is None:
            self._stop()
            raise RuntimeError(message)
        return loads(raw)

    def _stop(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                process.stdin.close()
                process.wait(timeout=3)
            except Exception:
                process.kill()  # this process only, by its handle
        self.key = None

    def stop(self):
        with self.lock:
            self._stop()

    def _schedule_idle_stop(self):
        if self.timer is not None:
            self.timer.cancel()
        self.timer = threading.Timer(IDLE_SECONDS + 1, self._idle_check)
        self.timer.daemon = True
        self.timer.start()

    def _idle_check(self):
        if self.lock.acquire(blocking=False):
            try:
                if monotonic() - self.last_used >= IDLE_SECONDS:
                    self._stop()
            finally:
                self.lock.release()

    @property
    def pid(self):
        return self.process.pid if self.process is not None and self.process.poll() is None else None

    def request(self, config: KokoroConfig, body: dict) -> None:
        with self.lock:
            if self.pid is None or self.key != (str(config.python), str(config.assets)):
                self._start(config)
            try:
                self.process.stdin.write(dumps({"assets": str(config.assets), **body}, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except OSError:
                self._stop()
                raise RuntimeError("Kokoro worker stopped") from None
            reply = self._reply(REQUEST_SECONDS, "Kokoro worker timed out or stopped")
            self.last_used = monotonic()
            self._schedule_idle_stop()
            if not reply.get("ok"):
                raise RuntimeError(reply.get("error") or "Kokoro synthesis failed")


worker = KokoroWorker()
atexit.register(worker.stop)


def warm(config) -> None:
    """Start the resident worker and load the model while the script is still being written."""
    if isinstance(config, KokoroConfig):
        worker.request(config, {"warm": True})
    elif isinstance(config, VoicevoxConfig):
        voicevox.warm()


def synthesize(config: KokoroConfig | CompatibleConfig | VoicevoxConfig, language: Language,
               lines: list[Line], *, timings: list | None = None) -> bytes:
    if isinstance(config, CompatibleConfig):
        return _synthesize_compatible(config, lines, timings)
    if isinstance(config, VoicevoxConfig):
        return _synthesize_voicevox(config, lines, timings)
    payload = {
        "language": language, "voices": config.voices, "speed": config.speed,
        "speed_b": config.speed_b, "pitch_b": config.pitch_b, "pause_ms": config.pause_ms, "volume": config.volume,
        "lines": [line.model_dump() for line in lines], "timestamps": timings is not None,
    }
    with tempfile.TemporaryDirectory(prefix="langpal-listen-") as directory:
        output = Path(directory) / "exercise.wav"
        worker.request(config, {"output": str(output), "exercise": payload})
        if output.stat().st_size > MAX_AUDIO_BYTES:
            raise ValueError("WAV file exceeds permitted size")
        audio = output.read_bytes()
        validate_wav(audio)
        if timings is not None:
            timings.extend(loads(output.with_suffix(".json").read_text(encoding="utf-8")))
        return audio
