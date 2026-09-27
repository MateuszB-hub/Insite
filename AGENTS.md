# Agents working on Insite

Instructions for any coding agent (Claude Code, Cursor, Codex, Copilot,
Gemini CLI, …) or person working on this repo. Nothing here is tied to one
tool: the specs are plain Markdown, and tool-specific files (such as
`.claude/agents/`) only point back here.

**Read first:** [docs/PROJECT-GUIDE.md](docs/PROJECT-GUIDE.md): the intent,
how the code fits together, the patterns to follow, and the evaluation
checklist. Every role below assumes it.

## Roles

| Role | Spec | Does | Never |
|---|---|---|---|
| Planner | [docs/agents/planner.md](docs/agents/planner.md) | Turns a big feature into a plan: acceptance criteria, edge cases, test plan, risks, gaps | Edits code |
| Builder | [docs/agents/builder.md](docs/agents/builder.md) | Implements the plan on a branch | Writes the tests that judge its own work (beyond keeping existing ones green) |
| SWE tester | [docs/agents/swe-tester.md](docs/agents/swe-tester.md) | Writes pytest unit and integration tests and browser demos from the plan; runs the edge-case pass | Changes app code |
| Peer reviewer | [docs/agents/peer-reviewer.md](docs/agents/peer-reviewer.md) | Reviews the whole change against the guide; approves or requests changes | Changes code or tests |

## The chain

```
big feature:   planner ─► (user approves plan) ─► builder ─► swe-tester ─► peer-reviewer ─┐
small fix:                                        builder ─► swe-tester ─► peer-reviewer ─┤
                                        ▲                                                  │
                                        └──────── changes requested (H or M findings) ─────┘
approved ─► push with auto-merge ─► CI ─► release tag ─► staging ─► manual deploy:live
```

- A **big feature** is new behaviour a user sees, a new data source, a
  migration, or anything touching auth, privacy or deploy. Everything else is
  a small fix.
- The person or agent running the chain (the **coordinator**) hands each role
  the change record and the branch, and passes the result on. For a big
  feature the plan goes to the user before any code is written.
- Roles run **separately**: the tester works from the plan's acceptance
  criteria, not from the builder's reasoning. That's deliberate. Tests
  written with the builder's assumptions miss what the builder missed.
- The chain pushes **once**, after the reviewer approves (see
  [Delivery](#delivery)).

## History: the change record and commits

Every change has a **change record**, `docs/changes/<branch-name>.md`
(slashes become dashes: `feat/place-fixes` → `feat-place-fixes.md`), made
from [docs/changes/TEMPLATE.md](docs/changes/TEMPLATE.md). Each role fills in
its own section (Plan, Build, Tests, Review). It's committed with the change,
so the MR diff shows the whole story and git keeps it for good.

Every commit names the role that made it with a trailer:

```
Agent: planner | builder | swe-tester | peer-reviewer | coordinator
```

(`coordinator` is for commits the one running the chain makes directly, such
as writing the plan into the change record.)

`git log --grep "Agent: swe-tester"` then shows every test commit, for
example. The history is: the change record says what and why; the commits
say who and when; the pipeline says whether it shipped.

The change record is **public** (the repo is mirrored to GitHub). Keep it to
facts about the code. Candid notes, reviewer quotes and anything about
exploiting a weakness go in the private review log (below), not here.

## Delivery

- Branch from `origin/main`: `feat/…`, `fix/…`, `docs/…`. Never commit to `main`.
- Commit as the repo's configured identity (a GitHub noreply address). Never a personal email.
- Push once the reviewer approves, creating a self-merging MR:
  ```bash
  git push -u origin <branch> \
    -o merge_request.create -o merge_request.target=main \
    -o merge_request.merge_when_pipeline_succeeds -o merge_request.remove_source_branch \
    -o "merge_request.title=<title>" \
    -o "merge_request.description=Change record: docs/changes/<branch>.md"
  ```
- A merge to `main` is tagged and deployed to staging automatically. Going
  live is a manual job the owner presses.

## Private files (never committed)

| File | What |
|---|---|
| `REVIEW-LOG.md` | The peer reviewer's candid log: recurring patterns (P1…), open items, dated entries. Read §1–2 before planning or reviewing |
| `TODO.md`, `PLAN-*.md` | The owner's working notes |
| `backend/.env`, `.env` | Secrets. Never read into output, logs, commits or change records |
