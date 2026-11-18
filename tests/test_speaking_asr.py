"""The speaking page asks the local recognition service whether its model is there, and starts the download.

Written by the project lead. The recognition service is faked; no network."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.routers import speaking


class Service:
    """Answers like asr/service.py: GET /health, POST /download."""
    def __init__(self, health, after_download=None, down=False):
        self.health, self.after_download, self.down, self.calls = health, after_download, down, []

    def handler(self, request):
        self.calls.append((request.method, request.url.path))
        if self.down:
            raise httpx.ConnectError('refused')
        if request.method == 'POST' and request.url.path == '/download':
            self.health = self.after_download or self.health
        return httpx.Response(200, json=self.health)


class Asr(unittest.TestCase):
    def run_with(self, service, call):
        real = httpx.AsyncClient

        def client(*args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(service.handler)
            return real(*args, **kwargs)
        with patch.object(speaking.httpx, 'AsyncClient', client):
            return asyncio.run(call)

    def test_a_missing_model_is_reported_and_the_download_starts_on_request(self):
        service = Service({'ready': False, 'missing': True, 'downloading': False, 'total_bytes': None},
                          after_download={'ready': False, 'missing': True, 'downloading': True,
                                          'downloaded_bytes': 1048576, 'total_bytes': 1620000000})

        class Reply:
            headers = {}
        status = self.run_with(service, speaking.asr_status(Reply()))
        self.assertEqual(status, {'running': True, 'ready': False, 'missing': True, 'downloading': False,
                                  'downloaded': None, 'total': None, 'failed': False})
        started = self.run_with(service, speaking.asr_download())
        self.assertEqual((started['downloading'], started['downloaded'], started['total']), (True, 1048576, 1620000000))
        self.assertEqual(service.calls, [('GET', '/health'), ('POST', '/download')])

    def test_a_ready_model_and_a_service_that_is_not_running(self):
        class Reply:
            headers = {}
        ready = self.run_with(Service({'ready': True, 'missing': False, 'downloading': False}), speaking.asr_status(Reply()))
        self.assertEqual((ready['running'], ready['ready'], ready['failed']), (True, True, False))
        self.assertEqual(self.run_with(Service({}, down=True), speaking.asr_status(Reply())), {'running': False})

    def test_a_failed_download_is_shown_as_failed(self):
        class Reply:
            headers = {}
        failed = self.run_with(Service({'ready': False, 'missing': True, 'downloading': False, 'error': 'OSError: no space'}),
                               speaking.asr_status(Reply()))
        self.assertTrue(failed['failed'])


if __name__ == '__main__':
    unittest.main()
