# Insite: notes for coding agents

Read [docs/PROJECT-GUIDE.md](docs/PROJECT-GUIDE.md) first: the intent, how
the code fits together, the patterns to follow, and the checklist for
evaluating a change.

- Tests: `cd backend && .venv/bin/python -m pytest -q`; `cd frontend && npm run typecheck && npm run build`.
- Never fabricate data or leave estimates unlabelled; never log PII or API keys; keep migrations additive.
- Work on a branch; `main` deploys to staging automatically.
- If a private `REVIEW-LOG.md` exists at the repo root (gitignored), read it for open findings before a review.
