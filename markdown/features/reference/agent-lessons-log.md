# Agent Lessons Log

Two version-controlled Markdown files: `markdown/lessons-learned.md`, short curated rules that
agents read before starting work, and `markdown/lessons-archive.md`, the full history they
search by keyword. Agents add an entry when they discover a novel pitfall, so the same mistakes
are not repeated across sessions.

---

## How it works

Each participating agent reads `markdown/lessons-learned.md` (about 10 KB) before doing any
work. For a specific problem it searches `markdown/lessons-archive.md` with `grep`; the archive
is never read in full. If the run surfaces a novel issue — a stale file path, an unexpected test
pattern, a model field that moved — the agent adds a short entry at the top of
`lessons-learned.md` in the standard format.

Agents don't rewrite or delete other entries. `/agent-steward` curates the file: when it grows
past about 12 KB it folds related entries into one rule and moves entries that no longer apply
to the archive. The archive was created on 2026-10-13, when 82 entries (73 KB) were condensed
into the curated rules.

## Entry format

```
### YYYY-MM-DD — [agent-name] — [category]
**Problem:** One-sentence description of the pitfall.
**Solution:** What to do instead.
```

Category tags: `file-paths`, `endpoints`, `testing`, `models`, `frontend`, `agent-config`, `security`, `docs`

## Participating agents

The following agents read and write the log:

- `/developer`
- `/qa-engineer`
- `/security-reviewer`
- `/scoring-analyst`
- `/test-planner`
- `/security-patcher`
- `/technical-writer`
- `/ship`

## Log files

- `markdown/lessons-learned.md` — curated rules; read by the participating agents on every run, written when a run finds a new pitfall.
- `markdown/lessons-archive.md` — full history up to 2026-10-13; searched, not read.
