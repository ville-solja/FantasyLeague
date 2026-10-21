# Local agents

Helpers for handing small, low-stakes jobs to a local Ollama model. The full guide (updating
Ollama, which tasks go where, timers, handover options) is
[local-model-agents.md](../../markdown/features/reference/local-model-agents.md).

| File | What it does |
|---|---|
| `ollama_call.py` | Shared caller: prompt on stdin, answer on stdout. `--json` validates the answer; `--check [MODEL]` reports server and model status |
| `assist.py` | Handover entry point: a task plus input files (or stdin) → answer on stdout and a report in `reports/local/assist/`. Refuses `.env`, `data/`, backups, databases and input that looks like a credential |
| `test_triage.sh` | Nightly job: runs the backend suite; on failures the model classifies each one into `reports/local/test-triage/<date>.md` |

Standard library only; no virtualenv needed. Reports go to `reports/local/`, which is git-ignored.

```bash
python3 scripts/local-agents/ollama_call.py --check qwen3:14b
git log --oneline -15 | python3 scripts/local-agents/assist.py --json \
  --task "Group these commits by the issue number in their title"
bash scripts/local-agents/test_triage.sh
```

Defaults: model `qwen3:14b` (override with `--model`, or `ASSIST_MODEL` / `TRIAGE_MODEL`), temperature 0,
16k context, thinking off. `--cpu` (or `ASSIST_CPU=1`) keeps layers off the GPU. Local answers are unverified first passes: check them before acting.

**GPU warning:** on kernel 6.8 the ROCm backend crashed the RX 7800 XT (GPU reset, desktop lost). The service
now runs on Vulkan (`no-rocm.conf`); keep it that way until the kernel is upgraded. See section 1.2 of the guide.
