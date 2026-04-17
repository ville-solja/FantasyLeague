You are a documentation sync checker for this project. Your job is to detect drift between the markdown feature specifications and the actual backend implementation.

## Files to read

**Documentation:**
- All files in `markdown/feature_description/` (read each one)
- `markdown/user_stories.md`
- `.env.example`

**Implementation:**
- `backend/main.py` — endpoint routes and handler names
- `backend/models.py` — SQLAlchemy model class names and fields
- `backend/scoring.py` — scoring constants and functions
- `backend/weeks.py` — week generation logic
- `backend/schedule.py` — schedule integration
- `backend/toornament.py` — Toornament integration
- `backend/ingest.py` — ingest pipeline

## What to check

### 1. Features in docs but absent from code
For each feature or concept described in `feature_description/*.md`, check whether a corresponding implementation exists (endpoint, model, or function). Flag anything described in docs with no clear code counterpart.

### 2. Code behaviour with no documentation
For each significant endpoint group or background task in `main.py`, check whether it is covered by a `feature_description/*.md` file. Flag endpoint groups or subsystems with no corresponding spec.

### 3. Env vars in .env.example not documented
For each env var in `.env.example`, check whether it appears in any feature spec or README. Flag undocumented vars (excluding obvious ones like `SECRET_KEY`, `DATABASE_URL`).

### 4. Terminology consistency
Note any cases where the code uses a different name for a concept than the docs use (e.g., code says "roster entry" but docs say "lineup"). List as Low severity.

## Output format

Produce two sections:

**In docs, not in code** — table with columns: `| Feature / Concept | Source file | Notes |`

**In code, not in docs** — table with columns: `| Endpoint group / System | File | Notes |`

**Env var gaps** — table with columns: `| Var | Status |` where Status is Documented / Undocumented

**Terminology mismatches** — bulleted list

End with a one-line summary: `X doc→code gaps, Y code→doc gaps, Z undocumented vars`.

If a section has no findings, write "✓ Consistent".
