# Plan: Agent Lessons Log

## Context
Agents repeatedly encounter the same pitfalls — stale file references, test fixture quirks,
endpoint naming conventions, known SQLite edge cases — and have no way to pass that knowledge
forward. Each session starts cold and re-derives the same lessons. The fix is a shared
`markdown/lessons-learned.md` log that agents read at the start of a run and append to when
they discover something novel. The log is version-controlled, so lessons are visible and
auditable. Resolves GitHub issue #43.

## User Stories

### Read Lessons Before Working
**User story**
As a developer agent, I want to read the lessons log before starting implementation so
that I avoid mistakes that a previous agent already documented.

**Acceptance criteria**
- `markdown/lessons-learned.md` exists with a defined structure (date, agent, category,
  problem, solution)
- The developer, qa-engineer, security-reviewer, and scoring-analyst agent definitions
  each list `markdown/lessons-learned.md` in their `## Files to read` section
- When a run produces no new lessons, the file is not modified

### Write a Lesson After Encountering a Novel Issue
**User story**
As any agent, I want to append a lesson entry when I encounter a novel problem so that
future agents benefit from the discovery.

**Acceptance criteria**
- Any agent can append a new entry to `markdown/lessons-learned.md` using the standard
  format (see below) when it encounters an issue not already covered
- Entries are appended, never rewritten — the log is append-only
- Each entry includes: date (ISO), agent name, category tag, one-line problem summary,
  and a solution or workaround
- Lessons are not appended for issues already documented; duplicates are avoided by
  reading the log first

### Browse and Maintain the Lessons Log (Operator)
**User story**
As an operator, I want a readable, navigable lessons log so that I can understand
recurring issues and remove stale entries.

**Acceptance criteria**
- The log is a single Markdown file with a `## Table of Contents` auto-built from
  section anchors, or a flat list of `### [date] — [category]` heading entries
- Entries are sorted newest-first
- Stale or superseded entries can be manually deleted without breaking agent reads
  (agents scan for content, not line numbers)

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `markdown/lessons-learned.md` | Create; define structure and seed with known lessons |
| `.claude/commands/developer.md` | Add `markdown/lessons-learned.md` to Files to read; add write instruction |
| `.claude/commands/qa-engineer.md` | Add `markdown/lessons-learned.md` to Files to read; add write instruction |
| `.claude/commands/security-reviewer.md` | Add `markdown/lessons-learned.md` to Files to read; add write instruction |
| `.claude/commands/scoring-analyst.md` | Add `markdown/lessons-learned.md` to Files to read; add write instruction |
| `.claude/commands/test-planner.md` | Add `markdown/lessons-learned.md` to Files to read; add write instruction |

### Step 1 — Create `markdown/lessons-learned.md`

Create the file with this structure:

```markdown
# Lessons Learned

Persistent notes written by agents during their runs. Read this before starting work.
Append new entries when you encounter a novel problem not already documented here.

Entries are sorted newest-first. Format:

---

### YYYY-MM-DD — [agent-name] — [category]
**Problem:** One-sentence description of the pitfall or recurring issue.
**Solution:** What to do instead, or the correct approach.

---
```

Seed it with the first known lessons from recent sessions:

1. **frontend/app.js split** (agent-steward, 2026-05-25): `frontend/app.js` no longer
   exists — the frontend is split into `frontend/app-*.js` modules per tab.

2. **Endpoints in routers, not main.py** (agent-steward, 2026-05-25): almost all FastAPI
   endpoints are in `backend/routers/*.py`, not `backend/main.py`. Reading only `main.py`
   misses all endpoint definitions.

3. **`get_current_user` / `require_admin` in deps.py** (agent-steward, 2026-05-25): auth
   dependencies are defined in `backend/deps.py`, not `backend/main.py` or `backend/auth.py`.

4. **`seed_admin_from_env` uses `SessionLocal()` internally** (developer, 2026-05-25):
   tests for this function must patch `seed.SessionLocal` via `monkeypatch.setattr` to
   inject an in-memory test DB — cannot use the `db` fixture directly.

### Step 2 — Add read + write instructions to each agent

For each of the five agent files listed in Critical Files, make two edits:

**In `## Files to read`:** add a line:
```
- `markdown/lessons-learned.md` — read before starting; append new lessons if you
  encounter a novel issue not already documented
```

**After the existing checks section (or at the end of the agent instructions),** add a
paragraph:

```
## Lessons log

Before starting work, read `markdown/lessons-learned.md` in full.

If your run surfaces a novel pitfall (an assumption that turned out wrong, a file path
that no longer exists, a test pattern that failed unexpectedly), append a new entry using
this format:

### YYYY-MM-DD — [your agent name] — [category: file-paths | endpoints | testing | models | frontend]
**Problem:** One sentence.
**Solution:** What works instead.

Append at the top of the entries list (newest-first). Do not rewrite or delete existing
entries.
```

### Step 3 — Increment agent version numbers

Each modified agent file must have its `<!-- version: N -->` header incremented by 1.

---

## Verification
- `markdown/lessons-learned.md` exists and is valid Markdown with at least 4 seed entries
- Each of the 5 agent files lists `markdown/lessons-learned.md` in `## Files to read`
- Each of the 5 agent files has a `## Lessons log` section with the append format
- Version numbers on modified agents are incremented
- No existing agent logic (checks, output format, scope) is changed — only additions
