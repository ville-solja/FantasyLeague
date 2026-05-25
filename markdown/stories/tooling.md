# Development Tooling

## Agent Lessons Log

### Read Lessons Before Working
**User story**
As a developer agent, I want to read the lessons log before starting implementation so
that I avoid mistakes that a previous agent already documented.

**Acceptance criteria**
- `markdown/lessons-learned.md` exists with a defined structure (date, agent, category,
  problem, solution)
- The developer, qa-engineer, security-reviewer, scoring-analyst, and test-planner agent
  definitions each list `markdown/lessons-learned.md` in their `## Files to read` section
- When a run produces no new lessons, the file is not modified

### Write a Lesson After Encountering a Novel Issue
**User story**
As any agent, I want to append a lesson entry when I encounter a novel problem so that
future agents benefit from the discovery.

**Acceptance criteria**
- Any agent can append a new entry to `markdown/lessons-learned.md` using the standard
  format when it encounters an issue not already covered
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
- The log is a single Markdown file with flat `### [date] — [category]` heading entries
- Entries are sorted newest-first
- Stale or superseded entries can be manually deleted without breaking agent reads
