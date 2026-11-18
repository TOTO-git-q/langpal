"""Offline grading contract regression, isolated SQLite and no provider import."""
import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Annotated, Literal
import unittest
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
ROOT = Path(__file__).resolve().parents[1]
ROUTER = ast.parse((ROOT / "backend/app/routers/reading.py").read_text("utf-8"))
SERVICE = ast.parse((ROOT / "backend/app/services/reading_errors.py").read_text("utf-8"))
namespace = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, StrictInt=StrictInt, Annotated=Annotated, Literal=Literal)
model = next(n for n in ROUTER.body if isinstance(n, ast.ClassDef) and n.name == "ReadingSubmission")
exec(compile(ast.Module(body=[model], type_ignores=[]), "submission", "exec"), namespace)
Submission = namespace["ReadingSubmission"]
class Grading(unittest.TestCase):
    def test_request_rejects_coercion_and_extras(self):
        for value in [True, False, 1.0, "1", -1, 5, None]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Submission(choices=[value])
        for payload in [dict(choices=[]), dict(choices=[1]*10), dict(choices=[1], answer=1)]:
            with self.assertRaises(ValidationError): Submission(**payload)
        self.assertEqual(Submission(choices=[0,1,2,3,4]).choices,[0,1,2,3,4])
    def test_blocking_routes_use_worker_threads(self):
        for name in ["submit", "errors"]:
            self.assertIsInstance(next(n for n in ROUTER.body if getattr(n,"name",None)==name), ast.FunctionDef)
        exercise=next(n for n in ROUTER.body if getattr(n,"name",None)=="exercises")
        code=ast.unparse(exercise)
        self.assertIn("await asyncio.to_thread(reading_errors.load_set",code)
        self.assertIn("await asyncio.to_thread(reading_errors.save_set",code)
    def test_invalid_service_input_never_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"test.sqlite"
            def connect():
                conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row;return conn
            items=[dict(options=["a","b","c","d"],answer=1)]
            with closing(connect()) as conn, conn:
                conn.executescript("CREATE TABLE reading_exercises (id TEXT PRIMARY KEY,payload_json TEXT); CREATE TABLE reading_errors (exercise_id TEXT,item_index INTEGER,selected INTEGER,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(exercise_id,item_index));")
                conn.execute("INSERT INTO reading_exercises VALUES (?,?)",("test",json.dumps(dict(items=items))))
            env=dict(closing=closing,json=json,get_conn=connect)
            func=next(n for n in SERVICE.body if getattr(n,"name",None)=="submit")
            exec(compile(ast.Module(body=[func],type_ignores=[]),"submit","exec"),env)
            submit=env["submit"]
            for values in [[True],[1.0],["1"],[-1],[4],[],None,(1,)]:
                with self.subTest(values=values),self.assertRaises(ValueError):submit("test",values)
            with closing(connect()) as conn:self.assertEqual(conn.execute("SELECT count(*) FROM reading_errors").fetchone()[0],0)
            self.assertEqual(submit("test",[0])["correct"],0)
            self.assertEqual(submit("test",[0])["saved_errors"],1)
            self.assertEqual(submit("test",[1])["correct"],1)
            with closing(connect()) as conn:self.assertEqual(conn.execute("SELECT count(*) FROM reading_errors").fetchone()[0],1)
            with self.assertRaises(LookupError):submit("missing",[0])
if __name__ == "__main__":unittest.main()
