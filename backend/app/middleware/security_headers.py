"""Security response headers.

Follows the Mozilla Web Security guidelines:
https://infosec.mozilla.org/guidelines/web_security

Notes on the deliberate choices:

HSTS is **off unless explicitly enabled**. Mozilla is explicit that HSTS
should be ramped up, because if any subdomain cannot serve HTTPS, visitors
cannot reach it for the whole max-age. Sending it from a dev server on plain
HTTP is pointless, and shipping `preload` before you are certain every
subdomain does HTTPS is close to irreversible -- removal from the preload
list takes months. So: opt in, start short, lengthen deliberately.

CSP is conservative but assumes a built SPA (hashed asset files, no inline
script). Vite's dev server uses inline script and eval for hot reload, so the
policy relaxes automatically when INSECURE_COOKIES signals local dev rather
than silently breaking the dev experience.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: Mozilla: minimum six months (15768000); two years recommended once stable.
HSTS_MAX_AGE = int(os.getenv("HSTS_MAX_AGE", "15768000"))
HSTS_ENABLED = os.getenv("HSTS_ENABLED", "").lower() in {"1", "true", "yes"}
HSTS_INCLUDE_SUBDOMAINS = os.getenv("HSTS_INCLUDE_SUBDOMAINS", "true").lower() in {"1", "true", "yes"}
#: Only set once every subdomain is verified HTTPS. Hard to undo.
HSTS_PRELOAD = os.getenv("HSTS_PRELOAD", "").lower() in {"1", "true", "yes"}

DEV_MODE = os.getenv("INSECURE_COOKIES", "").lower() in {"1", "true", "yes"}


def _csp() -> str:
    """Content-Security-Policy.

    `frame-ancestors 'none'` supersedes X-Frame-Options in modern browsers;
    the legacy header is still sent for older ones.
    """
    script = "'self'"
    style = "'self' 'unsafe-inline'"   # Tailwind emits a stylesheet, not inline JS
    connect = "'self'"

    if DEV_MODE:
        # Vite HMR needs inline/eval and a websocket back to the dev server.
        script = "'self' 'unsafe-inline' 'unsafe-eval'"
        connect = "'self' ws: wss:"

    return "; ".join([
        "default-src 'self'",
        f"script-src {script}",
        f"style-src {style}",
        "img-src 'self' data:",
        "font-src 'self' data:",
        f"connect-src {connect}",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests" if not DEV_MODE else "",
    ]).strip("; ").replace("; ;", ";")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers

        # Stop MIME sniffing turning an upload into executable content.
        headers.setdefault("X-Content-Type-Options", "nosniff")
        # Do not leak the path (which can carry ids) to third-party sites.
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Legacy clickjacking defence; CSP frame-ancestors is authoritative.
        headers.setdefault("X-Frame-Options", "DENY")
        # Mozilla A+ expects at least one feature explicitly disabled.
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Content-Security-Policy", _csp())

        if HSTS_ENABLED and not DEV_MODE:
            value = f"max-age={HSTS_MAX_AGE}"
            if HSTS_INCLUDE_SUBDOMAINS:
                value += "; includeSubDomains"
            if HSTS_PRELOAD:
                value += "; preload"
            headers.setdefault("Strict-Transport-Security", value)

        return response
