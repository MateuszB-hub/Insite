# Agent roles, specs and change records

Branch: `docs/agent-specs` · Kind: small fix (docs only) · Release: next tag after merge

## Plan
*Written by the coordinator, per the owner's request.*

**Goal:** give every agent working on Insite, whatever the tool, an explicit
role spec (planner, builder, SWE tester, peer reviewer) built on one shared
project guide. Each change's plan, tests and review become part of git
history.

**Acceptance criteria:**
1. Each role has a plain-Markdown spec in `docs/agents/` that doesn't depend on any one tool.
2. `AGENTS.md` at the root describes the roles, the chain, change records, commit trailers and delivery.
3. The Claude Code subagents in `.claude/agents/` only point to those specs. Deleting the folder loses nothing.
4. The change record template has sections for each role, and this change uses it.
5. No secrets, private notes or reviewer quotes in any committed file.

**Approach:** tool-neutral specs are the source of truth, with thin adapters
per tool. Plans and findings go in a committed change record rather than in
MR descriptions set through the API: this works with plain `git push` and
survives the GitHub mirror.

**Gaps and open questions:** adapters for other tools (Cursor rules, Copilot
instructions) aren't written yet; each is a short pointer file when needed.

**Release note:** none (internal docs).

## Build

Added `AGENTS.md`, `docs/agents/{planner,builder,swe-tester,peer-reviewer}.md`,
`docs/changes/TEMPLATE.md`, `.claude/agents/*.md` (adapters). `CLAUDE.md` and
`docs/PROJECT-GUIDE.md` now point to `AGENTS.md`.

## Tests

Docs only. Checked that every file and script path the specs name exists.
Backend suite 326 passed on this base (ae2770a).
**Not tested:** that the Claude Code subagents load. They're read at session
start, so that's checked in the next session.

## Review

Not run: the reviewer role is defined by this change. The first full chain
runs on the next feature (place-handling fixes O1–O8).
