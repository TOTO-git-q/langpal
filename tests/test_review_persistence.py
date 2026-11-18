"""No real database, model, or application-startup imports."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import review
from app.routers.review import router


class ReviewPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "review.sqlite"
        self.now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        def connect():
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        self.connect = connect
        with closing(connect()) as conn:
            conn.executescript((ROOT / "backend/db/schema.sql").read_text("utf-8"))
            # Repeated additive schema application must preserve review tables.
            conn.executescript((ROOT / "backend/db/schema.sql").read_text("utf-8"))
            conn.execute("INSERT INTO reading_exercises VALUES (?,?,?,?,?)",
                         ("reading-one", "en", "Title", "", json.dumps({"items": [{"answer": 1, "options": ["a", "b"]}]})))
            conn.execute("INSERT INTO reading_errors(exercise_id,item_index,selected) VALUES ('reading-one',0,0)")
            conn.execute("INSERT INTO listening_error_sets VALUES ('listening-one','ja','Title',?)", (b"audio",))
            conn.execute("INSERT INTO listening_errors(practice_id,item_index,payload_json) VALUES ('listening-one',0,?)",
                         (json.dumps({"answer": 1, "choices": ["a", "b"], "selection": 0}),))
            conn.commit()
        self.patches = [patch.object(review, "get_conn", connect), patch.object(review, "utcnow", lambda: self.now)]
        for p in self.patches: p.start()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def payload(self, **changes):
        return dict(kind="reading", item_id="reading-one", item_index=0, selection=1,
                    mode="independent", attempt_id=str(uuid4()), **{}) | changes

    def submit(self, **changes):
        response = self.client.post("/api/review/attempt", json=self.payload(**changes))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_schedule_no_same_day_or_early_inflation(self):
        first = self.submit()
        self.assertEqual(first["state"]["stage"], 1)
        self.assertEqual(first["state"]["due_at"], "2026-11-11T12:00:00Z")
        for _ in range(3):
            repeated = self.submit()
            self.assertEqual(repeated["state"]["stage"], 1)
            self.assertEqual(repeated["state"]["independent_correct_count"], 1)
        self.now += timedelta(days=1)
        second = self.submit()
        self.assertEqual(second["state"]["stage"], 2)
        self.now += timedelta(days=1)
        early = self.submit()
        self.assertEqual(early["state"]["due_at"], second["state"]["due_at"])
        self.assertEqual(early["state"]["stage"], 2)
        self.assertEqual(early["state"]["independent_correct_count"], 3)
        self.now += timedelta(days=2)
        self.assertEqual(self.submit()["state"]["stage"], 3)

    def test_wrong_or_revealed_first_exposure_blocks_daily_evidence(self):
        for changes in [{"selection": 0}, {"mode": "revealed", "selection": None}]:
            with self.subTest(changes=changes):
                self.now += timedelta(days=1)
                prior = self.submit(**changes)["state"]["independent_correct_count"]
                result = self.submit()
                self.assertTrue(result["correct"])
                self.assertEqual(result["outcome"], "correct")
                self.assertEqual(result["state"]["independent_correct_count"], prior)
                self.assertEqual(result["state"]["stage"], 0)

    def test_wrong_reveal_and_originals_preserved(self):
        before = self.snapshot()
        self.submit()
        wrong = self.submit(selection=0)
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["state"]["stage"], 0)
        reveal = self.submit(mode="revealed", selection=1)
        self.assertIsNone(reveal["correct"])
        self.assertEqual(reveal["state"]["independent_correct_count"], 1)
        self.assertEqual(self.submit()["state"]["stage"], 0)
        self.assertEqual(before, self.snapshot())
        self.now += timedelta(days=1)
        self.assertEqual(self.submit()["state"]["stage"], 1)

    def snapshot(self):
        with closing(self.connect()) as conn:
            return [list(map(tuple, conn.execute("SELECT * FROM " + table))) for table in
                    ("reading_exercises", "reading_errors", "listening_error_sets", "listening_errors")]

    def test_idempotency_and_conflict(self):
        payload = self.payload()
        first = self.client.post("/api/review/attempt", json=payload)
        self.now += timedelta(days=9)
        self.assertEqual(first.json(), self.client.post("/api/review/attempt", json=payload).json())
        payload["selection"] = 0
        self.assertEqual(self.client.post("/api/review/attempt", json=payload).status_code, 409)
        self.assertEqual(self.client.get("/api/review/state").json()["items"][0]["attempt_count"], 1)

    def test_listening_filter_and_missing_original(self):
        self.submit(kind="listening", item_id="listening-one", mode="revealed", selection=None)
        self.assertEqual(self.client.get("/api/review/state?lang=en").json()["items"], [])
        self.assertEqual(len(self.client.get("/api/review/state?lang=ja").json()["items"]), 1)
        with closing(self.connect()) as conn, conn:
            conn.execute("DELETE FROM listening_errors")
        self.assertEqual(self.client.get("/api/review/state").json()["items"], [])
        self.assertEqual(self.client.post("/api/review/attempt", json=self.payload(kind="listening", item_id="listening-one")).status_code, 404)

    def test_validation_and_cross_origin(self):
        for field, value in [("item_index", True), ("item_index", -1), ("item_index", "0"),
                             ("selection", True), ("selection", "1"), ("selection", 1.0),
                             ("selection", None), ("item_id", "x" * 101), ("answer", 1),
                             ("attempt_id", "bad"), ("mode", "correct"), ("selection", 2)]:
            with self.subTest(field=field, value=value):
                self.assertEqual(self.client.post("/api/review/attempt", json=self.payload(**{field: value})).status_code, 422)
        for headers in [{"origin": "https://evil.example"}, {"sec-fetch-site": "cross-site"}]:
            self.assertEqual(self.client.post("/api/review/attempt", json=self.payload(), headers=headers).status_code, 403)
            self.assertEqual(self.client.get("/api/review/state", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/review/capabilities").json()["version"], 1)
        self.assertEqual(self.client.get("/api/review/capabilities", headers={"origin": "http://testserver"}).status_code, 200)

    def test_daily_limit_and_uuid_retry(self):
        first = self.payload()
        self.assertEqual(self.client.post("/api/review/attempt", json=first).status_code, 200)
        with closing(self.connect()) as conn, conn:
            conn.executemany("INSERT INTO review_attempts VALUES (?,'reading','reading-one',0,'{}','{}',?)",
                             [(str(uuid4()), review.stamp(self.now)) for _ in range(199)])
        self.assertEqual(self.client.post("/api/review/attempt", json=self.payload()).status_code, 429)
        self.assertEqual(self.client.post("/api/review/attempt", json=first).status_code, 200)

    def test_concurrent_duplicate_only_counts_once(self):
        from app.routers.review import ReviewAttempt
        body = ReviewAttempt(**self.payload())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: review.attempt(body), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(review.states()["items"][0]["attempt_count"], 1)

    def test_window_matches_original_error_lists(self):
        self.submit()
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE reading_errors SET updated_at='2000-01-01'")
            for index in range(151):
                ident = f"new-{index:03d}"
                conn.execute("INSERT INTO reading_exercises VALUES (?, 'en','Title','',?)",
                             (ident, json.dumps({"items": [{"answer": 1, "options": ["a", "b"]}]})))
                conn.execute("INSERT INTO reading_errors(exercise_id,item_index,selected) VALUES (?,0,0)", (ident,))
        self.submit(item_id="new-000")
        state = self.client.get("/api/review/state?lang=en").json()
        self.assertFalse(state["truncated"])
        self.assertEqual([row["item_id"] for row in state["items"]], ["new-000"])
        self.assertEqual(review.states("en", limit=0)["truncated"], True)

    def test_malformed_original_is_not_written(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE reading_exercises SET payload_json='{}'")
        self.assertEqual(self.client.post("/api/review/attempt", json=self.payload()).status_code, 422)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_attempts").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
