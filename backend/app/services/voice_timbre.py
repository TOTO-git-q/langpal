"""给角色的朗读声换音色（只改声音质感，不改说话内容、口吻和语速）。

参数来自角色的声音设置或 frontend/assets/live2d/characters.json 里的 `voice`：
- pitch   音高，半音。声音整体抬高（连共鸣一起，听起来更小、更轻）。合成时先按同样比例念慢一点，
          再整体加快回原长，所以语速不变。
- breath  气声，dB（相对人声的音量）。一层跟着人声起落、尾巴拖得比人声长一点的气息噪声，句尾听得出气声。
- nasal   鼻音，dB。1.2 kHz 附近的共鸣抬高。
- close   贴麦，dB。200 Hz 以下抬高一点，再轻压缩，小声的细节（气息）更近。
- rate    语速倍数。换了底子音色（`base`）而那个音色本身念得慢时，用它把语速拉回和原来一样。
- base    底子音色（本机 Kokoro 的音色名），由合成配置选择。

只用 numpy。输入输出都是 16 位单声道 wav。
"""
from __future__ import annotations

import io
import wave
from dataclasses import replace

import numpy as np


def speed_factor(params: dict) -> float:
    """合成时语速要乘的系数（抬高音高之后再加快回原长；再乘上 rate）。"""
    return float(params.get("rate", 1) or 1) / _ratio(params)


def synthesize(config, language, lines, params: dict) -> bytes:
    from . import listening_tts

    config = replace(config, speed=config.speed * speed_factor(params))
    return apply(listening_tts.synthesize(config, language, lines), params)


def _ratio(params: dict) -> float:
    return float(2 ** (float(params.get("pitch", 0) or 0) / 12))


def _read(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("only 16-bit mono wav")
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    return pcm, rate


def _write(x: np.ndarray, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def _shape(x: np.ndarray, rate: int, gain_db) -> np.ndarray:
    """零相位地按频率改音量：gain_db(freqs) -> dB。"""
    n = len(x)
    spec = np.fft.rfft(x, n)
    freqs = np.fft.rfftfreq(n, 1 / rate)
    return np.fft.irfft(spec * 10 ** (gain_db(freqs) / 20), n)


def _envelope(x: np.ndarray, rate: int, attack: float, release: float) -> np.ndarray:
    a, r = np.exp(-1 / (attack * rate)), np.exp(-1 / (release * rate))
    env = np.empty_like(x)
    level = 0.0
    for i, v in enumerate(np.abs(x)):            # 一阶跟随，起得快、落得慢
        k = a if v > level else r
        level = k * level + (1 - k) * v
        env[i] = level
    return env


def _envelope_fast(x: np.ndarray, rate: int, attack: float, release: float) -> np.ndarray:
    # 先降采样到 1 kHz 再跟随，避免逐样本的 Python 循环太慢
    hop = max(1, rate // 1000)
    blocks = np.abs(x[: len(x) // hop * hop]).reshape(-1, hop).max(axis=1)
    env = _envelope(blocks, 1000, attack, release)
    return np.interp(np.arange(len(x)) / hop, np.arange(len(env)), env)


def apply(data: bytes, params: dict, seed: int = 7) -> bytes:
    x, rate = _read(data)
    if not len(x):
        return data
    loud = np.sqrt(np.mean(x ** 2))
    ratio = _ratio(params)
    if abs(ratio - 1) > 1e-3:
        # 抬高前先把会超过奈奎斯特的高频去掉，再按比例重采样（时长缩短 ratio 倍，音高和共鸣抬高 ratio 倍）
        cut = rate / 2 / ratio * 0.97
        x = _shape(x, rate, lambda f: np.where(f > cut, -120.0, 0.0))
        x = np.interp(np.arange(0, len(x) - 1, ratio), np.arange(len(x)), x)
    nasal, close = float(params.get("nasal", 0) or 0), float(params.get("close", 0) or 0)
    if nasal or close:
        def eq(f):
            g = nasal * np.exp(-0.5 * (np.log2(np.maximum(f, 1) / 1200) / 0.45) ** 2)   # 1.2 kHz 附近的鼓包，约 ±0.5 个八度
            g = g - 0.35 * nasal * np.exp(-0.5 * (np.log2(np.maximum(f, 1) / 3800) / 0.5) ** 2)   # 3–4 kHz 稍收，鼻音更明显、不刺
            g = g + close / (1 + (np.maximum(f, 1) / 200) ** 2)                            # 200 Hz 以下的贴麦感
            return g
        x = _shape(x, rate, eq)
    breath = params.get("breath")
    if breath is not None:
        rng = np.random.default_rng(seed)
        noise = _shape(rng.standard_normal(len(x)), rate,
                       lambda f: np.where((f > 1800) & (f < 9500), 0.0, -60.0) - 3 * np.log2(np.maximum(f, 1800) / 1800))
        env = _envelope_fast(x, rate, 0.005, 0.18)                 # 落得比人声慢：句尾留一口气
        noise *= env
        # breath 就是气声和人声的音量差（整段的均方根）
        noise *= np.sqrt(np.mean(x ** 2)) * 10 ** (float(breath) / 20) / (np.sqrt(np.mean(noise ** 2)) + 1e-12)
        x = x + noise
    if close:
        # 轻压缩：-26 dBFS 以上 2:1，小声的部分相对更近
        env = _envelope_fast(x, rate, 0.004, 0.08) + 1e-6
        thr = 10 ** (-26 / 20)
        gain = np.where(env > thr, (env / thr) ** (-0.5), 1.0)
        x = x * gain
    x = x * (loud / (np.sqrt(np.mean(x ** 2)) + 1e-9))               # 响度和处理前一样（用户在设置里调过音量）
    peak = np.max(np.abs(x))
    if peak > 0.89:
        x = x * (0.89 / peak)                                          # 峰值不超过 -1 dBFS
    return _write(x, rate)
