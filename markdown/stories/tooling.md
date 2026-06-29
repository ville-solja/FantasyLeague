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

## Process Diagrams

### View the Season Lifecycle Diagram
**User story**
As a new contributor or operator, I want to see a visual diagram of the season lifecycle
so that I can understand the pre-season setup and the recurring weekly loop without reading
all the source files.

**Acceptance criteria**
- A Mermaid `flowchart LR` diagram exists in `markdown/process-diagrams.md`
- It shows a pre-season phase (player pool setup, league configuration, week creation)
- It shows the during-season weekly loop (ingest → score → lock → roster snapshot → repeat)
- It shows the Twitch MVP flow as a side-group connected to match scoring
- Admin tools are shown as a side group, not inline with the main flow

---

### View the Token and Card Economy Diagram
**User story**
As a developer working on scoring or draw logic, I want a visual map of all token sources
and sinks and the card lifecycle so that I can trace how tokens move through the system.

**Acceptance criteria**
- A second Mermaid diagram shows all token sources (initial allocation, promo code, token
  grant event, Twitch drop, player refund)
- It shows all token sinks (standard draw, booster draw, reroll)
- It shows the card lifecycle after a draw (activate vs bench, weekly scoring, swap window)
- All sources and sinks match the current implementation

---

### Discover Process Diagrams from the Documentation Index
**User story**
As any reader of the docs, I want the process diagrams to be discoverable from the main
documentation entry points so that I do not have to know they exist in order to find them.

**Acceptance criteria**
- `markdown/features/README.md` includes a link to `markdown/process-diagrams.md`
- The main `README.md` documentation section also links to `markdown/process-diagrams.md`
- The page title and file name are descriptive enough to be findable by search
