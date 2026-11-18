"""Every study route (reading, listening, courses, review, storage, voice) checks the request origin."""
import sys
import unittest
from pathlib import Path

from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import security
from app.routers import (furigana, learning, notebook, listening, reader_bridge, reader_zotero, reading, reading_sources, review, speaking, study_storage,
                         teaching, voice_settings)

GUARDS = {security.same_origin, security.local_request}


def guarded(dependant):
    return dependant.call in GUARDS or any(guarded(child) for child in dependant.dependencies)


class OriginGuards(unittest.TestCase):
    def test_every_route_has_a_guard(self):
        modules = [furigana, learning, notebook, listening, reader_bridge, reader_zotero, reading, reading_sources, review, speaking, study_storage, teaching, voice_settings]
        missing = [f'{module.__name__}:{",".join(route.methods)} {route.path}'
                   for module in modules for route in module.router.routes
                   if isinstance(route, APIRoute) and not guarded(route.dependant)]
        self.assertEqual(missing, [])

    def test_bridge_and_zotero_require_loopback_not_just_origin(self):
        def local(dependant):
            return dependant.call is security.local_request or any(local(child) for child in dependant.dependencies)
        for module in (reader_bridge, reader_zotero, speaking, voice_settings):
            for route in module.router.routes:
                self.assertTrue(local(route.dependant), f'{module.__name__} {route.path}')


if __name__ == '__main__':
    unittest.main()
