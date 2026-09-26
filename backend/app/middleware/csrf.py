"""CSRF defence for the cookie-authenticated API.

Two checks on every state-changing request (POST/PUT/PATCH/DELETE) under
/api, following OWASP's CSRF cheat sheet:

1. Origin verification. Browsers attach `Origin` to every cross-origin
   request that can change state, and scripts cannot forge it. It must name
   one of our own origins (CORS_ORIGINS plus APP_BASE_URL). `Referer` is the
   fallback when a browser omits `Origin`.
2. A custom header, `X-Insite-CSRF`. A cross-site form cannot set headers,
   and cross-site script can only do so after a CORS preflight that our CORS
   policy refuses. Belt and braces over (1).

Requests with neither `Origin` nor `Referer` are not from a browser page
(curl, the test client, server-to-server). They cannot carry a victim's
session cookie against the victim's will, so they are let through; the
session check still applies to them as normal.

SameSite=Lax on the session cookie remains a third layer. It alone is not
enough: it does not cover same-site subdomains, and it offers nothing
against login CSRF (logging a victim into the attacker's account), which is
why the unauthenticated auth routes are checked too.
"""

import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CSRF_HEADER = "X-Insite-CSRF"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def trusted_origins() -> set[str]:
    raw = [
        *os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
        os.getenv("APP_BASE_URL", ""),
    ]
    return {o for o in (_origin_of(u) for u in raw if u.strip()) if o}


def _reject(reason: str) -> Response:
    return JSONResponse({"detail": f"Request blocked: {reason}"}, status_code=403)


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.trusted = trusted_origins()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in UNSAFE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        if origin is None and referer is None:
            return await call_next(request)

        # "null" (sandboxed frames, opaque redirects) is never trusted.
        source = _origin_of(origin) if origin else _origin_of(referer or "")
        if source not in self.trusted:
            return _reject("untrusted origin")
        if request.headers.get(CSRF_HEADER) != "1":
            return _reject("missing CSRF header")

        return await call_next(request)
