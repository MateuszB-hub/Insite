"""Backend entrypoint.

Run from the `backend/` directory:

    .venv/bin/uvicorn main:app --reload --port 8000

The application itself lives in `app/main.py`; this module is the stable
import target for process managers and the root `npm run dev` script.
"""

from app.main import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
