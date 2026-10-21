# Local Model Agents (Ollama)

This guide sets up local models alongside the Claude agents in `.claude/commands/`, for recurring, high-volume, low-stakes work. It covers four things:
1. updating Ollama on this machine;
2. deciding which tasks go to which worker;
3. scheduling the recurring checks;
4. how Claude and a local model can hand work to each other.

Local models are **pre-filters and drafters**. They never decide, merge, post or ship.

**Machine this was written for (2026-10):**
- AMD GPU with 16 GB of video memory (Navi 32, likely an RX 7800 XT);
- 31 GB of RAM and 12 cores;
- Ollama 0.1.41, which is too old and needs updating.

**Model names below are from mid-2026.** Check https://ollama.com/library for newer versions of the same families before pulling.

---

## 1. Update Ollama

### 1.1 Upgrade
The official installer upgrades in place and, when it finds an AMD GPU, installs the ROCm build:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version            # expect a 2025–2026 version, not 0.1.x
sudo systemctl restart ollama
```

### 1.2 Check that the GPU is used

> **Known crash on this machine (2026-10-21):** Ollama 0.40.7 with its bundled ROCm 7.2 on kernel 6.8 hung the RX 7800 XT's firmware scheduler on the first computation. The kernel logged `MES failed to response` and `VRAM is lost due to GPU reset!`, the desktop died, and the PC needed a restart. **Don't use the ROCm backend on kernel 6.8.** Pick one of these, then do a load test only from a terminal you can afford to lose:
> - **Vulkan backend (in use here since 2026-10-21; works, about 13 s for a short job with `qwen3:14b` at 100 % GPU):** hide the card from ROCm so Ollama falls back to Vulkan, which goes through the normal graphics driver: `Environment="ROCR_VISIBLE_DEVICES=-1"` and `Environment="HIP_VISIBLE_DEVICES=-1"`, here in `/etc/systemd/system/ollama.service.d/no-rocm.conf`. After the restart, the log should show `library=Vulkan` on the "inference compute" line. Check this before loading any model.
> - **CPU only (always safe, slower):** `Environment="OLLAMA_LLM_LIBRARY=cpu"` plus the two variables above. A 14B model then answers short jobs in a minute or two, which is fine for nightly runs. The helpers' `--cpu` flag (`ASSIST_CPU=1`) also keeps layers off the GPU, but only hiding the card at service level guarantees no GPU work.
> - **ROCm later:** upgrade to the HWE kernel (6.14 or newer) and `linux-firmware` first, then remove the hiding variables and retest.
>
> To check a crash after the fact: `journalctl -b -1 -k | grep -E "MES|GPU reset"`.

```bash
journalctl -u ollama --since "5 min ago" | grep -iE "amdgpu|rocm|gfx"
ollama run gemma3:12b "say hi"   # in a second terminal while it loads:
ollama ps                    # the PROCESSOR column should read "100% GPU"
```
If Ollama falls back to the CPU on this card (gfx1101), add an override and restart. The settings in 1.3 go in the same file.
```bash
sudo systemctl edit ollama
# [Service]
# Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0"
sudo systemctl restart ollama
```

### 1.3 Service settings for background jobs
Add these with `sudo systemctl edit ollama`, then `sudo systemctl restart ollama`:

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"   # localhost only (the default); never expose it
Environment="OLLAMA_KEEP_ALIVE=10m"         # unload the model after a job, so the GPU is free for games
Environment="OLLAMA_MAX_LOADED_MODELS=1"    # 16 GB of video memory: one model at a time
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"     # halves the memory the context window uses
Environment="OLLAMA_CONTEXT_LENGTH=16384"   # default context; jobs can raise it per request
```
Unknown variables are ignored by older versions. Run `ollama serve --help` to see what yours supports.

### 1.4 Pull the models
```bash
ollama rm llava                 # the old 2024 model, not needed
ollama pull qwen3-coder:30b     # code and test-log reasoning; MoE, part of it runs in system RAM
ollama pull gpt-oss:20b         # general reasoning, structured output; fits fully on the GPU
ollama pull qwen3:14b           # summaries, labels, short text; fast
ollama pull gemma3:12b          # prose (player bios), release-note digests
ollama pull nomic-embed-text    # embeddings for doc and issue search
```
**Smoke test:**
```bash
curl -s localhost:11434/api/chat -d '{"model":"qwen3:14b","stream":false,
  "messages":[{"role":"user","content":"Reply with the JSON {\"ok\": true}"}],
  "format":"json","options":{"temperature":0}}' | python3 -c "import json,sys;print(json.load(sys.stdin)['message']['content'])"
```

---

## 2. Separation of tasks

Four workers, each with a clear limit:

| Worker | Does | Never does |
|---|---|---|
| **Deterministic scripts** (pytest, pip-audit, gh, grep) | Produce facts: test results, outdated packages, new issues, changed files | Judge or summarise |
| **Local model** (Ollama) | First pass over those facts: classify, summarise, flag likely problems, draft text. Writes a report | Edit code, gate a pipeline, post to GitHub, read secrets |
| **Claude agents** (`/develop`, `/ship`, the reviewers) | Plan, implement, review security, decide, act on reports | Trust a local report without checking it |
| **You** | Merge, deploy, approve anything outward or irreversible | |

### 2.1 Which tasks go where

| Task | Facts from | Local model | Claude's part |
|---|---|---|---|
| Nightly test-failure triage | `pytest -n auto` | `qwen3-coder:30b`: flaky, order-dependent or real, with a suspected cause | `/qa-engineer` or `/developer` fixes the real ones |
| Doc drift pre-scan | `git diff` since the last run, plus a grep of `markdown/` | `qwen3-coder:30b` plus `nomic-embed-text`: passages that still describe the old behaviour | `/documentation-steward` confirms and fixes |
| Issue intake | `gh issue list` (new since the last run) | `qwen3:14b` plus embeddings: area, likely duplicates, questions for unclear issues | `/product-planner` plans |
| Dependency digest | `pip list --outdated`, `pip-audit` | `gemma3:12b`: release notes summarised as "breaking for us or not" | `/security-reviewer` on anything security-relevant |
| Weekly log digest | Server logs, `markdown/lessons-learned.md` changes | `qwen3:14b`: recurring warnings, ingest failures | `/agent-steward` curates |
| Player bios (product) | Profile facts (`backend/enrich.py`) | `gemma3:12b`: replaces the paid Haiku call | None (public data, low stakes) |

### 2.2 Rules for local jobs
- **Inputs:** never send `.env`, anything under `data/`, backups, tokens or user data to a prompt. Repo code, test output, public docs and public match stats are fine.
- **Outputs:** write to `reports/local/<job>/<YYYY-MM-DD>.md`, which is git-ignored. A report states its model, its inputs and the time.
- **No outward actions:** a local job never comments on GitHub, pushes, labels or emails. If a report is worth acting on, a Claude agent or you do it.
- **No gate:** CI and `/develop` never wait for or depend on a local result. A missing or wrong report costs nothing.
- **Deterministic settings:** `temperature: 0`, `format: "json"` where a script parses the answer, and a fixed `num_ctx` per job.
- **Measure before trusting:** for the first weeks, compare each report with what the Claude agents found on the same change. Keep only the jobs that catch real things.

---

## 3. Set up recurring checks

### 3.1 Layout
```
scripts/local-agents/
  ollama_call.py        # one shared helper: chat or embed, JSON in and out
  test_triage.sh        # nightly
  doc_drift.py          # after commits (or nightly over the day's commits)
  issue_intake.py       # daily
  deps_digest.sh        # weekly
reports/local/          # git-ignored output
```

### 3.2 The shared helper (sketch)
Standard library only, so it runs without a virtualenv:

```python
#!/usr/bin/env python3
"""ollama_call.py MODEL [--json] [--ctx N] < prompt.txt  ->  answer on stdout."""
import argparse, json, sys, urllib.request

p = argparse.ArgumentParser()
p.add_argument("model"); p.add_argument("--json", action="store_true")
p.add_argument("--ctx", type=int, default=16384)
a = p.parse_args()
body = {"model": a.model, "stream": False,
        "messages": [{"role": "user", "content": sys.stdin.read()}],
        "options": {"temperature": 0, "num_ctx": a.ctx}}
if a.json:
    body["format"] = "json"
req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    print(json.load(r)["message"]["content"])
```

### 3.3 Example job: nightly test triage (sketch)
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
out="reports/local/test-triage/$(date +%F).md"; mkdir -p "$(dirname "$out")"
log=$(cd backend && python3 -m pytest tests/ -n auto -q --tb=short 2>&1 | tail -200) || true
if ! grep -q "failed" <<<"$log"; then echo "All tests passed $(date)" > "$out"; exit 0; fi
{ echo "Classify each failing test as flaky, order-dependent or real, with a one-line suspected cause."
  echo "Answer as JSON: {\"failures\":[{\"test\":...,\"kind\":...,\"cause\":...}]}"
  echo "--- pytest output ---"; echo "$log"; } \
  | python3 scripts/local-agents/ollama_call.py qwen3-coder:30b --json > "$out.json"
{ echo "# Test triage $(date +%F) (qwen3-coder:30b, local, unverified)"; cat "$out.json"; } > "$out"
```

### 3.4 Schedule with systemd user timers
User timers run as you, see the repo, and log to the journal. One service and timer pair per job:

```ini
# ~/.config/systemd/user/kana-test-triage.service
[Unit]
Description=Kana Cards nightly local test triage
[Service]
Type=oneshot
WorkingDirectory=/home/mint/Programming/dota-kanaliiga-fantasy
ExecStart=/home/mint/Programming/dota-kanaliiga-fantasy/scripts/local-agents/test_triage.sh
Nice=10
```
```ini
# ~/.config/systemd/user/kana-test-triage.timer
[Unit]
Description=Run Kana Cards test triage nightly
[Timer]
OnCalendar=*-*-* 03:30
Persistent=true          # catch up after the machine was off
RandomizedDelaySec=10m
[Install]
WantedBy=timers.target
```
```bash
systemctl --user daemon-reload
systemctl --user enable --now kana-test-triage.timer
loginctl enable-linger "$USER"        # run while logged out
systemctl --user list-timers          # check the schedule
journalctl --user -u kana-test-triage # logs
systemctl --user start kana-test-triage.service   # run once now
```

**Suggested schedule:**

| Job | When | Why |
|---|---|---|
| Test triage | Nightly 03:30 | Full suite in about 80 s plus the model; machine idle |
| Doc drift | Nightly 03:45, over the day's commits | Batches small commits |
| Issue intake | Daily 07:30 | Ready before the day starts |
| Dependency digest | Monday 07:00 | Matches the Dependency Scout in `CLAUDE.md` |
| Log digest | Sunday 20:00 | Feeds the week's `/agent-steward` run |

**Cron alternative:** add a line with `crontab -e`, e.g. `30 3 * * * /path/to/test_triage.sh >> ~/kana-local.log 2>&1`. Cron doesn't catch up after downtime the way `Persistent=true` does.

---

## 4. How Claude and the local model hand work to each other

Ordered from simplest and safest to most involved:

### 4.1 Claude reads local reports (start here)
The local jobs write `reports/local/…`, and the Claude agents read them as input:
- `/documentation-steward` reads the latest `doc-drift` report first, then confirms each finding against the code;
- `/qa-engineer` reads `test-triage` before re-running anything;
- `/product-planner issue N` reads the `issue-intake` notes for N (duplicates, questions).

Nothing calls anything. Add one line to each command's "Read before starting" section once a job has proven useful.

### 4.2 Claude calls Ollama through the helper
For bulk work where only a summary matters, Claude runs the helper with Bash and checks the answer. Examples: summarising 200 match logs, labelling every open issue, drafting placeholder copy.

```bash
python3 scripts/local-agents/ollama_call.py qwen3:14b --json < prompt.txt
```
To allow it without a prompt each time, add `Bash(python3 scripts/local-agents/ollama_call.py:*)` to `.claude/settings.json` (the `update-config` skill can do this).

**Hand over when** the task is high volume, low stakes, easy to check, uses no secrets and is cheap to retry. **Keep with Claude:** security reviews, architecture, code that ships, anything outward or irreversible, and product decisions.

### 4.3 Hooks: a local check after Claude edits
A Claude Code hook can run the drift pre-scan on the files Claude just changed and show the result in the session, for example a `Stop` hook running `doc_drift.py --files <changed>`. The hook's output reaches Claude as feedback; Claude decides what to do with it. Keep hooks fast (under about 30 s) and treat a timeout as "no findings". Set them up with the `update-config` skill.

### 4.4 An MCP server around Ollama
A small local MCP server can expose tools such as `local_summarize`, `local_classify` and `local_embed_search`, so Claude calls them by name instead of through Bash. That adds typed inputs and outputs, and one place to enforce the input rules in 2.2. Community Ollama MCP servers exist, but read the code of any you install. A 50-line custom server wrapping the helper is often simpler. Register it with `claude mcp add`.

### 4.5 A whole agent on a local model (experimental)
Some recent Ollama versions offer an Anthropic- or OpenAI-compatible endpoint, so a coding agent can be pointed at a local model. Check what your version supports. Expect much weaker multi-step tool use than Claude.
- **Use it only for:** sandboxed chores in a scratch worktree, such as renaming across files or regenerating fixtures, whose result you review as a diff.
- **Never for:** the `/develop` pipeline or anything that pushes.

### 4.6 Never hand over
- Security and access decisions.
- Merging, deploying, posting to GitHub, emailing users.
- Anything that reads `.env`, the production database or user data.
- Final say on whether a test failure is "just flaky": a local model can suggest it, and a person or Claude confirms it.

---

## Checklist

- [ ] Ollama upgraded; `ollama ps` shows 100 % GPU
- [ ] Service settings applied (localhost only, one model, keep-alive)
- [ ] Models pulled; `llava` removed
- [ ] `reports/local/` git-ignored
- [ ] `scripts/local-agents/` written (the helper first, then one job)
- [ ] First timer enabled; `loginctl enable-linger` set
- [ ] Two weeks of reports compared with the Claude agents' findings, before any command reads them
