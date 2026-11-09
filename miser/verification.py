"""Evidence discovery. Search hits are candidates, never automatic proof."""

import os
import time
from urllib.parse import urlparse

from .client import post_json
from .ledger import now

DEFAULT_SEARCH_URL = "https://api.tavily.com/search"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def search_endpoint():
    """Resolve the search URL; plain HTTP is accepted only for a loopback test double."""
    url = os.getenv("TAVILY_API_URL") or DEFAULT_SEARCH_URL
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host:
        return url
    if parsed.scheme == "http" and host in LOOPBACK_HOSTS:
        return url
    raise ValueError(
        "TAVILY_API_URL must be an https URL (http is allowed only for loopback test doubles)")


class EvidenceSearch:
    def __init__(self, ledger, limit=3):
        self.ledger = ledger
        self.limit = limit
        self.attempts = 0

    def verify_claim(self, claim, version, domains):
        if not claim.strip() or len(claim) > 1000 or len(version) > 100:
            raise ValueError("Supply a short claim and applicable package version")
        if not domains or len(domains) > 5 or any(
            not d or "/" in d or ":" in d or " " in d for d in domains
        ):
            raise ValueError("Provide 1–5 official documentation hostnames, without https:// or paths")
        if self.attempts >= self.limit:
            raise ValueError("Search-attempt limit reached")
        key = os.getenv("TAVILY_API_KEY")
        if not key:
            raise ValueError("TAVILY_API_KEY is not configured; claim remains unverified")
        endpoint = search_endpoint()
        self.attempts += 1
        started = time.monotonic()
        try:
            response = post_json(endpoint, {
                "query": f"{claim} version {version}", "search_depth": "basic",
                "max_results": 3, "include_domains": domains,
                "include_answer": False, "include_raw_content": False,
            }, {"Authorization": "Bearer " + key}, timeout=30)
            # A malformed upstream payload is an error, never evidence. Validate it
            # inside the try so the ledger records the failed attempt either way.
            if not isinstance(response, dict):
                raise RuntimeError("Search service returned a non-object response")
            results = response.get("results")
            if results is None:
                results = []
            elif not isinstance(results, list):
                raise RuntimeError("Search service returned a malformed results field")
        except Exception:
            self.ledger.record("search", claim=claim, version=version, status="error",
                               elapsed_seconds=round(time.monotonic() - started, 3))
            raise
        candidates = []
        for result in results:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if not isinstance(url, str) or not url:
                continue
            host = (urlparse(url).hostname or "").lower()
            if urlparse(url).scheme != "https" or not any(
                host == d.lower() or host.endswith("." + d.lower()) for d in domains
            ):
                continue
            candidates.append({"url": url, "title": result.get("title", ""),
                               "excerpt": result.get("content", "")[:1800],
                               "published_at": result.get("published_date")})
        card = {"claim": claim, "applicable_version": version, "checked_at": now(),
                "verdict": "unverified", "freshness_score": None, "candidates": candidates,
                "invalidate_when": "Dependency version or cited documentation changes",
                "note": "Live retrieval alone does not establish support, version compatibility, or publication date. "
                        "Review candidates before relying on the claim. No invented confidence score."}
        self.ledger.record("search", claim=claim, version=version, status="candidates" if candidates else "no_evidence",
                           results=len(candidates), elapsed_seconds=round(time.monotonic() - started, 3),
                           api_usage=response.get("usage"))
        return card
