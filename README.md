# Insite

HR applicant portal. React + TypeScript + Vite frontend, FastAPI backend that
researches "Future of Work" trends for a given industry.

Analysis runs on **local models by default** — no API key, no per-token cost,
and no applicant data leaving the machine. A metered paid tier is wired in but
switched off until you opt in.

## Layout

```
frontend/                      React + TS + Vite + Tailwind v4
  src/lib/api.ts               typed API client (mirrors the Pydantic models)
  src/components/
    Dashboard.tsx              industry input + structured findings display
    ProviderPicker.tsx         engine selector; locks the paid tier
    Layout.tsx                 sidebar shell
  src/pages/                   route wrappers
backend/
  main.py                      entrypoint -> `uvicorn main:app`
  app/main.py                  FastAPI app, CORS, router wiring
  app/routes/future_of_work.py endpoints + request/response models
  app/services/
    search_service.py          web-search layer (mock | tavily)
    synthesis_service.py       prompt construction + report schema
    providers/
      base.py                  SynthesisProvider contract, tiers
      __init__.py              registry, auto-select, paid gating
      ollama_provider.py       local models  (tier: local)
      anthropic_provider.py    paid API      (tier: paid)
      mock_provider.py         offline stub  (tier: local)
dev.sh                         launches both servers
```

## Run

```bash
npm run dev     # or: ./dev.sh
```

- Frontend: http://localhost:5173 ← open this one
- Backend: http://localhost:8000 (interactive API docs at `/docs`)

Vite proxies `/api` to port 8000, so the browser only talks to 5173.

For local analysis, Ollama must be running: `ollama serve`. If it isn't,
`dev.sh` warns and the backend falls back to the mock provider rather than
failing.

## Engines

| Provider | Tier | Key needed | Default |
|---|---|---|---|
| `ollama` | local | no | ✅ preferred |
| `mock` | local | no | fallback |
| `anthropic` | **paid** | `ANTHROPIC_API_KEY` | 🔒 off |

`SYNTHESIS_PROVIDER=auto` (the default) tries **ollama → mock**. It will
*never* auto-select a paid provider. Spending money takes two explicit steps:

1. `ENABLE_PAID_PROVIDERS=true`
2. Name it — `SYNTHESIS_PROVIDER=anthropic`, or per-request
   `{"provider": "anthropic"}`

Miss either and the API returns `503` with the reason. Every response carries
`provider` / `provider_label`, and the UI badges which engine wrote the report.

### Local models

Configured via `OLLAMA_MODEL`. Bare names resolve to a pulled tag, so
`llama3.1` finds `llama3.1:8b`. Currently pulled here: `llama3.1:8b`,
`qwen3.5:9b`, `qwen2.5:7b`, `qwen2.5-coder:7b`, `qwen-agent`.

Generation is constrained by a JSON schema passed to Ollama's `format`
parameter, so output conforms without relying on the model to follow
formatting instructions. Expect ~20-25s per report on an 8B model; the
frontend sets expectations during the wait and `OLLAMA_TIMEOUT` defaults to
300s.

### Adding another engine

Subclass `SynthesisProvider`, implement `generate_json` and `health`, add it to
`_REGISTRY`. Roughly 40 lines — that is the path for vLLM, llama.cpp,
LM Studio, OpenAI, or Gemini.

## API

```
GET  /api/health
GET  /api/providers          -> engines, availability, paid_enabled
POST /api/future-of-work     -> {"industry": "...", "job_title": "...", "provider": "..."}
```

`job_title` and `provider` are optional. Status codes: `422` invalid input,
`503` engine unavailable (with an actionable reason), `502` unexpected failure.

## Search layer — measured, not guessed

| Provider | Key | Cost | Verdict |
|---|---|---|---|
| `mock` | no | free | default; deterministic stand-ins |
| `ddg` | no | free | **dev/demo only** — see below |
| `tavily` | yes | paid | production path |

### What testing DuckDuckGo actually showed

DuckDuckGo publishes **no web-search API**. (`api.duckduckgo.com` is the
Instant Answer API — definitions and disambiguation, not web results.) The only
route is the `ddgs` package, which scrapes HTML endpoints.

Measured on this machine, single residential IP:

- 12-query burst, no concurrency, ~0.5 req/s → **1 hard failure (~8%)**
- Pinned to DuckDuckGo only (`DDG_BACKEND=duckduckgo`), 5-query fan-out →
  **4 of 5 queries failed all 3 retries**
- Left on `auto`, the same fan-out returned **25 good findings** (Deloitte,
  WRI, WEF) in ~62s

That gap matters: `ddgs` 9.x bundles ~17 engines and, unpinned, silently fans
out to **Google, Bing, Brave, Yandex, Startpage, Mojeek, Yahoo**. Brave and
Google returned `429`/captcha during the run. So "we use DuckDuckGo" would be
inaccurate — unpinned, it scrapes most of the major engines, none of which
permit it.

We default to `DDG_BACKEND=duckduckgo` so behaviour matches the name. Set
`auto` for resilience, understanding what it does.

**Bottom line:** fine for local dev. Not something to put in front of
applicants — it is a scraper against ToS, with no availability guarantee.

## Career pathway — the labour-market layer

`POST /api/career-pathway` answers *"doing this work, after N months, what
opens up, who's hiring, what's the pay?"* by composing three sources, each
independently live or mocked:

| Capability | Source | Status | Register |
|---|---|---|---|
| Occupations + adjacency | O*NET | offline fallback | [developer](https://services.onetcenter.org/developer) |
| Wages | BLS OEWS | needs key | [registration](https://data.bls.gov/registrationEngine/) |
| Hiring + pay spread | Adzuna | needs key | [developer](https://developer.adzuna.com/) |

`GET /api/labor/status` reports which are live and where to register. Every
response carries `data_sources`, and the UI shows an amber banner naming what
is not yet connected — **a fallback is never presented as measured data**.

Design notes worth keeping:

- **BLS keyless does not cover wages.** Verified against the live API: CES/LNS
  series return data without a key, but every OEWS wage series returns "No Data
  Available" — including BLS's own documented example. The key is required for
  any pay figure.
- **Missing wage data returns `null`, not an estimate.** Pay is the field an
  applicant is most likely to act on, so the fallback omits it rather than
  inventing a plausible number. Likewise Adzuna's fallback names no employers.
- **Credentialled paths are tested.** Adzuna and BLS parsing were exercised
  against local stub servers shaped like the real APIs, so adding keys turns on
  a verified path rather than untested code.
- OEWS series IDs are built by `oews_series_id()`:
  `OE + U + areatype(1) + area(7) + industry(6) + occupation(6) + datatype(2)`.

## Where the real answers come from

The goal — *"after a year in this role, what opens up, who hires, what's the
pay?"* — is mostly **not** a web-search problem. Search returns prose; that
question wants structured labour-market data:

| Need | Source | Key | Cost |
|---|---|---|---|
| Role → adjacent roles, skills | **O*NET Web Services** | register | free |
| Wages, employment projections | **BLS Public API v2** | optional | free (500/day) |
| Live postings, **top hiring companies**, **salary histograms**, salary history | **Adzuna** | register | free tier (~1k/mo) |
| Narrative colour, recent news | Tavily / Brave / Exa | yes | paid |

- **O*NET** answers "what would I qualify for" — related occupations and
  skill overlap, not a model's guess.
- **BLS** answers "what is the pay" with official wage data. Verified working
  keyless here (returned Aug 2026 figures).
- **Adzuna** answers "who has been hiring" directly: `top_companies` and
  `histogram` endpoints, plus salary `history` for the look-back.

Web search should be the *garnish* on that, not the substrate.

## Environment

Copy `backend/.env.example` to `backend/.env` and edit. Every value has a safe
default; the app runs with no `.env` at all.

## Toolchain notes

- **Python 3.12.14**, installed via [uv](https://docs.astral.sh/uv/) into
  `~/.local/share/uv/python`. The venv is `backend/.venv`. macOS system Python
  (3.9) is no longer used.
- Rebuild the backend env: `uv venv --python 3.12 backend/.venv && uv pip install -r backend/requirements.txt`
- **Tailwind v4** via `@tailwindcss/vite`, not PostCSS. No `tailwind.config.js`
  is needed.
- `dev.sh` targets macOS bash 3.2, so no `wait -n`.
