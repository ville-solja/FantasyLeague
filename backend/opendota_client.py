"""
OpenDota HTTP: one place for api_key + headers + a sliding-window RPM cap.

Free tier is ~60 req/min; default OPENDOTA_MAX_RPM=55 leaves headroom.
"""
from __future__ import annotations

import json
import os
import threading
import time

import requests

OPEN_DOTA_URL = "https://api.opendota.com/api"

DEFAULT_HEADERS = {
    "User-Agent": "FantasyLeague/1.0 (+https://github.com/)",
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


def throttle() -> None:
    """Block until another request fits under the per-minute cap (rolling 60s window)."""
    window = 60.0
    while True:
        wait_s = 0.0
        with _lock:
            now = time.time()
            cutoff = now - window
            while _req_times and _req_times[0] < cutoff:
                _req_times.pop(0)
            limit = _max_rpm()
            if len(_req_times) < limit:
                _req_times.append(now)
                return
            wait_s = _req_times[0] + window - now + 0.05
        time.sleep(max(wait_s, 0.05))


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


def parse_json_object(res: requests.Response, *, context: str = "") -> dict | None:
    """Decode JSON object body; log and return None on empty/HTML/error pages (no exception)."""
    raw = (res.text or "").strip()
    if not raw:
        print(f"[WARN] OpenDota empty body {context} status={res.status_code}")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:200].replace("\n", " ")
        print(f"[WARN] OpenDota non-JSON {context} status={res.status_code}: {e!s} snippet={snippet!r}")
        return None
    if isinstance(data, dict):
        return data
    print(f"[WARN] OpenDota expected JSON object, got {type(data).__name__} {context} status={res.status_code}")
    return None
