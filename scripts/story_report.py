"""
story_report.py — generates markdown/story-report.md by auditing the codebase
against the user stories in markdown/User_stories.md using the Claude API.

Usage:
    ANTHROPIC_API_KEY=sk-... python scripts/story_report.py

Output:
    markdown/story-report.md  (overwritten on each run)
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("anthropic package not found — run: pip install anthropic")

REPO = Path(__file__).parent.parent

SOURCE_FILES = [
    "backend/main.py",
    "backend/models.py",
    "frontend/app.js",
    "frontend/index.html",
]

STORIES_FILE = "markdown/User_stories.md"
REPORT_FILE  = "markdown/story-report.md"


def read(rel_path: str) -> str:
    return (REPO / rel_path).read_text(encoding="utf-8")


def build_prompt(stories: str, sources: dict[str, str]) -> str:
    codebase_block = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in sources.items()
    )

    return f"""You are auditing a fantasy sports web app POC against its user stories.
Your job is to produce a coverage report that a developer will use to decide whether to
clarify a user story or update the implementation. Be concise but specific in the Notes column.

## User Stories
{stories}

## Codebase
{codebase_block}

---

Produce the report in exactly this format — no other prose outside it:

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
(one row per story subsection, e.g. 1.1, 1.2, 2.1, ...)

Use these Status values:
- ✅ Aligned — story matches implementation
- ⚠️ Diverged — implementation exists but differs from the story
- 🔲 Not implemented — no implementation found in the codebase
- ❓ Ambiguous — story is too vague to evaluate confidently

After the table add:

## Key divergences

A numbered list of the most significant gaps or divergences (max 10), each with a one-sentence
description and a resolution hint: either "clarify story" or "update implementation".
"""


def main() -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY environment variable is not set")

    stories = read(STORIES_FILE)
    sources = {path: read(path) for path in SOURCE_FILES}

    prompt = build_prompt(stories, sources)

    print("Calling Claude API…")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    report_body = message.content[0].text.strip()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = f"<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->\n"
    report += f"_Last updated: {generated_at}_\n\n"
    report += report_body + "\n"

    out = REPO / REPORT_FILE
    out.write_text(report, encoding="utf-8")
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
