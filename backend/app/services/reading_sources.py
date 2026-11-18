"""Reader sources: one ordered list of built-in and custom sources, one fetch line.

Layout
- Registry: built-ins (`_BUILTINS`) plus custom rows kept in `reader_source_registry`
  (order, enabled flags, custom specs). `list_sources` / `get_source` read it.
- Connectors: every row has a `connector`. `feed` / `papers` / `textbooks` are the
  hand-written readers in services/reading.py; `spec` is the generic JSON-field-path
  or RSS/Atom reader below. `collect()` sends each row to its connector and merges.
  A new connector type = a new value here plus one branch in `collect()`.
- Transport for `spec`: resolve DNS first, refuse unless every address is public
  (or private and the source explicitly allows it), then connect only to those
  pinned addresses; no redirects, 7 s timeouts, 2 MB response cap.
- Keys: sealed with DPAPI (Windows) or AES-GCM; responses only show a mask.
- `allow_private` can only be switched by a trusted (local) caller: pass `trusted=True`.
"""
import asyncio
import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Timer
from time import monotonic
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..db import get_conn
from . import languages, reading

MAX_SOURCES = 16
MAX_RESPONSE = 2_000_000
MAX_ITEMS = 20
TIMEOUT = 7
SECRET_NAMES = {"key", "apikey", "xapikey", "subscriptionkey", "accesstoken", "token", "password",
                "secret", "clientsecret", "signature", "authorization"}
BLOCKED_HEADERS = {"host", "cookie", "connection", "content-length", "transfer-encoding", "upgrade", "accept-encoding"}
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(block) for block in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "100.64.0.0/10", "fc00::/7", "::1/128",
))
NETWORK_SLOTS = asyncio.Semaphore(4)
NETWORK_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reader-source")


class SourceError(Exception):
    pass


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=200)

    items: str = ""
    title: str = ""
    url: str = ""
    text: str = ""
    authors: str = ""
    author_name: str = ""
    date: str = ""
    image: str = ""
    doi: str = ""


class Auth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "header", "query"] = "none"
    name: str = Field("", max_length=80)
    prefix: str = Field("", max_length=60)
    configured: bool = Field(False, exclude=True)
    key: str | None = Field(None, max_length=2048, exclude=True, repr=False)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    kind: Literal["paper", "article"]
    lang: languages.LanguageTag | None = None
    format: Literal["json", "rss"] = "json"
    method: Literal["GET"] = "GET"
    url: str = Field(min_length=1, max_length=2048)
    query_param: str = Field("", max_length=80)
    params: dict[str, str] = Field(default_factory=dict, max_length=20)
    fields: Fields = Field(default_factory=Fields)
    auth: Auth = Field(default_factory=Auth)
    allow_private: bool = False
    enabled: bool = True


def _endpoint(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None or parts.fragment
                or "%" in parts.hostname or "\\" in url or any(ord(char) < 33 for char in url)):
            raise ValueError
        return parts, parts.hostname.encode("idna").decode("ascii"), parts.port or (443 if parts.scheme == "https" else 80)
    except (ValueError, UnicodeError):
        raise SourceError("地址须为 HTTP 或 HTTPS，且不能包含账号、密码或锚点") from None


def _secret_param(name):
    return re.sub(r"[^a-z0-9]", "", name.lower()) in SECRET_NAMES


def _check_source(data):
    try:
        spec = Source.model_validate(data)
    except ValidationError as exc:
        loc = exc.errors(include_input=False)[0]["loc"]
        schema = {**Source.model_fields, **Auth.model_fields, **Fields.model_fields}
        path = ".".join(part for part in loc if part in schema)
        raise SourceError(f"来源配置有误{f'（{path}）' if path else ''}") from None
    spec.name = spec.name.strip()
    if not spec.name:
        raise SourceError("请填写来源名称")
    if spec.kind == "article" and not spec.lang:
        raise SourceError("请选择文章语言")
    if spec.format == "json" and not spec.fields.title:
        raise SourceError("请填写标题字段路径")
    if spec.kind == "paper" and not spec.query_param:
        raise SourceError("请填写论文搜索参数")
    for path in spec.fields.model_dump().values():
        if path and (len(path.split(".")) > 12 or any(not part for part in path.split("."))):
            raise SourceError("字段路径须用点分隔")
    parts, _, _ = _endpoint(spec.url)
    try:
        url_params = parse_qsl(parts.query, max_num_fields=25, keep_blank_values=True)
    except ValueError:
        raise SourceError("地址包含过多查询参数") from None
    names = [name for name, _ in url_params] + list(spec.params)
    if any(not name or len(name) > 80 or _secret_param(name) for name in names):
        raise SourceError("请把 API 密钥放在鉴权字段")
    if any(len(value) > 500 for value in spec.params.values()):
        raise SourceError("查询参数值过长")
    if spec.query_param and (_secret_param(spec.query_param) or not re.fullmatch(r"[A-Za-z0-9_.~-]+", spec.query_param)):
        raise SourceError("搜索参数名称无效")
    auth = spec.auth
    if auth.mode != "none":
        name = auth.name.lower()
        if not re.fullmatch(r"[A-Za-z0-9_.~-]+", auth.name):
            raise SourceError("鉴权字段名称无效")
        if auth.mode == "header" and (name in BLOCKED_HEADERS or name.startswith(("proxy-", "sec-"))):
            raise SourceError("该请求头不能用于鉴权")
        if auth.mode == "query" and name in {param.lower() for param in [*names, spec.query_param]}:
            raise SourceError("鉴权参数和其他查询参数重名")
        if any(ord(char) < 32 or ord(char) > 126 for char in auth.prefix + (auth.key or "")):
            raise SourceError("鉴权内容包含无效字符")
        if parts.scheme != "https" and not spec.allow_private:
            raise SourceError("使用密钥的公网接口须采用 HTTPS")
    return spec


def _builtin(source_id, name, kind, url, **options):
    return {
        **Source(name=name, kind=kind, url=url, **options).model_dump(),
        "id": f"builtin-{source_id}", "builtin": True,
    }


_BUILTINS = [
    _builtin("europe-pmc", "Europe PMC", "paper", f"{reading.PMC_API}/search", query_param="query"),
    _builtin("crossref", "Crossref", "paper", "https://api.crossref.org/works", query_param="query"),
    _builtin("arxiv", "arXiv", "paper", "https://export.arxiv.org/api/query", format="rss", query_param="search_query"),
    _builtin("datacite", "DataCite", "paper", "https://api.datacite.org/dois", query_param="query",
             params={"resource-type-id": "journal-article", "page[size]": "8"},
             fields=Fields(items="data", title="attributes.titles.0.title", url="attributes.url",
                           text="attributes.descriptions.0.description", authors="attributes.creators",
                           author_name="name", date="attributes.publicationYear", doi="attributes.doi")),
    _builtin("hal", "HAL", "paper", "https://api.archives-ouvertes.fr/search/", query_param="q",
             params={"fq": "docType_s:ART", "fl": "title_s,abstract_s,uri_s,authFullName_s,producedDate_s,doiId_s", "rows": "8"},
             fields=Fields(items="response.docs", title="title_s.0", url="uri_s", text="abstract_s.0",
                           authors="authFullName_s", date="producedDate_s", doi="doiId_s")),
    _builtin("bbc-world", "BBC World", "article", reading.FEEDS["en"]["BBC World"], lang="en", format="rss"),
    _builtin("nasa", "NASA", "article", reading.FEEDS["en"]["NASA"], lang="en", format="rss"),
    _builtin("itmedia", "ITmedia NEWS", "article", reading.FEEDS["ja"]["ITmedia NEWS"], lang="ja", format="rss"),
    _builtin("meti", "経済産業省", "article", reading.FEEDS["ja"]["経済産業省"], lang="ja", format="rss"),
    _builtin("jst-science", "サイエンスポータル", "article", reading.FEEDS["ja"]["サイエンスポータル"], lang="ja", format="rss"),
    _builtin("aozora", "青空文庫", "article", reading.AOZORA + "/", lang="ja"),
    _builtin("wikipedia-en", "Wikipedia", "article", "https://en.wikipedia.org/", lang="en"),
    _builtin("wikipedia-ja", "Wikipedia", "article", "https://ja.wikipedia.org/", lang="ja"),
    _builtin("textbooks", "BCcampus Open Education", "article", "https://opentextbc.ca/", lang="en"),
]

EXTRA_PAPER_SOURCES = frozenset({"DataCite", "HAL"})


def _read(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS reader_source_registry (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
    row = conn.execute("SELECT value FROM reader_source_registry WHERE id=1").fetchone()
    return json.loads(row[0]) if row else {"order": [], "enabled": {}, "custom": {}}


def _state():
    with closing(get_conn()) as conn:
        return _read(conn)


def _change(update):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        state = _read(conn)
        result = update(state)
        conn.execute(
            "INSERT INTO reader_source_registry (id,value) VALUES (1,?) "
            "ON CONFLICT(id) DO UPDATE SET value=excluded.value", (json.dumps(state, ensure_ascii=False),),
        )
        return result


def _ordered(state):
    rows = {
        row["id"]: {**row, "enabled": state["enabled"].get(row["id"], True)}
        for row in _BUILTINS
    }
    rows.update(state["custom"])
    return [rows[key] for key in dict.fromkeys([*state["order"], *rows]) if key in rows]


KEY_MASK = "••••••••"


def _connector(row):
    """Which reader fetches this row (see module docstring)."""
    if not row["builtin"] or row["name"] in EXTRA_PAPER_SOURCES:
        return "spec"
    if row["id"] == "builtin-textbooks":
        return "textbooks"
    return "papers" if row["kind"] == "paper" else "feed"


def _public(row):
    """Never returns a key: only whether one is saved, and a fixed mask."""
    configured = bool(row.get("_secret"))
    return {
        **{key: value for key, value in row.items() if key != "_secret"},
        "connector": _connector(row),
        "auth": {**row["auth"], "configured": configured, "key_mask": KEY_MASK if configured else ""},
    }


def _filtered(kind, lang):
    return [
        row for row in _ordered(_state())
        if (kind is None or row["kind"] == kind) and (lang is None or row["lang"] == lang)
    ]


def list_sources(kind=None, lang=None):
    return [_public(row) for row in _filtered(kind, lang)]


def _lookup(source_id, state):
    return next((row for row in _ordered(state) if row["id"] == source_id), None)


def get_source(source_id):
    row = _lookup(source_id, _state())
    return _public(row) if row else None


def enabled_builtins(kind, lang=None):
    return {row["name"] for row in _filtered(kind, lang) if row["enabled"] and row["builtin"]}


def _binding(spec):
    parts, host, port = _endpoint(spec.url)
    return parts.scheme, host, port, spec.auth.mode, spec.auth.name, spec.auth.prefix


def _dpapi(data, encrypt):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    storage = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.addressof(storage))
    target = Blob()
    library = ctypes.windll.crypt32
    operation = library.CryptProtectData if encrypt else library.CryptUnprotectData
    operation.argtypes = (
        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob),
    )
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise SourceError("当前账户无法访问来源密钥")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = (ctypes.c_void_p,)
        free.restype = ctypes.c_void_p
        free(target.data)


def _cipher():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = base64.urlsafe_b64decode(os.environ.get("LANGPAL_READER_SOURCE_MASTER_KEY", ""))
        if len(key) != 32:
            raise ValueError
        return AESGCM(key)
    except (ImportError, ValueError):
        raise SourceError("服务器尚未配置密钥存储。请配置 LANGPAL_READER_SOURCE_MASTER_KEY 和 cryptography") from None


def _seal(key):
    data = key.encode("utf-8")
    if os.name == "nt":
        scheme, encrypted = "dpapi", _dpapi(data, True)
    else:
        nonce = os.urandom(12)
        scheme, encrypted = "aesgcm", nonce + _cipher().encrypt(nonce, data, b"langpal-reader-source")
    return f"{scheme}:{base64.urlsafe_b64encode(encrypted).decode('ascii')}"


def _open(secret):
    try:
        scheme, token = secret.split(":", 1)
        data = base64.urlsafe_b64decode(token)
        if scheme == "dpapi" and os.name == "nt":
            return _dpapi(data, False).decode("utf-8")
        if scheme == "aesgcm":
            return _cipher().decrypt(data[:12], data[12:], b"langpal-reader-source").decode("utf-8")
    except Exception:
        pass
    raise SourceError("无法读取已保存的密钥，请重新填写")


def _draft(data, old):
    merged = {key: value for key, value in (old or {}).items() if key not in {"id", "builtin", "_secret"}}
    for key, value in data.items():
        if key in {"auth", "fields"} and isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    spec = _check_source(merged)
    previous = old.get("_secret", "") if old else ""
    if spec.auth.mode == "none" or (
        previous and _binding(spec) != _binding(Source.model_validate({
            key: value for key, value in old.items() if key in Source.model_fields
        }))
    ):
        previous = ""
    return spec, previous


def _guard_private(spec, old, trusted):
    """Only the user at this computer may let a source reach the private network."""
    if spec.allow_private != bool(old and old.get("allow_private")) and not trusted:
        raise SourceError("「允许私有网络」只能在本机的设置页修改")


def create_source(data, *, trusted=False):
    def create(state):
        if len(state["custom"]) >= MAX_SOURCES:
            raise SourceError(f"最多可添加 {MAX_SOURCES} 个自定义来源")
        spec, _ = _draft(data, None)
        _guard_private(spec, None, trusted)
        source_id = f"custom-{uuid4().hex}"
        secret = _seal(spec.auth.key) if spec.auth.mode != "none" and spec.auth.key else ""
        row = {**spec.model_dump(), "id": source_id, "builtin": False, "_secret": secret}
        state["custom"][source_id] = row
        return _public(row)

    return _change(create)


def edit_source(source_id, data, *, trusted=False):
    def edit(state):
        old = _lookup(source_id, state)
        if old is None:
            raise KeyError
        if old["builtin"]:
            if set(data) != {"enabled"} or not isinstance(data["enabled"], bool):
                raise SourceError("内置来源可启用、停用或调整排序")
            state["enabled"][source_id] = data["enabled"]
            return _public({**old, "enabled": data["enabled"]})
        spec, secret = _draft(data, old)
        _guard_private(spec, old, trusted)
        if spec.auth.key is not None:
            secret = _seal(spec.auth.key) if spec.auth.mode != "none" and spec.auth.key else ""
        row = {**spec.model_dump(), "id": source_id, "builtin": False, "_secret": secret}
        state["custom"][source_id] = row
        return _public(row)

    return _change(edit)


def delete_source(source_id):
    def delete(state):
        row = _lookup(source_id, state)
        if row is None:
            raise KeyError
        if row["builtin"]:
            raise SourceError("内置来源可以停用")
        del state["custom"][source_id]
        state["order"] = [key for key in state["order"] if key != source_id]

    _change(delete)


def reorder_sources(ids):
    def reorder(state):
        current = {row["id"] for row in _ordered(state)}
        if len(ids) != len(set(ids)) or not set(ids) <= current:
            raise SourceError("来源排序已过期，请刷新后重试")
        ordered = [row["id"] for row in _ordered(state)]
        selected = iter(ids)
        moved = set(ids)
        state["order"] = [next(selected) if source_id in moved else source_id for source_id in ordered]
        return [_public(row) for row in _ordered(state)]

    return _change(reorder)


def _permitted(address, allow_private):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_multicast or ip.is_link_local or ip.is_unspecified or str(ip) == "168.63.129.16":
        return False
    return (ip.is_global and not ip.is_reserved) or (allow_private and any(ip in network for network in PRIVATE_NETWORKS))


def _resolve(host, port, allow_private):
    if host.rstrip(".").lower() in {"metadata.google.internal", "instance-data"}:
        raise SourceError("来源地址不可访问")
    candidates = list(dict.fromkeys(
        info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ))
    if not candidates or not all(_permitted(address, allow_private) for address in candidates):
        raise SourceError("来源地址不可访问，请确认是否需要启用私有网络")
    return candidates


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, addresses, secure):
        super().__init__(host, port, timeout=TIMEOUT)
        self.addresses = addresses
        self.secure = secure
        self.default_port = 443 if secure else 80
        self._abort_timer = None

    def finish(self):
        if self._abort_timer:
            self._abort_timer.cancel()
        self.close()

    @staticmethod
    def _abort(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def connect(self):
        deadline = monotonic() + TIMEOUT
        for address in self.addresses:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                sock = socket.create_connection((address, self.port), timeout=remaining)
            except OSError:
                continue
            try:
                self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host) if self.secure else sock
            except BaseException:
                sock.close()
                raise
            self._abort_timer = Timer(TIMEOUT, self._abort, args=(self.sock,))
            self._abort_timer.daemon = True
            self._abort_timer.start()
            return
        raise OSError("Unable to connect")


@contextmanager
def _connection(host, port, addresses, secure):
    conn = _PinnedHTTP(host, port, addresses, secure)
    try:
        yield conn
    finally:
        conn.finish()


def _download(spec, query, key):
    parts, host, port = _endpoint(spec.url)
    addresses = _resolve(host, port, spec.allow_private)
    if key and parts.scheme != "https" and any(_permitted(address, False) for address in addresses):
        raise SourceError("使用密钥的公网接口须采用 HTTPS")
    params = dict(parse_qsl(parts.query, max_num_fields=25, keep_blank_values=True))
    params.update(spec.params)
    if spec.query_param and query:
        params[spec.query_param] = query
    headers = {
        "Accept": "application/json" if spec.format == "json" else "application/atom+xml,application/rss+xml,application/xml,text/xml",
        "Accept-Encoding": "identity",
        "User-Agent": "JINE-Reader/1.0",
    }
    if spec.auth.mode == "header" and key:
        headers[spec.auth.name] = spec.auth.prefix + key
    if spec.auth.mode == "query" and key:
        params[spec.auth.name] = spec.auth.prefix + key
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    target = urlunsplit(("", "", path, urlencode(params), ""))
    with _connection(host, port, addresses, parts.scheme == "https") as conn:
        conn.request("GET", target, headers=headers)
        with conn.getresponse() as response:
            if not 200 <= response.status < 300:
                raise SourceError(f"来源接口返回 HTTP {response.status}")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise SourceError("来源接口须支持未压缩响应")
            deadline = monotonic() + TIMEOUT
            data = bytearray()
            while True:
                block = response.read1(min(65_536, MAX_RESPONSE + 1 - len(data)))
                if not block:
                    return bytes(data)
                data.extend(block)
                if len(data) > MAX_RESPONSE or monotonic() > deadline:
                    raise SourceError("来源接口响应过大或耗时过长")


def _at(value, path):
    for part in path.split(".") if path else ():
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isascii() and part.isdecimal() and len(part) <= 5:
            index = int(part)
            value = value[index] if index < len(value) else None
        else:
            return None
    return value


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _as_text(value):
    if type(value) is int:
        return str(value)
    return value if isinstance(value, str) else " ".join(part for part in _as_list(value) if isinstance(part, str))


def _redact(value, key):
    if key:
        encoded = quote(key, safe="")
        for variant in {key, encoded, re.sub(r"%[0-9A-F]{2}", lambda match: match[0].lower(), encoded)}:
            if variant:
                value = value.replace(variant, "•••")
    return value


def _safe_link(spec, value, key):
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value) or _redact(value, key) != value:
        return ""
    try:
        url = urljoin(spec.url, value)
        parts, _, _ = _endpoint(url)
        if _redact(url, key) != url or len(url) > 2048:
            return ""
        if any(_secret_param(name) for name, _ in parse_qsl(parts.query, max_num_fields=25)):
            return ""
        return url
    except (SourceError, ValueError):
        return ""


def _rss_rows(data):
    if b"\x00" in data or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.I):
        raise SourceError("订阅源含不支持的 XML 声明")
    root = ET.fromstring(data)
    rows = []
    for node in (root.findall(".//{*}item") or root.findall("{*}entry"))[:MAX_ITEMS]:
        def find(*tags):
            for tag in tags:
                child = node.find(f"{{*}}{tag}")
                if child is not None:
                    value = "".join(child.itertext()).strip()
                    if value:
                        return value
            return ""

        full_text = find("encoded", "content")
        links = node.findall("{*}link")
        url = next((link.get("href") for link in links if link.get("href") and link.get("rel", "alternate") == "alternate"), None)
        image = next((element.get("url") for element in node if element.get("url")
                      and (element.tag.endswith("thumbnail") or element.get("type", "").startswith("image/"))), "")
        row = {child.tag.rsplit("}", 1)[-1]: "".join(child.itertext()).strip() for child in node}
        row.update({
            "title": find("title"), "url": url or find("link"), "text": full_text or find("description", "summary"),
            "authors": node.findtext("{*}author/{*}name") or find("creator", "author"),
            "date": find("pubDate", "published", "updated", "date"), "doi": find("doi"),
            "image": image, "_summary": not bool(full_text),
        })
        rows.append(row)
    return rows


def _normalize(data, spec, key):
    fields = spec.fields.model_dump()
    if spec.format == "rss":
        rows = _rss_rows(data)
        fields = {name: fields[name] or name for name in ("title", "url", "text", "authors", "date", "image", "doi")} | {
            "author_name": spec.fields.author_name,
        }
    else:
        rows = _at(json.loads(data), spec.fields.items)
        if not isinstance(rows, list):
            raise SourceError("结果列表字段没有指向数组")

    result = []
    for row in rows[:MAX_ITEMS]:
        def value(field):
            return _as_text(_at(row, fields[field])) if fields[field] else ""

        title = _redact(reading.plain(value("title")), key)[:500]
        url = _safe_link(spec, value("url"), key)
        doi = _redact(value("doi"), key).strip()[:200]
        if not url and re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi) and "•••" not in doi:
            url = f"https://doi.org/{quote(doi, safe='/')}"
        if not title or (not url and spec.kind == "article"):
            continue
        raw_text = _redact(value("text"), key)[:24_000]
        paragraphs = []
        for paragraph in re.split(r"(?:</p\s*>|\r?\n\s*\r?\n)", raw_text, flags=re.I):
            plain = _redact(reading.plain(paragraph), key)
            if plain:
                paragraphs.append(plain)
        body = "\n\n".join(paragraphs)[:18_000]
        authors = _at(row, fields["authors"]) if fields["authors"] else None
        names = [_redact(reading.plain(_as_text(_at(author, fields["author_name"]))), key)
                 for author in _as_list(authors)[:10]]
        result.append({
            "title": title, "url": url, "text": body, "source": spec.name, "lang": spec.lang or "en",
            "date": _redact(value("date"), key)[:80], "author": ", ".join(filter(None, names))[:400],
            "doi": doi, "access": "", "ref": "", "academic": False,
            "feedOnly": spec.kind == "article" and (not body or (spec.format == "rss" and row["_summary"])),
            "image": _safe_link(spec, value("image"), key),
        })
    if rows and not result:
        raise SourceError("有返回记录，但没有读到标题或有效原文地址")
    return result


def _load(spec, query, key):
    try:
        if spec.auth.mode != "none" and not key:
            raise SourceError("请填写来源密钥")
        return _normalize(_download(spec, query, key), spec, key)
    except (OSError, http.client.HTTPException):
        raise SourceError("连接来源失败，请检查地址、网络或证书") from None
    except (UnicodeError, ValueError, ET.ParseError, RecursionError):
        raise SourceError("来源返回的格式与配置不符") from None


async def _run(spec, query, key):
    async with NETWORK_SLOTS:
        try:
            task = asyncio.get_running_loop().run_in_executor(NETWORK_POOL, _load, spec, query, key)
            return await asyncio.wait_for(task, 22)
        except TimeoutError:
            raise SourceError("来源接口请求超时") from None


def _spec_and_key(row):
    # Callers may hold the public row (no key, extra display fields); read the stored one.
    stored = _lookup(row["id"], _state()) or row
    spec, secret = _draft({}, stored)
    return spec, (_open(secret) if secret else "")


def _restricted(row):
    """Sources that may reach the private network or spend a saved key: local callers only."""
    keyed = bool(row.get("_secret")) or bool(row.get("auth", {}).get("configured"))
    return not row["builtin"] and (row.get("allow_private") or keyed)


async def _read_spec(row, query):
    try:
        spec, key = await asyncio.to_thread(_spec_and_key, row)
        items = await _run(spec, query[:300], key)
        return {"items": [{"source_id": row["id"], **item} for item in items], "unavailable": []}
    except SourceError:
        return {"items": [], "unavailable": [row["name"]]}


async def _skip(row):
    return {"items": [], "unavailable": [row["name"]]}


async def collect(kind, *, rows=None, query="", lang=None, source_id=None, include_private=True):
    """The single fetch line: send each enabled row to its connector, merge in list order.

    `rows` defaults to the registry filtered by kind/lang. `source_id` narrows to one
    row (by id, or a built-in's name). A failing source is listed in `unavailable`.
    """
    if rows is None:
        rows = await asyncio.to_thread(_filtered, kind, lang)
    rows = [row for row in rows if row["enabled"] and (
        not source_id or row["id"] == source_id or (row["builtin"] and row["name"] == source_id))]
    tasks = []
    names = {connector: [row["name"] for row in rows if _connector(row) == connector]
             for connector in ("feed", "papers")}
    if names["feed"]:
        tasks.append(reading.news(lang, names["feed"]))
    if names["papers"]:
        tasks.append(reading.papers(query, "all", names["papers"]))
    if any(_connector(row) == "textbooks" for row in rows):
        tasks.append(reading.university_textbooks())
    for row in rows:
        if _connector(row) == "spec":
            tasks.append(_skip(row) if _restricted(row) and not include_private else _read_spec(row, query))
    groups = await asyncio.gather(*tasks)
    order = {key: index for index, row in enumerate(rows) for key in (row["id"], row["name"])}
    items = [item for group in groups for item in group["items"]]
    items.sort(key=lambda item: order.get(item.get("source_id") or item.get("source"), len(rows)))
    unavailable = [label for group in groups for label in group["unavailable"]]
    unavailable.sort(key=lambda label: order.get(label, len(rows)))
    return {"items": items, "unavailable": list(dict.fromkeys(unavailable))}


async def collect_custom(kind, *, query="", lang=None, source_id=None, include_private=True):
    rows = [row for row in await asyncio.to_thread(_filtered, kind, lang) if not row["builtin"]]
    return await collect(kind, rows=rows, query=query, lang=lang, source_id=source_id, include_private=include_private)


async def collect_extra_papers(query, *, source_id=None):
    rows = [row for row in await asyncio.to_thread(_filtered, "paper", None)
            if row["builtin"] and row["name"] in EXTRA_PAPER_SOURCES]
    return await collect("paper", rows=rows, query=query, source_id=source_id)


def _test_target(source_id, data, trusted):
    row = _lookup(source_id, _state()) if source_id else None
    if source_id and row is None:
        raise KeyError
    if row and row["builtin"]:
        if data:
            raise SourceError("内置来源使用预设配置")
        return row, None, ""
    spec, secret = _draft(data or {}, row)
    if spec.allow_private and not trusted:
        raise SourceError("允许私有网络的来源只能在本机测试")
    key = spec.auth.key if spec.auth.key is not None else (_open(secret) if secret else "")
    return row, spec, key


async def test_source(source_id=None, data=None, query="", *, trusted=False):
    """Try a saved source, or an unsaved configuration, without saving anything."""
    row, spec, key = await asyncio.to_thread(_test_target, source_id, data, trusted)
    if spec is None:
        sample = query or ("climate change" if row["kind"] == "paper" else "")
        result = await collect(row["kind"], rows=[{**row, "enabled": True}], query=sample, lang=row["lang"])
        if result["unavailable"]:
            raise SourceError("内置来源暂不可用")
        items = result["items"]
    else:
        items = await _run(spec, query or ("climate change" if spec.kind == "paper" else ""), key)
    return {"ok": True, "count": len(items), "items": items[:3], "message": "" if items else "连接成功，当前查询没有结果"}
