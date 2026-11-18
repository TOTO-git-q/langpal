"""Bounded, server-side access to published feeds and scholarly indexes."""
import asyncio
import json
import random
import re
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET

import httpx

FEEDS = {
    "en": {
        "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "NASA": "https://www.nasa.gov/news-release/feed/",
    },
    "ja": {
        "ITmedia NEWS": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
        "経済産業省": "https://www.meti.go.jp/ml_index_release_atom.xml",
        # JST Science Portal: full articles in content:encoded (science explanations, N1 説明文)
        "サイエンスポータル": "https://scienceportal.jst.go.jp/feed/rss.xml",
    },
}
# Aozora Bunko essayists (modern kana editions only): 説明文・随筆・評論 at N1 level.
AOZORA_AUTHORS = {42: "寺田寅彦", 1569: "中谷宇吉郎", 1395: "和辻哲郎", 148: "夏目漱石"}
AOZORA = "https://www.aozora.gr.jp"
# JLPT N1 reading lengths: 短文 ~200, 中文 ~500, 長文 ~1000 characters.
JA_BANDS = (("短文", 150, 450, 220), ("中文", 350, 800, 520), ("長文", 700, 1400, 1000))
PAPER_SOURCES = ("Europe PMC", "Crossref", "arXiv")
MEDIA_RSS = "{http://search.yahoo.com/mrss/}"
IMAGE_DOMAINS = {
    "BBC World": ("bbci.co.uk", "bbc.co.uk"),
    "NASA": ("nasa.gov",),
    "ITmedia NEWS": ("itmedia.co.jp", "itmedia.jp"),
    "Wikipedia": ("upload.wikimedia.org", "thumb.wikimedia.org"),
}
PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_cache = {}
_arxiv_lock = asyncio.Lock()
_arxiv_at = 0.0
_JATS_DTD = re.compile(
    rb"""<!DOCTYPE\s+article\s+(?:PUBLIC\s+(?:"[^"]*"|'[^']*')\s+|SYSTEM\s+)(?:"[^"]*"|'[^']*')\s*>""", re.I,
)


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = _Plain()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.current = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.active = True
            self.current = []

    def handle_data(self, data):
        if self.active:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.active:
            value = " ".join("".join(self.current).split())
            if value:
                self.paragraphs.append(value)
            self.active = False


def ja_length(text):
    """Characters as JLPT counts them (kana and kanji); the same count reading_formats uses."""
    return len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text))


def japanese_excerpts(text, bands=JA_BANDS):
    """One continuous excerpt per JLPT length band, cut at sentence ends and kept in paragraphs."""
    units = []
    for number, paragraph in enumerate(p.strip() for p in re.split(r"\n+", text)):
        if not paragraph:
            continue
        sentences = [s for s in re.split(r"(?<=[。！？])", paragraph) if s.strip()]
        units.extend((number, sentence) for sentence in sentences)
    results = []
    for name, low, high, target in bands:
        best = None
        for start in range(len(units)):
            # An excerpt should stand on its own: start at a paragraph, not at "そこで…" / "この…".
            penalty = (0 if start == 0 or units[start - 1][0] != units[start][0] else 80) + (
                40 if re.match(r"\s*(そこで|しかし|また|さらに|これ|それ|この|その|あの|ただ|なお|つまり|だが|一方)", units[start][1]) else 0)
            size = 0
            for end in range(start, len(units)):
                size += ja_length(units[end][1])
                if size > high:
                    break
                score = abs(size - target) + penalty
                if size >= low and (best is None or score < best[0]):
                    best = score, start, end
        if best:
            _, start, end = best
            parts, previous = [], None
            for number, sentence in units[start:end + 1]:
                parts.append(("\n" if previous is not None and number != previous else "") + sentence.strip())
                previous = number
            results.append((name, "".join(parts)))
    return results


def excerpt_items(item, text):
    """Japanese source text -> one reading item per JLPT length band."""
    return [{**item, "title": f"{item['title']}（{name}）", "text": excerpt, "url": f"{item['url']}#{name}",
             "scope": "节选", "band": name, "feedOnly": False}
            for name, excerpt in japanese_excerpts(text)]


def link(value):
    if not isinstance(value, str):
        return ""
    value = (value or "").strip()
    try:
        url = urlsplit(value)
    except ValueError:
        return ""
    return value if url.scheme in {"http", "https"} and url.hostname and not url.username else ""


def image_url(source, value):
    url = link(value)
    if not url or len(url) > 1600:
        return ""
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme != "https" or ":" in parts.netloc or not any(
        host == domain or host.endswith("." + domain) for domain in IMAGE_DOMAINS.get(source, ())
    ):
        return ""
    return parts._replace(query="", fragment="").geturl() if source == "Wikipedia" else url


def rss_image(item, source):
    for tag in ("thumbnail", "content"):
        for media in item.iter(MEDIA_RSS + tag):
            if media.get("medium", "image") == "image" and media.get("type", "image/").startswith("image/"):
                if image := image_url(source, media.get("url")):
                    return image
    return ""


def xml(raw, *, jats=False):
    # Strip only a standard external JATS DTD declaration. Reject internal subsets and entities.
    if jats:
        raw = _JATS_DTD.sub(b"", raw, count=1)
    if b"\x00" in raw or re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("XML declarations are unsupported")
    return ET.fromstring(raw)


async def fetch(client, url, *, params=None, limit=2_000_000):
    async with client.stream("GET", url, params=params) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Response exceeded size limit")
    return bytes(data)


def client():
    return httpx.AsyncClient(
        timeout=8, follow_redirects=False,
        headers={"User-Agent": "LangPal-Reader/1.0 (interactive personal reader)"},
    )


def get_cache(key):
    entry = _cache.get(key)
    if entry and monotonic() < entry[0]:
        return True, entry[1]
    return False, None


def put_cache(key, ttl, result):
    if len(_cache) >= 150:
        _cache.pop(next(iter(_cache)))
    _cache[key] = monotonic() + ttl, result


async def cached(key, ttl, loader):
    found, result = get_cache(key)
    if found:
        return result
    result = await loader()
    put_cache(key, ttl, result)
    return result


async def collect(sources, loader):
    rows = await asyncio.gather(*(loader(name) for name in sources), return_exceptions=True)
    return {
        "items": [item for row in rows if not isinstance(row, Exception) for item in row],
        "unavailable": [name for name, row in zip(sources, rows) if isinstance(row, Exception)],
    }


async def news(lang, sources=None):
    async with client() as http:
        async def read(name):
            async def load():
                root = xml(await fetch(http, FEEDS[lang][name]))
                if name == "経済産業省":
                    return [
                        {"title": plain(item.findtext("{*}title")), "url": url, "source": name, "lang": lang,
                         "text": plain(item.findtext("{*}summary"))[:1200],
                         "date": (item.findtext("{*}updated") or "")[:10], "feedOnly": True}
                        for item in root.findall("{*}entry")[:12]
                        if (item_link := item.find("{*}link")) is not None and (url := link(item_link.get("href")))
                    ]
                results = []
                for item in root.findall(".//item")[:18]:
                    title, url = plain(item.findtext("title")), link(item.findtext("link"))
                    if not title or not url:
                        continue
                    text = plain(item.findtext("description"))[:1200]
                    full = ""
                    if (name == "NASA" and re.match(r"https://www\.nasa\.gov/news-release/", url)) or (
                            name == "サイエンスポータル" and re.match(r"https://scienceportal\.jst\.go\.jp/", url)):
                        parser = _Paragraphs()
                        parser.feed(item.findtext("{*}encoded") or "")
                        full = "\n\n".join(parser.paragraphs)[:11_000]
                    if name == "サイエンスポータル":
                        if full:
                            results.extend(excerpt_items({"title": title, "url": url, "source": name, "lang": lang,
                                                          "date": item.findtext("pubDate") or "", "academic": True,
                                                          "license": "JST サイエンスポータル · 节选，原文见链接"}, full))
                        continue
                    results.append({"title": title, "url": url, "source": name, "lang": lang,
                                    "text": full or text, "date": item.findtext("pubDate") or "",
                                    "feedOnly": not bool(full), "academic": False, "image": rss_image(item, name)})
                return results
            return await cached(("news", name), 900, load)

        async def read_source(name):
            if name == "青空文庫":
                return await cached(("aozora",), 3600, lambda: aozora(http))
            if name != "Wikipedia":
                return await read(name)
            return await cached(("wiki", lang), 3600, lambda: wikipedia(lang))

        available = (*FEEDS[lang], "Wikipedia", *(("青空文庫",) if lang == "ja" else ()))
        selected = available if sources is None else [name for name in sources if name in available]
        return await collect(selected, read_source)


async def university_textbooks():
    from . import reading_textbooks

    async def load():
        return await reading_textbooks.textbooks()

    items = await cached(("university-textbooks",), 1800, load)
    return {"items": items, "unavailable": [] if items else ["大学教材"]}


async def aozora(http, works=2):
    """Random essays by AOZORA_AUTHORS (public domain, modern kana), excerpted to JLPT lengths."""
    items = []
    for author in random.sample(list(AOZORA_AUTHORS), k=min(works, len(AOZORA_AUTHORS))):
        page = (await fetch(http, f"{AOZORA}/index_pages/person{author}.html")).decode("utf-8", "ignore")
        cards = re.findall(r'<li><a href="\.\./cards/(\d+)/card(\d+)\.html">([^<]+)</a>[^<]*（新字新仮名', page)
        for folder, card, title in random.sample(cards, k=min(3, len(cards))):
            card_page = (await fetch(http, f"{AOZORA}/cards/{folder}/card{card}.html")).decode("utf-8", "ignore")
            files = re.findall(r'href="\./files/(\d+_\d+\.html)"', card_page)
            if not files:
                continue
            raw = (await fetch(http, f"{AOZORA}/cards/{folder}/files/{files[0]}")).decode("cp932", "ignore")
            body = re.search(r'<div class="main_text">(.*?)<div class="bibliographical_information">', raw, re.S)
            if not body or body.group(1).count("<img") > 3:  # many missing characters: skip
                continue
            html = re.sub(r"<rt>.*?</rt>|<rp>.*?</rp>|<span class=\"notes\">.*?</span>", "", body.group(1), flags=re.S)
            text = re.sub(r"<br\s*/?>", "\n", html)
            text = "\n".join(line.strip() for line in plain_lines(text).split("\n") if line.strip())
            if ja_length(text) < 300:
                continue
            item = {"title": f"{AOZORA_AUTHORS[author]}「{plain(title)}」", "source": "青空文庫", "lang": "ja",
                    "url": f"{AOZORA}/cards/{folder}/card{card}.html", "academic": False,
                    "license": "青空文库 · 公有领域"}
            items.extend(excerpt_items(item, text))
            break
    return items


def plain_lines(value):
    """Like plain() but keeps line breaks."""
    return "\n".join(plain(line) for line in value.split("\n"))


async def wikipedia(lang):
    # Featured / good articles, starting at a random letter so the list changes between visits.
    category = random.choice({"ja": ["Category:秀逸な記事", "Category:良質な記事"],
                              "en": ["Category:Featured articles"]}[lang])
    prefix = random.choice("あかさたなはまやらわ" if lang == "ja" else "ABCDEFGHIKLMNOPRSTW")
    params = {
        "action": "query", "generator": "categorymembers", "gcmtitle": category, "gcmstartsortkeyprefix": prefix,
        "gcmtype": "page", "gcmlimit": 6, "prop": "extracts|info|pageimages", "inprop": "url",
        "piprop": "thumbnail|name", "pithumbsize": 200, "pilicense": "free",
        "exintro": 1, "explaintext": 1, "exlimit": "max", "format": "json", "formatversion": 2,
    }
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urlencode(params)
    raw = await asyncio.to_thread(wikipedia_response, url)
    entries = [
        {"title": row["title"], "url": row["fullurl"], "text": row["extract"][:11_000],
         "source": "Wikipedia", "license": "CC BY-SA 4.0 · 条目节选", "lang": lang, "academic": True,
         "image": image_url("Wikipedia", (row.get("thumbnail") or {}).get("source")),
         "imageSource": f"https://{lang}.wikipedia.org/wiki/File:" + quote(row["pageimage"], safe="")
         if row.get("pageimage") else ""}
        for row in json.loads(raw).get("query", {}).get("pages", [])
        if row.get("extract") and link(row.get("fullurl"))
    ]
    if lang == "ja":
        async def longer(item):
            params = {"action": "query", "prop": "extracts", "titles": item["title"], "explaintext": 1,
                      "exchars": 3500, "exsectionformat": "plain", "format": "json", "formatversion": 2}
            raw = await asyncio.to_thread(wikipedia_response, f"https://ja.wikipedia.org/w/api.php?" + urlencode(params))
            extract = json.loads(raw).get("query", {}).get("pages", [{}])[0].get("extract")
            return {**item, "text": extract} if extract and len(extract) > len(item["text"]) else item

        selected = sorted(entries, key=lambda item: len(item["text"]), reverse=True)[:3]
        longer_entries = await asyncio.gather(*(longer(item) for item in selected), return_exceptions=True)
        # JLPT-sized excerpts of the longer articles (headings dropped), plus the short intros as they are.
        result = []
        for item in longer_entries:
            if isinstance(item, dict):
                text = "\n".join(line for line in item["text"].split("\n") if line.strip() and not re.fullmatch(r"\s*=+.*=+\s*", line))
                result.extend(excerpt_items(item, text))
        return result + [item for item in entries if item["url"] not in {i.get("url") for i in selected}]
    return entries


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def wikipedia_response(url):
    # Wikimedia rejects the default HTTPX transport on the target Windows setup.
    limit = 500_000
    request = Request(url, headers={"User-Agent": "LangPal-Reader/1.0"})
    with build_opener(_NoRedirect).open(request, timeout=8) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Response exceeded size limit")
    return raw


def paper(source, *, title, url, text="", doi="", date="", author="", access="", ref=""):
    return {
        "source": source, "title": plain(title), "url": link(url), "text": plain(text)[:12_000],
        "date": date, "doi": doi, "author": plain(author), "lang": "en", "access": access, "ref": ref,
    }


async def crossref(http, query):
    doi = re.fullmatch(r"10\.\d{4,9}/[^\s]+", query, re.I)
    if doi:
        raw = await fetch(http, "https://api.crossref.org/works/" + quote(query, safe="/"))
        items = [json.loads(raw)["message"]]
    else:
        raw = await fetch(http, "https://api.crossref.org/works", params={
            "query.bibliographic": query, "rows": 10,
            "select": "title,DOI,URL,author,published",
        })
        items = json.loads(raw)["message"]["items"]
    return [
        paper("Crossref", title=(row.get("title") or [""])[0], url=row.get("URL"),
              doi=row.get("DOI", ""), date="-".join(map(str, (row.get("published", {}).get("date-parts") or [[]])[0])),
              author=", ".join(person.get("family", "") for person in row.get("author", [])[:4]))
        for row in items
    ]


async def europe_pmc(http, query):
    doi = re.fullmatch(r"10\.\d{4,9}/[^\s]+", query, re.I)
    if doi:
        query = 'DOI:"' + query.replace('"', "") + '"'

    async def search(search_query, size):
        raw = await fetch(http, f"{PMC_API}/search", params={
            "query": search_query, "format": "json", "resultType": "core", "pageSize": size,
        })
        return json.loads(raw)["resultList"]["result"]

    if doi:
        rows = await search(query, 10)
    else:
        general, open_text = await asyncio.gather(
            search(query, 8), search(f"({query}) AND OPEN_ACCESS:y AND IN_PMC:y", 5), return_exceptions=True,
        )
        if isinstance(general, Exception) and isinstance(open_text, Exception):
            raise general
        rows = (open_text if isinstance(open_text, list) else []) + (general if isinstance(general, list) else [])
    return [
        paper("Europe PMC", title=row.get("title"), text=row.get("abstractText"),
              url=f"https://europepmc.org/article/{quote(row['source'], safe='')}/{quote(str(row['id']), safe='')}",
              doi=row.get("doi", ""), date=row.get("pubYear", ""), author=row.get("authorString"),
              access="oa-text" if row.get("isOpenAccess") == "Y" and row.get("pmcid") else "",
              ref=row.get("pmcid", ""))
        for row in rows
    ]


async def arxiv(http, query):
    global _arxiv_at
    async with _arxiv_lock:
        await asyncio.sleep(max(0, 3 - (monotonic() - _arxiv_at)))
        _arxiv_at = monotonic()
        raw = await fetch(http, "https://export.arxiv.org/api/query", params={
            "search_query": 'all:"' + query.replace('"', " ") + '"', "max_results": 10,
        })
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    results = []
    for row in xml(raw).findall("a:entry", ns):
        url = row.findtext("a:id", namespaces=ns) or ""
        ref = url.partition("/abs/")[2]
        if re.fullmatch(r"(?:[a-zA-Z.\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", ref):
            results.append(paper(
                "arXiv", title=row.findtext("a:title", namespaces=ns), url=f"https://arxiv.org/abs/{ref}",
                text=row.findtext("a:summary", namespaces=ns), doi=row.findtext("arxiv:doi", namespaces=ns) or "",
                date=(row.findtext("a:published", namespaces=ns) or "")[:10],
                author=", ".join(node.text or "" for node in row.findall("a:author/a:name", ns)[:4]),
                access="pdf", ref=ref,
            ))
    return results


async def papers(query, source, sources=None):
    adapters = dict(zip(PAPER_SOURCES, (europe_pmc, crossref, arxiv)))
    async with client() as http:
        async def read(name):
            return await cached(("papers", name, query.casefold()), 300, lambda: adapters[name](http, query))

        selected = PAPER_SOURCES if source == "all" else (source,)
        if sources is not None:
            selected = [name for name in sources if name in selected]
        data = await collect(selected, read)
    records = {}
    for item in data["items"]:
        if item["title"]:
            key = item["doi"].lower() if item["doi"] else item["url"]
            if key not in records or (item["access"] and not records[key]["access"]):
                records[key] = item
    data["items"] = list(records.values())
    return data


async def open_pmc(pmcid):
    async with client() as http:
        tree = xml(await fetch(http, f"{PMC_API}/{pmcid}/fullTextXML", limit=5_000_000), jats=True)
    body = tree.find("body")
    if body is None:
        raise ValueError("Full text unavailable")
    paragraphs = []
    for node in body.iter():
        if node.tag in {"p", "title", "caption"}:
            text = " ".join("".join(node.itertext()).split())
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)[:240_000]


async def open_arxiv(ref):
    async with client() as http:
        data = await fetch(http, f"https://arxiv.org/pdf/{ref}", limit=35_000_000)
    if not data.startswith(b"%PDF-"):
        raise ValueError("Not a PDF")
    return data
