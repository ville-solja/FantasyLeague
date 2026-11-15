"""
OpenDota HTTP: one place for api_key + headers + a sliding-window RPM cap.

Free tier is ~60 req/min; default OPENDOTA_MAX_RPM=55 leaves headroom.
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Health record: what OpenDota answered lately, for Admin › League Management
# (GET /admin/opendota-status), so a rate limit or outage is visible without the
# container logs. In memory only: a restart starts it empty.
# ---------------------------------------------------------------------------
HEALTH_WINDOW_SECONDS = 24 * 3600
# A rate limit seen this recently, with no successful call since, counts as "now".
RATE_LIMITED_NOW_SECONDS = 15 * 60
_HEALTH_EVENTS_MAX = 2000
# Problem kinds: rate_limited (429), server_error (5xx), network (timeout or no
# connection), client_error (4xx other than 404), gave_up (retries exhausted).
_PROBLEM_KINDS = ("rate_limited", "server_error", "network", "client_error", "gave_up")
_health_lock = threading.Lock()
_health = {"last_ok_at": None, "last_problem": None}
_health_events: list[tuple[float, str]] = []


def _record(kind: str, label: str = "", status: int | None = None) -> None:
    now = time.time()
    with _health_lock:
        if kind == "ok":
            _health["last_ok_at"] = now
            return
        _health["last_problem"] = {"at": now, "kind": kind, "label": label[:120], "status": status}
        _health_events.append((now, kind))
        cutoff = now - HEALTH_WINDOW_SECONDS
        while _health_events and (_health_events[0][0] < cutoff or len(_health_events) > _HEALTH_EVENTS_MAX):
            _health_events.pop(0)


def health_snapshot(now: float | None = None) -> dict:
    """Last success, last problem, problem counts in the past 24 h, and whether OpenDota
    is rate-limiting the server now (a 429 in the last 15 min with no success since)."""
    now = time.time() if now is None else now
    with _health_lock:
        last_ok = _health["last_ok_at"]
        last_problem = dict(_health["last_problem"]) if _health["last_problem"] else None
        cutoff = now - HEALTH_WINDOW_SECONDS
        counts = {k: 0 for k in _PROBLEM_KINDS}
        for at, kind in _health_events:
            if at >= cutoff:
                counts[kind] = counts.get(kind, 0) + 1
    rate_limited_now = bool(
        last_problem and last_problem["kind"] in ("rate_limited", "gave_up")
        and now - last_problem["at"] <= RATE_LIMITED_NOW_SECONDS
        and (last_ok is None or last_ok < last_problem["at"])
        and counts["rate_limited"] > 0
    )
    failing_now = bool(
        last_problem and now - last_problem["at"] <= RATE_LIMITED_NOW_SECONDS
        and (last_ok is None or last_ok < last_problem["at"])
    )
    return {
        "last_ok_at": int(last_ok) if last_ok else None,
        "last_problem": ({**last_problem, "at": int(last_problem["at"])} if last_problem else None),
        "problems_24h": counts,
        "rate_limited_now": rate_limited_now,
        "failing_now": failing_now,
        "api_key_set": bool((os.getenv("OPENDOTA_API_KEY") or "").strip()),
    }


def reset_health() -> None:
    """Tests only."""
    with _health_lock:
        _health.update(last_ok_at=None, last_problem=None)
        _health_events.clear()

OPEN_DOTA_URL = "https://api.opendota.com/api"

DEFAULT_HEADERS = {
    "User-Agent": "KanaCards/1.0 (+https://kana-cards.com)",
    "Accept": "application/json",
}

_lock = threading.Lock()
_req_times: list[float] = []


def _max_rpm() -> int:
    raw = (os.getenv("OPENDOTA_MAX_RPM") or "55").strip()
    try:
        n = int(raw)
        return max(1, min(n, 120))
    except ValueError:
        return 55


def _admit(cost: int) -> float:
    """Take `cost` slots in the rolling 60 s window if they fit and return 0; otherwise
    take nothing and return how long to wait."""
    window = 60.0
    with _lock:
        now = time.time()
        cutoff = now - window
        while _req_times and _req_times[0] < cutoff:
            _req_times.pop(0)
        # An empty window always admits the call, even if cost > limit —
        # otherwise a single expensive call could never proceed.
        if len(_req_times) + cost <= _max_rpm() or not _req_times:
            _req_times.extend([now] * cost)
            return 0.0
        return max(_req_times[0] + window - now + 0.05, 0.05)


def throttle(cost: int = 1) -> None:
    """Block until `cost` more requests fit under the per-minute cap (rolling 60s window).

    OpenDota bills some calls as more than one request (POST /request/{match_id}
    counts as 10), so `cost` timestamps are appended to mirror its accounting.
    """
    cost = max(1, int(cost))
    while True:
        wait_s = _admit(cost)
        if not wait_s:
            return
        time.sleep(wait_s)


def try_throttle(cost: int = 1) -> bool:
    """Like throttle, but never waits: True when the call fits in the window now (its
    slots are taken), False when the window is full. For user-facing lookups (issue
    #220) that must not hold a request thread or crowd out ingest."""
    return _admit(max(1, int(cost))) == 0.0


def _api_key_params() -> dict:
    key = (os.getenv("OPENDOTA_API_KEY") or "").strip()
    return {"api_key": key} if key else {}


def get(
    url: str,
    *,
    timeout: float = 30,
    extra_headers: dict | None = None,
    extra_params: dict | None = None,
) -> requests.Response:
    """GET with throttle, api_key query param, and default JSON-friendly headers."""
    throttle()
    headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
    params = {**_api_key_params(), **(extra_params or {})}
    return requests.get(url, params=params, headers=headers, timeout=timeout)


def get_json_once(url: str, *, timeout: float = 6, label: str = "") -> dict | list | None:
    """One GET without throttling or retries, for a caller that already took its slot
    with try_throttle. Returns the decoded JSON, or None on any failure (recorded)."""
    tag_label = label or url
    try:
        res = requests.get(url, params=_api_key_params(), headers=DEFAULT_HEADERS, timeout=timeout)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.warning("get_json_once %s network error (%s)", tag_label, e.__class__.__name__)
        _record("network", tag_label)
        return None
    if res.status_code != 200:
        logger.warning("get_json_once %s HTTP %d", tag_label, res.status_code)
        if res.status_code != 404:
            kind = "rate_limited" if res.status_code == 429 else "server_error" if res.status_code >= 500 else "client_error"
            _record(kind, tag_label, res.status_code)
        return None
    _record("ok")
    try:
        return res.json()
    except Exception as e:
        logger.warning("get_json_once non-JSON %s: %s", tag_label, e)
        return None


def get_json(
    url: str,
    *,
    retries: int = 5,
    base_backoff: float = 10.0,
    timeout: float = 30,
    label: str = "",
) -> dict | list | None:
    """GET + parse JSON with exponential back-off + jitter on 429/5xx.

    Returns the decoded JSON value (dict or list) or None after all retries
    are exhausted or on a non-retryable client error.
    """
    tag_label = label or url
    for attempt in range(retries):
        try:
            res = get(url, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            wait = base_backoff * (2 ** attempt) + random.uniform(0, 3)
            logger.warning("get_json %s network error (%s), retry in %.1fs", tag_label, e.__class__.__name__, wait)
            _record("network", tag_label)
            time.sleep(wait)
            continue
        if res.status_code == 200:
            _record("ok")
            try:
                return res.json()
            except Exception as e:
                logger.warning("get_json non-JSON %s: %s", tag_label, e)
                return None
        if res.status_code == 429 or res.status_code >= 500:
            wait = base_backoff * (2 ** attempt) + random.uniform(0, 3)
            if res.status_code == 429:
                logger.warning("get_json rate limited %s HTTP %d, retry in %.1fs", tag_label, res.status_code, wait)
                _record("rate_limited", tag_label, res.status_code)
            else:
                logger.error("get_json %s HTTP %d, retry in %.1fs", tag_label, res.status_code, wait)
                _record("server_error", tag_label, res.status_code)
            time.sleep(wait)
            continue
        # 4xx (except 429) — no point retrying
        logger.warning("get_json %s HTTP %d — not retrying", tag_label, res.status_code)
        if res.status_code != 404:  # 404 is an answer (no such match), not a problem
            _record("client_error", tag_label, res.status_code)
        return None
    logger.error("get_json %s gave up after %d retries", tag_label, retries)
    _record("gave_up", tag_label)
    return None


def post_json(
    url: str,
    *,
    timeout: float = 30,
    label: str = "",
    cost: int = 1,
) -> dict | None:
    """POST with throttle, api_key query param and default headers; returns the decoded
    JSON object (``{}`` for an empty/non-object 2xx body) or None on any failure.

    No retries — callers (parse requests) re-check on the next poll cycle anyway.
    """
    tag_label = label or url
    throttle(cost=cost)
    try:
        res = requests.post(url, params=_api_key_params(), headers=DEFAULT_HEADERS, timeout=timeout)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.warning("post_json %s network error (%s)", tag_label, e.__class__.__name__)
        _record("network", tag_label)
        return None
    if not 200 <= res.status_code < 300:
        logger.warning("post_json %s HTTP %d", tag_label, res.status_code)
        kind = "rate_limited" if res.status_code == 429 else "server_error" if res.status_code >= 500 else "client_error"
        _record(kind, tag_label, res.status_code)
        return None
    _record("ok")
    try:
        data = res.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_json_object(res: requests.Response, *, context: str = "") -> dict | None:
    """Decode JSON object body; log and return None on empty/HTML/error pages (no exception)."""
    raw = (res.text or "").strip()
    if not raw:
        logger.warning("OpenDota empty body %s status=%d", context, res.status_code)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:200].replace("\n", " ")
        logger.warning("OpenDota non-JSON %s status=%d: %s snippet=%r", context, res.status_code, e, snippet)
        return None
    if isinstance(data, dict):
        return data
    logger.warning("OpenDota expected JSON object, got %s %s status=%d", type(data).__name__, context, res.status_code)
    return None
