"""Local VOICEVOX engine. In development, set LANGPAL_VOICEVOX_ENGINE to the absolute path to run.exe."""
import atexit
import os
import re
import subprocess
import threading
from concurrent.futures import Future
from pathlib import Path
from time import monotonic

import httpx

_URL = "http://127.0.0.1:50121"
_START_TIMEOUT = 90
_PARAMS = ("speedScale", "pitchScale", "intonationScale", "volumeScale", "pauseLengthScale",
           "prePhonemeLength", "postPhonemeLength")
_lock = threading.Lock()
_stopping = threading.Event()
_process = None
_startup: Future | None = None
_starter: threading.Thread | None = None


class Unavailable(RuntimeError):
    pass


def _engine_path() -> Path | None:
    path = Path(os.environ.get("LANGPAL_VOICEVOX_ENGINE", ""))
    return path if path.is_absolute() and path.is_file() else None


def available() -> bool:
    return _engine_path() is not None


def _probe(client):
    try:
        version = client.get("/version").raise_for_status().json()
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version):
            return None
        # The version alone is a bare string. Check the VOICEVOX catalog as well.
        catalog = client.get("/speakers").raise_for_status().json()
        if isinstance(catalog, list) and catalog and all(
            isinstance(speaker, dict) and {"name", "speaker_uuid", "styles"} <= speaker.keys()
            for speaker in catalog
        ):
            return catalog
    except (httpx.HTTPError, ValueError):
        pass
    return None


def running() -> bool:
    if not available():
        return False
    with _lock:
        if _startup is not None:
            return (_startup.done() and _startup.exception() is None
                    and (_process is None or _process.poll() is None))
    with httpx.Client(base_url=_URL, timeout=0.5, trust_env=False) as client:
        return _probe(client) is not None


def _terminate(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _start(path: Path, startup: Future):
    global _process
    process = None
    try:
        with httpx.Client(base_url=_URL, timeout=0.5, trust_env=False) as client:
            catalog = _probe(client)
            if catalog is None and not _stopping.is_set():
                deadline = monotonic() + _START_TIMEOUT
                process = subprocess.Popen(
                    [str(path), "--host", "127.0.0.1", "--port", "50121", "--cpu_num_threads", "4"],
                    cwd=path.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                while monotonic() < deadline and not _stopping.wait(0.25):
                    if (catalog := _probe(client)) is not None or process.poll() is not None:
                        break
            if catalog is None or _stopping.is_set():
                raise Unavailable("VOICEVOX did not start")
        if process is not None and process.poll() is not None:
            process = None  # Another instance won the port while this one was launching.
        with _lock:
            _process = process
            startup.set_result(catalog)
    except Exception as error:
        try:
            _terminate(process)
        finally:
            startup.set_exception(error)


def _launch() -> Future:
    global _startup, _starter
    path = _engine_path()
    with _lock:
        if path is None or _stopping.is_set():
            raise Unavailable("VOICEVOX engine was not found")
        if _startup is not None and (not _startup.done() or (
            _startup.exception() is None and (_process is None or _process.poll() is None)
        )):
            return _startup
        _startup = Future()
        _starter = threading.Thread(target=_start, args=(path, _startup), daemon=True, name="voicevox-start")
        _starter.start()
        return _startup


def warm() -> None:
    """Start the engine on a background thread."""
    if available():
        _launch()


def speakers() -> list[dict]:
    return _launch().result()


def synthesize(text: str, style_id: int, params: dict) -> bytes:
    speakers()
    with httpx.Client(base_url=_URL, timeout=120, trust_env=False) as client:
        query = client.post("/audio_query", params={"text": text, "speaker": style_id}).raise_for_status().json()
        query.update({key: params[key] for key in _PARAMS if key in params})
        query.update(outputSamplingRate=24000, outputStereo=False)
        return client.post("/synthesis", params={"speaker": style_id}, json=query).raise_for_status().content


def stop() -> None:
    global _process, _startup, _starter
    with _lock:
        _stopping.set()
        starter = _starter
    if starter is not None:
        starter.join()
    with _lock:
        _terminate(_process)
        _process = _startup = _starter = None
        _stopping.clear()


atexit.register(stop)
