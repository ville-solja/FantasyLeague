#!/usr/bin/env bash
# Nightly local test triage (markdown/features/reference/local-model-agents.md section 3.3).
# Runs the backend suite; on failures, asks the local model to classify each one and writes
# reports/local/test-triage/<date>.md. Never fails the caller: a missing report costs nothing.
# TRIAGE_LOG=<file> classifies an existing pytest log instead of running the suite.
set -uo pipefail
cd "$(dirname "$0")/../.."
model="${TRIAGE_MODEL:-qwen3:14b}"
out="reports/local/test-triage/$(date +%F).md"
mkdir -p "$(dirname "$out")"

if [[ -n "${TRIAGE_LOG:-}" ]]; then
  log=$(tail -150 "$TRIAGE_LOG")
else
  log=$(cd backend && python3 -m pytest tests/ -n auto -q --tb=line -p no:cacheprovider 2>&1 | tail -150)
fi
summary=$(tail -1 <<<"$log")

if ! grep -qE "[0-9]+ (failed|error)" <<<"$summary"; then
  printf '# Test triage %s\n\nAll tests passed: %s\n' "$(date +%F)" "$summary" > "$out"
  exit 0
fi

answer=$(python3 scripts/local-agents/assist.py --no-report --json --model "$model" \
  --task 'Classify each failing test as "flaky", "order-dependent", "environment" or "real", with a one-line suspected cause. Answer as {"failures":[{"test":"...","kind":"...","cause":"..."}]}.' \
  <<<"$log") || answer="(local model unavailable)"

{
  echo "# Test triage $(date +%F) ($model, local, unverified)"
  echo
  echo "**Suite:** $summary"
  echo
  echo '```json'
  echo "$answer"
  echo '```'
  echo
  echo '<details><summary>pytest output (last 150 lines)</summary>'
  echo
  echo '```'
  echo "$log"
  echo '```'
  echo '</details>'
} > "$out"
echo "Report: $out"
