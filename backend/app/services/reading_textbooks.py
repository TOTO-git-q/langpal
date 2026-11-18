"""Allowlisted CC BY 4.0 Pressbooks excerpts for English academic reading."""
import asyncio
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from time import monotonic
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCE = "BCcampus Open Education"
LICENSE = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
MAX_RESPONSE_BYTES = 512_000
MAX_WORDS = 900
MIN_WORDS = 300
REQUEST_TIMEOUT = 7
_ROOT = "https://opentextbc.ca/"
_WORD = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")


@dataclass(frozen=True)
class Chapter:
    book_slug: str
    chapter_id: int
    chapter_slug: str
    title: str
    book: str
    author: str
    subject: str
    begins_with: str
    paragraphs: int
    license_terms: tuple[int, ...] = ()

    @property
    def url(self):
        return f"{_ROOT}{self.book_slug}/chapter/{self.chapter_slug}/"

    @property
    def api_url(self):
        return f"{_ROOT}{self.book_slug}/wp-json/pressbooks/v2/chapters/{self.chapter_id}"


# Licensing is checked against the edition and the selected prose, not the
# publisher as a whole. An empty chapter license list inherits the book's terms.
CHAPTERS = (
    Chapter(
        "physicalgeology2ed", 761, "17-1-waves", "17.1 Waves",
        "Physical Geology – 2nd Edition", "Steven Earle", "地质学",
        "Waves form on the ocean", 7, (52,),
    ),
    Chapter(
        "introductiontosociology3rdedition", 706, "20-2-urbanization", "20.2 Urbanization",
        "Introduction to Sociology – 3rd Canadian Edition", "William Little", "社会学",
        "As cities grew more crowded", 6,
    ),
    Chapter(
        "introductorybusinessstatistics", 77, "descriptive-statistics-and-frequency-distributions-2",
        "Chapter 1. Descriptive Statistics and Frequency Distributions",
        "Introductory Business Statistics with Interactive Spreadsheets – 1st Canadian Edition",
        "Mohammad Mahbobi and Thomas K. Tiemann", "商务统计",
        "Other measures of location are the median", 5,
    ),
)

_BLOCK_TAGS = {
    "aside", "audio", "blockquote", "button", "canvas", "figcaption", "figure", "footer",
    "form", "iframe", "math", "nav", "noscript", "ol", "script", "style", "svg", "table",
    "template", "ul", "video",
}
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _Prose(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str | None] = []
        self._parts: list[str] | None = None
        self._skip: list[str] = []

    def _finish_paragraph(self):
        if self._parts is not None:
            text = " ".join("".join(self._parts).split())
            if text:
                self.blocks.append(text)
            self._parts = None

    def handle_starttag(self, tag, attrs):
        if self._skip:
            if tag not in _VOID_TAGS:
                self._skip.append(tag)
            return
        info = dict(attrs)
        classes = (info.get("class") or "").split()
        if (tag in _BLOCK_TAGS or "hidden" in info or info.get("aria-hidden") == "true"
                or info.get("role") in {"dialog", "doc-noteref"}
                or any(token.startswith(("textbox", "footnote", "glossary", "wp-caption", "credit"))
                       for token in classes)):
            if tag not in _VOID_TAGS:
                self._skip.append(tag)
            return
        if tag in _HEADINGS:
            self._finish_paragraph()
            self.blocks.append(None)
        elif tag == "p":
            self._finish_paragraph()
            self._parts = []
        elif tag == "br" and self._parts is not None:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if self._skip:
            if tag in self._skip:
                index = len(self._skip) - 1 - self._skip[::-1].index(tag)
                del self._skip[index:]
            return
        if tag == "p":
            self._finish_paragraph()

    def handle_data(self, data):
        if self._parts is not None and not self._skip:
            self._parts.append(data)


def _extract(html: str, chapter: Chapter) -> str:
    parser = _Prose()
    parser.feed(html)
    parser.close()
    start = next((i for i, paragraph in enumerate(parser.blocks)
                  if paragraph and paragraph.startswith(chapter.begins_with)), None)
    if start is None:
        return ""
    paragraphs = []
    words = 0
    for paragraph in parser.blocks[start:start + chapter.paragraphs]:
        if not paragraph or re.search(r"\[(?:/?latex|caption)\b", paragraph, re.IGNORECASE):
            break
        count = len(_WORD.findall(paragraph))
        if words + count > MAX_WORDS:
            break
        paragraphs.append(paragraph)
        words += count
    return "\n\n".join(paragraphs) if len(paragraphs) >= 3 and words >= MIN_WORDS else ""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(chapter: Chapter) -> dict:
    request = Request(chapter.api_url, headers={
        "Accept": "application/json",
        "User-Agent": "JINE-Reader/1.0 (public textbook excerpt)",
    })
    deadline = monotonic() + REQUEST_TIMEOUT
    with build_opener(_NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("Expected a public Pressbooks JSON chapter")
        data = bytearray()
        while chunk := response.read1(65_536):
            data.extend(chunk)
            if len(data) > MAX_RESPONSE_BYTES or monotonic() > deadline:
                raise ValueError("Pressbooks response exceeded its limit")
    record = json.loads(data)
    if not isinstance(record, dict):
        raise ValueError("Expected a Pressbooks chapter object")
    return record


def _record(chapter: Chapter, payload: dict) -> dict | None:
    content = payload.get("content")
    if (payload.get("id") != chapter.chapter_id or payload.get("status") != "publish"
            or payload.get("link") != chapter.url or payload.get("license") != list(chapter.license_terms)
            or not isinstance(content, dict) or content.get("protected") is not False
            or not isinstance(content.get("rendered"), str)):
        return None
    text = _extract(content["rendered"], chapter)
    if not text:
        return None
    return {
        "title": chapter.title,
        "url": chapter.url,
        "source": SOURCE,
        "book_title": chapter.book,
        "author": chapter.author,
        "attribution": f"{chapter.book} by {chapter.author}. Excerpt with non-prose elements omitted.",
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "subject": chapter.subject,
        "material_type": "open_textbook",
        "text": text,
        "lang": "en",
        "academic": True,
    }


async def textbooks() -> list[dict]:
    """Fetch at most one public chapter per allowlisted entry. Skip failed sources."""
    async def one(chapter):
        try:
            return _record(chapter, await asyncio.to_thread(_fetch, chapter))
        except (OSError, URLError, ValueError):
            return None

    return [record for record in await asyncio.gather(*(one(chapter) for chapter in CHAPTERS)) if record]
