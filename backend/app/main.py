"""FastAPI application factory and middleware wiring."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# MUST run before any app import. Several modules (app.db.base,
# search_service, providers) read their configuration at import time, so
# loading .env afterwards silently leaves every one of them on its default.
load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.middleware.csrf import CSRFMiddleware  # noqa: E402
from app.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402
from app.routes import auth, career, future_of_work, jobs, portal  # noqa: E402

logging.basicConfig(level=logging.INFO)

# httpx logs every request URL at INFO, query string included. Several of our
# upstreams (Adzuna in particular) pass credentials as query parameters, so
# leaving this on writes API keys to the log in plaintext. Our own error paths
# redact; this silences the library's.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Redact PII and credentials from every log record, regardless of call site.
from app.logging_filters import install as _install_redaction  # noqa: E402

_install_redaction()

# Interactive docs (/docs, /redoc, /openapi.json) are a full map of the API.
# Handy locally; on the public site they only help someone probing it.
# serve.sh sets SERVE_STATIC, so production gets none of them.
_PUBLIC = os.getenv("SERVE_STATIC", "").lower() in {"1", "true", "yes"}

app = FastAPI(
    title="Insite API",
    description="Backend API for the Insite HR applicant portal",
    version="0.1.0",
    docs_url=None if _PUBLIC else "/docs",
    redoc_url=None if _PUBLIC else "/redoc",
    openapi_url=None if _PUBLIC else "/openapi.json",
)

# The Vite dev server proxies /api, so CORS only matters for direct calls.
_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(future_of_work.router, prefix="/api")
app.include_router(career.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(portal.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")


# ---------------------------------------------------------------------------
# Static frontend (production)
# ---------------------------------------------------------------------------
# In development the Vite dev server serves the UI and proxies /api here. In
# production we serve the built assets from this process instead, so there is
# exactly one origin and one port to expose through the tunnel. The dev server
# must never face the internet: it ships unminified source and an open
# hot-reload websocket.

_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
SERVE_STATIC = os.getenv("SERVE_STATIC", "").lower() in {"1", "true", "yes"}


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok", "service": "insite-api", "version": app.version}


if SERVE_STATIC:
    if not _DIST.is_dir():
        raise RuntimeError(
            f"SERVE_STATIC is on but {_DIST} does not exist. "
            "Run `npm run build` in frontend/ first."
        )

    from fastapi.responses import FileResponse  # noqa: E402
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    # Hashed asset filenames, so they can be cached hard.
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve index.html for client-side routes.

        Registered last so every /api route still wins. A real file is served
        when one exists (favicon, vite.svg); everything else falls through to
        the SPA, which is what makes /pathway and /jobs work on a hard reload.
        """
        candidate = (_DIST / full_path).resolve()
        # Contain the path: never serve outside dist, whatever the URL says.
        if full_path and candidate.is_file() and _DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
