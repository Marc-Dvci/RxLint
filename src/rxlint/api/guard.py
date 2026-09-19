"""Spend guards for a public deployment: per-client rate limits, a daily budget, and a live-check cache."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_daily: dict[tuple[str, str], int] = defaultdict(int)

LIMITS = {  # action: (per client per hour, per day overall)
    "upload": (int(os.environ.get("RXLINT_UPLOADS_PER_HOUR", "12")), int(os.environ.get("RXLINT_UPLOADS_PER_DAY", "300"))),
    "live": (int(os.environ.get("RXLINT_LIVE_PER_HOUR", "10")), int(os.environ.get("RXLINT_LIVE_PER_DAY", "60"))),
    "explain": (int(os.environ.get("RXLINT_EXPLAIN_PER_HOUR", "60")), int(os.environ.get("RXLINT_EXPLAIN_PER_DAY", "2000"))),
    "drift": (3, 20),
}


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown"))[:64]


def check(request: Request, action: str) -> None:
    per_hour, per_day = LIMITS[action]
    now = time.time()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = (client_id(request), action)
    with _lock:
        q = _hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= per_hour:
            raise HTTPException(429, f"Rate limit: {per_hour} {action} requests per hour. Demo cases stay available.")
        if _daily[(day, action)] >= per_day:
            raise HTTPException(429, f"Daily {action} budget of this public demo is used up. Demo cases stay available.")
        q.append(now)
        _daily[(day, action)] += 1


class LiveCache:
    """Regulator results are reused for a short freshness window and always shown with their retrieval time."""

    def __init__(self, root: Path, ttl_s: int = 6 * 3600):
        self.root = root
        self.ttl = ttl_s

    def _path(self, key: dict[str, Any]) -> Path:
        h = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]
        return self.root / f"{h}.json"

    def get(self, key: dict[str, Any]) -> dict[str, Any] | None:
        p = self._path(key)
        if not p.exists() or time.time() - p.stat().st_mtime > self.ttl:
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return {**data, "cached": True}

    def put(self, key: dict[str, Any], value: dict[str, Any]) -> None:
        # Only a completed check is cached; an unavailable one is retried next time.
        if value.get("status") not in ("LIVE_REVIEW", "LIVE_CLEAR"):
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
