#!/usr/bin/env python3
"""Shared helper for local Ollama calls (markdown/features/reference/local-model-agents.md).

    ollama_call.py MODEL [--json] [--system TEXT] [--ctx N] < prompt.txt   -> answer on stdout
    ollama_call.py --check [MODEL]                                          -> server and model status

Standard library only, so it runs without the backend virtualenv. Deterministic settings
(temperature 0, fixed context). Exit codes: 0 ok, 1 server or model problem, 2 bad answer
(--json requested but the reply isn't JSON).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")


def _request(path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def installed_models():
    return [m["name"] for m in _request("/api/tags", timeout=10).get("models", [])]


def chat(model, prompt, system=None, as_json=False, ctx=16384, think=False, timeout=600, cpu=None):
    """One chat turn; returns (answer text, stats dict).

    cpu=True keeps every layer off the GPU (num_gpu 0). Default: the ASSIST_CPU env var.
    """
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    body = {
        "model": model,
        "stream": False,
        "messages": messages,
        "think": think,
        "options": {"temperature": 0, "num_ctx": ctx},
    }
    if cpu is None:
        cpu = os.environ.get("ASSIST_CPU") == "1"
    if cpu:
        body["options"]["num_gpu"] = 0
    if as_json:
        body["format"] = "json"
    reply = _request("/api/chat", body, timeout=timeout)
    stats = {
        "model": reply.get("model", model),
        "prompt_tokens": reply.get("prompt_eval_count"),
        "answer_tokens": reply.get("eval_count"),
        "seconds": round((reply.get("total_duration") or 0) / 1e9, 1),
    }
    return reply["message"]["content"].strip(), stats


def check(model=None):
    try:
        version = _request("/api/version", timeout=5)["version"]
        models = installed_models()
    except (urllib.error.URLError, OSError) as exc:
        print(f"Ollama not reachable at {HOST}: {exc}", file=sys.stderr)
        return 1
    print(f"Ollama {version} at {HOST}")
    print("Models: " + (", ".join(models) or "none"))
    if model and model not in models and f"{model}:latest" not in models:
        print(f"Missing model {model}: run `ollama pull {model}`", file=sys.stderr)
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("model", nargs="?")
    p.add_argument("--json", action="store_true", help="ask for a JSON answer and validate it")
    p.add_argument("--system", help="system prompt")
    p.add_argument("--ctx", type=int, default=16384, help="context window (num_ctx)")
    p.add_argument("--think", action="store_true", help="let reasoning models think (slower)")
    p.add_argument("--cpu", action="store_true", help="keep the model off the GPU (also ASSIST_CPU=1)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--stats", action="store_true", help="print token and time stats to stderr")
    p.add_argument("--check", action="store_true", help="report server and model status, then exit")
    a = p.parse_args()

    if a.check:
        return check(a.model)
    if not a.model:
        p.error("MODEL is required")
    prompt = sys.stdin.read()
    if not prompt.strip():
        p.error("empty prompt on stdin")
    try:
        answer, stats = chat(a.model, prompt, a.system, a.json, a.ctx, a.think, a.timeout, a.cpu or None)
    except urllib.error.HTTPError as exc:
        print(f"Ollama error {exc.code}: {exc.read().decode(errors='replace')[:300]}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"Ollama not reachable at {HOST}: {exc}", file=sys.stderr)
        return 1
    if a.json:
        try:
            json.loads(answer)
        except json.JSONDecodeError:
            print(answer)
            print("Answer is not valid JSON", file=sys.stderr)
            return 2
    print(answer)
    if a.stats:
        print(json.dumps(stats), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
