# Plan: Automated Feature Pipeline

## Context

The current workflow requires a human to manually invoke each agent in sequence. This plan
introduces a two-component system that shifts the planning work to a background schedule
and compresses the development sequence into a single command:

1. **Issue Crawler** (scheduled) — periodically fetches open GitHub issues and converts each
   unplanned one into a plan file using the product-planner logic. Runs without human
   involvement. Plans accumulate in `markdown/plans/` until someone acts on them.

2. **`/develop` command** (human-triggered) — the human reviews the generated plans, picks one,
   and runs `/develop <plan-slug>`. This triggers an automated sequence: test stubs → implementation
   → QA + docs → consolidated report. The human then reads the report and, if satisfied, closes
   the GitHub issue.

Two human gates, nothing else:
- **Gate 1:** Choosing which plan to act on (implicit — by running `/develop`)
- **Gate 2:** Reading the report and closing the issue

---

## Token Cost Analysis

### Issue Crawler (scheduled)

Runs once per scheduled interval. For each new issue:
- GitHub API fetch: negligible
- Product-planner logic (reads stories index, features README, existing plans): ~12–18k input tokens
- Plan + stories + feature stub output: ~4–6k output tokens

At 1–3 new issues per week: **~25–70k tokens/week** for planning. At Sonnet pricing
(~$3/MTok in, ~$15/MTok out): **≈ $0.15–0.35/week**.

### `/develop` pipeline (human-triggered, subagents)

Each stage runs in an isolated subagent — no context accumulation between stages:

| Stage | Subagent input | Summary back |
|---|---|---|
| test-planner | 15–20k tok | 1–2k tok |
| developer | 25–45k tok | 2–3k tok |
| qa-engineer + doc-steward (parallel) | 18–25k tok | 1–2k tok |
| Orchestrator overhead | 5–8k tok | — |
| **Total** | **~65–100k tok** | **~6–9k tok** |

Per feature: **≈ $0.35–0.55**. At one feature per week: under $0.60/week total including
planning. For a hobby project this is negligible.

### Why subagents rather than inline skills

Running the stages in the same conversation accumulates context: by the time the developer
runs, it pays input-token cost for every file the test-planner and product-planner read even
though it does not need any of it. Subagents isolate context: each agent reads only what it
needs, and the `/develop` orchestrator accumulates only compact summaries (2–3k tokens each).

The quality benefit matters more than the cost: the developer agent starts with a clean
context focused entirely on the plan and critical files.

---

## Architecture

```
GitHub Issues (open)
       │
       ▼  [scheduled — no human involvement]
  Issue Crawler
       │  fetches new issues, skips already-planned ones
       │  runs product-planner logic per issue
       ▼
  markdown/plans/plan-issue-{N}-{slug}.md
  markdown/stories/ (updated)
  markdown/features/reference/{slug}.md (stub)
  markdown/plans/.issue-index (tracking file)

       │  [HUMAN GATE 1: review plan, choose to develop]
       │
       ▼  /develop <plan-slug>
  ┌─ test-planner ──────────────────────────────────┐
  │  reads plan → writes backend/tests/test_{slug}.py│
  │  (failing stubs, one per acceptance criterion)   │
  └──────────────────────────────────────────────────┘
       │
       ▼
  ┌─ developer ──────────────────────────────────────┐
  │  reads plan + stubs → implements feature          │
  │  makes all stubs pass → fills feature doc stub    │
  └──────────────────────────────────────────────────┘
       │
       ▼
  ┌─ qa-engineer ──────────┐  ┌─ doc-steward ───────┐
  │  runs full pytest suite │  │  checks doc drift    │
  └────────────────────────┘  └─────────────────────┘
       │
       ▼
  Consolidated report (files changed, test results, doc findings,
  gh issue close N command if issue number is known)

       │  [HUMAN GATE 2: read report, close issue]
       │
       ▼  gh issue close N
  Issue closed
```

---

## New Components

### Issue tracking file: `markdown/plans/.issue-index`

A plain-text file, one entry per line, mapping issue numbers to plan slugs:
```
47 plan-issue-47-weekly-summary-email
52 plan-issue-52-player-profile-ui
```
The crawler reads this before fetching issues to know what is already planned. Any agent
that creates a plan from a GH issue appends to this file. Manually created plans do not
need an entry — the crawler will not know about them and may re-plan the same issue; that
is acceptable since the operator can add entries manually.

### Issue naming convention

Plans created from GH issues are named `plan-issue-{N}-{slug}.md`. The `{N}` allows
`/develop` to extract the issue number and include `gh issue close {N}` in the report.
Plans created manually (without an issue) keep the existing `plan-{slug}.md` naming.

### Scheduled Issue Crawler

A background agent registered with CronCreate. Runs on a configurable schedule (default:
daily at 08:00). For each open issue not in `.issue-index`:
1. Fetch issue body via `gh api repos/{owner}/{repo}/issues/{N}`
2. Run product-planner logic to generate the plan, stories, and feature stub
3. Append `N plan-issue-N-{slug}` to `.issue-index`

The crawler creates plans but does not run `/develop`. It does not comment on issues.

### New skill: `/test-planner`

Reads an approved plan and writes failing pytest stubs to `backend/tests/test_{slug}.py`.
Each stub raises `pytest.fail("not yet implemented")` so it fails before the developer
writes any code. The developer replaces placeholders with real assertions as part of
implementation.

**One test per acceptance criterion** from the plan's user stories, plus one negative
case per new endpoint (auth failure or invalid input).

### New skill: `/develop`

Orchestrates the three post-approval stages in sequence using isolated subagents:
1. test-planner → test stubs
2. developer → implementation (makes stubs pass)
3. qa-engineer + doc-steward in parallel → validation

Stops if the developer reports a verification failure. Produces a consolidated report.

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `.claude/commands/test-planner.md` | New skill |
| `.claude/commands/develop.md` | New orchestrator skill |
| `markdown/plans/.issue-index` | New tracking file (empty initially) |
| `CLAUDE.MD` | Add new skills; replace Development Workflow section |

---

### Step 1 — Create `.issue-index`

Create `markdown/plans/.issue-index` as an empty file. The crawler appends to it;
no pre-population needed.

---

### Step 2 — Write the `test-planner` skill (`.claude/commands/test-planner.md`)

```markdown
<!-- version: 1 -->
<!-- mode: read-write -->

You are the **Test Planner** for this project.

## Role
Read an approved plan file and write failing pytest stubs that define acceptance criteria
before implementation begins. You write the test contracts; the developer fills them in.

## Scope
- Covers: `backend/tests/` (writing), `markdown/plans/` (reading), `backend/models.py`,
  `backend/tests/conftest.py`
- Does not cover: implementation, frontend tests, running tests (see `/qa-engineer`)

**Usage:** `/test-planner <plan-slug>`

## Precondition check
Resolve `markdown/plans/plan-$ARGUMENTS.md`. If missing, stop and list available plans.
If no `## Implementation` section, stop — plan is not ready.

---

## Phase 1 — Read context

1. Read the full plan file.
2. Read `backend/tests/conftest.py` — understand the `db` fixture.
3. Read one existing test file to understand naming and assertion conventions.
4. Read `backend/models.py` for model shapes the plan touches.

---

## Phase 2 — Write stubs

For each user story in the plan's user stories section:
- One test for the happy path
- One test for the primary failure path (auth failure, missing resource, or invalid input)

Each test:
- Named `test_<endpoint_or_function>_<scenario>`
- One-line docstring matching the acceptance criterion
- Uses `db` fixture for database-backed tests
- Body: `pytest.fail("not yet implemented")`

Write to `backend/tests/test_$ARGUMENTS.py`.

---

## Output format

```
Test stubs written: backend/tests/test_$ARGUMENTS.py

  test_<name> — <one-line description>
  ...

N stubs across Y user stories. Run /develop $ARGUMENTS to implement.
```
```

---

### Step 3 — Write the `/develop` skill (`.claude/commands/develop.md`)

```markdown
<!-- version: 1 -->
<!-- mode: read-write -->

You are the **Development Orchestrator** for this project.

## Role
Given an approved plan slug, run the full implementation pipeline: test stubs, code, and
validation. You spawn each stage as an isolated subagent. You stop on failure and report
clearly. You do not open PRs or push code.

**Usage:** `/develop <plan-slug>` — e.g. `/develop issue-47-weekly-summary-email`

## Precondition check
Resolve `markdown/plans/plan-$ARGUMENTS.md`. If missing, stop and list available plans.

---

## Stage 1 — Test stubs

Spawn a subagent with the test-planner role and instructions:
> Read `markdown/plans/plan-$ARGUMENTS.md`, then write failing pytest stubs to
> `backend/tests/test_$ARGUMENTS.py` following the test-planner skill instructions.

Collect: number of stubs written, file path.

---

## Stage 2 — Implementation

Spawn a subagent with the developer role and instructions:
> Read `markdown/plans/plan-$ARGUMENTS.md` and `backend/tests/test_$ARGUMENTS.py`.
> Implement the plan following the developer skill instructions, making all stubs pass.

If the subagent output contains `✗`, stop and display the failure. Do not proceed to Stage 3.

Collect: files changed list, verification results.

---

## Stage 3 — Validation (parallel)

Spawn two subagents simultaneously:

**QA Engineer subagent:**
> Run `cd backend && python -m pytest tests/ -v --tb=short 2>&1` and produce the QA
> engineer report format.

**Documentation Steward subagent:**
> Run the documentation steward checks against the current codebase and report findings.

Collect both reports.

---

## Output format

```
Development complete: $ARGUMENTS

Stage 1 — Test stubs:      backend/tests/test_$ARGUMENTS.py  (N stubs)
Stage 2 — Implementation:  ✓ / ✗
  Files changed:
    <path> — <description>
    ...
Stage 3 — QA:              ✓ all N tests pass / ✗ N failures
Stage 3 — Docs:            ✓ no drift / ✗ N gaps

{If any ✗:}
Action required:
  <specific failure description>

{If all ✓:}
Ready for review. If this resolves a GitHub issue:
  gh issue close <N>     ← replace N with the issue number
```

Extract the issue number from the plan slug if it matches `plan-issue-{N}-*`.
If found, replace the placeholder with the actual number in the output.
```

---

### Step 4 — Document the Issue Crawler design in CLAUDE.MD

The crawler itself is a prompt registered with CronCreate, not a skill file. Document it
in CLAUDE.MD under a new "Scheduled Jobs" section so future sessions know to re-register it:

```
### Issue Crawler (scheduled — re-register with CronCreate each session)

Fetches open GitHub issues and converts unplanned ones to plan files.

Schedule: daily at 08:00 (or: `/schedule daily issue crawl at 8am`)

What it does:
1. Read `markdown/plans/.issue-index` to find already-planned issue numbers
2. Run `gh issue list --state open --json number,title,body` to fetch open issues
3. For each issue number not in the index:
   a. Run product-planner logic on `{title} — {body}` as the feature description
   b. Name the plan `plan-issue-{N}-{slug}.md`
   c. Append `{N} plan-issue-{N}-{slug}` to `markdown/plans/.issue-index`
4. Report how many plans were created
```

---

### Step 5 — Update the Development Workflow in CLAUDE.MD

Replace the current 6-stage manual workflow with:

```
## Development Workflow

### Automated planning (background)
Plans are created automatically from GitHub issues by the scheduled Issue Crawler.
New plan files appear in `markdown/plans/` daily without manual intervention.
Re-register the crawler at the start of a session:
  /schedule daily issue crawl at 8am

### [HUMAN GATE 1] Choose a plan to implement
Review plan files in `markdown/plans/`. When ready to implement one:
  /develop <plan-slug>

This runs test stubs → implementation → QA + docs in sequence.
The command stops on failure and reports what needs fixing.

### [HUMAN GATE 2] Review report and close issue
Read the consolidated report. If the implementation is correct:
  gh issue close <N>

Individual skills (/product-planner, /developer, /qa-engineer, etc.) remain
directly invokable for ad-hoc work, bug fixes, and situations where the pipeline
is overkill.
```

---

## Verification

- Create a test GitHub issue on the repo
- Register the crawler via CronCreate (or trigger it manually)
- Confirm `markdown/plans/plan-issue-{N}-{slug}.md` is created and `.issue-index` is updated
- Run `/develop plan-issue-{N}-{slug}`
- Confirm test stubs are created and initially fail
- Confirm developer implementation makes stubs pass
- Confirm QA and doc-steward reports appear in the consolidated output
- Confirm `gh issue close N` appears in the output with the correct issue number
- Close the issue and confirm it closes on GitHub

---

## Design Decisions

**Why the crawler does not comment on issues**

Adding a GitHub comment when a plan is created creates noise and implies a commitment the
project may not honour. A plan file is internal infrastructure. The issue owner does not
need to know a plan file exists — they need to know when the feature is done.

**Why `.issue-index` over naming conventions alone**

Relying solely on `plan-issue-{N}-*.md` glob patterns fails silently if someone renames
a plan file or creates a plan manually with the standard `plan-{slug}.md` naming. A flat
index file is readable, auditable, and trivially updatable by any tool or by hand.

**Why `/develop` stops on Stage 2 failure**

Running QA when the developer reported a failure would produce a misleading "some tests
pass" report. The operator needs to fix the implementation failure before validation is
meaningful. Stopping early keeps the signal clean.

**Why the issue close is in the report, not automated**

The human reading the report is the authoritative reviewer. Automating the close would mean
the system asserts the feature is done — a claim only the operator can make after reading
diffs and the report. The close command in the output makes it one copy-paste away without
removing the human judgment step.
