"""全新的库默认就是糖糖：人设 1 换成糖糖（人设卡、世界书、头像、口吻样本）；老库一律不动。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import chat_room  # noqa: E402


class SeedAme(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.avatars = Path(self.temp.name) / "avatars"
        self.conn = sqlite3.connect(Path(self.temp.name) / "x.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript((ROOT / "backend/db/schema.sql").read_text(encoding="utf-8"))
        self.addCleanup(self.conn.close)

    def persona(self, persona_id=1):
        row = self.conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        return row, json.loads(row["profile_json"])

    def test_fresh_database_gets_ame(self):
        self.assertTrue(chat_room.seed_ame(self.conn, self.avatars))
        chat_room.seed_voices(self.conn)
        row, profile = self.persona()
        self.assertEqual(row["name"], "糖糖（あめ）")
        self.assertEqual(row["language"], "ja")
        self.assertTrue((self.avatars / row["avatar"]).is_file())
        book = self.conn.execute("SELECT * FROM world_books WHERE id = ?", (profile["world_book_ids"][0],)).fetchone()
        self.assertGreater(len(json.loads(book["book_json"])["entries"]), 10)
        self.assertTrue(profile["voice_samples"]["ja"])
        self.assertEqual([r["name"] for r in self.conn.execute("SELECT name FROM personas WHERE id > 1 ORDER BY id")], ["Emma", "Lena"])

    def test_runs_once(self):
        chat_room.seed_ame(self.conn, self.avatars)
        self.assertFalse(chat_room.seed_ame(self.conn, self.avatars))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM world_books").fetchone()[0], 1)

    def test_edited_first_persona_is_left_alone(self):
        self.conn.execute("UPDATE personas SET profile_json = '{}' WHERE id = 1")
        self.assertFalse(chat_room.seed_ame(self.conn, self.avatars))
        self.assertEqual(self.persona()[0]["name"], "雪菜")

    def test_existing_user_database_is_left_alone(self):
        self.conn.execute("INSERT INTO personas (id, name, language, profile_json) VALUES (5, '糖糖（あめ）', 'ja', '{}')")
        self.assertFalse(chat_room.seed_ame(self.conn, self.avatars))
        self.assertEqual(self.persona()[0]["name"], "雪菜")
        self.assertFalse(self.avatars.exists())


if __name__ == "__main__":
    unittest.main()
