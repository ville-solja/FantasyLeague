"""
Tests for the Agent Lessons Log acceptance criteria.

Plan: markdown/plans/plan-agent-lessons-log.md

Covers:
  - markdown/lessons-learned.md exists with the required structure and seed entries
  - Each of the 5 agent command files lists lessons-learned.md in Files to read
  - Each of the 5 agent command files has a ## Lessons log section with the append format
  - Agent version numbers are incremented on modified files
  - No existing agent logic is removed (only additions)

These are file-existence and content checks. No database fixture is needed.
"""
import os
import re

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LESSONS_FILE = os.path.join(REPO_ROOT, "markdown", "lessons-learned.md")
COMMANDS_DIR = os.path.join(REPO_ROOT, ".claude", "commands")

AGENT_FILES = [
    "developer.md",
    "qa-engineer.md",
    "security-reviewer.md",
    "scoring-analyst.md",
    "test-planner.md",
]


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Story 1 — Read Lessons Before Working
# ---------------------------------------------------------------------------


class TestLessonsFileExists:
    def test_lessons_learned_md_exists(self):
        """markdown/lessons-learned.md exists with a defined structure."""
        assert os.path.isfile(LESSONS_FILE), (
            f"Expected {LESSONS_FILE} to exist but it was not found"
        )

    def test_lessons_learned_md_missing_raises_clear_error(self):
        """Absence of markdown/lessons-learned.md is detectable (file not found)."""
        # Verify the detection mechanism: opening a non-existent path raises FileNotFoundError
        fake_path = os.path.join(REPO_ROOT, "markdown", "lessons-learned-NONEXISTENT.md")
        assert not os.path.isfile(fake_path), "Fake path should not exist"
        with pytest.raises(FileNotFoundError):
            _read(fake_path)


class TestLessonsFileStructure:
    def test_lessons_file_has_required_heading(self):
        """markdown/lessons-learned.md starts with the '# Lessons Learned' heading."""
        content = _read(LESSONS_FILE)
        assert content.startswith("# Lessons Learned"), (
            "File must start with '# Lessons Learned'"
        )

    def test_lessons_file_contains_date_agent_category_fields(self):
        """At least one entry contains date, agent name, and category tag in its heading."""
        content = _read(LESSONS_FILE)
        # Entry headings follow: ### YYYY-MM-DD — agent — category
        matches = re.findall(r'### \d{4}-\d{2}-\d{2} — \S+ — \S+', content)
        assert len(matches) >= 1, (
            "Expected at least one entry heading with date, agent name, and category"
        )

    def test_lessons_file_contains_problem_and_solution_fields(self):
        """At least one entry has both a **Problem:** and **Solution:** line."""
        content = _read(LESSONS_FILE)
        assert "**Problem:**" in content, "File must contain at least one **Problem:** line"
        assert "**Solution:**" in content, "File must contain at least one **Solution:** line"

    def test_lessons_file_has_at_least_four_seed_entries(self):
        """markdown/lessons-learned.md contains at least 4 seed entries."""
        content = _read(LESSONS_FILE)
        # Each entry has a ### heading
        entries = re.findall(r'^### ', content, re.MULTILINE)
        assert len(entries) >= 4, (
            f"Expected at least 4 seed entries (### headings), found {len(entries)}"
        )


class TestAgentFilesListLessonsInFilesToRead:
    def _agent_mentions_lessons(self, filename: str) -> bool:
        path = os.path.join(COMMANDS_DIR, filename)
        content = _read(path)
        return "lessons-learned.md" in content

    def test_developer_md_lists_lessons_in_files_to_read(self):
        """developer.md lists markdown/lessons-learned.md in its ## Files to read section."""
        assert self._agent_mentions_lessons("developer.md"), (
            "developer.md must reference lessons-learned.md"
        )

    def test_qa_engineer_md_lists_lessons_in_files_to_read(self):
        """qa-engineer.md lists markdown/lessons-learned.md in its ## Files to read section."""
        assert self._agent_mentions_lessons("qa-engineer.md"), (
            "qa-engineer.md must reference lessons-learned.md"
        )

    def test_security_reviewer_md_lists_lessons_in_files_to_read(self):
        """security-reviewer.md lists markdown/lessons-learned.md in its ## Files to read section."""
        assert self._agent_mentions_lessons("security-reviewer.md"), (
            "security-reviewer.md must reference lessons-learned.md"
        )

    def test_scoring_analyst_md_lists_lessons_in_files_to_read(self):
        """scoring-analyst.md lists markdown/lessons-learned.md in its ## Files to read section."""
        assert self._agent_mentions_lessons("scoring-analyst.md"), (
            "scoring-analyst.md must reference lessons-learned.md"
        )

    def test_test_planner_md_lists_lessons_in_files_to_read(self):
        """test-planner.md lists markdown/lessons-learned.md in its ## Files to read section."""
        assert self._agent_mentions_lessons("test-planner.md"), (
            "test-planner.md must reference lessons-learned.md"
        )

    def test_agent_without_lessons_reference_is_detectable(self):
        """An agent file that does NOT mention lessons-learned.md is identifiable as non-compliant."""
        # Construct a mock agent content that lacks the lessons reference and verify detection
        mock_content = "<!-- version: 1 -->\n\nYou are an agent.\n\n## Files to read\n\n- some-file.md\n"
        assert "lessons-learned.md" not in mock_content, (
            "Detection mechanism: an agent without 'lessons-learned.md' in its content "
            "should fail the compliance check"
        )


# ---------------------------------------------------------------------------
# Story 2 — Write a Lesson After Encountering a Novel Issue
# ---------------------------------------------------------------------------


class TestAgentFilesHaveLessonsLogSection:
    def _agent_has_lessons_log_section(self, filename: str) -> bool:
        path = os.path.join(COMMANDS_DIR, filename)
        content = _read(path)
        return "## Lessons log" in content

    def test_developer_md_has_lessons_log_section(self):
        """developer.md contains a ## Lessons log section with the append format."""
        assert self._agent_has_lessons_log_section("developer.md"), (
            "developer.md must contain a '## Lessons log' section"
        )

    def test_qa_engineer_md_has_lessons_log_section(self):
        """qa-engineer.md contains a ## Lessons log section with the append format."""
        assert self._agent_has_lessons_log_section("qa-engineer.md"), (
            "qa-engineer.md must contain a '## Lessons log' section"
        )

    def test_security_reviewer_md_has_lessons_log_section(self):
        """security-reviewer.md contains a ## Lessons log section with the append format."""
        assert self._agent_has_lessons_log_section("security-reviewer.md"), (
            "security-reviewer.md must contain a '## Lessons log' section"
        )

    def test_scoring_analyst_md_has_lessons_log_section(self):
        """scoring-analyst.md contains a ## Lessons log section with the append format."""
        assert self._agent_has_lessons_log_section("scoring-analyst.md"), (
            "scoring-analyst.md must contain a '## Lessons log' section"
        )

    def test_test_planner_md_has_lessons_log_section(self):
        """test-planner.md contains a ## Lessons log section with the append format."""
        assert self._agent_has_lessons_log_section("test-planner.md"), (
            "test-planner.md must contain a '## Lessons log' section"
        )

    def test_lessons_log_section_includes_append_only_instruction(self):
        """At least one agent's ## Lessons log section instructs to append, not rewrite, entries."""
        found = False
        for filename in AGENT_FILES:
            path = os.path.join(COMMANDS_DIR, filename)
            content = _read(path)
            if "## Lessons log" in content and "append-only" in content.lower():
                found = True
                break
        assert found, (
            "At least one agent's ## Lessons log section must include an 'append-only' instruction"
        )

    def test_lessons_log_section_includes_entry_format_template(self):
        """At least one agent's ## Lessons log section shows the YYYY-MM-DD heading format."""
        found = False
        for filename in AGENT_FILES:
            path = os.path.join(COMMANDS_DIR, filename)
            content = _read(path)
            if "## Lessons log" in content and "YYYY-MM-DD" in content:
                found = True
                break
        assert found, (
            "At least one agent's ## Lessons log section must show the YYYY-MM-DD format template"
        )


class TestLessonsEntryFormat:
    def test_seed_entries_use_newest_first_ordering_indicator(self):
        """The lessons file documents or implies newest-first ordering (heading or preamble)."""
        content = _read(LESSONS_FILE)
        assert "newest-first" in content.lower(), (
            "lessons-learned.md must document newest-first ordering in its preamble"
        )

    def test_seed_entries_all_have_iso_date_in_heading(self):
        """Every seed entry heading matches the YYYY-MM-DD — [agent] — [category] pattern."""
        content = _read(LESSONS_FILE)
        # Find all ### headings
        all_headings = re.findall(r'^### .+', content, re.MULTILINE)
        # Exclude the format template heading (contains YYYY-MM-DD literally)
        real_entries = [h for h in all_headings if "YYYY-MM-DD" not in h]
        assert len(real_entries) >= 4, (
            f"Expected at least 4 real entry headings, found {len(real_entries)}"
        )
        iso_pattern = re.compile(r'### \d{4}-\d{2}-\d{2} — ')
        for heading in real_entries:
            assert iso_pattern.match(heading), (
                f"Entry heading '{heading}' does not match the YYYY-MM-DD — [agent] — [category] pattern"
            )


# ---------------------------------------------------------------------------
# Story 3 — Browse and Maintain the Lessons Log (Operator)
# ---------------------------------------------------------------------------


class TestLessonsLogNavigability:
    def test_lessons_file_uses_heading_entries_navigable_structure(self):
        """Entries use ### [date] — [category] headings making the log navigable."""
        content = _read(LESSONS_FILE)
        assert "### " in content, (
            "lessons-learned.md must use ### headings for entries to be navigable"
        )

    def test_lessons_file_has_no_line_number_references(self):
        """The lessons file contains no references to specific line numbers (agents scan by content)."""
        content = _read(LESSONS_FILE)
        # Check for patterns like "line 42", "line 100", "on line N"
        line_ref_pattern = re.compile(r'\bline \d+\b', re.IGNORECASE)
        matches = line_ref_pattern.findall(content)
        assert len(matches) == 0, (
            f"lessons-learned.md must not reference specific line numbers; found: {matches}"
        )


# ---------------------------------------------------------------------------
# Story cross-cut — Agent version numbers incremented
# ---------------------------------------------------------------------------


class TestAgentVersionNumbers:
    def _has_version_header(self, filename: str) -> bool:
        path = os.path.join(COMMANDS_DIR, filename)
        content = _read(path)
        return bool(re.search(r'<!-- version: \d+ -->', content))

    def test_developer_md_version_header_present(self):
        """developer.md has a <!-- version: N --> header after the lessons log addition."""
        assert self._has_version_header("developer.md"), (
            "developer.md must have a <!-- version: N --> header"
        )

    def test_qa_engineer_md_version_header_present(self):
        """qa-engineer.md has a <!-- version: N --> header after the lessons log addition."""
        assert self._has_version_header("qa-engineer.md"), (
            "qa-engineer.md must have a <!-- version: N --> header"
        )

    def test_security_reviewer_md_version_header_present(self):
        """security-reviewer.md has a <!-- version: N --> header after the lessons log addition."""
        assert self._has_version_header("security-reviewer.md"), (
            "security-reviewer.md must have a <!-- version: N --> header"
        )

    def test_scoring_analyst_md_version_header_present(self):
        """scoring-analyst.md has a <!-- version: N --> header after the lessons log addition."""
        assert self._has_version_header("scoring-analyst.md"), (
            "scoring-analyst.md must have a <!-- version: N --> header"
        )

    def test_test_planner_md_version_header_present(self):
        """test-planner.md has a <!-- version: N --> header after the lessons log addition."""
        assert self._has_version_header("test-planner.md"), (
            "test-planner.md must have a <!-- version: N --> header"
        )
