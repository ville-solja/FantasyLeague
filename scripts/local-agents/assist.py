#!/usr/bin/env python3
"""Hand a small, low-stakes task to the local model and keep a report of it.

    assist.py --task "Group these commits by issue number" [--json] [--model M] [--name slug] [FILE ...]
    git log --oneline -20 | assist.py --task "..." --json

Inputs are the named files, or stdin when no file is given. The answer goes to stdout and a
report to reports/local/assist/<date>-<name>.md (git-ignored). The caller (Claude or you)
checks the answer before using it: local output is a first pass, never a decision.

Guard rails from markdown/features/reference/local-model-agents.md section 2.2: files that may
hold secrets or user data (.env, data/, backups, databases, archives) are refused, and so is
input that looks like it carries a credential.
"""
import argparse
import datetime
import os
import re
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ollama_call  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.environ.get("ASSIST_MODEL", "qwen3:14b")
MAX_INPUT_CHARS = 40_000  # about 10k tokens; leaves room in a 16k context

FORBIDDEN_PARTS = {"data", "backups", ".git", "node_modules"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".zip", ".pem", ".key", ".bak"}
SECRET_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9_]*(SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*\s*[=:]\s*['\"]?[^\s'\"]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def refuse_path(path: Path):
    """Return a reason when a file must not go into a prompt, else None."""
    resolved = path.resolve()
    name = resolved.name.lower()
    if name.startswith(".env"):
        return "env file"
    try:
        parts = set(resolved.relative_to(REPO).parts[:-1])
    except ValueError:
        return "outside the repo"
    if parts & FORBIDDEN_PARTS:
        return "under " + ", ".join(sorted(parts & FORBIDDEN_PARTS))
    if resolved.suffix.lower() in FORBIDDEN_SUFFIXES:
        return f"{resolved.suffix} file"
    return None


def gather(files):
    """Return [(label, text)] for the inputs, raising SystemExit on a refused input."""
    if not files:
        return [("stdin", sys.stdin.read())]
    items = []
    for f in files:
        path = Path(f)
        reason = refuse_path(path)
        if reason:
            sys.exit(f"Refused {f}: {reason} (see local-model-agents.md section 2.2)")
        items.append((str(path.resolve().relative_to(REPO)), path.read_text(errors="replace")))
    return items


def build_prompt(task, items, as_json):
    parts = [f"Task: {task.strip()}"]
    if as_json:
        parts.append("Answer with a single JSON object and nothing else.")
    parts.append("Use only the input below. If the input doesn't support an answer, say so.")
    for label, text in items:
        parts.append(f"--- input: {label} ---\n{text.rstrip()}")
    prompt = "\n\n".join(parts)
    if len(prompt) > MAX_INPUT_CHARS:
        sys.exit(f"Input is {len(prompt)} characters; the limit is {MAX_INPUT_CHARS}. Split the task.")
    return prompt


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="*", help="input files (default: stdin)")
    p.add_argument("--task", required=True, help="what the model should do with the input")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--json", action="store_true", help="require a JSON answer")
    p.add_argument("--name", help="report name (default: from the task)")
    p.add_argument("--ctx", type=int, default=16384)
    p.add_argument("--cpu", action="store_true", help="keep the model off the GPU (also ASSIST_CPU=1)")
    p.add_argument("--no-report", action="store_true", help="print only, write no report")
    a = p.parse_args()

    items = gather(a.files)
    for label, text in items:
        if SECRET_PATTERN.search(text):
            sys.exit(f"Refused {label}: it looks like it contains a credential")
    prompt = build_prompt(a.task, items, a.json)

    started = datetime.datetime.now()
    try:
        answer, stats = ollama_call.chat(a.model, prompt, as_json=a.json, ctx=a.ctx, cpu=a.cpu or None)
    except (urllib.error.URLError, OSError) as exc:
        sys.exit(f"Ollama call failed: {exc}. Check with: ollama_call.py --check {a.model}")
    print(answer)

    if a.no_report:
        return 0
    out = REPO / "reports" / "local" / "assist" / f"{started:%Y-%m-%d}-{slug(a.name or a.task)}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    fence = "json" if a.json else ""
    out.write_text(
        f"# Assist: {a.name or a.task}\n\n"
        f"- **When:** {started:%Y-%m-%d %H:%M}\n"
        f"- **Model:** {stats['model']} (local, unverified)\n"
        f"- **Inputs:** {', '.join(label for label, _ in items)}\n"
        f"- **Tokens:** {stats['prompt_tokens']} in, {stats['answer_tokens']} out, {stats['seconds']} s\n\n"
        f"## Task\n{a.task.strip()}\n\n"
        f"## Answer\n```{fence}\n{answer}\n```\n"
    )
    print(f"Report: {out.relative_to(REPO)} ({stats['seconds']} s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
