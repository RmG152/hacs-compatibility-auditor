"""GitHub API client with rate limiting, caching and retry support."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    DEFAULT_GITHUB_RETRIES,
    DEFAULT_GITHUB_TIMEOUT,
    GITHUB_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class GitHubIssue:
    """Represents a GitHub issue relevant to compatibility."""

    title: str
    url: str
    state: str
    labels: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    priority: int = 0  # Higher = more relevant


@dataclass
class GitHubRelease:
    """Represents a GitHub release."""

    tag_name: str
    name: str
    published_at: str
    prerelease: bool
    html_url: str
    body: str = ""


@dataclass
class GitHubManifest:
    """Represents a HACS manifest.json from a repository."""

    name: str = ""
    version: str = ""
    homeassistant: str = ""  # Version requirement, e.g., "2024.1.0"
    requirements: list[str] = field(default_factory=list)
    zip_release: bool = False
    filename: str = ""


class GitHubClient:
    """Async GitHub API client with rate limit handling and caching."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | None = None,
        timeout: int = DEFAULT_GITHUB_TIMEOUT,
        retries: int = DEFAULT_GITHUB_RETRIES,
    ) -> None:
        """Initialize the GitHub client."""
        self._session = session
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._retries = retries
        self._rate_limit_remaining: int = 60
        self._rate_limit_reset: float = 0
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl: float = 43200  # 12 hours in seconds

    def _get_headers(self) -> dict[str, str]:
        """Get request headers including auth if token is available."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    async def close(self) -> None:
        """Close the client (session is managed externally, this is a no-op)."""
        pass

    async def validate_token(self) -> bool:
        """Validate the GitHub token by making a test request."""
        if not self._token:
            return True
        try:
            async with self._session.get(
                f"{GITHUB_API_BASE}/user",
                headers=self._get_headers(),
                timeout=self._timeout,
            ) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _is_cache_valid(self, key: str) -> bool:
        """Check if a cached entry is still valid."""
        if key not in self._cache:
            return False
        cached_time, _ = self._cache[key]
        return (time.time() - cached_time) < self._cache_ttl

    def _get_cached(self, key: str) -> Any | None:
        """Get a cached value if valid."""
        if self._is_cache_valid(key):
            _, data = self._cache[key]
            return data
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        """Store data in cache."""
        self._cache[key] = (time.time(), data)

    def clear_cache(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()

    async def _request(self, url: str) -> dict[str, Any] | list[Any] | None:
        """Make a rate-limit-aware request with retries and backoff."""
        cache_key = url
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        last_error: Exception | None = None

        for attempt in range(self._retries):
            # Check rate limits
            if self._rate_limit_remaining <= 5 and self._rate_limit_reset > time.time():
                wait_time = self._rate_limit_reset - time.time() + 1
                _LOGGER.warning(
                    "GitHub rate limit approaching. Waiting %.0f seconds.", wait_time
                )
                await asyncio.sleep(min(wait_time, 60))

            try:
                async with self._session.get(
                    url,
                    headers=self._get_headers(),
                    timeout=self._timeout,
                ) as resp:
                    # Update rate limit info
                    remaining = resp.headers.get("X-RateLimit-Remaining")
                    reset = resp.headers.get("X-RateLimit-Reset")
                    if remaining is not None:
                        self._rate_limit_remaining = int(remaining)
                    if reset is not None:
                        self._rate_limit_reset = float(reset)

                    if resp.status == 200:
                        data = await resp.json()
                        self._set_cache(cache_key, data)
                        return data

                    if resp.status == 403:
                        # Rate limited
                        if self._rate_limit_reset > time.time():
                            wait_time = self._rate_limit_reset - time.time() + 1
                            _LOGGER.warning(
                                "GitHub rate limited. Waiting %.0f seconds (attempt %d/%d).",
                                wait_time,
                                attempt + 1,
                                self._retries,
                            )
                            await asyncio.sleep(min(wait_time, 60))
                            continue
                        _LOGGER.error("GitHub API access forbidden (403).")
                        return None

                    if resp.status == 404:
                        _LOGGER.debug("GitHub resource not found: %s", url)
                        return None

                    if resp.status >= 500:
                        _LOGGER.warning(
                            "GitHub server error %d (attempt %d/%d): %s",
                            resp.status,
                            attempt + 1,
                            self._retries,
                            url,
                        )
                        await asyncio.sleep(2 ** attempt)
                        continue

                    _LOGGER.error(
                        "Unexpected GitHub API status %d for %s",
                        resp.status,
                        url,
                    )
                    return None

            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError()
                _LOGGER.warning(
                    "GitHub request timeout (attempt %d/%d): %s",
                    attempt + 1,
                    self._retries,
                    url,
                )
                await asyncio.sleep(2 ** attempt)

            except aiohttp.ClientError as exc:
                last_error = exc
                _LOGGER.warning(
                    "GitHub request error (attempt %d/%d): %s - %s",
                    attempt + 1,
                    self._retries,
                    url,
                    exc,
                )
                await asyncio.sleep(2 ** attempt)

        _LOGGER.error(
            "All retries exhausted for %s. Last error: %s", url, last_error
        )
        return None

    async def get_releases(
        self, owner: str, repo: str, per_page: int = 10
    ) -> list[GitHubRelease]:
        """Get releases for a repository."""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases?per_page={per_page}"
        data = await self._request(url)

        if not data or not isinstance(data, list):
            return []

        releases = []
        for item in data[:per_page]:
            releases.append(
                GitHubRelease(
                    tag_name=item.get("tag_name", ""),
                    name=item.get("name", ""),
                    published_at=item.get("published_at", ""),
                    prerelease=item.get("prerelease", False),
                    html_url=item.get("html_url", ""),
                    body=item.get("body", ""),
                )
            )
        return releases

    async def get_tags(self, owner: str, repo: str, per_page: int = 10) -> list[str]:
        """Get tags for a repository."""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/tags?per_page={per_page}"
        data = await self._request(url)

        if not data or not isinstance(data, list):
            return []

        return [tag.get("name", "") for tag in data if tag.get("name")]

    async def get_manifest(self, owner: str, repo: str) -> GitHubManifest | None:
        """Get the HACS manifest.json from a repository."""
        # Try hacs.json first (HACS v2 format)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/hacs.json"
        data = await self._request(url)

        if data and isinstance(data, dict) and "content" in data:
            try:
                import base64
                import json

                content = base64.b64decode(data["content"]).decode("utf-8")
                manifest_data = json.loads(content)
                return GitHubManifest(
                    name=manifest_data.get("name", ""),
                    version=manifest_data.get("version", ""),
                    homeassistant=manifest_data.get("homeassistant", ""),
                    requirements=manifest_data.get("requirements", []),
                    zip_release=manifest_data.get("zip_release", False),
                    filename=manifest_data.get("filename", ""),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                _LOGGER.debug(
                    "Failed to parse hacs.json for %s/%s: %s", owner, repo, exc
                )

        # Fallback: try manifest.json (custom component format)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/custom_components/{repo}/manifest.json"
        data = await self._request(url)

        if data and isinstance(data, dict) and "content" in data:
            try:
                import base64
                import json

                content = base64.b64decode(data["content"]).decode("utf-8")
                manifest_data = json.loads(content)
                return GitHubManifest(
                    name=manifest_data.get("name", ""),
                    version=manifest_data.get("version", ""),
                    homeassistant=manifest_data.get("homeassistant", ""),
                    requirements=manifest_data.get("requirements", []),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                _LOGGER.debug(
                    "Failed to parse manifest.json for %s/%s: %s", owner, repo, exc
                )

        return None

    async def get_issues(
        self,
        owner: str,
        repo: str,
        labels: list[str] | None = None,
        keywords: list[str] | None = None,
        state: str = "open",
        per_page: int = 30,
        since: str | None = None,
    ) -> list[GitHubIssue]:
        """Search for issues related to compatibility in a repository."""
        all_issues: list[GitHubIssue] = []

        # First, search by labels if provided
        if labels:
            for label in labels[:5]:  # Limit to avoid too many API calls
                url = (
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues"
                    f"?state={state}&labels={label}&per_page={per_page}"
                )
                if since:
                    url += f"&since={since}"

                data = await self._request(url)
                if data and isinstance(data, list):
                    for item in data:
                        # Skip PRs
                        if "pull_request" in item:
                            continue
                        issue_labels = [
                            lbl.get("name", "") for lbl in item.get("labels", [])
                        ]
                        all_issues.append(
                            GitHubIssue(
                                title=item.get("title", ""),
                                url=item.get("html_url", ""),
                                state=item.get("state", ""),
                                labels=issue_labels,
                                created_at=item.get("created_at", ""),
                                updated_at=item.get("updated_at", ""),
                                body=item.get("body", "")[:500] if item.get("body") else "",
                                priority=self._calculate_issue_priority(
                                    issue_labels, label
                                ),
                            )
                        )

        # Also search using GitHub search API for keywords
        if keywords:
            for keyword in keywords[:3]:  # Limit keyword searches
                search_query = (
                    f"repo:{owner}/{repo} is:issue is:{state} {keyword}"
                )
                url = (
                    f"{GITHUB_API_BASE}/search/issues"
                    f"?q={search_query}&per_page={per_page}"
                )
                data = await self._request(url)
                if data and isinstance(data, dict) and "items" in data:
                    for item in data["items"]:
                        issue_labels = [
                            lbl.get("name", "")
                            for lbl in item.get("labels", [])
                        ]
                        # Check if already found
                        existing_urls = {i.url for i in all_issues}
                        if item.get("html_url", "") in existing_urls:
                            continue
                        all_issues.append(
                            GitHubIssue(
                                title=item.get("title", ""),
                                url=item.get("html_url", ""),
                                state=item.get("state", ""),
                                labels=issue_labels,
                                created_at=item.get("created_at", ""),
                                updated_at=item.get("updated_at", ""),
                                body=item.get("body", "")[:500] if item.get("body") else "",
                                priority=self._calculate_keyword_priority(
                                    issue_labels, keyword
                                ),
                            )
                        )

        # Sort by priority (highest first) and deduplicate
        seen_urls: set[str] = set()
        unique_issues: list[GitHubIssue] = []
        for issue in sorted(all_issues, key=lambda x: x.priority, reverse=True):
            if issue.url not in seen_urls:
                seen_urls.add(issue.url)
                unique_issues.append(issue)

        return unique_issues[:20]  # Limit to top 20 most relevant

    async def get_ha_releases(self, per_page: int = 5) -> list[GitHubRelease]:
        """Get Home Assistant core releases."""
        return await self.get_releases("home-assistant", "core", per_page)

    def _calculate_issue_priority(
        self, issue_labels: list[str], matched_label: str
    ) -> int:
        """Calculate priority score for a label-matched issue."""
        score = 5  # Base score for label match
        high_priority_labels = {
            "breaking-change": 20,
            "breaking": 15,
            "incompatible": 15,
            "deprecation": 10,
            "upgrade": 8,
            "compatibility": 8,
        }
        for label in issue_labels:
            label_lower = label.lower()
            if label_lower in high_priority_labels:
                score += high_priority_labels[label_lower]
        return score

    def _calculate_keyword_priority(
        self, issue_labels: list[str], matched_keyword: str
    ) -> int:
        """Calculate priority score for a keyword-matched issue."""
        score = 2  # Lower base score for keyword match
        keyword_boost = {
            "breaking change": 10,
            "incompatible": 8,
            "not compatible": 8,
            "deprecated": 6,
            "stopped working": 5,
            "no longer works": 5,
        }
        if matched_keyword.lower() in keyword_boost:
            score += keyword_boost[matched_keyword.lower()]

        # Also boost by labels
        high_priority_labels = {
            "breaking-change": 15,
            "breaking": 12,
            "incompatible": 12,
            "bug": 3,
        }
        for label in issue_labels:
            label_lower = label.lower()
            if label_lower in high_priority_labels:
                score += high_priority_labels[label_lower]
        return score
