"""
Tests for the DB Backup Leak Fix plan (GitHub issue #126).

Story 1 — Prevent Future DB Backup Leaks
Story 2 — Audit for Other Leakable DB Artifact Patterns

Story 3 ("Rotate Exposed Admin Credentials and Decide on History Purge") is a
manual/operational story with no automated-test-shaped acceptance criteria
(rotating a live password, recording a human decision) and is intentionally
not covered here.

These are filesystem/git-config assertions rather than application logic, so
they shell out to `git` from the repo root rather than importing backend
modules.
"""
import os
import pathlib
import subprocess

import pytest

# backend/tests/ -> backend/ -> repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

LEAKED_BACKUP_FILES = [
    "data/fantasy.db.backup-20260730-154012",
    "data/fantasy.db.backup-20260803-060905",
]


def _git_ls_files():
    """Return the list of paths currently tracked by git in this repo."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git ls-files failed: {result.stderr}"
    return result.stdout.splitlines()


# ---------------------------------------------------------------------------
# Story 1 — Prevent Future DB Backup Leaks
# ---------------------------------------------------------------------------

class TestGitignoreExcludesBackupPattern:
    def test_gitignore_contains_backup_pattern(self):
        """.gitignore excludes a data/*.backup-* (or equivalent) pattern, in
        addition to the existing data/fantasy.db, data/fantasy.db-shm,
        data/fantasy.db-wal entries."""
        content = GITIGNORE_PATH.read_text()
        assert "data/fantasy.db" in content
        assert "data/fantasy.db-shm" in content
        assert "data/fantasy.db-wal" in content
        assert "data/*.backup-*" in content, (
            ".gitignore does not contain a data/*.backup-* pattern"
        )


class TestSyntheticBackupFilenameIsIgnored:
    def test_synthetic_backup_filename_is_git_ignored(self):
        """A synthetic filename matching the backup naming convention
        (data/fantasy.db.backup-YYYYMMDD-HHmmss) is actually ignored by git —
        `git check-ignore -q` returns 0 for it."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", "data/fantasy.db.backup-20990101-000000"],
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, (
            "git does not ignore a synthetic data/fantasy.db.backup-* filename"
        )


class TestLeakedBackupFilesRemovedFromRepo:
    def test_leaked_backup_file_20260730_not_tracked(self):
        """data/fantasy.db.backup-20260730-154012 is no longer tracked by git
        (absent from `git ls-files`)."""
        tracked = _git_ls_files()
        assert LEAKED_BACKUP_FILES[0] not in tracked

    def test_leaked_backup_file_20260803_not_tracked(self):
        """data/fantasy.db.backup-20260803-060905 is no longer tracked by git
        (absent from `git ls-files`)."""
        tracked = _git_ls_files()
        assert LEAKED_BACKUP_FILES[1] not in tracked


# ---------------------------------------------------------------------------
# Story 2 — Audit for Other Leakable DB Artifact Patterns
# ---------------------------------------------------------------------------

class TestNoDatabaseArtifactsTrackedByGit:
    def test_git_ls_files_has_no_db_extension_entries(self):
        """git ls-files contains no *.db entries after the fix is applied."""
        tracked = _git_ls_files()
        db_files = [f for f in tracked if f.endswith(".db")]
        assert db_files == [], f"found tracked *.db files: {db_files}"

    def test_git_ls_files_has_no_db_shm_entries(self):
        """git ls-files contains no *.db-shm entries after the fix is applied."""
        tracked = _git_ls_files()
        shm_files = [f for f in tracked if f.endswith(".db-shm")]
        assert shm_files == [], f"found tracked *.db-shm files: {shm_files}"

    def test_git_ls_files_has_no_db_wal_entries(self):
        """git ls-files contains no *.db-wal entries after the fix is applied."""
        tracked = _git_ls_files()
        wal_files = [f for f in tracked if f.endswith(".db-wal")]
        assert wal_files == [], f"found tracked *.db-wal files: {wal_files}"

    def test_git_ls_files_has_no_backup_dash_entries(self):
        """git ls-files contains no *.backup-* entries after the fix is applied."""
        tracked = _git_ls_files()
        backup_files = [f for f in tracked if ".backup-" in f]
        assert backup_files == [], f"found tracked *.backup-* files: {backup_files}"


class TestBackupScriptCustomPathCaveatDocumented:
    def test_db_sustainability_doc_notes_custom_path_caveat(self):
        """markdown/features/reference/db-sustainability.md warns that
        `scripts/backup-db.sh /custom/path` (a non-default argument) writes
        outside the gitignored data/ directory and is not covered by this
        fix."""
        doc_path = REPO_ROOT / "markdown" / "features" / "reference" / "db-sustainability.md"
        content = doc_path.read_text()
        assert "custom" in content.lower() and "backup-db.sh" in content, (
            "db-sustainability.md does not mention the custom-path caveat "
            "for scripts/backup-db.sh"
        )
        assert "data/" in content, (
            "db-sustainability.md does not reference the gitignored data/ "
            "directory in its custom-path caveat"
        )
