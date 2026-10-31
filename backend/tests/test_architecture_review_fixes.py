"""Fixes from the 2026-10-31 systems architecture review.

- Dependencies are hash-locked (scripts/lock-deps.sh): the Docker image and CI install
  only backend/requirements.lock / requirements-dev.lock, so a new upstream release
  reaches production only through a commit that passes the tests.
- docker-publish.yml builds the image only after the unit and UI tests pass.
- The profile enrichment timeout actually frees the loop, without running two batches.
- The finals check also runs from the week maintenance loop (no live thread without
  STEAM_API_KEY or in DEMO_MODE).
- Startup refuses more than one worker process.
"""
import re
import threading
import time
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
WORKFLOWS = REPO / ".github" / "workflows"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _ranges(path: Path) -> list[Requirement]:
    out = []
    for line in _read(path).splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.append(Requirement(line))
    return out


def _lock_pins(path: Path) -> dict[str, dict]:
    """{name: {"version", "hashes"}} from a pip-compile style lock (continuation lines)."""
    text = _read(path).replace("\\\n", " ")
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)", line)
        assert m, f"unpinned line in {path.name}: {line[:80]}"
        name = canonicalize_name(m.group(1).split("[")[0])
        pins[name] = {"version": m.group(2), "hashes": re.findall(r"--hash=sha256:[0-9a-f]{64}", line)}
    return pins


# ---------------------------------------------------------------------------
# Lock files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ranges, lock", [
    ("requirements.txt", "requirements.lock"),
    ("requirements-dev.txt", "requirements-dev.lock"),
])
def test_lock_pins_every_range_within_its_bounds(ranges, lock):
    """Each package named in a ranges file is pinned in its lock at a version the range
    allows, so editing a range without re-locking fails here."""
    pins = _lock_pins(BACKEND / lock)
    for req in _ranges(BACKEND / ranges):
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} missing from {lock}: run scripts/lock-deps.sh"
        assert req.specifier.contains(pins[name]["version"], prereleases=True), (
            f"{lock} pins {req.name}=={pins[name]['version']} outside {req.specifier}: run scripts/lock-deps.sh")


@pytest.mark.parametrize("lock", ["requirements.lock", "requirements-dev.lock"])
def test_every_pin_carries_hashes(lock):
    pins = _lock_pins(BACKEND / lock)
    assert pins
    missing = [n for n, p in pins.items() if not p["hashes"]]
    assert not missing, f"pins without hashes in {lock}: {missing}"


def test_dev_lock_uses_the_runtime_versions():
    """CI tests the exact versions the image installs."""
    runtime = _lock_pins(BACKEND / "requirements.lock")
    dev = _lock_pins(BACKEND / "requirements-dev.lock")
    differ = {n: (v["version"], dev[n]["version"]) for n, v in runtime.items()
              if n in dev and dev[n]["version"] != v["version"]}
    assert not differ, f"dev lock differs from runtime lock: {differ}"
    assert set(runtime) <= set(dev)


def test_lock_script_regenerates_both_files():
    script = _read(REPO / "scripts" / "lock-deps.sh")
    assert "--generate-hashes" in script
    assert "-o backend/requirements.lock" in script
    assert "-o backend/requirements-dev.lock" in script
    assert "-c backend/requirements.lock" in script


def test_dockerfile_installs_only_the_lock_with_hashes():
    docker = _read(REPO / "Dockerfile")
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in docker
    assert "COPY backend/requirements.lock ." in docker
    assert "-r requirements.txt" not in docker


# ---------------------------------------------------------------------------
# CI gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf, lock", [
    ("unit-tests.yml", "backend/requirements-dev.lock"),
    ("ui-tests.yml", "backend/requirements.lock"),
])
def test_test_workflows_install_locks_and_are_reusable(wf, lock):
    text = _read(WORKFLOWS / wf)
    assert f"pip install -r {lock} --require-hashes" in text
    assert "requirements.txt" not in text.split("pip-audit")[0]
    on = text.split("\non:", 1)[1].split("\njobs:", 1)[0]
    assert "workflow_call:" in on
    assert "pull_request:" in on
    assert "push:" not in on, "main pushes run these from docker-publish.yml"


def test_pip_audit_checks_the_locked_versions():
    text = _read(WORKFLOWS / "unit-tests.yml")
    assert "pip-audit -r backend/requirements.lock --require-hashes" in text


def test_image_build_waits_for_unit_and_ui_tests():
    text = _read(WORKFLOWS / "docker-publish.yml")
    jobs = text.split("\njobs:", 1)[1]
    assert re.search(r"\n  unit-tests:\n    uses: \./\.github/workflows/unit-tests\.yml", jobs)
    assert re.search(r"\n  ui-tests:\n    uses: \./\.github/workflows/ui-tests\.yml", jobs)
    build = jobs.split("\n  build-and-push:\n", 1)[1]
    assert re.match(r"    needs: \[unit-tests, ui-tests\]\n", build)


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------

def test_profile_enrichment_timeout_frees_the_loop_without_a_second_batch(monkeypatch):
    """A batch stuck past the timeout no longer blocks the loop; while it runs, later
    cycles are skipped (never two batches at once); once it ends, batches resume."""
    import main

    release = threading.Event()
    calls = []

    def fake_enrichment(batch_size):
        calls.append(time.monotonic())
        if len(calls) == 1:
            release.wait(5)
        return {"enriched": 0, "errors": 0}

    stop = threading.Event()
    monkeypatch.setattr(main, "_stop_event", stop)
    monkeypatch.setattr(main, "run_profile_enrichment", fake_enrichment)
    monkeypatch.setattr(main, "_ENRICHMENT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main, "_ENRICHMENT_INTERVAL", 0.05)

    loop = threading.Thread(target=main._profile_enrichment_loop, daemon=True)
    loop.start()
    time.sleep(0.4)  # several cycles pass while batch 1 is stuck
    assert len(calls) == 1, "a second batch started while the first was still running"
    release.set()
    deadline = time.monotonic() + 3
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    stop.set()
    loop.join(2)
    assert len(calls) >= 2, "enrichment did not resume after the stuck batch finished"
    assert not loop.is_alive()


def test_profile_enrichment_does_not_wait_on_a_with_executor():
    import inspect
    import main
    src = inspect.getsource(main._profile_enrichment_loop).replace(main._profile_enrichment_loop.__doc__, "")
    assert "with ThreadPoolExecutor" not in src
    assert "shutdown(wait=False" in src


def test_week_maintenance_loop_runs_the_finals_check(monkeypatch):
    """The finals check runs every maintenance tick, even when maintenance itself fails."""
    import main

    stop = threading.Event()
    ran = []

    class _BoomSession:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(main, "_stop_event", stop)
    monkeypatch.setattr(main, "SessionLocal", _BoomSession())
    monkeypatch.setattr(main, "_WEEK_CHECK_INTERVAL", 0.01)

    def fake_check():
        ran.append(1)
        stop.set()

    monkeypatch.setattr(main, "_run_finals_check", fake_check)
    t = threading.Thread(target=main._week_maintenance_loop, daemon=True)
    t.start()
    t.join(2)
    assert ran == [1]
    assert not t.is_alive()


# ---------------------------------------------------------------------------
# Single process
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["2", "4"])
def test_startup_refuses_several_workers(monkeypatch, value):
    import main
    monkeypatch.setenv("WEB_CONCURRENCY", value)
    with pytest.raises(RuntimeError, match="single process"):
        main._single_process_guard()


@pytest.mark.parametrize("value", [None, "", "1", "junk"])
def test_startup_allows_one_worker(monkeypatch, value):
    import main
    if value is None:
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("WEB_CONCURRENCY", value)
    main._single_process_guard()


def test_guard_runs_first_in_lifespan():
    import inspect
    import main
    src = inspect.getsource(main.lifespan)
    assert src.index("_single_process_guard()") < src.index("run_migrations(engine)")
