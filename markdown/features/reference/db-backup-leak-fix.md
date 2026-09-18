# DB Backup Leak Fix

Fixes a `.gitignore` gap that let two SQLite database backup snapshots — containing an admin
account's email and bcrypt password hash — get committed to git.

*(see `markdown/plans/plan-issue-126-db-backup-leak-fix.md`, resolves GitHub issue #126)*

---

## What leaked

A community security disclosure (2026-09-18) found `data/fantasy.db.backup-20260730-154012`
and `data/fantasy.db.backup-20260803-060905` tracked in git (originally added by a commit
dated 2026-08-03, "Season end and week management finalized...") and still present in the
working tree. Both are full database snapshots, including the `users` table with an admin
account's email and bcrypt-hashed password. That commit has since been rewritten as part of
the history purge below, so it no longer contains these files — its pre-purge hash isn't cited
here since it no longer identifies an accurate state of the repository.

## Root cause

`.gitignore` excluded the live database (`data/fantasy.db`, `data/fantasy.db-shm`,
`data/fantasy.db-wal`) but not the `.backup-*` naming pattern produced by both
`scripts/backup-db.sh` and the app's own online-backup mechanism
(`backup_sqlite_db()` in `backend/database.py` — including the scheduled automatic backup
loop added this session). Any backup taken at the default path, next to the live DB, was
silently included by a routine `git add`.

## Fix

1. `.gitignore` gained a `data/*.backup-*` entry, covering every backup either backup path
   creates at its default location.
2. The two leaked files were removed from the repository (`git rm`).
3. A regression test (`backend/tests/test_issue_126_db_backup_gitignore.py`) confirms a
   synthetic backup-shaped filename is actually ignored by git.

## What this fix does *not* cover

- `scripts/backup-db.sh /custom/path` — passing a non-default path writes the backup outside
  `data/`, which this `.gitignore` change does not protect. See
  `reference/db-sustainability.md`.

## History purge (2026-09-18)

The two blobs were purged from git history entirely using `git filter-repo --invert-paths`,
run against a full mirror clone, then force-pushed to every affected ref on `origin`. This
was a separate, deliberate action taken after the `.gitignore`/tree-removal fix above, not
folded into that routine change, since rewriting history is disruptive to anyone else who had
cloned the repo (this project has 0 forks, which simplified the decision).

**Scope:** the leak was reachable from 4 branches (`main`, `XSS-vuln-patch`,
`ExtensionApproval`, `ville-solja-patch-1`) and 1 tag (`v1.3.1`) on the live remote — not the
much larger set of local branch names it initially appeared to affect, which turned out to be
stale, already-deleted local remote-tracking refs rather than anything still on GitHub. All 5
were rewritten and pushed; every other ref (`kc-rautilus-2`, `v1.1.0`, `v1.2.0`, `v1.3`) never
contained the leak.

**Process notes for any future repeat of this:**
- `main` has a branch protection ruleset ("Main Defence") blocking force-pushes. It had to be
  temporarily set to Disabled to allow the rewrite push, then re-enabled immediately after.
  Verify its `enforcement` is back to `active` via
  `gh api repos/{owner}/{repo}/rulesets --jq '.[] | {name, enforcement}'` after any operation
  like this.
- A full mirror backup was taken first (`git clone --mirror`) and kept until the push was
  verified, as the rollback point had anything gone wrong.
- Verified clean afterward with a fresh bare clone of the live remote and
  `git log --all --oneline -- 'data/*.backup-*'` returning empty across every ref.

## Operational follow-up (not code)

- ✅ The exposed admin account's password has been rotated in the live deployment.
- ✅ History purge performed — see above.
