"""Isolated notebook API tests. Never opens the user's database."""
import inspect
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.routers import notebook
from app.services.learning import store
from fastapi import HTTPException

class NotebookTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.db=Path(self.folder.name)/'test.db'
  conn=sqlite3.connect(self.db);conn.row_factory=sqlite3.Row
  conn.executescript((Path(__file__).resolve().parents[1]/'backend/db/schema.sql').read_text('utf-8'))
  conn.execute('DELETE FROM personas');store.migrate(conn);conn.commit();conn.close()
  def connection():
   conn=sqlite3.connect(self.db, timeout=10);conn.row_factory=sqlite3.Row;return conn
  self.patch=patch.object(notebook,'get_conn',connection);self.patch.start()
 def tearDown(self): self.patch.stop();self.folder.cleanup()
 def test_concurrent_duplicate_saves_are_idempotent(self):
  barrier=Barrier(8)
  def save(i):
   barrier.wait()
   return notebook.add_vocab(notebook.VocabIn(language='en',lemma='read',meaning=f'meaning{i}',context_sentence='I read.'))
  with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(save,range(8)))
  self.assertEqual(len({r['id'] for r in results}),1)
  self.assertEqual(len({r['meaning'] for r in results}),1)
  self.assertEqual(len(notebook.list_vocab()['items']),1)
  self.assertTrue(sum(r['created'] for r in results)==1)
  old=results[0]
  again=notebook.add_vocab(notebook.VocabIn(language='en',lemma='read',meaning='replacement',context_sentence='new'))
  # Saving again keeps the entry and its meaning, and adds the sentence as one more context.
  self.assertEqual((again['id'],again['meaning'],again['created'],again['context_count']),(old['id'],old['meaning'],False,2))
 def test_language_isolation_and_deletion(self):
  en=notebook.add_vocab(notebook.VocabIn(language='en',lemma='gift',context_sentence='a gift'))
  de=notebook.add_vocab(notebook.VocabIn(language='de',lemma='gift',context_sentence='Gift'))
  self.assertNotEqual(en['id'],de['id']);self.assertEqual([r['id'] for r in notebook.list_vocab('de')['items']],[de['id']])
  notebook.delete_vocab(en['id']);self.assertEqual([r['id'] for r in notebook.list_vocab()['items']],[de['id']])
  with self.assertRaises(HTTPException) as error: notebook.delete_vocab(en['id'])
  self.assertEqual(error.exception.status_code,404)
 def test_patterns_and_sync_handlers(self):
  item=notebook.add_pattern(notebook.PatternIn(language='en',pattern_name='If only'))
  self.assertEqual(notebook.list_patterns('en')['items'],[item]);self.assertEqual(notebook.list_patterns('de')['items'],[])
  notebook.delete_pattern(item['id']);self.assertEqual(notebook.list_patterns()['items'],[])
  for name in ['list_vocab','add_vocab','delete_vocab','list_patterns','add_pattern','delete_pattern']:
   self.assertFalse(inspect.iscoroutinefunction(getattr(notebook,name)))

if __name__=='__main__':unittest.main()
