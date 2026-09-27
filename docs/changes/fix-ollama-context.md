# Résumé upload 524: the local model's context, output limits and polling

Branch: `fix/ollama-context` · Kind: small fix (a user-visible failure) · Release: <tag after merge>

## Plan
*Coordinator, inline.*

**Goal:** a long résumé imports instead of failing with Cloudflare's 524 page. The model sees the whole prompt, in every feature that uses it.

**Acceptance criteria:**
1. Every Ollama request sets a context window that fits the whole prompt plus the answer, and caps the answer's length.
2. An answer cut off at the cap is reported as such, not parsed as broken JSON.
3. The extraction schema enforces its own limits (jobs 20, skills 25, certifications 15, text lengths).
4. Résumé upload returns at once, and the page polls for the result. No request waits on the model, so Cloudflare's 100 s limit can't apply.
5. Jobs are private to their owner, handed over once, and forgotten after 10 minutes. Nothing is stored or logged.
6. A slow or failed read ends in a plain message.

**Current behaviour** (the owner's 7-page, 25k-character résumé, measured locally):
- Ollama's default context passed **2,050 of ~4,300 prompt tokens**, so over half the résumé was dropped without a word.
- The model then wrote until the 300 s timeout without closing its JSON.
- The site showed Cloudflare's **524**.
- Separately, the 20k-character cap cut the last pages: 0 certifications found, 3 jobs missing.

## Build
*Builder, inline.*

- `ollama_provider.py`:
  - `context_size(prompt)` works at 3 characters per token (on the safe side), plus the answer and a margin, rounded to 1k, within 4k–16k
  - `num_predict` defaults to 2048 (`OLLAMA_NUM_PREDICT`)
  - `done_reason == "length"` raises `ProviderUnavailable`
  - this also applies to the pathway narrative and synthesis prompts
- `resume.py`:
  - schema `maxItems`/`maxLength`
  - `MAX_CHARS` raised from 20k to 30k
  - `suggest_from_text` split out
  - `MODEL_TIMEOUT_S` = 240 s
- `routes/portal.py`: POST validates the PDF and returns 202 with a `job_id`; GET `/me/profile/resume/{job_id}` returns reading / done / failed. Held in memory; there is one worker (`serve.sh --workers 1`).
- `api.ts`: `uploadResume` polls every 2 s and gives up after 5 minutes. `ResumeImport.tsx` is unchanged apart from its wait message.

## Tests
*SWE tester, inline.*

| Criterion | Test | Result |
|---|---|---|
| 1 | `test_ollama_context.py`: short, long and capped sizes; the request carries `num_ctx`/`num_predict` | pass |
| 2 | `test_an_answer_cut_off_at_the_cap_is_reported_not_parsed` | pass |
| 3 | measured on the owner's PDF: 887–891 output tokens, `done=stop` (previously 2,048 and `length`) | pass |
| 4–5 | `test_portal.py`: 202 then poll; handed over once; someone else's job → 404; expiry; rate limit; bad file refused at once | pass |
| 6 | `test_resume_model_failure_is_a_plain_message`, `test_a_slow_model_gives_a_plain_message` | pass |
| end to end | `resume-demo.mjs` with `DEMO_EXTRA_RESUME` pointing at the owner's PDF: 13/13; the long résumé read in **51 s** without a timeout | pass |

**Tested:**
- pytest **336 passed**; typecheck and build pass
- the owner's PDF, locally only and never committed: previously >300 s and a failure; now 33–72 s
- 12 jobs and 9 certifications found (previously 9 jobs and 0 certifications); 4 invented certifications dropped by `check()`

**Not tested:**
- behaviour with two imports running at once (Ollama queues them, and each has 240 s)
- scanned PDFs (still refused, as before)
- whether the bigger context improves the pathway narrative or synthesis text; it's no longer cut, but the quality difference wasn't measured

## Review
*Peer reviewer, inline.*

**Verdict:** APPROVED

| ID | Sev | Finding | Resolution |
|---|---|---|---|
| R1 | M | Every feature using the local model may have had long prompts silently cut (synthesis with 25 findings, pathway narrative) | Fixed at the provider, so all callers are covered; the quality effect wasn't measured |
| R2 | L | Location stays empty on this résumé although the text has one near the top | Open: a model miss, and the field stays blank for the person to fill |
| R3 | L | Jobs are held in memory, so a server restart mid-read loses the job (the page then says "expired, upload again") | Accepted: single worker; the message is plain |
