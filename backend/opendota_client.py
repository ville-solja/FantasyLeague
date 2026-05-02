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


def get_json(
    url: str,
    *,
    retries: int = 5,
    base_backoff: float = 10.0,
    label: str = "",
) -> dict | list | None:
    """GET + parse JSON with exponential back-off + jitter on 429/5xx.

    Returns the decoded JSON value (dict or list) or None after all retries
    are exhausted or on a non-retryable client error.
    """
    tag_label = label or url
    for attempt in range(retries):
        try:
            res = get(url, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            wait = base_backoff * (2 ** attempt) + random.uniform(0, 3)
            logger.warning("get_json %s network error (%s), retry in %.1fs", tag_label, e.__class__.__name__, wait)
            time.sleep(wait)
            continue
        if res.status_code == 200:
            try:
                return res.json()
            except Exception as e:
                logger.warning("get_json non-JSON %s: %s", tag_label, e)
                return None
        if res.status_code == 429 or res.status_code >= 500:
            wait = base_backoff * (2 ** attempt) + random.uniform(0, 3)
            if res.status_code == 429:
                logger.warning("get_json rate limited %s HTTP %d, retry in %.1fs", tag_label, res.status_code, wait)
            else:
                logger.error("get_json %s HTTP %d, retry in %.1fs", tag_label, res.status_code, wait)
            time.sleep(wait)
            continue
        # 4xx (except 429) — no point retrying
        logger.warning("get_json %s HTTP %d — not retrying", tag_label, res.status_code)
        return None
    logger.error("get_json %s gave up after %d retries", tag_label, retries)
    return None


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
