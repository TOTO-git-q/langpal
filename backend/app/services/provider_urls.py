"""Validate user-entered service locations before making or opening requests."""
import re
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit, urlunsplit

_PRIVATE_NETWORKS = tuple(ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def is_private_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or any(address in network for network in _PRIVATE_NETWORKS)


def service_url(value: str, *, origin_only: bool = False) -> str:
    if not value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
        raise ValueError("服务地址无效")
    parts = urlsplit(value)
    host = parts.hostname
    port = parts.port
    local = host in {"localhost", "127.0.0.1", "::1"}
    if (not host or not host.isascii() or "%" in host or port == 0 or parts.username is not None
            or parts.password is not None or "?" in value or "#" in value
            or (parts.scheme != "https" and not (parts.scheme == "http" and local))
            or (origin_only and parts.path not in {"", "/"})):
        raise ValueError("使用 HTTPS，或本机 HTTP 地址，不带账号、查询参数或片段")
    if ":" not in host and not all(_DNS_LABEL.fullmatch(label) for label in host.removesuffix(".").split(".")):
        raise ValueError("服务域名无效")
    default_port = 443 if parts.scheme == "https" else 80
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != default_port:
        netloc += f":{port}"
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))
