"""Isolated fixtures for the course kernel; no provider or application startup."""
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import db
from app.services import clock, course

START = datetime(2026, 11, 13, 10)
TEXT = '予定が変わると準備ができないので、先に確認してください。'


def event(outline, n=1, *, point=0, unit=0, at=START, result='success', context='a', channel='lesson', **extra):
    unit = course.lessons.available(outline)[unit][1]
    point = unit.points[point]
    return {'id': n, 'at': clock.stamp(at), 'language': outline.language, 'course_id': outline.id,
            'unit_id': unit.id, 'point_id': point.id, 'point_key': course.point_key(outline, unit.id, point.id),
            'result': result, 'context': context, 'channel': channel, 'ref': 'event-' + str(n),
            'quote': TEXT, **extra}



class DatabaseFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'course.db'
        directory = ROOT / 'tests' / 'fixtures' / 'lessons'
        guard = patch.object(course.lessons, 'DIRECTORY', directory)
        guard.start()
        self.addCleanup(guard.stop)
        self.addCleanup(course.lessons.reload)
        course.lessons.reload()
        original = course.lessons.courses()['toefl-2026']
        self.outline = original.model_copy(update={'language': 'ja', 'sections': [
            original.sections[0].model_copy(update={'lessons': original.sections[0].lessons[:2]})]})
        self.units = [unit for _, unit in course.lessons.available(self.outline)]
        guard = patch.object(course.content, 'presets', return_value={self.outline.id: self.outline})
        guard.start()
        self.addCleanup(guard.stop)
        self.now = START
        self.guard = patch.object(db, 'DB_PATH', self.path)
        self.guard.start()
        self.addCleanup(self.guard.stop)
        guard = patch.object(clock, 'now', lambda: self.now)
        guard.start()
        self.addCleanup(guard.stop)
        with closing(db.get_conn()) as conn, conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
            course.save_language_settings(conn, 'ja', course.Teaching(mode='ambient', preset=self.outline.id))

    def connect(self):
        return db.get_conn()

    def write(self, *rows):
        with closing(self.connect()) as conn, conn:
            return course.ledger.write(conn, self.outline, rows, now=self.now)

    def rows(self):
        with closing(self.connect()) as conn:
            return course.ledger.read(conn, self.outline)
