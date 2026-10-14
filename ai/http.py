"""Tiny JSON-over-HTTP helper (stdlib only) shared by the providers."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import AIProviderError

MAX_RESPONSE_BYTES = 2_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would copy the Authorization header to a redirect target on another host. Never follow redirects."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def open_no_redirect(req, timeout: float):
    return _OPENER.open(req, timeout=timeout)


def request_json(url: str, *, payload: dict | None = None, headers: dict | None = None,
                 timeout: float = 30.0, label: str = "server") -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with open_no_redirect(req, timeout) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        extra = " (redirects are not followed)" if 300 <= exc.code < 400 else ""
        raise AIProviderError(f"{label} returned HTTP {exc.code}{extra}", retriable=exc.code >= 500 or exc.code == 429) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise AIProviderError(f"Cannot reach {label}: {type(reason).__name__}", retriable=True) from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise AIProviderError(f"{label} response is too large")
    try:
        parsed = json.loads(body)
    except ValueError:
        raise AIProviderError(f"{label} returned invalid JSON") from None
    if not isinstance(parsed, dict):
        raise AIProviderError(f"{label} returned an unexpected response shape")
    return parsed
