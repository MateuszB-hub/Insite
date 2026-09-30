# Reliability: a real readiness check, one AI run at a time, and a long-résumé eval

Branch: `feat/reliability` · Kind: small fix (inline chain) · Release: <tag after merge>

## Plan
The owner asked for the reliability items (REVIEW-LOG W1, W2, W12, and the heat notes):
1. **Uptime monitoring (W1):** an outside monitor needs an endpoint that fails when the site is really down. `/api/health` stayed "ok" with the database gone. The monitor signup itself is the owner's step.
2. **Separate Adzuna key (W2):** the owner creates the key and edits their own env file; no code change needed (the dev `.env` and the live `.env.production` are already separate files).
3. **Heat:** the host is a fanless MacBook Air, and each model run is 30–70 s at full load. Run one at a time, unload the model after a minute, log each run's cost, and trial a smaller résumé model against the eval.
4. **Eval gap (W12):** every eval résumé was one page, so it scored 20/20 while a 7-page résumé failed live.

## Build
- **`GET /api/health/ready`** (no sign-in) returns `{"status", "database", "local_model"}`:
  - database down → **503** "down"
  - model off → 200 "degraded"
  - both answering → 200 "ok"
  - It runs `SELECT 1` and hits Ollama `/api/version` with a 2 s timeout. Nothing else is exposed.
- **`ollama_provider.py`:**
  - an app-side gate, one run at a time (per event loop, as in `adzuna_http`)
  - `keep_alive: "1m"` on every request (`OLLAMA_KEEP_ALIVE_SITE`)
  - one INFO line per run: `purpose`, model, time waited, time taken, prompt and output tokens; never content
  - callers name their purpose: `resume`, `pathway_summary`, `future_of_work`
- **`resume_eval.py`:**
  - a fifth résumé: 12 jobs with full bullets (about 17,700 characters, twice Ollama's old default context), with its certifications at the end
  - fixed: several models in one run now really use each model; before, the provider read `OLLAMA_MODEL` once, so a second model silently re-tested the first

## Tests
- pytest passes.
- `test_readiness.py`: ok, degraded, down (503), and minimal output.
- `test_ollama_context.py`: keep-alive sent, two runs at once take turns, the log line has purpose and tokens but no content.
- **Eval:**
  - llama3.1:8b scored **25/25** on every run (long résumé 37–41 s).
  - llama3.2:3b scored 23/25, then 25/25: about **2× faster** (long 18 s, short ~3.5 s), but one run lost the electrician's dates and location.
  - **Decision:** keep 8B for résumés, since the form shows these fields as facts.
- **Not tested:** the monitor itself (the owner sets it up); the heat effect in °C (use Activity Monitor, or `powermetrics`).

## Review
APPROVED.
- **L:** readiness is public, but reveals only ok, down or off, the same as the site being up or not.
- **L:** the gate queues a second résumé behind the first, so it can wait up to one run (about 30–70 s). The page polls, so it isn't cut off.
