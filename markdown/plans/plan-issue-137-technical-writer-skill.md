# Plan: Technical Writer Skill

## Context
The project's documentation (`markdown/features/`, `markdown/stories/`, `README.md`, `.env.example`, the agent definitions) is technically correct but often wordy. Most of it was written by agents during implementation, so it records everything that was done rather than what a reader needs first. A reader has to work to find the core message.

This adds a `/technical-writer` slash command. Given a documentation target, it names the audience, states the core message that audience needs, and rewrites the text to be clear and concise without losing facts. When the audience or purpose is unclear, it asks. When a change needs a human decision, such as dropping content or moving it to another file, it offers options to choose from.

It complements `/documentation-steward`, which checks whether docs match the code. The writer improves how docs read and leaves accuracy checks to the steward.

**Assumptions:**
- The command is an agent definition in `.claude/commands/`, like the other agents. No backend or frontend code changes.
- It runs in `read-write` mode but shows its proposed rewrite and waits for approval before editing a file, because documentation changes are judgment calls.
- One run handles one target: a file, a section of a file, or a small set of related files. Whole-folder rewrites are out of scope; a run on a folder proposes which files to tackle first.

Resolves GitHub issue #137.

## User Stories

### Rewrite a Document for Its Audience
**User story**
As a maintainer, I want to run `/technical-writer <target>` on a piece of documentation so that it states its core message clearly and concisely for the people who read it.

**Acceptance criteria**
- The command accepts a file path, a file path plus section heading (e.g. `README.md#Deployment`), or a short description of a documentation area (e.g. "hoster deploy notes")
- If no argument is given, the command stops and asks what documentation to consider
- If the target cannot be resolved to existing files, the command lists the closest matches and asks which one was meant
- Before proposing changes, the command prints the audience it identified, what that audience needs to know or do, and the one- or two-sentence core message of the document
- The rewrite keeps every fact that audience needs: env var names, defaults, endpoint paths, commands, file paths and version numbers stay exact
- Any fact the rewrite removes or moves elsewhere is listed in the report with the reason

### Identify the Audience and Ask When Unsure
**User story**
As a maintainer, I want the writer to tell me who it thinks the document is for, and ask me when it cannot tell, so that the rewrite targets the right readers.

**Acceptance criteria**
- The command infers the audience from the file's location and content using a documented mapping (e.g. `markdown/features/reference/` → developers and operators; `.env.example` and the README deployment section → the hoster; `markdown/stories/` → product owner and developers; `.claude/commands/` → the agents themselves)
- When the location and content point to different audiences, or the document serves more than one, the command asks the user to choose, offering 2–4 concrete options
- When a question is open that changes the rewrite (for example whether a section still applies), the command asks it instead of guessing
- The command never asks about choices that have a clear default in the project's conventions (CLAUDE.md, existing doc structure)

### Approve Changes Before They Are Written
**User story**
As a maintainer, I want to see the proposed rewrite and choose how to proceed so that no documentation changes without my agreement.

**Acceptance criteria**
- The command shows the proposed rewrite, or a before/after of each changed section for long files, with word counts before and after
- It then offers options: apply as proposed, apply with listed changes excluded, or discard
- Decisions that go beyond rewording, such as deleting a section, splitting a file, or moving content to another doc, are offered as separate options, not applied silently
- After approval, the command edits only the target files and any index it must keep in sync (`markdown/features/README.md`, `markdown/stories/_index.md`)
- It follows CLAUDE.md documentation rules: the README links to `markdown/features/` instead of duplicating it, and stories keep the standard **User story** / **Acceptance criteria** format

### Keep the Agent Roster Consistent
**User story**
As a maintainer, I want the new command registered like every other agent so that `/agent-steward` and the docs know about it.

**Acceptance criteria**
- `.claude/commands/technical-writer.md` starts with `<!-- version: 1 -->` and `<!-- mode: read-write -->` and follows the shared contract: Role, Scope, When to run, Precondition check, output format
- The command is listed in `CLAUDE.md` under Developer Agents and in `.claude/commands/README.md` under Maintenance agents
- The command reads `markdown/lessons-learned.md` at the start of a run and appends an entry when it finds a novel documentation pitfall
- `/agent-steward` reports no missing headers or broken file references for the new command

## Implementation

### Critical Files
| File | Change |
|---|---|
| `.claude/commands/technical-writer.md` | New agent definition |
| `CLAUDE.md` | Add `/technical-writer` to Developer Agents and to the review-gates table |
| `.claude/commands/README.md` | Add a row to the Maintenance agents table |
| `markdown/features/reference/agent-lessons-log.md` | Add `/technical-writer` to the participating agents |
| `markdown/features/reference/technical-writer.md` | Fill in the feature stub |
| `backend/tests/test_issue_137_technical_writer_skill.py` | Checks that the command file exists with the right headers and is registered in CLAUDE.md and the commands README |

### Step 1 — Write the agent definition
Create `.claude/commands/technical-writer.md` with these sections:

- **Headers:** `<!-- version: 1 -->`, `<!-- mode: read-write -->`
- **Role:** technical writer who makes documentation state its core message clearly and concisely for its audience, keeping it technically correct
- **Scope:** covers `markdown/`, `README.md`, `.env.example`, `.claude/commands/`. It does not check docs against code (that is `/documentation-steward`) and does not touch source code or code comments
- **Usage:** `/technical-writer <path>`, `/technical-writer <path>#<heading>`, `/technical-writer <description>`
- **Precondition check:** no argument → ask what documentation to consider. Unresolvable target → list close matches and ask.

**Phase 1 — Resolve and read.** Resolve the target to files and sections. Read them in full, plus `markdown/lessons-learned.md` and the files they link to when needed to understand the context.

**Phase 2 — Audience and core message.** Use this mapping as the starting point:

| Location | Default audience | What they need first |
|---|---|---|
| `README.md` (top) | New contributors | What the app is, how to run it |
| `README.md` Deployment, `.env.example` | Hoster / operator | What to set, what breaks if they don't |
| `markdown/features/core/` | Developers, product owner | What the feature does for users, how it works |
| `markdown/features/reference/` | Developers, operators | How to use, configure or change it |
| `markdown/stories/` | Product owner, developers | What the user can do and how to verify it |
| `markdown/ui_description/` | Developers, UI designers | What is on screen and how it behaves |
| `markdown/plans/` | Developer implementing it | What to build and why, in order |
| `.claude/commands/` | The agent itself | Exact steps and output format |

Print the audience, what they need, and the core message. If the mapping and the content disagree, or there are several audiences, ask with 2–4 options (AskUserQuestion). Ask any open question that changes the rewrite; do not ask about things CLAUDE.md or existing conventions already decide.

**Phase 3 — Draft.** Rewrite following these rules:
- Lead with the core message; put the reader's action or answer before background
- Cut repetition, history the reader doesn't need, and narration of how the doc was produced
- Short sentences and plain words; define a term once, then use it consistently with `markdown/features/reference/terminology.md`
- Tables for reference data (env vars, endpoints), numbered steps for procedures
- Keep names, values, paths, commands and code blocks exact
- Keep the file's required structure (story format, plan sections, agent headers)

Track every fact that is removed or moved, with the reason.

**Phase 4 — Propose and choose.** Show the draft (full for short files, before/after per section for long ones), word counts, and the removed/moved facts list. Offer options: apply, apply with exclusions, discard. Offer each structural change (delete a section, split a file, move content) as its own choice.

**Phase 5 — Apply.** Edit only the approved changes. Update `markdown/features/README.md` or `markdown/stories/_index.md` if a description there changed. Append a lessons-learned entry for any novel pitfall.

**Output format:**
```
Technical writer: {target}

Audience:      {who}
They need:     {what}
Core message:  {1–2 sentences}

Changes applied:  {file} — {words before} → {words after}
Removed/moved:    {fact} — {reason}   (or "none")
Declined:         {option} (if any)
Follow-up:        [ ] {e.g. run /documentation-steward if facts were questioned}
```

### Step 2 — Register the command
Add `/technical-writer` to `CLAUDE.md` (Developer Agents section, with role, what it does, when to run, usage) and to the review-gates table ("After a significant documentation change"). Add a row to the Maintenance agents table in `.claude/commands/README.md`. Add it to the participating agents in `markdown/features/reference/agent-lessons-log.md`.

### Step 3 — Tests
`backend/tests/test_issue_137_technical_writer_skill.py` reads the repo files and checks:
- `.claude/commands/technical-writer.md` exists and its first two lines are the version and mode headers
- It contains the Role, Scope, When to run, Precondition check and Output format sections
- `CLAUDE.md` and `.claude/commands/README.md` both mention `/technical-writer`

Bump the suite-size tripwire in `test_issue_85_split_admin_router.py` by the number of new tests.

### Step 4 — Try it
Run `/technical-writer` on one wordy document, for example `markdown/features/reference/security-audit-3.md` or the README Deployment section, and keep the result only if it passes review.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_137_technical_writer_skill.py -v` passes, and the full suite still passes.
- `/agent-steward` reports the new command as valid, with no missing headers or broken references.
- `/technical-writer` with no argument asks what to consider and changes nothing.
- `/technical-writer does-not-exist.md` lists close matches and asks.
- On a real doc, the report names an audience and core message, shows word counts, lists removed/moved facts, and nothing is written until an option is chosen.
- Discard leaves `git status` clean.
- All env var names, endpoints and commands in the original doc are still present after an applied rewrite, or appear in the removed/moved list.
