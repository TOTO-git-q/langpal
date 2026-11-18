"""Explicit smoke render against the already installed local Kokoro model."""
import io
import json
import struct
import wave
from pathlib import Path

from app.services.listening_tts import KokoroConfig, synthesize
from app.services.listening_formats import Line

root = Path(__file__).resolve().parents[3]
assets = root / 'kokoro-models'
python = root / 'kokoro-runtime' / 'Scripts' / 'python.exe'
output = Path(__file__).resolve().parents[2] / 'voice-evidence'
output.mkdir(exist_ok=True)
results = {}
for language, voices, lines in (
    ('en', {'A':'af_heart','B':'am_michael'}, ['The library opens at nine today.', 'Great. I will bring the books after breakfast.']),
    ('ja', {'A':'jf_alpha','B':'jm_kumo'}, ['図書館は、今日は九時に開きます。', 'わかりました。朝ごはんのあとで本を持っていきます。']),
):
    config = KokoroConfig(python, assets, voices, .9, 450, .8, 1.1)
    timings = []
    audio = synthesize(config, language, [Line(speaker='A' if i == 0 else 'B', text=text) for i,text in enumerate(lines)], timings=timings)
    path = output / f'kokoro-settings-{language}.wav'
    path.write_bytes(audio)
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        samples = struct.unpack('<'+'h'*wav.getnframes(), wav.readframes(wav.getnframes()))
        duration = wav.getnframes() / wav.getframerate()
    assert len(timings) == 2 and abs(timings[1]['start']-timings[0]['end']-.45)<.0001
    assert any(samples) and all(-32768 < sample < 32767 for sample in samples)
    results[language] = {'path':str(path),'voices':voices,'speed_a':.9,'speed_b':1.1,'pause_ms':450,'volume':.8,
                         'duration':round(duration,3),'timings':timings,'peak':max(abs(value) for value in samples),'clipped':sum(abs(value)>=32767 for value in samples)}
(output/'kokoro-settings-audio.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
