# Insite

**Career planning for job seekers in any field.** Enter the work you do today
and Insite shows where it can realistically lead: which roles open up next,
what they pay, who is hiring, and which other jobs your current skills
already carry over to. It also filters job postings honestly, and lets you
keep track of the applications you send.

Built for people planning their next move, not just "which software company
next". Career paths cover **867 occupations across all 23 US occupation
groups**, from nurses and electricians to accountants, cooks and truck
drivers.

> Live at **app.mateuszbieda.dev**. Invite-only while in early testing.

## What it does

| Feature | What you get |
|---|---|
| **Career Pathway** | From your current role: realistic next steps, official wages (BLS), who is hiring (Adzuna), and a readable summary |
| **Your skills also apply to** | Other occupations your skills transfer to, labelled *likely qualify now* vs *needs more training*, with the pay difference |
| **Honest job filter** | Every posting says whether its salary is **employer-stated or estimated**, and whether "remote" is **really remote** |
| **Application tracking** | Mark live postings as applied and record what happened next; survives reposts |
| **Your data, your call** | Export everything you've entered from the profile page; account erasure is built into the API (`DELETE /api/me`) |

### Why the honest filter exists

Measured against live Adzuna data before building it: of **250** sampled US
postings, only **14%** carried an employer-stated salary. The other 86% were
the job board's own predictions, returned in the same fields. A search for
"remote software engineer" returned 1,206 results, of which exactly **one**
was genuinely remote with employer-stated pay.

So every posting carries a `salary_source` (stated / estimated / absent) and
a `remote_claim` (remote / conflicted / onsite), shown in the UI. A salary
floor only admits employer-stated figures, and when filters hide results the
UI says how many and why.

## Design principles

- **Facts come from data; the model only writes prose.** Occupations, pathways,
  wages and hiring figures come from O*NET, BLS and Adzuna. The language model
  turns them into a readable summary and never supplies a number.
- **A fallback is never presented as measured data.** Each response names its
  sources, and the UI flags any source that isn't live. Missing wage data is
  `null`, never a plausible guess.
- **Local AI by default.** Summaries run on a local model through Ollama: no
  per-token cost, and nothing a user enters is sent to an outside AI service.
  A paid API tier exists but is off unless explicitly enabled twice (see
  [Engines](#engines)).
- **Privacy by default.** Argon2id passwords, server-side sessions, CSRF
  protection, PII and credentials redacted from logs, data export and
  erasure, scheduled retention.

## Architecture

```
Browser ── React + TypeScript + Vite + Tailwind
   │
   ▼  /api  (same origin; CSRF-checked)
FastAPI ── routes ─► services ─► labour sources   O*NET · BLS · Adzuna
   │                    │       ► synthesis        Ollama (local) · Anthropic (off)
   │                    │       ► web search       Tavily · mock
   ▼
Postgres 17 (Alembic migrations)
```

```
frontend/src/
  pages/, components/      Career Pathway, Find Roles, Applications, Profile
  lib/api.ts               typed API client (mirrors the Pydantic models)
backend/app/
  routes/                  career, jobs, portal (profile/applications), auth
  services/labor/          O*NET, BLS, Adzuna clients + skills taxonomy
  services/providers/      synthesis engines: ollama, anthropic, mock
  services/job_search.py   honest filter: salary provenance, remote verification
  middleware/              CSRF, security headers
  data/                    vendored O*NET occupations and relatedness graph
backend/tests/             159 tests (SQLite, no network, no secrets)
frontend/e2e/              browser checks (Playwright)
```

## Data sources

| Need | Source | Notes |
|---|---|---|
| Occupations, related roles, skills | **O*NET** | Public database files vendored in `backend/app/data/` (867 occupations, 15,933 relatedness edges, 35-dimension skill profiles) |
| Wages | **BLS OEWS** | Needs a free key. Verified against the live API: keyless access returns no wage series at all |
| Hiring, top employers, pay spread | **Adzuna** | Free tier |
| Recent context | **Tavily** | Optional; web search is garnish, not the substrate |

US-first by necessity: O*NET and BLS are US-only. Other countries need their
own sources (e.g. ONS in the UK, ESCO in the EU); the provider pattern makes
that additive.

## Run it locally

Requirements: Python 3.12, Node 20+, Docker, and optionally
[Ollama](https://ollama.com) (`ollama pull llama3.1:8b`). Without Ollama the
backend falls back to a mock engine.

```bash
# 1. Database
cp .env.example .env                       # set POSTGRES_PASSWORD
docker compose up -d

# 2. Backend
cp backend/.env.example backend/.env       # set DATABASE_URL; API keys optional
uv venv --python 3.12 backend/.venv        # or: python3.12 -m venv backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
(cd backend && .venv/bin/alembic upgrade head)

# 3. Frontend
(cd frontend && npm install)

# 4. Both servers
./dev.sh                                   # open http://localhost:5173
```

Every setting has a safe default; data sources without keys run on clearly
labelled fallbacks. `GET /api/labor/status` shows which sources are live.

### Tests

```bash
cd backend && .venv/bin/python -m pytest -q          # 159 tests
cd frontend && npm run typecheck && npm run build
cd frontend && npm run demo        # browser checks; needs ./dev.sh running
```

## Engines

| Provider | Tier | Key needed | Default |
|---|---|---|---|
| `ollama` | local | no | ✅ preferred |
| `mock` | local | no | fallback |
| `anthropic` | **paid** | `ANTHROPIC_API_KEY` | 🔒 off |

`SYNTHESIS_PROVIDER=auto` tries **ollama → mock** and never auto-selects a
paid provider. Spending money takes two explicit steps:
`ENABLE_PAID_PROVIDERS=true` **and** naming the provider. Miss either and the
API returns `503` with the reason.

Generation is constrained by a JSON schema passed to Ollama's `format`
parameter, so output conforms without relying on the model to follow
formatting instructions. Expect ~20–25 s per summary on an 8B model.

Adding an engine: subclass `SynthesisProvider`, implement `generate_json` and
`health`, register it in `_REGISTRY`. That's the path for vLLM, llama.cpp,
LM Studio, OpenAI or Gemini.

## Search layer: measured, not guessed

DuckDuckGo publishes no web-search API; the `ddgs` package scrapes HTML
endpoints. Measured from one residential IP:

- 12-query burst at ~0.5 req/s → **1 hard failure (~8%)**
- Pinned to DuckDuckGo only, 5-query fan-out → **4 of 5 queries failed all 3 retries**
- Left on `auto`, the same fan-out succeeded, because `ddgs` 9.x silently
  fans out to Google, Bing, Brave, Yandex and others, none of which permit it

So `ddg` stays a dev-only option pinned to DuckDuckGo, and production uses
Tavily.

## Delivery

- **CI** (GitLab): backend tests, frontend typecheck and build, SAST and
  secret detection on every change.
- **Environments:** dev → staging → live. Every merge to `main` is tagged
  as a release (`vYYYY.MM.DD-N`) automatically; the tag deploys itself to
  staging and is verified there, and the same build goes live with one
  manual pipeline job, which only ships what staging is running. The
  previous release is kept, so rollback is one job as well. Release and
  deploy jobs run on a protected runner on the host machine.
- **Production mode** (`serve.sh`) serves the built frontend from the API
  process on one origin, runs migrations, and refuses to start with insecure
  settings (non-HTTPS URL, insecure cookies, localhost CORS, undeliverable
  email).
- **Backups:** nightly encrypted `pg_dump` with an offsite copy.

## Attribution

This site incorporates information from O*NET Web Services by the U.S.
Department of Labor, Employment and Training Administration (USDOL/ETA).
O*NET® is a trademark of USDOL/ETA. O*NET data is licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Wage data from the
U.S. Bureau of Labor Statistics. Job data from Adzuna.

## License

No license is granted. The source is published so it can be read and
reviewed; all rights are reserved.
