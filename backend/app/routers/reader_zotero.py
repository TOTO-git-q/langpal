"""Read Zotero on the same computer, through its local API."""
import asyncio
import json
import re
from contextlib import closing
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from urllib.request import url2pathname

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints

from ..db import get_conn
from ..services import reading
from ..security import local_request

router = APIRouter(prefix="/reader/zotero", tags=["reader-zotero"], dependencies=[Depends(local_request)])
_CONNECTION_KEY = "reader_zotero_connection"


class Connection(BaseModel):
    port: int = Field(default=23119, ge=1024, le=65535)
    library: Annotated[str, StringConstraints(pattern=r"^(users/0|groups/[1-9][0-9]{0,14})$")] = "users/0"

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}/api/{self.library}/items"


def _connection():
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (_CONNECTION_KEY,)).fetchone()
    try:
        return Connection.model_validate_json(row["value"]) if row else Connection()
    except ValueError:
        return Connection()


def client():
    return httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False,
                             headers={"Zotero-API-Version": "3", "User-Agent": "LangPal-Reader/1.0"})


def verify_key(key):
    if not re.fullmatch(r"[A-Z0-9]{8}", key):
        raise HTTPException(422, "无效的 Zotero 条目")


@router.get("/connection")
def get_connection():
    return _connection()


@router.put("/connection")
def put_connection(body: Connection):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (_CONNECTION_KEY, body.model_dump_json()),
        )
    return body


@router.post("/connection/test")
async def test_connection(body: Connection):
    async with client() as http:
        try:
            rows = json.loads(await reading.fetch(http, body.base + "/top", params={"limit": 1}))
            if not isinstance(rows, list):
                raise ValueError("Unexpected response")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "连接失败，请检查 Zotero 本机访问、端口和书库路径") from None
    return {"ok": True}


@router.get("/items")
async def items(q: str = ""):
    base = (await asyncio.to_thread(_connection)).base
    async with client() as http:
        try:
            rows = json.loads(await reading.fetch(http, base + "/top", params={
                "q": q[:140], "limit": 25, "sort": "dateModified", "direction": "desc",
            }))
            if not isinstance(rows, list):
                raise ValueError("Unexpected response")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "请打开 Zotero，并在高级设置中启用本机访问") from None
    records = []
    for row in rows:
        item = row.get("data", {})
        title, key = item.get("title"), item.get("key", "")
        if not title or not re.fullmatch(r"[A-Z0-9]{8}", key):
            continue
        url = reading.link(item.get("url"))
        if not url and item.get("DOI"):
            url = reading.link("https://doi.org/" + item["DOI"])
        records.append({
            "title": title, "url": url, "zoteroKey": key, "source": "Zotero",
            "author": ", ".join(author.get("lastName") or author.get("name") or "" for author in item.get("creators", [])[:4]),
            "text": item.get("abstractNote", "")[:12_000], "date": item.get("date", "")[:20],
            "lang": "ja" if re.search(r"[\u3040-\u30ff]", title) else "en",
        })
    return {"items": records}


@router.get("/items/{key}/pdf")
async def attachment(key: str):
    verify_key(key)
    base = (await asyncio.to_thread(_connection)).base
    async with client() as http:
        try:
            rows = json.loads(await reading.fetch(http, f"{base}/{key}/children", params={"limit": 25}))
            if not isinstance(rows, list):
                raise ValueError("Unexpected response")
            keys = [item.get("key", "") for row in rows if (item := row.get("data", {})).get("contentType") == "application/pdf"]
            for child in keys:
                verify_key(child)
                async with http.stream("GET", f"{base}/{child}/file") as response:
                    if response.status_code != 302:
                        continue
                    target = urlsplit(response.headers.get("location", ""))
                    if target.scheme != "file" or target.netloc not in {"", "localhost"} or target.query or target.fragment:
                        continue
                    # Read only an attachment location returned by the local Zotero server.
                    path = Path(url2pathname(target.path))
                    if not path.is_absolute() or path.suffix.lower() != ".pdf" or str(path).startswith(("\\\\", "//")):
                        continue
                    try:
                        data = await asyncio.to_thread(read_pdf, path)
                    except OSError:
                        continue
                    if data:
                        return Response(data, media_type="application/pdf", headers={"Cache-Control": "no-store"})
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Zotero 暂时不可用") from None
    raise HTTPException(404, "这篇没有已下载的本地 PDF，可先读摘要或打开来源")


def read_pdf(path):
    limit = 35_000_000
    if not path.is_file() or path.stat().st_size > limit:
        return None
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    return data if len(data) <= limit and data.startswith(b"%PDF-") else None
