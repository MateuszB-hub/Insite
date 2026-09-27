# Insite project guide

What Insite is for, how the code fits together, the patterns it follows, and
how to evaluate a change. The [README](../README.md) covers features, data
sources, setup and delivery; this guide doesn't repeat them. Read it before
changing code or reviewing a change.

## 1. Intent

Insite helps a job seeker in **any** field answer three questions honestly:

1. *Where can my current work lead?* (Career Pathway: next roles, pay, training, skill gaps)
2. *Who is hiring for it, and is the posting what it claims?* (Find Roles: stated vs. estimated pay, real vs. "remote")
3. *What have I applied to?* (Applications)

Most of the value is in being **trustworthy**. Job boards mix predicted
salaries in with real ones and call hybrid jobs "remote". Insite is useful
only if it never does the same. A missing number is better than a
plausible-looking guess.

### Goals

- **Honest by construction:** every figure has a source; estimates are labelled; filters say what they hid and why.
- **Works outside tech:** 867 occupations in all 23 US groups. A nurse, cook or electrician gets the same quality as a software engineer.
- **Private by default:** personal data (profile, résumé text) only goes to the local model; logs never contain PII or keys.
- **Cheap to run:** it runs on one Mac behind a Cloudflare tunnel, with free API tiers and a local LLM.
- **Measured, not guessed:** search and parsing quality are tracked with evaluation scripts, not impressions.

### Non-goals (for now)

- Countries outside the US (O*NET, BLS and the Census place list are US-only).
- Applying to jobs on the user's behalf, or scraping employer sites.
- Using a paid AI API by default.

## 2. How the code fits together

```
Browser (React/Vite/TS/Tailwind)
  pages/*Page.tsx  ->  components/*.tsx  ->  lib/api.ts  (typed fetch, CSRF header)
                                               |
FastAPI  app/main.py  (middleware: CSRF, security headers, log redaction)
  routes/        thin: validate input, check auth, call a service, shape the response
  services/      the logic; no FastAPI imports beyond HTTPException where unavoidable
    career_service.py   pathway: taxonomy -> wages -> hiring -> readiness -> optional narrative
    job_search.py       Adzuna search + honest filter + title matching + dedupe + date cut-off
    places.py           typed location -> real US place (or unknown/invalid + suggestions)
    resume.py           PDF -> text (pypdf, capped) -> local model -> check() against the text
    labor/              data sources: taxonomy (O*NET), bls, adzuna(+_http), abbreviations, learning
    providers/          text engines: ollama (default), mock, anthropic (off unless enabled twice)
  data/          vendored JSON built by app/scripts/vendor_*.py (O*NET, BLS OEWS, Census places)
  db/models.py   SQLAlchemy models; alembic/versions for migrations
Postgres 17 (Docker): insite_dev, insite_staging, insite (live)
```

### One request, end to end (Find Roles)

1. `JobSearch.tsx` builds the query and calls `searchJobs()` in `lib/api.ts`.
2. `routes/jobs.py` requires sign-in, validates the parameters, and runs every
   typed place through `places.resolve()`. Unknown and junk places are
   reported in `place_checks` and never sent to the board. If none resolve,
   nothing is searched.
3. `services/job_search.search_jobs()` calls Adzuna via `labor/adzuna_http`,
   which paces calls (2 at a time) and retries 429/5xx while honouring
   Retry-After. It then applies title matching, the stated-pay and real-remote
   checks, job type, the exact date cut-off and dedupe, **counting everything
   it excludes**.
4. The response carries postings, the exclusion counts, `place_checks` and
   `also_searched`, so the UI can explain every gap.

### Vendored data

External data that rarely changes is fetched **once** by a script and
committed as JSON. The app doesn't depend on a live API for it, and the daily
quota isn't spent on page views.

| File | Built by | Source |
|---|---|---|
| `occupations.json`, `related.json`, `titles.json`, `abbreviations.json` | `vendor_onet.py` | O*NET 30.0 |
| `oews.json` | `vendor_bls.py` | BLS OEWS (500 calls/day key; resumable) |
| `places.json` | `vendor_places.py` | Census 2023 gazetteer + population estimates |

Live APIs are used only for things that change daily (job postings, hiring
counts).

### Environments and release

| Env | Port | Runs from | DB |
|---|---|---|---|
| dev | 8000 + Vite 5173 | the checkout (`./dev.sh`) | insite_dev |
| staging | 8081 | `~/Insite-Staging` (launchd `com.insite.staging`) | insite_staging |
| live | 8080 | `~/Insite-Live` (launchd `com.insite.web`) | insite |

The flow is: branch → MR (tests on shared runners) → self-merge →
`release:tag` → tag pipeline → `deploy:staging` and verify (Mac runner) →
**manual** `deploy:live` → `rollback:live` if needed. `scripts/live.sh` does
the deploy work and keeps the previous release in `$DIR.prev`, including its
migration files.

## 3. Coding patterns

### Honesty

- **Deterministic facts first, model text last.** Numbers, occupations and
  lists come from data. The model writes prose only. Model output is optional
  and labelled as such in the UI.
- **Check model output against the source.** `resume.check()` drops any item
  not found in the résumé text. Summaries that guess gender are dropped.
- **Label every estimate** (`salary_source`, `remote_claim`, "estimated, not
  from employer").
- **Count what filters remove** (`excluded_*` fields) and show it.
- **`null` over a guess.** When a wage is missing the UI says so; it never
  shows a nearby number.
- **Failures are loud and specific.** "Couldn't search Seattle just now" is
  good; silently returning fewer results is not. Failed upstream calls are
  **not cached**.

### Matching

- Use **general rules learned from data**, not one-off fixes: title matching
  on whole words, abbreviations learned from O*NET's paired titles, and places
  from the Census list. If a fix would only help the one example in a bug
  report, it's the wrong fix.
- Ambiguity is surfaced, not hidden: shared titles and place names show
  "showing X. Or: …" with one-click alternatives.

### Security and privacy

- Every `/api` route except auth requires sign-in. Changes need a CSRF header
  and a trusted origin.
- Logs go through `logging_filters.py`: never log request URLs that carry
  keys, never log résumé text, emails or names. Use `adzuna_http.describe(exc)`
  for errors (status code only).
- Personal data only goes to the **local** model (`get_provider("ollama")`).
- Limit inputs: size, pages, characters, time and rate (e.g. 5 MB / 10 pages /
  20k chars / 15 s / 5 per hour for résumés).
- Paid providers need `ENABLE_PAID_PROVIDERS=true` **and** an explicit name.

### Data and migrations

- **Migrations are additive** (new nullable columns or tables). Rollback runs
  old code against the new schema, so never rename or drop in the same
  release that stops using something.
- Vendored data is rebuilt by its script, never edited by hand.

### Style

- Backend: typed Python 3.12, small pure functions in services, dataclasses
  for results, `async` for I/O. Tests use SQLite, make no network calls and
  need no secrets. Mock external calls at the service boundary.
- Frontend: function components, Tailwind classes inline, types in
  `lib/api.ts` mirror the Pydantic models, and anything a hook doesn't need
  isn't named `use*`.
- Comments explain **why** (usually a measured fact or an incident), not what.
- UI text is plain English and says what happened and what to do next.

## 4. Evaluating a change

Use this list for any feature or review. A change isn't done until each item
has either been checked or is named as untested in the MR.

### Must pass

- [ ] `pytest -q` (backend), `npm run typecheck && npm run build` (frontend)
- [ ] New behaviour has tests, including at least one **failure** path
- [ ] Browser demo for UI changes (`frontend/e2e/*-demo.mjs`, `DEMO_BASE_URL` for a non-default port)
- [ ] Evaluation scripts still hold when search or parsing changed: `app/scripts/search_eval.py` (title matching 245/245) and `app/scripts/resume_eval.py` (no invented fields)

### Edge-case pass (do it, don't assume it)

| Category | Examples to try |
|---|---|
| Real-world input | abbreviations (QA, RN, NYC), accents (San José), punctuation (O'Fallon, St Paul), case and extra spaces |
| Wrong but plausible | typos, a city in the wrong state, a shared name (Springfield, Portland), a ZIP code, "Remote", a non-US city |
| Abuse | HTML/script, SQL-looking text, 100+ characters, empty, numbers only, very many values |
| Limits | upstream 429/5xx/timeouts, daily quotas, empty upstream results, slow model |
| Honesty | Does every number have a source? Is anything estimated and unlabelled? Does a filter hide results without saying so? |
| Privacy | Does anything new reach logs, a cache key or an outside service? |
| Deploy | Is the migration additive? Does rollback to the previous release still start? |

### Report boundaries honestly

State in the MR what **wasn't** tested: live APIs not called, browsers not
tried, data coverage gaps. An untested area that's written down is fine; one
that's hidden isn't.

## 5. Where things live

| Need | Look at |
|---|---|
| Add a data source | `services/labor/` (follow `bls.py`: live client + stored fallback) |
| Add a text engine | `services/providers/` (subclass `SynthesisProvider`, register it) |
| Change search behaviour | `services/job_search.py`, then run `search_eval.py` |
| Change location handling | `services/places.py`, `tests/test_places.py` |
| Change the pathway | `services/career_service.py`, `services/labor/taxonomy.py` |
| Deploy or rollback logic | `scripts/live.sh`, `.gitlab-ci.yml`, `scripts/release_tag.sh` |
| Backups | `scripts/backup_db.sh`, `scripts/restore_db.sh` |
