# Place handling: boroughs, remote, ZIPs, regions, non-US, accents, ranking

Branch: `feat/place-fixes` · Kind: big feature · Release: <tag after merge>

## Plan
*Coordinator, done inline. Covers review items O1–O8 from the place-check
release (v2026.09.27-6, staged).*

**Goal:** the common ways people type a US location either search the place
they meant or say exactly why not: boroughs, "Remote", ZIP codes, metro
regions, accented names, a wrong state. Places that share a name are ranked
by real population.

**Acceptance criteria:**
1. `Brooklyn`, `Manhattan`, `Queens`, `Bronx`/`The Bronx`, `Staten Island` (alone or with `NY`) search New York, NY, with a note saying so. `Brooklyn, OH` still searches Ohio.
2. `Remote`, `WFH`, `work from home`, `anywhere` aren't searched as places. They turn on the Remote-only filter, and when no other place is given the search is nationwide. A note says so, and the UI's Remote box shows as ticked.
3. A 5-digit ZIP (also `78701-1234` and `Austin, TX 78701`) searches the place it's in (`78701` → Austin, TX), with a note. A ZIP not in the Census list is `unknown`: "no US ZIP code 00000".
4. `Bay Area`, `Silicon Valley`, `DFW`, `Twin Cities`, `Research Triangle` search their main cities. `Greater Boston area` / `Boston metro` search Boston.
5. Well-known non-US cities say "Insite lists US jobs only". London still offers London, OH (ambiguous) and never suggests a random fuzzy match. Canadian/UK postcodes are invalid with the same message.
6. Accents are ignored when matching (`San José` = `San Jose` → San Jose, CA).
7. Places without a 2023 estimate (census-designated places, Puerto Rico) are ranked by their 2010 census count (`San Juan` → San Juan, PR). The count is used for ranking only and never displayed.
8. A known name in the wrong state (`Austin, CA`) suggests the same name in its real states (Austin, TX).
9. When a bare name is also a state (`Washington`), "WA State" is the first alternative.
10. No more than 3 places are searched per query (the Adzuna cost). If region expansion would exceed that, the dropped places are named in the response and on the page, not cut silently.
11. Nothing regresses: every existing place, route and browser test passes.

**Current behaviour (probe, 35 cases):**
- Brooklyn → OH, Manhattan → KS, Queens → unknown
- Remote → "did you mean Rote, PA"
- 78701 → invalid
- Bay Area → unknown, suggesting Bay Head, NJ
- London → London, OH with no warning
- San José → PR
- San Juan → TX (PR population 0)
- Austin, CA → no suggestion
- Washington State is 4th of 4 alternatives
- **12,748 of 35,320 places (36%) have population 0**, so ranking among shared names is often arbitrary.

**Approach:**
- *Data* (`vendor_places.py`):
  - 2010 gazetteer `POP10` by GEOID as a fallback for places and counties missing from the 2023 estimates.
  - New `zips.json`, built from the Census 2020 ZIP↔place and ZIP↔county relationship files. The place is used if it covers ≥50% of the ZIP's land; otherwise the county with the most overlap.
  - All sources are keyless public files.
- *Resolver* (`places.py`):
  - accent folding in `_norm`
  - borough and region tables (a region expands to ≤3 places)
  - "greater … area" / "… metro" stripping
  - remote words → status `remote`
  - ZIP lookup, which runs before the has-letters rule
  - a short list of well-known non-US cities, plus a postcode pattern
  - wrong-state suggestions
  - state alternative first
  - `Resolution` gains `note` and `places` (the expanded list)
- *Route* (`jobs.py`): flatten `places`, dedupe, cap at 3 and report the rest in `places_not_searched`. A remote check forces `remote_only`, and if there are no real places the search is nationwide.
- *UI* (`JobSearch.tsx`): PlaceNotes shows `note`. Tags become the expanded places. A remote check ticks the Remote box. "US jobs only" goes under the location field.

*Rejected:*
- Passing ZIPs straight to the board: unverified, and it undoes "the board never has to guess".
- The Census API for 2020 counts: it now needs a key.
- A general neighbourhood gazetteer: no free national source. The boroughs cover the big case; others are listed under Gaps.

**Files:** `backend/app/scripts/vendor_places.py`, `backend/app/data/places.json`, `backend/app/data/zips.json` (new), `backend/app/data/README.md`, `backend/app/services/places.py`, `backend/app/routes/jobs.py`, `frontend/src/lib/api.ts`, `frontend/src/components/JobSearch.tsx`, and tests.

**Data and migrations:**
- No schema change. `zips.json` is expected to be about 0.4 MB, loaded only when a ZIP is typed.
- `places.json` stays the same size.
- No quota use: all data is vendored.

**Edge cases:**

| Input / situation | Expected |
|---|---|
| `brooklyn ny`, `BROOKLYN` | New York, NY + note |
| `Brooklyn, OH` | Brooklyn, OH |
| `remote`, `Remote US`, `wfh` | remote: nationwide + remote only |
| `Remote` + `Austin` | Austin, TX, remote only |
| `78701-1234`, `Austin TX 78701` | Austin, TX + note |
| `00000`, `123456` | unknown ZIP / invalid |
| `M5V 2T6`, `SW1A 1AA` | invalid, US-only message |
| `Paris` | Paris, TX (ambiguous) + US-only note |
| `Tokyo` | unknown, US-only note, no fuzzy suggestion |
| `Bay Area` + `Austin` + `Denver` | 3 searched; the rest named as not searched |
| `greater  boston area` | Boston, MA |
| `San José`, `Cañon City` | accents folded |
| `<script>`, 120 chars, `.` | unchanged: unknown / 422 / invalid |
| Privacy | nothing new logged; inputs aren't stored |
| Deploy | data-only plus code; rollback safe (no migration) |

**Test plan:**
- *Unit:* a parametrized table in `test_places.py` covering criteria 1–9 and the edge cases.
- *Integration:* route tests in `test_portal.py` for 2 (nationwide + remote_only passed), 4/10 (expansion and cap reported) and 3.
- *Browser:* extend `places-demo.mjs` with Brooklyn and Remote.
- *Data:* the vendor script prints the zero-population count before and after.

**Risks and rollback:**
- A borough alias hides a real small town (Brooklyn, IA). Mitigated: the state suffix still wins, and the note shows what was searched.
- The region list is opinionated. It's kept small.
- No migration, so rolling back to v2026.09.27-6 is safe.

**Gaps and open questions:**
- Other neighbourhoods (Hollywood, Harlem, SoHo) aren't covered. *Recommend:* grow the alias table when real searches show them.
- Remote words could also be detected inside the job title field ("remote nurse"). *Recommend:* out of scope.
- The 2010 counts are old. They're only used to break ties among uncounted places, which is acceptable.

**Release note:** Find Roles now understands NYC boroughs, ZIP codes, "Remote", and areas like the Bay Area. It also says clearly when a place is outside the US.

## Build
*Builder, done inline.*

- **Data:**
  - `vendor_places.py` adds 2010 counts (by GEOID) where the 2023 estimates skip a place. Places without a population fell from **12,748 to 2,966** of 35,320. San Juan, PR (381,931) now outranks San Juan, TX.
  - New `zips.json`: **33,571 ZIP codes**, 425 KB, loaded only when a ZIP is typed. Spot checks: 78701 → Austin, TX; 11201 → New York, NY; 00901 → San Juan, PR; 59001 (rural) → Stillwater County, MT.
- **Resolver (`places.py`):**
  - accent folding
  - borough, region, remote-word and non-US tables
  - ZIP and postcode patterns
  - "greater … area" / "… metro" retry
  - wrong-state suggestions
  - state alternative first
  - `note` and `places` on every `Resolution`
- **Route:** places are flattened and deduped, then capped at 3, with the rest in `places_not_searched`. A remote word sets `remote_only` and allows a nationwide search (`remote_from_place`).
- **UI:**
  - PlaceNotes shows notes and the not-searched list
  - tags show every searched place
  - the Remote box ticks itself after a remote word
  - the label says "US only"
  - 5-digit ZIPs pass the client-side check
- **Differs from plan:** none. The borough note uses the borough's own name, not the raw input ("Brooklyn", not "brooklyn ny").
- **Checks:** pytest 326 passed; `npm run typecheck` and `npm run build` pass.
