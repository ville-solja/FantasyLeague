## Documentation

The `markdown/` folder is the single source of truth for product intent. Always consult and keep these three locations up to date:

### markdown/stories/
User stories split into per-section files. The index is at `markdown/stories/_index.md`. Before implementing a feature, check whether it is already covered. After implementing, confirm the relevant story file matches the implementation.

### markdown/ui_description/
Short specifications for each UI tab and major component (one file per tab). Describes visible elements, table columns, button behaviours, and conditional states. When a tab changes — new element added, interaction changed, column removed — update the corresponding file. When adding a new tab or major section, create a new file here.

### markdown/features/
In-depth documentation for non-trivial features and mechanics, split into two tiers:
- `markdown/features/core/` — major user-facing surfaces (auth, cards, weeks, players, admin, twitch)
- `markdown/features/reference/` — implementation details, integrations, and operator tooling

The index is at `markdown/features/README.md`. When implementing a feature with enough complexity to warrant explanation, create or update a file in the appropriate tier. The README links to `markdown/features/README.md` rather than duplicating its content.

When a suitably large or complex subject is identified during implementation, ask the user whether a feature description document should be created.

## Readme
The README should stay reasonably sized with links to the markdown documentation. Do not duplicate content that belongs in `markdown/features/`.

---

## Developer Agents

The project uses role-based agents. Each is a slash command in `.claude/commands/`. Run them in Claude Code by typing the command name. All agents follow a shared design contract: they declare their scope, check preconditions before doing deep work, and define an explicit output format.

**Recommended session start:** run `/agent-steward` before `/product-planner` to ensure agent definitions are current.

---

### `/agent-steward`
**Role: Agent Steward (orchestrator)**
Validates all agent definitions in `.claude/commands/` and keeps them aligned with the codebase. It does not run other agents — it inspects and repairs their definitions.
- Checks every file path referenced in agent prompts still exists
- Verifies cited endpoint names appear in `backend/main.py`
- Confirms each agent has `<!-- version: N -->` and `<!-- mode: ... -->` headers
- Detects `backend/` or `markdown/features/` additions not covered by any agent
- Flags `CLAUDE.MD` entries whose command files have been deleted

**When to run:** After any merge that renames files, adds backend modules, or removes endpoints. Also run before `/product-planner` at the start of a planning session.

---

### `/product-planner`
**Role: Product Planner**
Formalises the creation of a new feature in one step. Given a feature description as the argument, it:
- Reads `markdown/stories/_index.md` to assign the correct next section number
- Drafts 2–5 user stories in the project's standard format
- Writes a plan file to `markdown/plans/plan-{slug}.md` (with user stories embedded)
- Creates a story section file at `markdown/stories/{NN}-{slug}.md` and updates `_index.md`
- Creates a feature stub in `markdown/features/reference/{slug}.md` (or `core/`) and updates `markdown/features/README.md`

**When to run:** At the start of any new feature, before writing any implementation code. Run `/agent-steward` first to ensure file references are current.

**Usage:** `/product-planner <description>` — e.g. `/product-planner Add a weekly summary email to notify users of their points`

---

### `/security-reviewer`
**Role: Security Reviewer**
Audits every FastAPI endpoint for authentication gaps, session leaks, input validation holes, and data over-exposure.
- Classifies every endpoint as Public / Auth required / Admin required / Twitch JWT required
- Flags missing `Depends()` guards
- Flags `SessionLocal()` calls without try/finally
- Flags bare `str` fields with no `Field(min_length, max_length)` constraint
- Flags endpoints returning raw SQLAlchemy model objects

**When to run:** Before pushing any change to `backend/main.py`. Also run after any new router is added.

---

### `/documentation-steward`
**Role: Documentation Steward**
Detects drift between `markdown/features/` docs and the actual backend implementation.
- Features described in docs with no corresponding endpoint or model
- Backend systems with no documentation counterpart
- Env vars in `.env.example` not mentioned in any doc
- Terminology mismatches between code and docs

**When to run:** After a significant backend change (new endpoints, renamed models, new env vars), or before writing a new plan.

---

### `/scoring-analyst`
**Role: Scoring Analyst**
Validates the fantasy scoring pipeline through static analysis — no code execution required.
- Checks every stat in `SCORING_STATS` has a matching `PlayerMatchStats` field
- Traces `fantasy_score()` and `card_fantasy_score()` with synthetic inputs and shows expected output
- Verifies `run_enrichment()` applies updates correctly and without double-counting
- Flags division-by-zero risks or unconstrained `CardModifier.stat_key` values

**When to run:** After any change to `backend/scoring.py`, `backend/enrich.py`, or the `WEIGHTS_JSON` env var.

---

### `/product-analyst`
**Role: Product Analyst**
Maps each entry in `markdown/stories/` to the implementation and marks it as Fully implemented / Partial / Missing. Produces a coverage percentage and a prioritised list of gaps.

**When to run:** Before sprint reviews or feature planning sessions.

---

### `/qa-engineer`
**Role: QA Engineer**
Runs the pytest suite in `backend/tests/` and reports results grouped by module.
- Covers `scoring.py` (unit tests for `fantasy_score` and `card_fantasy_score`)
- Covers `weeks.py` (fixture tests with in-memory SQLite for `generate_weeks` and `auto_lock_weeks`)
- Covers `auth.py` (bcrypt hash/verify round-trips)

**When to run:** After any change to `backend/scoring.py`, `backend/weeks.py`, or `backend/auth.py`. Also run after `/scoring-analyst` to confirm analytically traced inputs pass in code.

---

### `/systems-architect`
**Role: Systems Architect**
Reviews the full application architecture and produces a prioritised findings table covering:
- Separation of concerns (business logic mixed into request handlers, repeated query patterns)
- Data layer risks (N+1 queries, missing indexes, SQLite write-serialisation limits)
- Background job resilience (exception handling in background loops)
- Error handling and observability (print vs logging, unhandled 500 paths)
- Security posture (SQL injection in raw `text()` queries, insecure defaults, session config)
- Dependency and configuration hygiene (hardcoded values, unpinned packages, missing health check)
- Frontend structure (split points in `app.js`, async state management)

Each finding is classified **High / Medium / Low** with a concrete recommendation. The report ends with the top 3 highest-impact changes in priority order.

**When to run:** Before a refactor, after a significant feature addition, or when onboarding a new contributor. Run `/agent-steward` after if structural changes affect file paths that agents reference.

---

### `/developer`
**Role: Developer / Implementer**
Implements a feature from an approved plan file. Given a plan slug, it reads the plan, understands the existing codebase, writes code following project conventions, runs tests, and updates documentation stubs.
- Reads the plan's Critical Files table and all referenced source files before writing
- Follows existing FastAPI/SQLAlchemy/vanilla-JS patterns exactly
- Runs `pytest` and a quick import check after implementation
- Fills in `markdown/features/` stubs with actual endpoint signatures and env vars
- Flags any verification failure and stops rather than marking work as done

**When to run:** After `/product-planner` has created a plan and it has been reviewed. Run `/security-reviewer` and `/qa-engineer` after the developer finishes. Or use `/develop` to run the full pipeline automatically.

**Usage:** `/developer <plan-slug>` — e.g. `/developer azure-cloud-hosting`

---

### `/test-planner`
**Role: Test Planner**
Reads an approved plan and writes failing pytest stubs to `backend/tests/test_{slug}.py` — one stub per acceptance criterion. Each stub raises `pytest.fail("not yet implemented")` so it fails before the developer writes any code.

**When to run:** After a plan is approved and before implementation begins. Called automatically by `/develop` as Stage 1. Can also be run standalone before `/developer` for a manual workflow.

**Usage:** `/test-planner <plan-slug>` — e.g. `/test-planner twitch-mvp-series-window`

---

### `/develop`
**Role: Development Orchestrator**
Runs the full post-approval pipeline in three sequential stages using isolated subagents: test stubs → implementation → QA + docs validation. Stops and reports clearly if any stage fails.

1. **Stage 1 — Test stubs:** spawns test-planner to write failing stubs
2. **Stage 2 — Implementation:** spawns developer to implement the plan and make stubs pass
3. **Stage 3 — Validation:** spawns QA engineer + documentation steward in parallel

Produces a consolidated report including `gh issue close N` if the plan was created from a GitHub issue.

**When to run:** After reviewing a plan file and deciding to implement it. Replaces running `/test-planner`, `/developer`, `/qa-engineer`, and `/documentation-steward` individually.

**Usage:** `/develop <plan-slug>` — e.g. `/develop issue-42-twitch-mvp-series-window`

---

### `/ui-design`
**Role: UI Designer**
Generates well-branded interfaces and assets for Kanaliiga and its Fantasy app — production code edits or throwaway prototypes, mocks, and stream overlays.
- Reads brand context, design tokens, and the Fantasy web UI kit before producing any output
- Enforces non-negotiable brand rules: Big Shoulders Text ALL CAPS, orange/red flame palette, no emoji, no pill buttons, no left-border accent cards
- Produces either production edits to `frontend/` or self-contained HTML artifacts depending on the request

**When to run:** When building or redesigning any UI surface — new page, component, stream overlay, or design system change.

---

### `/ux-reviewer`
**Role: UX Reviewer**
Audits the Fantasy web app for usability and experience problems. Produces a prioritised findings table and a Top 5 improvements list, without touching code.
- Checks flow completeness, state coverage (loading/empty/error), information hierarchy, cross-tab consistency, accessibility basics, and copy quality
- Scoped to one tab or the full app depending on the argument
- Severity: High (blocks task) / Medium (friction) / Low (polish)

**When to run:** After a significant frontend change, before a release, or when a usability complaint is raised.

**Usage:** `/ux-reviewer` for a full review, or `/ux-reviewer <tab-name>` to scope to one tab.

---

---

## Development Workflow

### Automated planning (background)

Plans are created automatically from GitHub issues by the scheduled Issue Crawler (see Scheduled Jobs below). New plan files appear in `markdown/plans/` daily without manual intervention. Ad-hoc planning is still available via `/product-planner <description>`.

### [HUMAN GATE 1] — Review plan and implement

Browse `markdown/plans/` for pending plans. When ready to implement one:

```
/develop <plan-slug>
```

This runs three stages automatically: test stubs → implementation → QA + docs validation. The command stops on failure and reports what needs fixing.

For ad-hoc work, bug fixes, or situations where the full pipeline is overkill, the individual agents remain directly invokable: `/test-planner`, `/developer`, `/qa-engineer`, `/documentation-steward`.

### [HUMAN GATE 2] — Review report and close issue

Read the consolidated report from `/develop`. If the implementation is correct:

```
gh issue close <N>
```

(The `gh issue close` command appears in the report when the plan slug contains an issue number.)

### Review gates (run after any implementation)

| Agent | When required | Focus |
|---|---|---|
| `/security-reviewer` | Any change to `backend/main.py` | Auth gaps, session leaks, input validation, data exposure |
| `/qa-engineer` | Any backend change | pytest suite pass/fail |
| `/scoring-analyst` | Changes to `scoring.py`, `enrich.py`, or `WEIGHTS_JSON` | Formula correctness, division-by-zero, stat mapping |
| `/documentation-steward` | Any significant backend change | Doc drift, missing env vars, terminology mismatches |
| `/ux-reviewer` | Any significant frontend change | Flow completeness, state coverage, consistency, accessibility |
| `/product-analyst` | After a sprint or milestone | Story coverage percentage, prioritised gaps |
| `/systems-architect` | Before a refactor or new subsystem | Architecture risks, N+1 queries, background job resilience |

Address any **High** severity findings from `/security-reviewer` or `/systems-architect` before opening a PR.

### PR checklist

- [ ] `/security-reviewer` — no High findings
- [ ] `/qa-engineer` — all tests pass
- [ ] `markdown/features/` stub filled in (no `*(planned)*` for implemented routes)
- [ ] `.env.example` updated if new env vars were added
- [ ] `markdown/features/README.md` updated if a new feature file was created

---

## Scheduled Jobs

These are session-scoped — re-register at the start of a session.

### Issue Crawler (re-register with `/schedule daily issue crawl at 8am`)

Fetches open GitHub issues and converts unplanned ones to plan files automatically.

**What it does:**
1. Read `markdown/plans/.issue-index` to find already-planned issue numbers
2. Run `gh issue list --state open --json number,title,body` to fetch open issues
3. For each issue number not in the index:
   a. Run product-planner logic on `"{title} — {body}"` as the feature description
   b. Name the plan `plan-issue-{N}-{slug}.md`
   c. Append `{N} plan-issue-{N}-{slug}` to `markdown/plans/.issue-index`
4. Report how many plans were created

Plans are created but not implemented — the human reviews them and runs `/develop` when ready.

### Dependency Scout (re-register with `/schedule weekly dep check on Monday mornings`)

Checks every pinned package in `backend/requirements.txt` against PyPI and flags outdated or security-relevant versions. Run an ad-hoc check any time by asking: *"Check backend/requirements.txt packages for CVEs."*