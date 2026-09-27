# Insite: notes for Claude Code

The tool-neutral instructions are in [AGENTS.md](AGENTS.md): roles, the
planner → builder → swe-tester → peer-reviewer chain, change records, and
commit trailers. Read it, and [docs/PROJECT-GUIDE.md](docs/PROJECT-GUIDE.md),
first.

- The Claude Code subagents in `.claude/agents/` are thin adapters. Each role's spec is in `docs/agents/`.
- Tests: `cd backend && .venv/bin/python -m pytest -q`; `cd frontend && npm run typecheck && npm run build`.
- Never fabricate data or leave estimates unlabelled; never log PII or API keys; keep migrations additive.
- Work on a branch; `main` deploys to staging automatically.
- The private `REVIEW-LOG.md` (repo root, gitignored) holds open findings. Read it before planning or reviewing.
