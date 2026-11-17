"""Local load test of the hot endpoints (issue #251).

Each virtual user registers a marked test account (`loadtest-...`), logs in, and
then loops over a weighted mix of the calls the website and the Twitch panel make:
leaderboards, roster, schedule, players and the panel's Live tab as reads, a card
draw and a roster save as writes. Standard library plus `requests`.

It writes test accounts and cards, so run it against a throwaway copy of the
database, never production. It refuses a base URL that is not localhost unless
`--allow-remote` is given.

Usage (from the repo root, with a local instance running on a database copy):
    python3 scripts/load_test.py --base-url http://localhost:8251 --users 20 --seconds 30
    python3 scripts/load_test.py --base-url http://localhost:8251 --ramp --json

Rate limits have no off switch. Start the target with the RATE_LIMIT_* settings in
RATE_LIMIT_SETTINGS raised (all virtual users share one IP), with a high
INITIAL_TOKENS so draws don't run out, and with TWITCH_LOCAL_DEV=true so the
panel route accepts the test token. See
markdown/features/reference/architecture-maturity-review.md.

`--ramp` raises the user count step by step and stops at the first level whose
p95 latency is over 1 second or whose error rate is over 1%.
"""

import argparse
import json
import math
import random
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

import requests

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
USERNAME_PREFIX = "loadtest-"
P95_LIMIT_SECONDS = 1.0
ERROR_RATE_LIMIT = 0.01
# The limits a single-IP load test runs into; raise them on the target instance.
RATE_LIMIT_SETTINGS = (
    "RATE_LIMIT_GLOBAL", "RATE_LIMIT_REGISTER", "RATE_LIMIT_LOGIN",
    "RATE_LIMIT_CARD_ACTION", "RATE_LIMIT_CARD_ACTION_IP", "RATE_LIMIT_ROSTER_MUTATION",
    "RATE_LIMIT_TWITCH_ACTION", "RATE_LIMIT_TWITCH_JOIN_IP",
)
RATE_LIMIT_NOTE = "assumed raised on the target instance (the script cannot read them)"

# name -> (method, path template, weight in the mix). Paths are the ones
# frontend/app-*.js and twitch-extension/panel.js call.
ENDPOINTS = {
    "leaderboard_season": ("GET", "/leaderboard/season", 20),
    "leaderboard_weekly": ("GET", "/leaderboard/weekly?week_id={week_id}", 10),
    "roster": ("GET", "/roster/{user_id}", 25),
    "schedule": ("GET", "/schedule", 10),
    "players": ("GET", "/players", 10),
    "twitch_panel": ("GET", "/twitch/panel", 10),
    "draw": ("POST", "/draw", 5),
    "roster_save": ("PUT", "/roster", 10),
}
SETUP_ENDPOINTS = {
    "register": ("POST", "/register"),
    "login": ("POST", "/login"),
    "me": ("GET", "/me"),
    "weeks": ("GET", "/weeks"),
}
ROSTER_SLOTS = 5


def is_local(url: str) -> bool:
    """True when the URL's host is exactly localhost, 127.0.0.1 or ::1."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    return host in LOCAL_HOSTS


def percentiles(samples) -> dict:
    """p50, p95 and p99 by nearest rank: the value at position ceil(p/100 * n) of the
    sorted samples. None for no samples."""
    ordered = sorted(samples)
    if not ordered:
        return {"p50": None, "p95": None, "p99": None}
    return {f"p{p}": ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1] for p in (50, 95, 99)}


class Stats:
    """Thread-safe latencies, errors and refusals per endpoint."""

    def __init__(self):
        self._lock = threading.Lock()
        self.latencies, self.errors, self.refused = {}, {}, {}

    def record(self, name, seconds, error=False, refused=False):
        with self._lock:
            self.latencies.setdefault(name, []).append(seconds)
            if error:
                self.errors[name] = self.errors.get(name, 0) + 1
            if refused:
                self.refused[name] = self.refused.get(name, 0) + 1

    def summary(self, names, seconds) -> dict:
        out = {}
        for name in names:
            samples = self.latencies.get(name, [])
            out[name] = _summarise(samples, self.errors.get(name, 0), seconds,
                                   self.refused.get(name, 0))
        return out

    def total(self, names, seconds) -> dict:
        samples = [s for n in names for s in self.latencies.get(n, [])]
        return _summarise(samples, sum(self.errors.get(n, 0) for n in names), seconds,
                          sum(self.refused.get(n, 0) for n in names))


def _ms(value):
    return None if value is None else round(value * 1000, 1)


def _summarise(samples, errors, seconds, refused=0) -> dict:
    pct = percentiles(samples)
    count = len(samples)
    return {
        "count": count,
        "rps": round(count / seconds, 2) if seconds > 0 else 0.0,
        "errors": errors,
        "error_rate": round(errors / count, 4) if count else 0.0,
        "refused": refused,
        "p50_ms": _ms(pct["p50"]), "p95_ms": _ms(pct["p95"]), "p99_ms": _ms(pct["p99"]),
    }


def _default_request(session, method, url, **kwargs):
    return session.request(method, url, **kwargs)


class VirtualUser:
    """One test account with its own session and its last known roster."""

    def __init__(self, base_url, name, request, stats, timeout, twitch_token, clock):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.session = requests.Session()
        self._request, self._stats, self._timeout = request, stats, timeout
        self._twitch_token, self._clock = twitch_token, clock
        self.user_id = 0
        self.week_id = 1
        self.roster = None
        self.can_draw = True

    def call(self, name, method, path, body=None, headers=None):
        """One timed request. Returns the parsed JSON body, or None after an error.
        A failed connection, a timeout and any status of 400 or more count as errors,
        except a 409 on a draw (out of tokens or players), which counts as refused."""
        started = self._clock()
        data, error, refused = None, False, False
        try:
            response = self._request(self.session, method, self.base_url + path, json=body,
                                     headers=headers, timeout=self._timeout)
            if name == "draw" and response.status_code == 409:
                refused = True
            elif response.status_code >= 400:
                error = True
            else:
                try:
                    data = response.json()
                except ValueError:
                    data = None
        except requests.RequestException:
            error = True
        self._stats.record(name, self._clock() - started, error=error, refused=refused)
        return None if (error or refused) else (data if data is not None else {})

    def setup(self):
        password = uuid.uuid4().hex
        self.call("register", "POST", "/register",
                  {"username": self.name, "email": f"{self.name}@loadtest.invalid",
                   "password": password})
        self.call("login", "POST", "/login", {"username": self.name, "password": password})
        me = self.call("me", "GET", "/me")
        if isinstance(me, dict) and me.get("user_id"):
            self.user_id = me["user_id"]
        weeks = self.call("weeks", "GET", "/weeks")
        if isinstance(weeks, list) and weeks and isinstance(weeks[-1], dict) and weeks[-1].get("id"):
            self.week_id = weeks[-1]["id"]

    def step(self, name):
        method, template, _ = ENDPOINTS[name]
        path = template.format(user_id=self.user_id, week_id=self.week_id)
        if name == "roster":
            self.roster = self.call(name, method, path)
        elif name == "twitch_panel":
            self.call(name, method, path, headers={"Authorization": "Bearer " + self._twitch_token})
        elif name == "draw":
            if self.can_draw and self.call(name, method, path) is None:
                self.can_draw = False
            self.roster = None
        elif name == "roster_save":
            if not isinstance(self.roster, dict):
                self.step("roster")
            if isinstance(self.roster, dict):
                saved = self.call(name, method, path, _next_layout(self.roster))
                self.roster = saved if isinstance(saved, dict) else None
        else:
            self.call(name, method, path)


def _next_layout(roster: dict) -> dict:
    """A changed, valid layout from a GET /roster answer: fill empty slots from the
    bench with players not yet active, then rotate the active cards by one slot."""
    active = [c for c in roster.get("active") or [] if isinstance(c, dict)]
    bench = [c for c in roster.get("bench") or [] if isinstance(c, dict)]
    players = {c.get("player_id") for c in active}
    while len(active) < ROSTER_SLOTS:
        pick = next((c for c in bench if c.get("player_id") not in players), None)
        if pick is None:
            break
        bench.remove(pick)
        active.append(pick)
        players.add(pick.get("player_id"))
    ids = [c.get("id") for c in active]
    ids = ids[1:] + ids[:1]
    return {"active": ids, "bench": [c.get("id") for c in bench],
            "base_version": str(roster.get("version") or "0")}


def _run_id() -> str:
    """Digits only: a hex id could spell a reserved word after look-alike mapping."""
    return f"{uuid.uuid4().int % 10**8:08d}"


def make_users(base_url, count, existing=None, request=None, stats=None, timeout=10.0,
               twitch_token="local-dev", clock=time.monotonic, run_id=None):
    """Register and log in virtual users until there are `count` of them."""
    users = list(existing or [])
    run_id = run_id or _run_id()
    for index in range(len(users), count):
        user = VirtualUser(base_url, f"{USERNAME_PREFIX}{run_id}-{index}", request or _default_request,
                           stats, timeout, twitch_token, clock)
        user.setup()
        users.append(user)
    return users


def _user_loop(user, deadline, think, rng, clock, sleep):
    names = list(ENDPOINTS)
    weights = [ENDPOINTS[n][2] for n in names]
    # Users start spread over one think interval, not all in the same instant. The
    # first pass covers every endpoint once, even past the deadline, so a short run
    # still has the whole mix.
    if think > 0:
        sleep(rng.uniform(0, think))
    first = names[:]
    rng.shuffle(first)
    while first or clock() < deadline:
        user.step(first.pop() if first else rng.choices(names, weights)[0])
        if think > 0:
            sleep(think * rng.uniform(0.5, 1.5))


def run(base_url, users, seconds, request=None, think=1.0, timeout=10.0, twitch_token="local-dev",
        clock=time.monotonic, sleep=time.sleep, seed=None, state=None) -> dict:
    """Drive `users` virtual users for `seconds` and return the measured numbers.
    `state` (a dict) keeps the registered users between calls, for the ramp."""
    state = state if state is not None else {}
    setup_stats = Stats()
    run_id = state.setdefault("run_id", _run_id())
    pool = make_users(base_url, users, existing=state.get("users"), request=request,
                      stats=setup_stats, timeout=timeout, twitch_token=twitch_token, clock=clock,
                      run_id=run_id)
    state["users"] = pool
    stats = Stats()
    for user in pool:
        user._stats = stats
    started = clock()
    deadline = started + seconds
    threads = [threading.Thread(
        target=_user_loop, daemon=True,
        args=(user, deadline, think, random.Random(None if seed is None else seed + i), clock, sleep))
        for i, user in enumerate(pool[:users])]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = max(round(clock() - started, 2), 0.01)
    return {
        "base_url": base_url,
        "users": users,
        "seconds": elapsed,
        "think_seconds": think,
        "rate_limits": {"settings": list(RATE_LIMIT_SETTINGS), "note": RATE_LIMIT_NOTE},
        "endpoints": stats.summary(ENDPOINTS, elapsed),
        "total": stats.total(ENDPOINTS, elapsed),
        "setup": setup_stats.summary(SETUP_ENDPOINTS, elapsed),
    }


def ramp(measure, start=10, step=10, max_users=100, p95_limit=P95_LIMIT_SECONDS,
         error_limit=ERROR_RATE_LIMIT) -> dict:
    """Call `measure(users)` at start, start+step, ... up to max_users and stop at the
    first level whose total p95 is over `p95_limit` seconds or whose error rate is over
    `error_limit`. `limit_users` is None when no level crossed a threshold."""
    levels, limit, reason = [], None, None
    users = start
    while users <= max_users:
        result = measure(users)
        total = result["total"]
        levels.append({"users": users, "rps": total["rps"], "error_rate": total["error_rate"],
                       "p50_ms": total["p50_ms"], "p95_ms": total["p95_ms"],
                       "p99_ms": total["p99_ms"], "endpoints": result.get("endpoints")})
        if total["p95_ms"] is not None and total["p95_ms"] > p95_limit * 1000:
            limit, reason = users, "p95 > 1 s"
        elif total["error_rate"] > error_limit:
            limit, reason = users, "errors > 1%"
        if limit is not None:
            break
        users += step
    return {"levels": levels, "limit_users": limit, "reason": reason,
            "max_users": levels[-1]["users"] if levels else None,
            "rate_limits": {"settings": list(RATE_LIMIT_SETTINGS), "note": RATE_LIMIT_NOTE}}


def _num(value) -> str:
    return "n/a" if value is None else str(value)


def _row(name, s) -> str:
    return (f"  {name:<20} {s['count']:>7} {s['rps']:>8} {s['error_rate']:>8} {s['refused']:>8} "
            f"{_num(s['p50_ms']):>9} {_num(s['p95_ms']):>9} {_num(s['p99_ms']):>9}")


def _limits_text() -> str:
    return f"Rate limits: {RATE_LIMIT_NOTE}: " + ", ".join(RATE_LIMIT_SETTINGS)


def format_result(result: dict) -> str:
    lines = [f"Load test: {result['users']} users for {result['seconds']} s against "
             f"{result['base_url']} (think time {result['think_seconds']} s)",
             _limits_text(),
             f"  {'endpoint':<20} {'count':>7} {'req/s':>8} {'err rate':>8} {'refused':>8} "
             f"{'p50 ms':>9} {'p95 ms':>9} {'p99 ms':>9}"]
    lines += [_row(name, s) for name, s in result["endpoints"].items()]
    lines.append(_row("TOTAL", result["total"]))
    lines.append("Setup (not in the total):")
    lines += [_row(name, s) for name, s in result["setup"].items()]
    return "\n".join(lines)


def format_ramp(result: dict) -> str:
    lines = ["Ramp", _limits_text(),
             f"  {'users':>6} {'req/s':>8} {'err rate':>8} {'p50 ms':>9} {'p95 ms':>9} {'p99 ms':>9}"]
    lines += [f"  {lv['users']:>6} {lv['rps']:>8} {lv['error_rate']:>8} {_num(lv['p50_ms']):>9} "
              f"{_num(lv['p95_ms']):>9} {_num(lv['p99_ms']):>9}" for lv in result["levels"]]
    if result["limit_users"] is None:
        lines.append(f"No limit found up to {result['max_users']} users "
                     "(p95 stayed under 1 s and errors under 1%).")
    else:
        lines.append(f"Limit: {result['limit_users']} users ({result['reason']}).")
    return "\n".join(lines)


def main(argv=None, out=print, err=None, request=None) -> int:
    err = err or (lambda message: print(message, file=sys.stderr))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True, help="e.g. http://localhost:8251")
    parser.add_argument("--users", type=int, default=10, help="virtual users (the ramp's first level)")
    parser.add_argument("--seconds", type=float, default=30.0, help="length of the run, or of each ramp level")
    parser.add_argument("--think", type=float, default=1.0, help="mean pause between a user's calls, seconds")
    parser.add_argument("--timeout", type=float, default=10.0, help="request timeout, seconds")
    parser.add_argument("--ramp", action="store_true", help="raise the users step by step to the limit")
    parser.add_argument("--step", type=int, default=10, help="users added per ramp level")
    parser.add_argument("--max-users", type=int, default=100, help="last ramp level")
    parser.add_argument("--twitch-token", default="local-dev",
                        help="Bearer token for /twitch/panel (any value with TWITCH_LOCAL_DEV=true)")
    parser.add_argument("--allow-remote", action="store_true",
                        help="allow a base URL that is not localhost (never production)")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = parser.parse_args(argv)
    if not is_local(args.base_url) and not args.allow_remote:
        err(f"Refusing {args.base_url}: not localhost. This test writes accounts and cards; "
            "run it against a local copy, or pass --allow-remote for a non-production host.")
        return 2
    if args.users < 1 or args.seconds <= 0 or args.step < 1:
        err("--users and --step must be at least 1 and --seconds above 0")
        return 2
    kwargs = dict(request=request, think=args.think, timeout=args.timeout,
                  twitch_token=args.twitch_token)
    if args.ramp:
        state = {}
        result = ramp(lambda n: run(args.base_url, n, args.seconds, state=state, **kwargs),
                      start=args.users, step=args.step, max_users=max(args.max_users, args.users))
        out(json.dumps(result, indent=2) if args.json else format_ramp(result))
    else:
        result = run(args.base_url, args.users, args.seconds, **kwargs)
        out(json.dumps(result, indent=2) if args.json else format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
