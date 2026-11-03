# CLAUDE.md — Developer rules for this repo

## Schema migrations

When adding a column to an existing table in `backend/models.py`, add a numbered migration to `backend/migrate.py` in the same edit: a conditional `ALTER TABLE … ADD COLUMN` inside `run_migrations()`, guarded by a `PRAGMA table_info` check (see existing examples). New tables created by `Base.metadata.create_all()` need no migration. `tests/test_migrate.py::TestSchemaCoverage::test_all_model_columns_present_after_migration` enforces this.

## Pre-deploy backup

Run `bash scripts/backup-db.sh` before every deploy. See `markdown/features/reference/db-sustainability.md`.

## Tests

- Full backend suite: `cd backend && python -m pytest tests/ -n auto -q` (pytest-xdist; about a minute). CI runs the same.
- While iterating, run only the affected test files; run the full suite once at the end.
- Import check: `cd backend && DEBUG=true python -c "import main"`.

## Documentation

`markdown/` is the source of truth for product intent:
- `markdown/stories/`: user stories by topic; index `markdown/stories/_index.md`. Check before implementing, confirm after.
- `markdown/ui_description/`: one short spec per UI tab; update when a tab changes.
- `markdown/features/`: `core/` for major user-facing surfaces, `reference/` for implementation details and operator tooling; index `markdown/features/README.md`. Create or update a doc for non-trivial features.
- `markdown/lessons-learned.md`: short curated rules for agents; history in `markdown/lessons-archive.md` (search it, don't read it in full).
- `markdown/research/`: one-off studies, not product docs; agents don't read them by default.

Keep `README.md` short, with links into `markdown/`; don't duplicate feature docs there. When a large subject comes up during implementation, ask whether it needs a feature doc.

## Developer Agents

Role-based agents are slash commands in `.claude/commands/`; the full reference, with a workflow diagram, is `.claude/commands/README.md`. Each agent declares its scope, checks preconditions first and defines its output.

Two conventions:
- **The invocation is the consent.** Running a command authorises what its description says; options are arguments (`--dry-run`, `apply`, `fix`, `--fix`, `full`). When input is missing or a choice can't be made from the repo, the agent stops and prints the invocations for each choice.
- **Every run ends with `Next:`** and one ready-to-run invocation.

| Command | Role |
|---|---|
| `/product-planner <description \| issue N>` | Plan, stories and feature stub for new work |
| `/develop <plan-slug>` | Pipeline: test stubs → implementation → QA, docs check (change mode) and, for sensitive changes, a security change review → labels the issue `implemented` |
| `/ship` | Commit, push, open or update the PR against `main` (`--watch`, `--fix`, `status`, `sync <N>`) |
| `/test-planner <plan-slug>` | Failing pytest stubs from a plan (`/develop` Stage 1) |
| `/developer <plan-slug>` | Implements a plan (`/develop` Stage 2) |
| `/qa-engineer` | Runs the suite and reports failures |
| `/documentation-steward [full \| <range>]` | Doc drift; change mode by default |
| `/security-reviewer [diff \| fix]` | Auth, sessions, validation, data exposure, Dependabot |
| `/security-patcher <alert>` | Fixes one code-scanning alert |
| `/scoring-analyst` | Scoring pipeline trace |
| `/systems-architect` | Architecture review |
| `/ux-reviewer [tab]` | Usability review |
| `/ui-design` | Branded UI edits or prototypes |
| `/product-analyst` | Story coverage |
| `/technical-writer <path>` | Rewrites a doc for its audience |
| `/agent-steward [apply \| <guidance>]` | Keeps agent definitions current; curates the lessons log |

## Development Workflow

1. `/product-planner issue N` (or a description), then review the plan.
2. `/develop <plan-slug>`, then review its report.
3. `/ship`, then merge the PR in GitHub. `Closes #N` closes the issue and the `issue-closed` workflow removes the `implemented` label.

`markdown/plans/.issue-index` lists planned issues, one `<N> <plan-slug>` per line; status comes from GitHub (open, `implemented` label, closed).

### Review gates

| Agent | When | Focus |
|---|---|---|
| `/security-reviewer` | Changes to routers, `main.py`, auth, sessions, Twitch/Steam sign-in, rate limits, secrets, dependencies (`/develop` runs a change review) | Auth gaps, session leaks, validation, data exposure |
| `/qa-engineer` | Any backend change | Suite pass/fail |
| `/scoring-analyst` | `scoring.py`, `enrich.py`, `WEIGHTS_JSON` | Formula correctness |
| `/documentation-steward` | Significant backend change (`full` before a release) | Doc drift |
| `/ux-reviewer` | Significant frontend change | Flows, states, accessibility |
| `/technical-writer` | Significant documentation change | Clarity, audience fit |
| `/product-analyst` | After a milestone | Story coverage |
| `/systems-architect` | Before a refactor or new subsystem | Architecture risks |

Fix **High** findings from `/security-reviewer` or `/systems-architect` before opening a PR.

## Scheduled Jobs

Session-scoped; re-register at the start of a session.

- **Issue Crawler** (`/schedule daily issue crawl at 8am`): for each open GitHub issue not in `markdown/plans/.issue-index`, run the product-planner logic on `"{title} — {body}"`, name the plan `plan-issue-{N}-{slug}.md`, add `{N} plan-issue-{N}-{slug}` to the index, and report how many plans were created. Plans are not implemented automatically.
- **Dependency Scout** (`/schedule weekly dep check on Monday mornings`): check every pin in `backend/requirements.txt` against PyPI and flag outdated or security-relevant versions; also check Pillow's bundled native libraries (`pillow.libs`), Brotli included, against advisories, since `pip-audit` sees only Python packages. To take a new version, edit the range there and run `bash scripts/lock-deps.sh`: the image and CI install only the hash-locked `backend/requirements.lock` / `requirements-dev.lock` (see `markdown/features/reference/dependency-locking.md`).
