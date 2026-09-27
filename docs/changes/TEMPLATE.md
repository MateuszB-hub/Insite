# <Change title>

Branch: `<branch>` · Kind: big feature | small fix · Release: <tag, filled after merge>

## Plan
*Planner. For a small fix: the coordinator writes the goal and acceptance criteria only.*

**Goal:** what a user can do after this that they couldn't before, in one or two sentences.

**Acceptance criteria:** testable statements, numbered so tests can cite them.
1. …

**Current behaviour:** what was probed and what it showed (inputs → outputs).

**Approach:** chosen design, and alternatives rejected with the reason.

**Files:** expected to change.

**Data and migrations:** new vendored data, schema changes (additive only), quota use.

**Edge cases:** from the guide's edge-case table, with the expected result for each.

| Input / situation | Expected |
|---|---|

**Test plan:** unit / integration / browser demo / eval script, mapped to the criteria.

**Risks and rollback:** what could break, and whether rolling back to the previous release is safe.

**Gaps and open questions:** what this plan doesn't cover, and decisions for the owner.

**Release note:** one or two plain-English lines for users.

## Build
*Builder.*

- What was built, and any place it differs from the plan (with the reason).
- Commands run and their results.

## Tests
*SWE tester.*

| Criterion / edge case | Test | Result |
|---|---|---|

**Tested:** counts (pytest, demos, evals).
**Not tested:** specific, e.g. live API at volume, Safari, mobile, screen readers.
**Bugs found:** each with a failing test name, handed back to the builder.

## Review
*Peer reviewer.*

**Verdict:** APPROVED | CHANGES REQUESTED

| ID | Sev | File:line | Finding | Resolution |
|---|---|---|---|---|

**Patterns:** which REVIEW-LOG patterns (P1…) this change risked, and whether it avoided them.
