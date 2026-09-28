# Mentor round 3: long titles, hidden jobs, a search radius, a summary that's always grounded

Branch: `feat/mentor-round3` · Kind: big feature (inline chain) · Release: <tag after merge>

## Plan
The mentor's feedback on v2026.09.28-1, and what each point needed:
1. **"VP EAC Compliance & Operational Risk Specialist turns up nothing."** Title matching needs every word in an advert's title. **Fix:** when nothing matches, search the job inside the title: drop level words (VP, Senior…) and words in none of O*NET's 64k titles (EAC); "&" joins two jobs that share the last word. Say so on the page.
2. **"Show what filter blocked it, or an option to see filtered items."** Counts per filter already showed. **Fix:** return the hidden adverts (up to 50) with a plain reason each, behind a "Show the N hidden jobs" button.
3. **"For city you might also consider a distance range."** **Measured:** the board's default radius is about 5 miles (Austin nurses: 662 at the default, 657 at 8 km, 919 at 40 km, 2,103 at 80 km). **Fix:** a "Within" picker (5 / 10 / 25 / 50 miles), defaulting to 25.
4. **Résumé summary left blank after clearing it.** The model's summary was dropped by the new grounding rule. **Fix:** fall back to a summary built only from checked facts ("<latest title> with N years of experience."), labelled "written from your job titles and dates".
5. Spelling variants no longer include possessives ("vice president's …").

Not addressed yet, pending the mentor's screenshots: "qa lead gives physical check jobs" (Find Roles' first 30 "qa lead" results were all software QA), and the job advert that differs from the job site.

## Build
- `job_search.py`: `core_titles()`, a broadened search when there are 0 title matches, `hidden` with reasons (`HIDDEN_REASONS`, `MAX_HIDDEN`), and `distance_km`.
- `taxonomy.py`: `tokens()` and `title_vocabulary()`.
- `abbreviations.py`: no possessive expansions.
- `routes/jobs.py`: a `distance` query parameter (validated miles → km), and `broadened_to` and `hidden` (with `hidden_reason`) in the response.
- `resume.py`: the grounded fallback summary.
- `JobSearch.tsx` and `api.ts`: the Within picker, the broadened note, and the hidden-jobs toggle.

## Tests
- pytest **401 passed**: core titles table, no possessives, broadened search (faked board), hidden reasons, distance in km, route validation and payload, summary fallback.
- `npm run demo:round3`: **7/7** live checks: the long title finds 30 jobs and says what was searched; hidden jobs are shown with reasons; the radius is disabled without a place and sent with the search.
- Typecheck and build pass.
- **Not tested:** other browsers; how often a broadened search is wrong for other long titles (the fallback is labelled, so the person can judge).

## Review
APPROVED.
- **L:** the 25-mile default changes every city search's results (more, from further away). That's deliberate, and it matches other job sites.
- **L:** hidden adverts only cover what was inspected before the page filled (the counts and the list agree).
