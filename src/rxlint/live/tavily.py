"""Minimal Tavily Search and Extract client with call logging."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

TAVILY_URL = "https://api.tavily.com"


class TavilyUnavailable(RuntimeError):
    pass


@dataclass
class TavilyCall:
    endpoint: str
    request: dict[str, Any]
    ok: bool
    latency_ms: int
    results: int = 0
    error: str | None = None


@dataclass
class TavilyClient:
    api_key: str | None = field(default_factory=lambda: os.environ.get("TAVILY_API_KEY") or None)
    timeout_s: float = 20.0
    log: list[TavilyCall] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            self.log.append(TavilyCall(endpoint, body, False, 0, error="TAVILY_API_KEY not set"))
            raise TavilyUnavailable("TAVILY_API_KEY is not configured")
        t = time.perf_counter()
        try:
            r = httpx.post(f"{TAVILY_URL}/{endpoint}", json=body, timeout=self.timeout_s,
                           headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            self.log.append(TavilyCall(endpoint, body, False, int((time.perf_counter() - t) * 1000), error=f"{type(exc).__name__}: {str(exc)[:200]}"))
            raise TavilyUnavailable(f"{endpoint}: {type(exc).__name__}") from exc
        n = len(data.get("results", []) or [])
        self.log.append(TavilyCall(endpoint, body, True, int((time.perf_counter() - t) * 1000), results=n))
        return data

    def search(self, query: str, include_domains: list[str], max_results: int = 5, topic: str = "general",
               search_depth: str = "basic", time_range: str | None = None, exact_match: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query, "include_domains": include_domains, "max_results": max_results,
                                "topic": topic, "search_depth": search_depth, "include_answer": False,
                                "include_raw_content": False, "include_published_date": True}
        if time_range:
            body["time_range"] = time_range
        if exact_match:
            body["exact_match"] = True
        return self._post("search", body)

    def extract(self, urls: list[str], extract_depth: str = "advanced") -> dict[str, Any]:
        # Markdown keeps links apart from body text; advanced depth keeps the lot tables of recall notices.
        return self._post("extract", {"urls": urls, "extract_depth": extract_depth, "format": "markdown", "include_images": False})
