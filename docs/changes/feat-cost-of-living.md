# Cost of living on Find Roles, and the résumé's location read by rule

Branch: `feat/cost-of-living` · Kind: big feature (inline chain) · Release: <tag after merge>

## Plan
The mentor asked for "cost-of-living differences if the candidate is switching cities" ("100k is basically 70k here"), and said of the résumé import: "the pdf gives the location". The owner chose the design after a review of the options:
- **Data:** BEA Regional Price Parities, stored with the app, not fetched live. Rejected: a live BEA API (no fresher, adds a key and a failure mode), paid indexes (C2ER, Numbeo), and AI research (no source).
- **Areas:**
  - For an advert, the job board's own place breakdown (US / state / county / city) → city → county → metro, falling back to the state.
  - For the person, their profile location through the place check.
- **Résumé location:** by rule first (a "City, ST" in the contact lines, checked against Census places), with the model's answer only as backup.
- **Calculation:** on the server; nothing in the page code.

**Acceptance criteria:**
1. A job with pay whose metro or state differs from home by at least 3% shows "≈ $X in <home> terms · living costs N% higher/lower in <area>", plus housing when it differs by at least 5%.
2. Same metro, remote jobs, unknown areas and no pay show no line.
3. A place outside any metro uses its state's average and says "on average".
4. With no home city, the page says how to add one.
5. Non-US places ("London") never count as home.
6. The résumé's contact-line location is found by rule; an invented one is still dropped.

## Build
- `vendor_col.py` → `col.json` (450 KB): 2024 indexes for 51 states and 387 metros, 1,186 metro counties, and 16,402 cities → metro. A city takes its county through shared ZIP-area land, since the Census publishes no place-to-county file. The .xlsx is read with the standard library.
- `living_costs.py`: `area_for_place`, `area_for_posting`, `compare`.
- `JobPosting.area` holds the board's breakdown. The route adds `living_cost` per job and `home_area`.
- `resume.location_in_text()`.
- `LivingCostLine` in `JobBits.tsx`, and the profile hint in `JobSearch.tsx`.

## Tests
- pytest **439 passed**. `test_living_costs.py` covers the data sanity checks, home areas (suburb, ZIP, borough, county, non-metro, state), advert areas (including the board's "Dallas" region level), the SF → Dallas figures, and the no-line cases. There's also a route test (no home → hint, home → comparison; same metro and remote → none), and résumé location by rule.
- `npm run demo:col` **4/4** live: the hint without a home city; San Francisco jobs shown in Dallas terms ("≈ $150,000 … living costs 12% higher in San Francisco; housing 65% higher"); Menlo Park counted as the San Francisco metro.
- On the mentor's own PDF, the location is now found (it was empty before).
- **Not tested:** other browsers; Career Pathway (not in scope).

## Review
APPROVED after one fix.
- **R1 (M):** "London" became a home area through its London, OH fallback. Fixed: a place carrying the US-only note is never home.
- **L:** a state average for non-metro places is coarse, and the page says "on average".
- **L:** taxes aren't included; the hover text says so.
