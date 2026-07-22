"""HTTP(S) / WS(S) scheme helpers for Edge ↔ Cloud transport."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def is_http_or_https_url(value: str) -> bool:
    """Return True when value is an http(s) URL with a host and without userinfo."""
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    return True


def http_url_to_websocket_url(base_url: str) -> str:
    """Map http→ws and https→wss for a Cloud HTTP(S) base URL. Raises ValueError otherwise."""
    parsed = urlparse(str(base_url or "").strip())
    if parsed.scheme == "http":
        ws_scheme = "ws"
    elif parsed.scheme == "https":
        ws_scheme = "wss"
    else:
        raise ValueError(f"unsupported Cloud URL scheme: {parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError("Cloud URL must include a host")
    return urlunparse((ws_scheme, parsed.netloc, parsed.path or "", "", "", ""))
