"""Run as a local stdio server. The browser must opt in before tools expose text."""
import base64
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent

BASE = os.getenv("LANGPAL_READER_ORIGIN", "http://127.0.0.1:8787").rstrip("/")
URL = urlsplit(BASE)
if URL.scheme != "http" or URL.hostname not in {"localhost", "127.0.0.1", "::1"} or URL.path or URL.query or URL.fragment or URL.username:
    raise ValueError("LANGPAL_READER_ORIGIN must be a local HTTP origin")

mcp = MCPServer("jine-reader")


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(BASE + "/api/reader/bridge/" + path, data=data,
                             headers={"Content-Type": "application/json"}), timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise ValueError(detail or f"Reader returned HTTP {exc.code}") from None


def invoke(tool, **args):
    result = json.loads(request("call", {"tool": tool, "args": args})["result"])
    if isinstance(result, dict) and result.get("error"):
        raise ValueError(result["error"])
    return result


@mcp.tool()
def reader_state() -> dict:
    """Return the current shared document title, page, and selected text."""
    return request("state")


@mcp.tool()
def read_pages(pages: list[int]) -> list[dict]:
    """Read up to five pages of the current document. Page numbers are one-based."""
    return invoke("read_pages", pages=pages)


@mcp.tool(structured_output=False)
def capture_region(page: int, x: float = 0, y: float = 0, width: float = 1, height: float = 1) -> ImageContent:
    """Get a PDF image crop. Coordinates are normalized from the top-left."""
    result = invoke("capture_region", page=page, rect=[x, y, width, height])
    base64.b64decode(result["png"], validate=True)
    return ImageContent(type="image", mimeType="image/png", data=result["png"])


@mcp.tool()
def list_annotations() -> list[dict]:
    """Read annotations in the current document, including replies."""
    return invoke("list_annotations")


@mcp.tool()
def reply_annotation(annotation_id: str, text: str) -> dict:
    """Reply to an annotation only if the reader enabled write access."""
    return invoke("reply_annotation", annotation_id=annotation_id, text=text)


@mcp.tool()
def list_shelf() -> list[dict]:
    """List up to 30 documents in the reader shelf."""
    return invoke("list_shelf")


@mcp.tool()
def open_paper(document_id: str) -> dict:
    """Open a saved paper from the reader shelf by ID."""
    return invoke("open_paper", document_id=document_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
