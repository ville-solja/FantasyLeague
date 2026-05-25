# Agent Lessons Log

A version-controlled Markdown file (`markdown/lessons-learned.md`) that agents read before
starting work and append to when they discover novel pitfalls, so the same mistakes are not
repeated across sessions.

---

## How it works

Each participating agent reads `markdown/lessons-learned.md` in full before doing any work.
If the run surfaces a novel issue — a stale file path, an unexpected test pattern, a model
field that moved — the agent appends a new entry in newest-first order using the standard
format.

Entries are never rewritten or deleted by agents. Operators may manually remove stale entries.

## Entry format

```
### YYYY-MM-DD — [agent-name] — [category]
**Problem:** One-sentence description of the pitfall.
**Solution:** What to do instead.
```

Category tags: `file-paths`, `endpoints`, `testing`, `models`, `frontend`, `agent-config`

## Participating agents

The following agents read and write the log:

- `/developer`
- `/qa-engineer`
- `/security-reviewer`
- `/scoring-analyst`
- `/test-planner`

## Log file

`markdown/lessons-learned.md` — live; seeded with entries from the initial implementation session. Read and written by the five participating agents on every run.
