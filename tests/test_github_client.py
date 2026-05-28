"""Unit tests for GitHub API client."""

import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock

from custom_components.hacs_compatibility_auditor.github_client import GitHubClient
import pytest

# --- Manifest Parsing Tests ---


class TestManifestParsing:
    """Tests for parsing hacs.json and manifest.json from GitHub API responses."""

    @pytest.mark.asyncio
    async def test_parse_hacs_json(self):
        """Test parsing a valid hacs.json file."""
        manifest_data = {
            "name": "Test Integration",
            "homeassistant": "2024.1.0",
            "version": "1.2.0",
            "requirements": ["requests>=2.0"],
        }
        encoded = base64.b64encode(json.dumps(manifest_data).encode()).decode()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"content": encoded})
        mock_response.headers = {
            "X-RateLimit-Remaining": "59",
            "X-RateLimit-Reset": "0",
        }
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        client = GitHubClient(session=mock_session, token=None)
        result = await client.get_manifest("test", "repo")

        assert result is not None
        assert result.name == "Test Integration"
        assert result.homeassistant == "2024.1.0"
        assert result.version == "1.2.0"

    @pytest.mark.asyncio
    async def test_manifest_not_found(self):
        """Test handling of 404 when manifest doesn't exist."""
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.headers = {
            "X-RateLimit-Remaining": "59",
            "X-RateLimit-Reset": "0",
        }
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        client = GitHubClient(session=mock_session, token=None)
        result = await client.get_manifest("test", "nonexistent")

        assert result is None


# --- Release Parsing Tests ---


class TestReleaseParsing:
    """Tests for parsing GitHub releases."""

    @pytest.mark.asyncio
    async def test_parse_releases(self):
        """Test parsing releases from GitHub API."""
        releases_data = [
            {
                "tag_name": "v1.2.0",
                "name": "Release 1.2.0",
                "published_at": "2024-05-01T00:00:00Z",
                "prerelease": False,
                "html_url": "https://github.com/test/repo/releases/tag/v1.2.0",
                "body": "Bug fixes",
            },
            {
                "tag_name": "v1.3.0-beta",
                "name": "1.3.0 Beta",
                "published_at": "2024-06-01T00:00:00Z",
                "prerelease": True,
                "html_url": "https://github.com/test/repo/releases/tag/v1.3.0-beta",
                "body": "Beta release",
            },
        ]

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=releases_data)
        mock_response.headers = {
            "X-RateLimit-Remaining": "58",
            "X-RateLimit-Reset": "0",
        }
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        client = GitHubClient(session=mock_session, token=None)
        releases = await client.get_releases("test", "repo")

        assert len(releases) == 2
        assert releases[0].tag_name == "v1.2.0"
        assert not releases[0].prerelease
        assert releases[1].prerelease is True


# --- Issue Parsing Tests ---


class TestIssueParsing:
    """Tests for parsing GitHub issues."""

    @pytest.mark.asyncio
    async def test_parse_issues_with_labels(self):
        """Test parsing issues returned by label search."""
        issues_data = [
            {
                "title": "Breaking change in HA 2024.7",
                "html_url": "https://github.com/test/repo/issues/10",
                "state": "open",
                "labels": [
                    {"name": "breaking-change"},
                    {"name": "home-assistant"},
                ],
                "pull_request": None,
                "created_at": "2024-05-01T00:00:00Z",
                "updated_at": "2024-05-02T00:00:00Z",
                "body": "This integration breaks after upgrading to HA 2024.7",
            },
        ]

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=issues_data)
        mock_response.headers = {
            "X-RateLimit-Remaining": "57",
            "X-RateLimit-Reset": "0",
        }
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        client = GitHubClient(session=mock_session, token=None)
        issues = await client.get_issues(
            "test",
            "repo",
            labels=["breaking-change"],
        )

        assert len(issues) >= 1
        assert "breaking-change" in issues[0].labels
        assert issues[0].priority > 0


# --- Cache Tests ---


class TestCaching:
    """Tests for caching behavior."""

    def test_cache_set_and_get(self):
        """Test that cache stores and retrieves data."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)
        client._cache_ttl = 3600  # 1 hour

        client._set_cache("test_key", {"data": "value"})
        result = client._get_cached("test_key")

        assert result == {"data": "value"}

    def test_cache_miss(self):
        """Test cache miss for non-existent key."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)

        result = client._get_cached("nonexistent_key")
        assert result is None

    def test_cache_expiry(self):
        """Test that expired cache entries are not returned."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)
        client._cache_ttl = 0  # Immediately expires

        client._set_cache("test_key", {"data": "value"})
        time.sleep(0.01)  # Ensure time passes
        result = client._get_cached("test_key")

        assert result is None

    def test_clear_cache(self):
        """Test that clear_cache removes all entries."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)

        client._set_cache("key1", "value1")
        client._set_cache("key2", "value2")
        client.clear_cache()

        assert client._get_cached("key1") is None
        assert client._get_cached("key2") is None


# --- Priority Calculation Tests ---


class TestPriorityCalculation:
    """Tests for issue priority scoring."""

    def test_label_priority_breaking_change(self):
        """Test that breaking-change label gets high priority."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)

        priority = client._calculate_issue_priority(["breaking-change", "bug"], "breaking-change")
        assert priority >= 20

    def test_keyword_priority_breaking(self):
        """Test that 'breaking change' keyword gets boosted priority."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)

        priority = client._calculate_keyword_priority(["bug"], "breaking change")
        assert priority >= 10

    def test_low_priority_issue(self):
        """Test that a regular issue gets low priority."""
        mock_session = MagicMock()
        client = GitHubClient(session=mock_session, token=None)

        priority = client._calculate_keyword_priority([], "feature request")
        assert priority < 5
