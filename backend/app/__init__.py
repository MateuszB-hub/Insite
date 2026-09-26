"""Insite backend package.

Environment is loaded here, at package import, so that EVERY entrypoint gets
it: the API server, Alembic, and the `python -m app.scripts.*` tools alike.
Doing it in `app/main.py` only covered the server, which meant the CLI tools
failed with "DATABASE_URL is not set" even though .env was sitting right
there.

`load_dotenv` does not override variables already present in the environment,
so explicit settings (CI, tests, `FOO=bar python -m ...`) still win.
"""

from pathlib import Path

from dotenv import load_dotenv

# backend/.env, resolved relative to this file rather than the cwd, so the
# tools work from any directory.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
