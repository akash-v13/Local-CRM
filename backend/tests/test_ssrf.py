"""SSRF protection: connectors may only call public internet addresses."""

import pytest

from app.security.ssrf import UnsafeUrlError, check_url


def resolver(*ips: str):  # type: ignore[no-untyped-def]
    return lambda host, port: list(ips)


def check(url: str, *ips: str, allow_http: bool = False, allowed: tuple[str, ...] = ()) -> None:
    check_url(url, allow_http=allow_http, allowed_hosts=allowed, resolve=resolver(*ips))


def test_public_https_is_allowed() -> None:
    check("https://api.example.com/orders/1", "93.184.216.34")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "172.16.3.4",  # private
        "192.168.1.10",  # private
        "169.254.169.254",  # cloud metadata (link-local)
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 private
        "224.0.0.1",  # multicast
    ],
)
def test_private_and_reserved_addresses_are_blocked(ip: str) -> None:
    with pytest.raises(UnsafeUrlError):
        check("https://sneaky.example.com/", ip)


def test_any_private_address_among_several_is_blocked() -> None:
    with pytest.raises(UnsafeUrlError):
        check("https://mixed.example.com/", "93.184.216.34", "10.0.0.1")


def test_scheme_rules() -> None:
    with pytest.raises(UnsafeUrlError):
        check("http://api.example.com/", "93.184.216.34")
    check("http://api.example.com/", "93.184.216.34", allow_http=True)
    with pytest.raises(UnsafeUrlError):
        check("file:///etc/passwd", "93.184.216.34", allow_http=True)


def test_credentials_in_url_are_rejected() -> None:
    with pytest.raises(UnsafeUrlError):
        check("https://user:pass@api.example.com/", "93.184.216.34")


def test_allow_list_bypasses_resolution_for_named_dev_hosts() -> None:
    check("http://mocks:8100/orders/1", "172.18.0.5", allow_http=True, allowed=("mocks",))


def test_unresolvable_host_is_rejected() -> None:
    def fail(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    with pytest.raises(UnsafeUrlError):
        check_url("https://nope.invalid/", allow_http=False, allowed_hosts=(), resolve=fail)
