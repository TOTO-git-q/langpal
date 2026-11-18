"""Request-origin checks shared by every router.

The app is a single-user local service. Browsers will happily send a request to
127.0.0.1 from any web page, so each route that reads or writes private data
declares one of these as a dependency:

- ``same_origin``: the request must not come from another site.
- ``local_request``: additionally, both ends must be the loopback interface.
"""
import ipaddress
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def _loopback(host) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def same_origin(request: Request):
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} or (
        origin and origin not in {f"http://{host}", f"https://{host}"}
    ):
        raise HTTPException(403, "仅接受应用同源请求")


def local_request(request: Request):
    host = request.headers.get("host", "")
    try:
        local_host = _loopback(urlsplit("//" + host).hostname)
    except ValueError:
        local_host = False
    if not request.client or not _loopback(request.client.host) or not local_host:
        raise HTTPException(403, "仅本机可以访问")
    same_origin(request)
