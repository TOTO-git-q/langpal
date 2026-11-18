"""Test app only. No production app startup or database reads."""
from pathlib import Path
import sys
import os
import ast
import unittest
from unittest.mock import patch
sys.path.insert(0,os.environ.get("LANGPAL_BACKEND_ROOT",str(Path(__file__).resolve().parents[1]/"backend")))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import notebook
if os.environ.get("LANGPAL_NOTEBOOK_SOURCE"):
 exec(compile(Path(os.environ["LANGPAL_NOTEBOOK_SOURCE"]).read_text("utf-8"),"staged_notebook","exec"),notebook.__dict__)
class Origins(unittest.TestCase):
 def setUp(self):
  app=FastAPI();app.include_router(notebook.router,prefix="/api");self.client=TestClient(app)
 def test_foreign_read_write_blocked_before_db(self):
  with patch.object(notebook,"get_conn",side_effect=AssertionError("database must not be reached")):
   for headers in [{"origin":"https://evil.example"},{"sec-fetch-site":"cross-site"},{"origin":"null"},{"sec-fetch-site":"same-site"}]:
    for method,path,body in [("GET","/api/vocab",None),("GET","/api/patterns",None),("POST","/api/vocab",dict(language="en",lemma="word",context_sentence="source")),("DELETE","/api/vocab/1",None)]:
     with self.subTest(headers=headers,path=path):
      response=self.client.request(method,path,headers=headers,json=body);self.assertEqual(response.status_code,403)
 def test_upload_route_has_same_origin_guard(self):
  source=Path(os.environ.get("LANGPAL_CHAT_SOURCE",str(Path(__file__).resolve().parents[1]/"backend/app/routers/chat.py")))
  module=ast.parse(source.read_text("utf-8"))
  upload=next(n for n in module.body if getattr(n,"name",None)=="upload_chat_image")
  self.assertTrue(any("Depends(same_origin)" in ast.unparse(d) for d in upload.decorator_list))
 def test_same_origin_and_local_clients_reach_router(self):
  from fastapi import HTTPException
  for headers in [{},{"origin":"http://testserver","sec-fetch-site":"same-origin"}]:
   with patch.object(notebook,"get_conn",side_effect=HTTPException(418,"safe stub")):
    self.assertEqual(self.client.get("/api/vocab",headers=headers).status_code,418)
if __name__=="__main__":unittest.main()
