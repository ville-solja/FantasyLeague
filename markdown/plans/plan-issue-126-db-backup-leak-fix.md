# Plan: DB Backup Leak Prevention

## Context
A community security disclosure (2026-09-18) found that two SQLite database snapshots —
`data/fantasy.db.backup-20260730-154012` and `data/fantasy.db.backup-20260803-060905` — are
tracked in git (originally added by a 2026-08-03 commit, since rewritten by the history purge —
see `markdown/features/reference/db-backup-leak-fix.md`) and still present in the current working tree. Both
contain the full `users` table, including an admin account's email and bcrypt password hash.
`.gitignore` excludes `data/fantasy.db` and its `-shm`/`-wal` siblings, but not the `.backup-*`
naming pattern produced by both `scripts/backup-db.sh` and the app's own automatic online-backup
mechanism (`backup_sqlite_db()` in `backend/database.py`, including this session's new scheduled
backup loop) — so any backup taken at the default path is silently swept up by a routine
`git add`. This plan closes that gap in the repo itself. Rotating the exposed admin password and
deciding whether to purge the two blobs from git history are operator actions outside what an
automated implementation can safely do — they are called out explicitly below rather than
attempted here. *Resolves GitHub issue #126.*

## User Stories

### Prevent Future DB Backup Leaks
**User story**
As a developer, I want backup files created under `data/` to be permanently git-ignored, so
that a routine `git add`/`git add -A` can never re-commit a database snapshot again.

**Acceptance criteria**
- `.gitignore` excludes the `data/*.backup-*` pattern in addition to the existing
  `data/fantasy.db`, `data/fantasy.db-shm`, `data/fantasy.db-wal` entries
- The two currently-tracked backup files are removed from the repository in the same change
- A regression test confirms a synthetic filename matching the backup naming convention
  (`data/fantasy.db.backup-YYYYMMDD-HHmmss`) is ignored by git

### Audit for Other Leakable DB Artifact Patterns
**User story**
As a developer, I want a broader check of `.gitignore` for other database-artifact patterns
that could leak the same way under a different filename, so this class of incident doesn't
recur via a pattern nobody thought to exclude.

**Acceptance criteria**
- `.gitignore` is reviewed against every place the app or its scripts can write a database
  file or copy (`backend/database.py::_default_database_url`, `backup_sqlite_db`,
  `scripts/backup-db.sh`'s default argument) and covers each of them
- `git ls-files` contains no `*.db`, `*.db-shm`, `*.db-wal`, or `*.backup-*` entries after the
  fix is applied
- `markdown/features/reference/db-sustainability.md` gets a short note warning that
  `scripts/backup-db.sh /custom/path` (a non-default argument) writes outside the
  gitignored `data/` directory and is not covered by this fix

### Rotate Exposed Admin Credentials and Decide on History Purge *(not yet implemented)*
**User story**
As an operator, I want the exposed admin account's password rotated and a recorded decision
on whether to purge the two blobs from git history entirely, so the specific credential
exposure from this incident is actually remediated, not just prevented from recurring.

**Acceptance criteria**
- The exposed admin account's password has been changed in the live deployment (manual —
  not verifiable by an automated test)
- A decision (purge history now / defer / decline, and why) is recorded in
  `markdown/features/reference/db-backup-leak-fix.md`
- If a history purge is chosen, it is executed as its own deliberate, coordinated step
  (`git filter-repo` + force-push) — never folded into this or any other routine PR, since it
  rewrites history other clones/forks depend on

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `.gitignore` | Add `data/*.backup-*` (and confirm existing `data/fantasy.db*` entries already cover the live DB and its WAL/SHM siblings) |
| `data/fantasy.db.backup-20260730-154012`, `data/fantasy.db.backup-20260803-060905` | Delete from the repository |
| `backend/tests/test_issue_126_db_backup_gitignore.py` | New regression test (written by test-planner) |
| `markdown/features/reference/db-backup-leak-fix.md` | New reference doc (stub created by product-planner, filled in by developer) |
| `markdown/features/reference/db-sustainability.md` | Add a short note on the custom-path caveat for `scripts/backup-db.sh` |

No model changes, no migrations, no `.env.example` changes.

### Step 1 — Harden `.gitignore`
Add one line to the existing DB-related block:
```
data/fantasy.db
data/fantasy.db-shm
data/fantasy.db-wal
data/*.backup-*
```
This covers every backup `scripts/backup-db.sh` and `backup_sqlite_db()` create at their
default path (both resolve next to the live DB file, i.e. under `data/`).

### Step 2 — Remove the two tracked backup files
```bash
git rm data/fantasy.db.backup-20260730-154012 data/fantasy.db.backup-20260803-060905
```
Use a full `git rm` (not `--cached`) — these are leaked credentials, not something worth
keeping in a local checkout now that the app's own automatic backup loop and
`scripts/backup-db.sh` will regenerate fresh ones as needed.

### Step 3 — Regression test
Add a test that asserts the new pattern actually works, e.g.:
```python
import subprocess

def test_backup_file_pattern_is_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", "-q", "data/fantasy.db.backup-20990101-000000"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
```
This is a filesystem/git-config assertion rather than application logic, so it belongs in its
own small test file rather than folded into an existing suite.

### Step 4 — Documentation
- Fill in `markdown/features/reference/db-backup-leak-fix.md` (stub below) with what leaked,
  the `.gitignore` fix, and the recorded decision on password rotation / history purge.
- Add the note to `markdown/features/reference/db-sustainability.md` about
  `scripts/backup-db.sh /custom/path` writing outside `data/`.
- Update `markdown/features/README.md` with a row for the new doc (done by product-planner).

---

## Verification
- `git check-ignore -v data/fantasy.db.backup-20990101-000000` reports a match against the
  new `.gitignore` line.
- `git ls-files data/` no longer lists either leaked backup file after `git rm`.
- `cd backend && python -m pytest tests/test_issue_126_db_backup_gitignore.py -v` passes.
- Manually confirm (outside automated tests) that the exposed admin account's password has
  been rotated, and that the history-purge decision has been written into the feature doc.
