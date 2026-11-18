"""CPU synthesis worker, run in the separate TTS Python environment.

Two ways to run it:
- `python listening_kokoro.py ASSETS OUTPUT` renders one exercise read from stdin (one-shot);
- `python listening_kokoro.py --serve` stays up: one JSON request per stdin line
  ({"assets", "output", "exercise"}), one reply line per request prefixed with REPLY.
  The model and the G2P pipelines are loaded once and reused. The process exits when
  stdin closes (the backend went away) or when it is told {"quit": true}.
"""
import json
import os
import re
import sys
import wave
from pathlib import Path

REPLY = "@@LANGPAL-TTS@@ "
_loaded = {}


def _model(assets: Path):
    import torch
    from kokoro import KModel

    key = str(assets)
    if key not in _loaded:
        torch.set_num_threads(int(os.environ.get("LANGPAL_TTS_THREADS", "4")))
        _loaded.clear()
        _loaded[key] = {"model": KModel(repo_id="hexgrad/Kokoro-82M", config=str(assets / "config.json"),
                                        model=str(assets / "kokoro-v1_0.pth")).eval(), "pipelines": {}}
    return _loaded[key]


def _resample_pitch(audio, ratio):
    """Resample a chunk to the exact sample count used by duration and timings."""
    if ratio == 1 or not len(audio):
        return audio
    import numpy as np

    count = round(len(audio) / ratio)
    return np.interp(np.arange(count) * ratio, np.arange(len(audio)), audio).astype(audio.dtype)


def render(assets: Path, output: Path, exercise: dict) -> None:
    if exercise["language"] == "en":
        import spacy

        if not spacy.util.is_package("en_core_web_sm"):
            raise RuntimeError("Install the English G2P model before starting the server")
    import torch
    from kokoro import KPipeline

    sample_rate = 24_000
    repo = "hexgrad/Kokoro-82M"
    state = _model(assets)
    model, pipelines = state["model"], state["pipelines"]
    voices = exercise["voices"]
    frames = 0
    timings = []
    with torch.inference_mode(), wave.open(str(output), "wb") as wav:
        wav.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
        for index, line in enumerate(exercise["lines"]):
            voice = voices[line["speaker"]]
            lang_code = voice[0]
            if lang_code not in pipelines:
                pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=repo, model=model, device="cpu")
            pipeline = pipelines[lang_code]
            if index:
                gap = sample_rate * exercise.get('pause_ms', 300) // 1000
                wav.writeframesraw(bytes(gap * 2))
                frames += gap
            start = frames / sample_rate
            text = line["text"]
            # One chunk per sentence, so each sentence's place in the audio is known exactly
            # (close listening replays and dictates single sentences, not whole turns).
            splitter = r"(?<=[.!?])\s+(?=[\"'A-Z0-9])" if exercise["language"] == "en" else r"(?<=[。！？!?])"
            chunks = [chunk.strip() for chunk in re.split(splitter, text) if chunk.strip()]
            if exercise["language"] == "ja" and any(len(pipeline.g2p(chunk)[0] or "") > 500 for chunk in chunks):
                raise ValueError("Japanese segment would be truncated")
            produced = False
            speed = exercise.get('speed_b') if line['speaker'] == 'B' else None
            speed = speed or exercise.get("speed", 1.0)
            pitch = exercise.get('pitch_b') if line['speaker'] == 'B' else None
            ratio = 2 ** ((pitch or 0) / 12)
            parts = []
            for chunk in chunks:
                part_start = frames
                for result in pipeline(chunk, voice=str(assets / "voices" / f"{voice}.pt"), speed=speed / ratio):
                    audio = result.audio
                    if audio is None or not audio.numel():
                        continue
                    if not torch.isfinite(audio).all():
                        raise ValueError("Non-finite audio")
                    if ratio != 1:
                        audio = torch.from_numpy(_resample_pitch(audio.cpu().numpy(), ratio))
                    frames += audio.numel()
                    if frames > sample_rate * 240:
                        raise ValueError("Audio exceeds duration limit")
                    pcm = ((audio * exercise.get('volume', 1.0)).clamp(-1, 1) * 32767).to(torch.int16).cpu().numpy().astype("<i2")
                    wav.writeframesraw(pcm.tobytes())
                    produced = True
                if frames > part_start:
                    parts.append({"start": part_start / sample_rate, "end": frames / sample_rate, "text": chunk})
            if not produced:
                raise ValueError("A line produced no audio")
            timings.append({"start": start, "end": frames / sample_rate, "parts": parts})
    if exercise.get("timestamps"):
        output.with_suffix(".json").write_text(json.dumps(timings), encoding="utf-8")


def serve() -> None:
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr  # library prints must not mix with replies
    protocol.write(REPLY + json.dumps({"ready": True}) + "\n")
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            request = json.loads(raw)
            if request.get("quit"):
                break
            if request.get("warm"):
                _model(Path(request["assets"]))
            else:
                render(Path(request["assets"]), Path(request["output"]), request["exercise"])
            reply = {"ok": True}
        except Exception as error:  # reported to the backend; the process stays usable
            reply = {"ok": False, "error": f"{type(error).__name__}: {error}"[:300]}
        protocol.write(REPLY + json.dumps(reply) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
    else:
        render(Path(sys.argv[1]), Path(sys.argv[2]), json.load(sys.stdin))
