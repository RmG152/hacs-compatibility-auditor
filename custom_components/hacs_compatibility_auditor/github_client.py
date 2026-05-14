"""GitHub API client with rate limiting, caching and retry support."""

import asyncio
import base64
from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any

import aiohttp

from .const import DEFAULT_GITHUB_RETRIES, DEFAULT_GITHUB_TIMEOUT, GITHUB_API_BASE

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

    async def validate_token(self) -> bool:
        """Validate the GitHub token by making a test request."""
        if not self._token:
            _LOGGER.debug("No GitHub token configured, skipping validation")
            return True
        _LOGGER.debug("Validating GitHub token")
        try:
            async with self._session.get(
                f"{GITHUB_API_BASE}/user",
                headers=self._get_headers(),
                timeout=self._timeout,
            ) as resp:
                valid = resp.status == 200
                _LOGGER.debug("GitHub token validation result: %s", valid)
                return valid
        except (aiohttp.ClientError, TimeoutError) as exc:
            _LOGGER.warning("GitHub token validation failed: %s", exc)
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
            _LOGGER.debug("Cache HIT for key: %s", key)
            return data
        _LOGGER.debug("Cache MISS for key: %s", key)
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        """Store data in cache."""
        self._cache[key] = (time.time(), data)
        _LOGGER.debug("Cached response for key: %s (cache size: %d)", key, len(self._cache))

    def clear_cache(self) -> None:
        """Clear the entire cache."""
        _LOGGER.debug("Clearing cache (%d entries)", len(self._cache))
        self._cache.clear()

    def update_cache_ttl(self, ttl_seconds: float) -> None:
        """Update the cache TTL."""
        self._cache_ttl = ttl_seconds

    async def _request(self, url: str) -> dict[str, Any] | list[Any] | None:
        """Make a rate-limit-aware request with retries and backoff."""
        cache_key = url
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        _LOGGER.debug(
            "GitHub API request: %s (rate_limit_remaining=%d)",
            url,
            self._rate_limit_remaining,
        )

        last_error: Exception | None = None

        for attempt in range(self._retries):
            # Check rate limits
            if self._rate_limit_remaining <= 5 and self._rate_limit_reset > time.time():
                wait_time = self._rate_limit_reset - time.time() + 1
                _LOGGER.warning("GitHub rate limit approaching. Waiting %.0f seconds", wait_time)
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

                    _LOGGER.debug(
                        "GitHub API response: %s -> status=%d, rate_limit_remaining=%s",
                        url,
                        resp.status,
                        remaining,
                    )

                    if resp.status == 200:
                        data = await resp.json()
                        self._set_cache(cache_key, data)
                        return data

                    if resp.status == 403:
                        # Rate limited
                        if self._rate_limit_reset > time.time():
                            wait_time = self._rate_limit_reset - time.time() + 1
                            _LOGGER.warning(
                                "GitHub rate limited. Waiting %.0f seconds (attempt %d/%d)",
                                wait_time,
                                attempt + 1,
                                self._retries,
                            )
                            await asyncio.sleep(min(wait_time, 60))
                            continue
                        _LOGGER.error("GitHub API access forbidden (403)")
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
                        await asyncio.sleep(2**attempt)
                        continue

                    _LOGGER.error(
                        "Unexpected GitHub API status %d for %s",
                        resp.status,
                        url,
                    )
                    return None

            except TimeoutError:
                last_error = TimeoutError()
                _LOGGER.warning(
                    "GitHub request timeout (attempt %d/%d): %s",
                    attempt + 1,
                    self._retries,
                    url,
                )
                await asyncio.sleep(2**attempt)

            except aiohttp.ClientError as exc:
                last_error = exc
                _LOGGER.warning(
                    "GitHub request error (attempt %d/%d): %s - %s",
                    attempt + 1,
                    self._retries,
                    url,
                    exc,
                )
                await asyncio.sleep(2**attempt)

        _LOGGER.error("All retries exhausted for %s. Last error: %s", url, last_error)
        return None

    async def get_releases(self, owner: str, repo: str, per_page: int = 10) -> list[GitHubRelease]:
        """Get releases for a repository."""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases?per_page={per_page}"
        _LOGGER.debug("Fetching releases for %s/%s (per_page=%d)", owner, repo, per_page)
        data = await self._request(url)

        if not data or not isinstance(data, list):
            _LOGGER.debug("No releases found for %s/%s", owner, repo)
            return []

        releases = [
            GitHubRelease(
                tag_name=item.get("tag_name", ""),
                name=item.get("name", ""),
                published_at=item.get("published_at", ""),
                prerelease=item.get("prerelease", False),
                html_url=item.get("html_url", ""),
                body=item.get("body", ""),
            )
            for item in data[:per_page]
        ]
        _LOGGER.debug("Found %d releases for %s/%s", len(releases), owner, repo)
        return releases

    async def get_tags(self, owner: str, repo: str, per_page: int = 10) -> list[str]:
        """Get tags for a repository."""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/tags?per_page={per_page}"
        _LOGGER.debug("Fetching tags for %s/%s (per_page=%d)", owner, repo, per_page)
        data = await self._request(url)

        if not data or not isinstance(data, list):
            _LOGGER.debug("No tags found for %s/%s", owner, repo)
            return []

        tags = [tag.get("name", "") for tag in data if tag.get("name")]
        _LOGGER.debug("Found %d tags for %s/%s", len(tags), owner, repo)
        return tags

    async def get_manifest(self, owner: str, repo: str) -> GitHubManifest | None:
        """Get the HACS manifest.json from a repository."""
        _LOGGER.debug("Fetching manifest for %s/%s", owner, repo)

        # Try hacs.json first (HACS v2 format)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/hacs.json"
        _LOGGER.debug("Trying hacs.json: %s", url)
        data = await self._request(url)

        if data and isinstance(data, dict) and "content" in data:
            try:
                content = base64.b64decode(data["content"]).decode("utf-8")
                manifest_data = json.loads(content)
                manifest = GitHubManifest(
                    name=manifest_data.get("name", ""),
                    version=manifest_data.get("version", ""),
                    homeassistant=manifest_data.get("homeassistant", ""),
                    requirements=manifest_data.get("requirements", []),
                    zip_release=manifest_data.get("zip_release", False),
                    filename=manifest_data.get("filename", ""),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                _LOGGER.debug("Failed to parse hacs.json for %s/%s: %s", owner, repo, exc)
            else:
                _LOGGER.debug(
                    "Found hacs.json for %s/%s (name=%s, version=%s, ha_req=%s)",
                    owner,
                    repo,
                    manifest.name,
                    manifest.version,
                    manifest.homeassistant,
                )
                return manifest

        # Fallback: try manifest.json (custom component format)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/custom_components/{repo}/manifest.json"
        _LOGGER.debug("Trying manifest.json fallback: %s", url)
        data = await self._request(url)

        if data and isinstance(data, dict) and "content" in data:
            try:
                content = base64.b64decode(data["content"]).decode("utf-8")
                manifest_data = json.loads(content)
                manifest = GitHubManifest(
                    name=manifest_data.get("name", ""),
                    version=manifest_data.get("version", ""),
                    homeassistant=manifest_data.get("homeassistant", ""),
                    requirements=manifest_data.get("requirements", []),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                _LOGGER.debug("Failed to parse manifest.json for %s/%s: %s", owner, repo, exc)
            else:
                _LOGGER.debug(
                    "Found manifest.json for %s/%s (name=%s, version=%s, ha_req=%s)",
                    owner,
                    repo,
                    manifest.name,
                    manifest.version,
                    manifest.homeassistant,
                )
                return manifest

        _LOGGER.debug("No manifest found for %s/%s", owner, repo)
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
        _LOGGER.debug(
            "Fetching issues for %s/%s (labels=%s, keywords=%s, state=%s, since=%s)",
            owner,
            repo,
            labels,
            keywords,
            state,
            since,
        )
        all_issues: list[GitHubIssue] = []

        # First, search by labels if provided
        if labels:
            for label in labels[:5]:  # Limit to avoid too many API calls
                url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues?state={state}&labels={label}&per_page={per_page}"
                if since:
                    url += f"&since={since}"

                _LOGGER.debug("Searching issues by label '%s' for %s/%s", label, owner, repo)
                data = await self._request(url)
                if data and isinstance(data, list):
                    count = 0
                    for item in data:
                        # Skip PRs
                        if item.get("pull_request"):
                            continue
                        issue_labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
                        all_issues.append(
                            GitHubIssue(
                                title=item.get("title", ""),
                                url=item.get("html_url", ""),
                                state=item.get("state", ""),
                                labels=issue_labels,
                                created_at=item.get("created_at", ""),
                                updated_at=item.get("updated_at", ""),
                                body=item.get("body", "")[:500] if item.get("body") else "",
                                priority=self._calculate_issue_priority(issue_labels, label),
                            )
                        )
                        count += 1
                    _LOGGER.debug(
                        "Found %d issues for label '%s' in %s/%s",
                        count,
                        label,
                        owner,
                        repo,
                    )

        # Also search using GitHub search API for keywords
        if keywords:
            for keyword in keywords[:3]:  # Limit keyword searches
                search_query = f"repo:{owner}/{repo} is:issue is:{state} {keyword}"
                url = f"{GITHUB_API_BASE}/search/issues?q={search_query}&per_page={per_page}"
                _LOGGER.debug("Searching issues by keyword '%s' for %s/%s", keyword, owner, repo)
                data = await self._request(url)
                if data and isinstance(data, dict) and "items" in data:
                    count = 0
                    for item in data["items"]:
                        issue_labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
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
                                priority=self._calculate_keyword_priority(issue_labels, keyword),
                            )
                        )
                        count += 1
                    _LOGGER.debug(
                        "Found %d issues for keyword '%s' in %s/%s",
                        count,
                        keyword,
                        owner,
                        repo,
                    )

        # Sort by priority (highest first) and deduplicate
        seen_urls: set[str] = set()
        unique_issues: list[GitHubIssue] = []
        for issue in sorted(all_issues, key=lambda x: x.priority, reverse=True):
            if issue.url not in seen_urls:
                seen_urls.add(issue.url)
                unique_issues.append(issue)

        result = unique_issues[:20]  # Limit to top 20 most relevant
        _LOGGER.debug(
            "Total unique issues for %s/%s: %d (from %d raw)",
            owner,
            repo,
            len(result),
            len(all_issues),
        )
        return result

    async def get_ha_releases(self, per_page: int = 5) -> list[GitHubRelease]:
        """Get Home Assistant core releases."""
        _LOGGER.debug("Fetching Home Assistant core releases (per_page=%d)", per_page)
        releases = await self.get_releases("home-assistant", "core", per_page)
        _LOGGER.debug("Found %d HA core releases", len(releases))
        return releases

    def _calculate_issue_priority(self, issue_labels: list[str], matched_label: str) -> int:
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

    def _calculate_keyword_priority(self, issue_labels: list[str], matched_keyword: str) -> int:
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
