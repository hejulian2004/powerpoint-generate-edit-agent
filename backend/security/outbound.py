"""Outbound provider URL policy with SSRF + DNS-rebinding defenses (PR #28 Phase 0).

Invariants:
- URL literal IPs are judged directly with ``ipaddress`` (no DNS involved).
- Hostnames are resolved; EVERY A/AAAA result must be a public, globally
  routable address. Any loopback / private / link-local / multicast /
  reserved / unspecified address rejects the whole URL.
- Redirects are always disabled (``follow_redirects=False``) so a safe
  initial URL cannot 302 to an intranet target.
- DNS-rebinding TOCTOU is closed by pinning: the validated address set is
  enforced during the actual HTTP connection by temporarily constraining
  ``socket.getaddrinfo`` to the validated IPs. Host header / TLS SNI keep
  using the original hostname, so certificates keep validating.

If pinning cannot be applied (non-socket transports), callers must restrict
custom providers to an explicit trusted-hostname allowlist instead of
claiming generic-URL SSRF safety.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from contextlib import contextmanager
from typing import Iterator, List, Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class OutboundURLRejected(ValueError):
    """Raised when an outbound provider URL fails the SSRF policy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    # Block everything that is not globally routable public unicast.
    # is_global is False for private/loopback/link-local/multicast/reserved.
    try:
        if not ip.is_global:
            return True
    except Exception:
        return True
    # Defense in depth: explicitly block the classic SSRF ranges even if
    # a platform's is_global behaves unexpectedly.
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    # Cloud metadata endpoints (also link-local, but be explicit).
    if isinstance(ip, ipaddress.IPv4Address) and str(ip) == "169.254.169.254":
        return True
    return False


def _resolve_all_ips(host: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OutboundURLRejected(
            "OUTBOUND_DNS_FAILED", f"无法解析目标主机 {host!r}：{exc}"
        )
    ips: List[str] = []
    for _family, _socktype, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0] if isinstance(sockaddr, tuple) else str(sockaddr)
        if ip_str and ip_str not in ips:
            ips.append(ip_str)
    if not ips:
        raise OutboundURLRejected(
            "OUTBOUND_DNS_FAILED", f"目标主机 {host!r} 没有可用的 A/AAAA 记录"
        )
    return ips


@contextmanager
def pinned_dns(host: str, allowed_ips: List[str]) -> Iterator[None]:
    """Constrain ``socket.getaddrinfo(host)`` to the validated IP set.

    Closes the DNS-rebinding TOCTOU window: the HTTP client re-resolves
    during connect, but the second resolution can only return IPs we already
    validated as public. Other hosts resolve normally.
    """
    allowed: Set[str] = set(allowed_ips)
    original_getaddrinfo = socket.getaddrinfo

    def _guarded(
        h: Optional[str], p: Optional[int], *args: object, **kwargs: object
    ):  # type: ignore[no-untyped-def]
        if h == host:
            results = original_getaddrinfo(h, p, *args, **kwargs)
            filtered = []
            for fam, stype, proto, canon, sockaddr in results:
                ip_str = sockaddr[0] if isinstance(sockaddr, tuple) else str(sockaddr)
                if ip_str in allowed:
                    filtered.append((fam, stype, proto, canon, sockaddr))
            if not filtered:
                raise socket.gaierror(
                    f"DNS pinning rejected unvalidated address for {host!r}"
                )
            return filtered
        return original_getaddrinfo(h, p, *args, **kwargs)

    socket.getaddrinfo = _guarded  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo  # type: ignore[method-assign]


class OutboundURLPolicy:
    """Validates an OpenAI-compatible ``base_url`` before any key is attached."""

    ALLOWED_SCHEMES = ("http", "https")

    @classmethod
    def parse(cls, base_url: str) -> tuple[str, str, int]:
        if not base_url or not str(base_url).strip():
            raise OutboundURLRejected("OUTBOUND_URL_REQUIRED", "Base URL is required")
        raw = str(base_url).strip()
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        if scheme not in cls.ALLOWED_SCHEMES:
            raise OutboundURLRejected(
                "OUTBOUND_SCHEME_BLOCKED",
                f"仅允许 http/https 出站探测，拒绝 scheme {scheme!r}",
            )
        host = (parsed.hostname or "").strip()
        if not host:
            raise OutboundURLRejected("OUTBOUND_HOST_REQUIRED", "Base URL 缺少主机名")
        # Reject URLs embedding userinfo (user:pass@host) — credential smuggling.
        if parsed.username or parsed.password:
            raise OutboundURLRejected(
                "OUTBOUND_USERINFO_BLOCKED", "Base URL 不允许携带 userinfo"
            )
        default_port = 443 if scheme == "https" else 80
        try:
            port = parsed.port or default_port
        except ValueError:
            raise OutboundURLRejected("OUTBOUND_PORT_INVALID", "Base URL 端口非法")
        return raw.rstrip("/"), host, port

    @classmethod
    def validate(
        cls,
        base_url: str,
        *,
        trusted_hosts: Optional[Set[str]] = None,
        allow_private_for_tests: bool = False,
    ) -> tuple[str, str, List[str]]:
        """Validate ``base_url`` and return ``(normalized, host, validated_ips)``.

        ``validated_ips`` is empty for literal-IP hosts (already checked) and
        holds every resolved public IP for DNS hosts. Callers must open the
        HTTP connection inside ``pinned_dns(host, validated_ips)`` when the
        list is non-empty.

        When ``trusted_hosts`` is non-empty, DNS hosts MUST be allowlisted;
        this is the strict v1 mode when callers cannot guarantee pinning.
        """
        normalized, host, port = cls.parse(base_url)

        # 1) Literal IP: judge directly, no DNS.
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if _is_blocked_ip(literal) and not allow_private_for_tests:
                raise OutboundURLRejected(
                    "OUTBOUND_SSRF_BLOCKED",
                    f"拒绝出站到内网/回环/保留地址 {host!r}",
                )
            return normalized, host, []

        # 2) DNS hostname: optional explicit allowlist enforcement.
        if trusted_hosts:
            if host.lower() not in {h.lower() for h in trusted_hosts}:
                raise OutboundURLRejected(
                    "OUTBOUND_HOST_NOT_TRUSTED",
                    f"自定义 provider 主机 {host!r} 不在 TRUSTED_PROVIDER_HOSTS 白名单中",
                )

        # 3) Resolve and require EVERY result to be public.
        ips = _resolve_all_ips(host, port)
        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                raise OutboundURLRejected(
                    "OUTBOUND_SSRF_BLOCKED", f"目标解析出非法地址 {ip_str!r}"
                )
            if _is_blocked_ip(ip) and not allow_private_for_tests:
                raise OutboundURLRejected(
                    "OUTBOUND_SSRF_BLOCKED",
                    f"拒绝出站到内网/回环/保留地址 {host!r} -> {ip_str}",
                )
        return normalized, host, ips


__all__ = ["OutboundURLPolicy", "OutboundURLRejected", "pinned_dns"]
