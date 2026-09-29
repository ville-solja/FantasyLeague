"""
Tests for issue #137 — Technical Writer skill (/technical-writer).

Plan: markdown/plans/plan-issue-137-technical-writer-skill.md

The feature is an agent definition (Markdown slash command), not backend code.
These are static file checks that read repo files. No database fixture is needed.

Behaviours that require running the agent interactively (asking questions,
waiting for approval, leaving git status clean on discard, preserving facts in an
actual rewrite) are verified manually per the plan's Verification section.
"""
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND_FILE = REPO_ROOT / ".claude" / "commands" / "technical-writer.md"
COMMANDS_README = REPO_ROOT / ".claude" / "commands" / "README.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
LESSONS_LOG_DOC = REPO_ROOT / "markdown" / "features" / "reference" / "agent-lessons-log.md"


def _cmd() -> str:
    return COMMAND_FILE.read_text(encoding="utf-8")


def _cmd_lower() -> str:
    return _cmd().lower()


def _section(heading: str) -> str:
    """Return the lower-cased body of a `## heading` section of the command file."""
    text = _cmd()
    match = re.search(rf"^## {re.escape(heading)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S | re.I)
    assert match, f"section '## {heading}' not found in {COMMAND_FILE}"
    return match.group(1).lower()


def _output_format() -> str:
    return _section("Output format")


# ---------------------------------------------------------------------------
# Story: Rewrite a Document for Its Audience
# ---------------------------------------------------------------------------

def test_technical_writer_usage_documents_path_section_and_description_targets():
    """Usage accepts a file path, a path#heading, or a short description of a documentation area."""
    text = _cmd_lower()
    assert "/technical-writer <path>" in text
    assert "/technical-writer <path>#<heading>" in text
    assert "/technical-writer <description>" in text


def test_technical_writer_no_argument_asks_and_makes_no_changes():
    """Precondition check: with no argument the command stops and asks what documentation to consider, changing nothing."""
    pre = _section("Precondition check")
    assert "$arguments" in pre and "empty" in pre
    assert "ask what documentation to consider" in pre
    assert "change nothing" in pre


def test_technical_writer_unresolvable_target_lists_close_matches():
    """Precondition check: an unresolvable target lists the closest matches and asks which was meant."""
    pre = _section("Precondition check")
    assert "closest matches" in pre
    assert "ask which" in pre


def test_technical_writer_prints_audience_needs_and_core_message():
    """Before proposing changes the command prints the audience, what they need, and the core message."""
    phase2 = _section("Phase 2")
    assert "print" in phase2
    for label in ("audience:", "they need:", "core message:"):
        assert label in phase2
        assert label in _output_format()


def test_technical_writer_exact_facts_rule_present():
    """Rewrite rules keep env var names, defaults, endpoint paths, commands, file paths and versions exact."""
    draft = _section("Phase 3")
    assert "exact" in draft
    for fact in ("env var names", "defaults", "endpoint paths", "commands", "file paths", "version numbers"):
        assert fact in draft, fact


def test_technical_writer_reports_removed_or_moved_facts():
    """Any fact removed or moved is listed in the report with a reason (Removed/moved line in output format)."""
    assert "removed/moved" in _output_format()
    assert "reason" in _output_format()
    assert "removed/moved facts list" in _section("Phase 4")


# ---------------------------------------------------------------------------
# Story: Identify the Audience and Ask When Unsure
# ---------------------------------------------------------------------------

def test_technical_writer_audience_mapping_covers_all_locations():
    """Audience mapping table covers README.md, .env.example, features/core, features/reference, stories, ui_description, plans and .claude/commands."""
    phase2 = _section("Phase 2")
    for location in (
        "`readme.md`",
        "`.env.example`",
        "`markdown/features/core/`",
        "`markdown/features/reference/`",
        "`markdown/stories/`",
        "`markdown/ui_description/`",
        "`markdown/plans/`",
        "`.claude/commands/`",
    ):
        assert location in phase2, location


def test_technical_writer_asks_with_options_when_audience_ambiguous():
    """When location and content disagree or there are several audiences, the command asks with 2-4 options."""
    phase2 = _section("Phase 2")
    assert "different audiences" in phase2 or "several" in phase2
    assert "2–4" in phase2 or "2-4" in phase2
    assert "askuserquestion" in phase2


# ---------------------------------------------------------------------------
# Story: Approve Changes Before They Are Written
# ---------------------------------------------------------------------------

def test_technical_writer_shows_word_counts_before_and_after():
    """The proposal shows word counts before and after (output format includes words before -> after)."""
    assert "word counts before and after" in _section("Phase 4")
    assert "{words before} → {words after}" in _output_format()


def test_technical_writer_offers_apply_exclusions_discard_options():
    """The command offers apply as proposed, apply with exclusions, or discard."""
    phase4 = _section("Phase 4")
    assert "apply** as proposed" in phase4
    assert "apply with exclusions" in phase4
    assert "discard" in phase4


def test_technical_writer_structural_changes_offered_separately():
    """Deleting a section, splitting a file or moving content is offered as its own choice, not applied silently."""
    phase4 = _section("Phase 4")
    assert "structural change" in phase4
    assert "own choice" in phase4
    assert "never applied silently" in phase4
    for change in ("deleting a section", "splitting a file", "moving content"):
        assert change in phase4, change


def test_technical_writer_edits_only_targets_and_indexes():
    """After approval only target files and the indexes (markdown/features/README.md, markdown/stories/_index.md) are edited."""
    apply = _section("Phase 5")
    assert "only the approved changes" in apply
    assert "markdown/features/readme.md" in apply
    assert "markdown/stories/_index.md" in apply
    assert "edit no other files" in apply
    assert "edit nothing until they approve" in _section("Role")


# ---------------------------------------------------------------------------
# Story: Keep the Agent Roster Consistent
# ---------------------------------------------------------------------------

def test_technical_writer_command_file_exists():
    """.claude/commands/technical-writer.md exists."""
    assert COMMAND_FILE.is_file()


def test_technical_writer_command_file_has_version_and_mode_headers():
    """First two lines are <!-- version: 1 --> and <!-- mode: read-write -->."""
    lines = _cmd().splitlines()
    assert lines[0].strip() == "<!-- version: 1 -->"
    assert lines[1].strip() == "<!-- mode: read-write -->"


def test_technical_writer_command_file_has_contract_sections():
    """Contains Role, Scope, When to run, Precondition check and Output format sections."""
    text = _cmd()
    for heading in ("Role", "Scope", "When to run", "Precondition check", "Output format"):
        assert re.search(rf"^## {heading}\b", text, re.M), heading


def test_technical_writer_scope_excludes_code_and_defers_accuracy_to_steward():
    """Scope says it does not touch source code and leaves doc-vs-code checks to /documentation-steward."""
    scope = _section("Scope")
    assert "does not cover" in scope
    assert "/documentation-steward" in scope
    assert "do not touch source code" in scope


def test_technical_writer_reads_and_appends_lessons_learned():
    """The command reads markdown/lessons-learned.md and appends an entry for novel pitfalls."""
    assert "read `markdown/lessons-learned.md`" in _section("Phase 1")
    log = _section("Lessons log")
    assert "markdown/lessons-learned.md" in log
    assert "append" in log


def test_technical_writer_registered_in_claude_md():
    """CLAUDE.md lists /technical-writer under Developer Agents and in the review-gates table."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    agents = text.split("## Developer Agents", 1)[1].split("## Development Workflow", 1)[0]
    assert "### `/technical-writer`" in agents
    gates = text.split("### Review gates", 1)[1]
    assert re.search(r"^\| `/technical-writer` \|", gates, re.M)


def test_technical_writer_registered_in_commands_readme():
    """.claude/commands/README.md lists /technical-writer in the Maintenance agents table."""
    text = COMMANDS_README.read_text(encoding="utf-8")
    maintenance = text.split("### Maintenance agents", 1)[1].split("\n## ", 1)[0]
    assert "`/technical-writer`" in maintenance
    assert "(technical-writer.md)" in maintenance


def test_technical_writer_listed_in_agent_lessons_log():
    """markdown/features/reference/agent-lessons-log.md lists /technical-writer as a participating agent."""
    text = LESSONS_LOG_DOC.read_text(encoding="utf-8")
    participants = text.split("## Participating agents", 1)[1].split("\n## ", 1)[0]
    assert "- `/technical-writer`" in participants
