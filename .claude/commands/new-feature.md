You are a feature planning agent for this FastAPI + vanilla JS fantasy league project. Your job is to formalise the creation of a new feature by reading existing documentation, drafting consistent artifacts, and writing them to disk.

**Feature to plan:** $ARGUMENTS

If no feature description was provided, stop and ask the user to re-invoke with a description: `/new-feature <description of the feature>`.

---

## Phase 1 — Read context

Read the following files before drafting anything:

- `markdown/user_stories.md` — read the full file. Find the **last section number** in the Table of Contents (e.g. if the last entry is `13.2 Twitch Integration - token drops`, the next section is `14`). Note the exact format of the TOC entries and story blocks.
- `markdown/feature_description/` — Glob `markdown/feature_description/*.md` to list existing feature doc filenames. Note the naming convention (lowercase, hyphens).
- `markdown/plans/` — Glob `markdown/plans/*.md` to list existing plan filenames. Avoid creating a duplicate slug.
- `README.md` — read the documentation table under the `### Feature descriptions` heading. You'll need to report its exact format for the follow-up instructions.

---

## Phase 2 — Draft content

Using `$ARGUMENTS` and everything you read in Phase 1:

### 2a. Derive names

- **Plan slug**: lowercase the feature name, replace spaces with hyphens, strip punctuation. Example: "Weekly Summary Email" → `weekly-summary-email`. Check it does not already exist in `markdown/plans/`.
- **Feature doc name**: same slug. Check it does not already exist in `markdown/feature_description/`.
- **Section number**: the integer after the last existing TOC section (e.g. last = 13 → new = 14).

### 2b. Draft user stories

Write 2–5 user stories in the **exact format** used throughout `markdown/user_stories.md`:

```
### [N.M] [Story Title]
**User story**
As a [role], I want to [action] so that [goal].

**Acceptance criteria**
- Specific, testable criterion
- Specific, testable criterion
```

- Use the section number determined in 2a (N = new section, M starts at 1).
- Write separate stories for distinct roles or user flows (e.g. one for the user-facing flow, one for the admin configuration).
- Acceptance criteria must be concrete and testable — not vague goals.
- If a story is clearly post-MVP or requires external dependency, add `**Phase:** Post-MVP` after the user story line.

### 2c. Draft the plan

Write a complete plan following the style of `markdown/plans/plan-security-audit.md`:

```
# Plan: [Feature Name]

## Context
[2–4 sentences: what problem this solves, why it is being added now, what the outcome looks like]

## User Stories
[The stories drafted in 2b, verbatim — the plan is self-contained]

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/main.py` | [what changes] |
| `backend/models.py` | [what changes, if any] |

### Step 1 — [First implementation step]
[Description and any relevant code sketch]

### Step 2 — [Next step]
...

## Verification
- [How to test the feature end-to-end]
- [Edge cases to verify]
- [Any migration or seed steps needed]
```

Implementation steps may be high-level stubs if full details aren't known yet. Do not invent technical details that contradict what you observe in the existing codebase.

### 2d. Draft the feature description stub

Write a stub following the style of `markdown/feature_description/profile.md` or `markdown/feature_description/weeks.md`:

```
# [Feature Name]

[1–2 sentence description of what the feature does and who uses it.]

---

## [Main concept or flow]

[Brief description. Mark any planned-but-not-yet-implemented endpoints as *(planned)*.]

## Endpoints

### `[METHOD] /[route]` *(planned)*
[Description]

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ENV_VAR` | *(empty)* | [what it does] |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
```

Omit sections that are clearly not applicable (e.g. no Configuration section if no env vars are expected).

---

## Phase 3 — Write files

Write all three artifacts now:

### File 1: `markdown/plans/plan-{slug}.md`
The complete plan from 2c (including the User Stories section).

### File 2: `markdown/user_stories.md` — append two blocks

**Block A — TOC entry:** Append a new line to the Table of Contents, continuing the numbering. Place it after the last entry in the TOC list. Format:
```
[N]. [[Feature Name]](#N-feature-name-anchor)
   - N.1 [Story Title]
   - N.2 [Story Title]
```

**Block B — Story section:** Append after the last `---` separator at the end of the file. Include the full story text from 2b, preceded by a `---` separator and a `## N. [Feature Name]` section header.

### File 3: `markdown/feature_description/{slug}.md`
The stub from 2d.

---

## Phase 4 — Report

After writing all files, output exactly this structure:

```
Created:
  markdown/plans/plan-{slug}.md
  markdown/feature_description/{slug}.md
  Appended section {N} to markdown/user_stories.md (stories {N}.1–{N}.M)

Manual follow-up:
  [ ] Add row to README.md documentation table:
      | [{Feature Name}](markdown/feature_description/{slug}.md) | {one-line description} |
  [ ] Implement the plan (markdown/plans/plan-{slug}.md)
```

---

## Style rules

- Plan files: `# Plan: [Name]`, `##` for sections, `###` for numbered steps; code blocks for all code
- User stories: bold labels (`**User story**`, `**Acceptance criteria**`), bullet-point AC, no AC numbering
- Feature descriptions: `#` title, `##` for sections, mark unimplemented routes as `*(planned)*`
- Never fabricate endpoint signatures, model fields, or env vars that don't exist and aren't clearly implied by the feature description
- If `$ARGUMENTS` is ambiguous, make reasonable assumptions based on the project's existing patterns and note them in the plan's Context section
