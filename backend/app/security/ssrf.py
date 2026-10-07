"""Protection against SSRF (server-side request forgery).

Connectors let *customers* choose URLs that *our servers* will call. Without
checks, someone could point a connector at our own internals — the cloud
metadata service (169.254.169.254), the database, localhost admin ports — and
read the responses through the connector test screen.

`check_url` rejects a URL unless:
- the scheme is https (or http, if explicitly allowed for local development),
- it has no embedded credentials (user:pass@host),
- the hostname resolves ONLY to public internet addresses (no private,
  loopback, link-local, multicast or reserved ranges), or the hostname is on an
  explicit allow-list (used for the local mock API in docker-compose).

The HTTP client must also not follow redirects (a public URL could redirect to
an internal one); see app/connectors/runner.py.

Known limitation: the address is checked at resolution time, and the HTTP
client resolves again when connecting (a "DNS rebinding" window). For
production, also run connector traffic through an egress proxy or firewall
that blocks private ranges.
"""

import ipaddress
import socket
from collections.abc import Callable, Collection
from urllib.parse import urlsplit

Resolver = Callable[[str, int], list[str]]


class UnsafeUrlError(Exception):
    """The URL must not be called from our servers."""


def resolve_host(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def check_url(
    url: str,
    *,
    allow_http: bool,
    allowed_hosts: Collection[str],
    resolve: Resolver = resolve_host,
) -> None:
    """Raise UnsafeUrlError if our servers must not call this URL."""
    parts = urlsplit(url)
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parts.scheme not in allowed_schemes:
        raise UnsafeUrlError(f"URL must use {' or '.join(sorted(allowed_schemes))}.")
    if parts.username or parts.password:
        raise UnsafeUrlError("Credentials in the URL aren't allowed; use the connector's auth.")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host.")
    if host.lower() in {h.lower() for h in allowed_hosts}:
        return

    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("URL has an invalid port.") from exc
    check_host(host, port, allowed_hosts=(), resolve=resolve)


def check_host(
    host: str,
    port: int,
    *,
    allowed_hosts: Collection[str],
    resolve: Resolver = resolve_host,
) -> None:
    """Raise UnsafeUrlError unless `host` resolves only to public internet addresses
    (or is explicitly allowed). Used for connector URLs and mail servers."""
    if host.lower() in {h.lower() for h in allowed_hosts}:
        return
    try:
        addresses = resolve(host, port)
    except OSError as exc:
        raise UnsafeUrlError(f"Could not resolve host '{host}'.") from exc
    if not addresses:
        raise UnsafeUrlError(f"Could not resolve host '{host}'.")

    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])  # strip IPv6 zone ids
        if not ip.is_global or ip.is_multicast:
            raise UnsafeUrlError(
                f"'{host}' resolves to a private or reserved address ({ip}); "
                "only public internet addresses are allowed."
            )
