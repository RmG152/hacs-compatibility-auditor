"""Unit tests for RulesClient."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from custom_components.hacs_compatibility_auditor.rules_client import RulesClient


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    return MagicMock()


@pytest.fixture
def client(mock_session):
    """Create a RulesClient with default settings and pre-loaded rules."""
    c = RulesClient(session=mock_session, hass_version="2026.4.0")
    c._rules = {
        "whitelist": {
            "repositories": [
                {"full_name": "trusted/owner", "ha_version": "*"},
                {"full_name": "versioned/repo", "ha_version": ">=2026.1.0"},
                {"full_name": "old/repo", "ha_version": "<2026.5.0"},
            ]
        },
        "blacklist": {
            "repositories": [
                {"full_name": "bad/actor", "ha_version": "*"},
                {"full_name": "broken/package", "ha_version": ">=2026.1.0,<2026.6.0"},
            ]
        },
        "false_positives": {
            "issues": [
                {"full_name": "noisy/repo", "issue_number": 42},
                {"full_name": "noisy/repo", "issue_number": 99},
                {"full_name": "noisy/repo", "issue_number": 100},
                {"full_name": "another/repo", "issue_number": 5},
            ]
        },
        "label_overrides": {
            "overrides": [
                {"full_name": "custom/repo", "labels": {"upgrade": 12, "bug": 0}},
            ]
        },
        "keyword_overrides": {
            "overrides": [
                {"full_name": "custom/repo", "keywords": {"breaking change": 15, "deprecated": 0}},
            ]
        },
    }
    return c


# --- Basic state ---


class TestRulesClientState:
    """Tests for basic client properties."""

    def test_is_loaded_true(self, client):
        """Test is_loaded returns True when rules are set."""
        assert client.is_loaded is True

    def test_is_loaded_false(self, mock_session):
        """Test is_loaded returns False when no rules loaded."""
        c = RulesClient(session=mock_session)
        assert c.is_loaded is False

    def test_last_update_none(self, mock_session):
        """Test last_update is None when no update performed."""
        c = RulesClient(session=mock_session)
        assert c.last_update is None

    def test_last_update_after_set(self, client):
        """Test last_update returns the stored timestamp."""
        client._last_update = 12345.0
        assert client.last_update == 12345.0


# --- Whitelist ---


class TestWhitelist:
    """Tests for whitelist matching."""

    def test_whitelisted_wildcard(self, client):
        """Test repo with wildcard ha_version is whitelisted."""
        assert client.is_whitelisted("trusted/owner") is True

    def test_whitelisted_version_match(self, client):
        """Test repo matching current HA version is whitelisted."""
        assert client.is_whitelisted("versioned/repo") is True

    def test_whitelisted_version_no_match(self, client):
        """Test repo with non-matching HA version is not whitelisted."""
        c = RulesClient(session=MagicMock(), hass_version="2027.1.0")
        c._rules = {
            "whitelist": {
                "repositories": [
                    {"full_name": "old/repo", "ha_version": "<2026.5.0"},
                ]
            }
        }
        assert c.is_whitelisted("old/repo") is False

    def test_not_whitelisted(self, client):
        """Test repo not in whitelist."""
        assert client.is_whitelisted("unknown/repo") is False

    def test_whitelisted_no_hass_version(self, mock_session):
        """Test that without hass_version, all entries match."""
        c = RulesClient(session=mock_session)
        c._rules = {
            "whitelist": {
                "repositories": [
                    {"full_name": "any/repo", "ha_version": ">=2026.1.0"},
                ]
            }
        }
        assert c.is_whitelisted("any/repo") is True

    def test_whitelist_empty(self, mock_session):
        """Test that empty whitelist returns False."""
        c = RulesClient(session=mock_session)
        c._rules = {"whitelist": {"repositories": []}}
        assert c.is_whitelisted("anything/repo") is False


# --- Blacklist ---


class TestBlacklist:
    """Tests for blacklist matching."""

    def test_blacklisted_wildcard(self, client):
        """Test repo with wildcard ha_version is blacklisted."""
        assert client.is_blacklisted("bad/actor") is True

    def test_blacklisted_range_match(self, client):
        """Test repo matching HA version range is blacklisted."""
        assert client.is_blacklisted("broken/package") is True

    def test_blacklisted_range_no_match(self, client):
        """Test repo outside HA version range is not blacklisted."""
        c = RulesClient(session=MagicMock(), hass_version="2027.1.0")
        c._rules = {
            "blacklist": {
                "repositories": [
                    {"full_name": "broken/package", "ha_version": ">=2026.1.0,<2026.6.0"},
                ]
            }
        }
        assert c.is_blacklisted("broken/package") is False

    def test_not_blacklisted(self, client):
        """Test repo not in blacklist."""
        assert client.is_blacklisted("unknown/repo") is False

    def test_blacklist_empty(self, mock_session):
        """Test that empty blacklist returns False."""
        c = RulesClient(session=mock_session)
        c._rules = {"blacklist": {"repositories": []}}
        assert c.is_blacklisted("anything/repo") is False


# --- False Positives ---


class TestFalsePositives:
    """Tests for false positives query."""

    def test_false_positives_found(self, client):
        """Test getting false positives for a repo."""
        assert client.get_false_positives("noisy/repo") == {42, 99, 100}

    def test_false_positives_not_found(self, client):
        """Test getting false positives for repo not in list."""
        assert client.get_false_positives("unknown/repo") == set()

    def test_false_positives_empty(self, mock_session):
        """Test getting false positives with no rules loaded."""
        c = RulesClient(session=mock_session)
        assert c.get_false_positives("noisy/repo") == set()

    def test_false_positives_single_entry(self, client):
        """Test getting false positives for repo with single entry."""
        assert client.get_false_positives("another/repo") == {5}


# --- Label Overrides ---


class TestLabelOverrides:
    """Tests for label overrides query."""

    def test_label_overrides_found(self, client):
        """Test getting label overrides for a repo."""
        overrides = client.get_label_overrides("custom/repo")
        assert overrides == {"upgrade": 12, "bug": 0}

    def test_label_overrides_not_found(self, client):
        """Test getting label overrides for repo not in list."""
        assert client.get_label_overrides("unknown/repo") == {}

    def test_label_overrides_empty(self, mock_session):
        """Test getting label overrides with no rules loaded."""
        c = RulesClient(session=mock_session)
        assert c.get_label_overrides("any/repo") == {}


# --- Keyword Overrides ---


class TestKeywordOverrides:
    """Tests for keyword overrides query."""

    def test_keyword_overrides_found(self, client):
        """Test getting keyword overrides for a repo."""
        overrides = client.get_keyword_overrides("custom/repo")
        assert overrides == {"breaking change": 15, "deprecated": 0}

    def test_keyword_overrides_not_found(self, client):
        """Test getting keyword overrides for repo not in list."""
        assert client.get_keyword_overrides("unknown/repo") == {}

    def test_keyword_overrides_empty(self, mock_session):
        """Test getting keyword overrides with no rules loaded."""
        c = RulesClient(session=mock_session)
        assert c.get_keyword_overrides("any/repo") == {}


# --- Version Matching ---


class TestVersionMatching:
    """Tests for HA version matching in whitelist/blacklist."""

    def test_wildcard_matches(self):
        """Test that wildcard ha_version always matches."""
        client = RulesClient(session=MagicMock(), hass_version="2026.1.0")
        assert client._match_ha_version({"ha_version": "*"}) is True

    def test_no_hass_version_matches_all(self):
        """Test that when hass_version is None, all constraints match."""
        client = RulesClient(session=MagicMock())
        assert client._match_ha_version({"ha_version": ">=2026.1.0"}) is True

    def test_gt_constraint(self):
        """Test >= constraint matching."""
        client = RulesClient(session=MagicMock(), hass_version="2026.4.0")
        assert client._match_ha_version({"ha_version": ">=2026.1.0"}) is True
        assert client._match_ha_version({"ha_version": ">=2027.1.0"}) is False

    def test_lt_constraint(self):
        """Test < constraint matching."""
        client = RulesClient(session=MagicMock(), hass_version="2026.4.0")
        assert client._match_ha_version({"ha_version": "<2026.5.0"}) is True
        assert client._match_ha_version({"ha_version": "<2026.1.0"}) is False

    def test_range_constraint(self):
        """Test range constraint matching."""
        client = RulesClient(session=MagicMock(), hass_version="2026.4.0")
        assert client._match_ha_version({"ha_version": ">=2026.1.0,<2026.6.0"}) is True
        assert client._match_ha_version({"ha_version": ">=2027.1.0,<2028.0.0"}) is False

    def test_exact_version(self):
        """Test exact version matching (treated as >=)."""
        client = RulesClient(session=MagicMock(), hass_version="2026.4.0")
        assert client._match_ha_version({"ha_version": "2026.4.0"}) is True
        assert client._match_ha_version({"ha_version": "2026.5.0"}) is False


# --- async_update ---


class TestAsyncUpdate:
    """Tests for async_update method."""

    @staticmethod
    def _make_mock_response(status=200, json_data=None, text_data=None):
        """Create an AsyncMock response that works as an async context manager."""
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.text = AsyncMock(return_value=text_data)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    @pytest.mark.asyncio
    async def test_update_from_release(self, mock_session):
        """Test successful update from GitHub release."""
        release_json = {
            "assets": [
                {"name": "index.json", "browser_download_url": "https://example.com/index.json"},
                {"name": "whitelist.yaml", "browser_download_url": "https://example.com/whitelist.yaml"},
                {"name": "blacklist.yaml", "browser_download_url": "https://example.com/blacklist.yaml"},
                {"name": "false_positives.yaml", "browser_download_url": "https://example.com/false_positives.yaml"},
                {"name": "label_overrides.yaml", "browser_download_url": "https://example.com/label_overrides.yaml"},
                {
                    "name": "keyword_overrides.yaml",
                    "browser_download_url": "https://example.com/keyword_overrides.yaml",
                },
            ]
        }
        index_json_str = json.dumps({"checksum": "abc123", "updated": "2026-01-01"})
        whitelist_yaml = yaml.dump({"repositories": [{"full_name": "trusted/repo", "ha_version": "*"}]})
        blacklist_yaml = yaml.dump({"repositories": [{"full_name": "bad/repo", "ha_version": "*"}]})
        false_positives_yaml = yaml.dump({
            "issues": [
                {"full_name": "noisy/repo", "issue_number": 1},
                {"full_name": "noisy/repo", "issue_number": 2},
                {"full_name": "noisy/repo", "issue_number": 3},
            ]
        })
        label_overrides_yaml = yaml.dump({"overrides": [{"full_name": "custom/repo", "labels": {"bug": 10}}]})
        keyword_overrides_yaml = yaml.dump({"overrides": [{"full_name": "custom/repo", "keywords": {"breaking change": 20}}]})

        responses = {
            "releases/latest": self._make_mock_response(json_data=release_json),
            "index.json": self._make_mock_response(text_data=index_json_str),
            "whitelist.yaml": self._make_mock_response(text_data=whitelist_yaml),
            "blacklist.yaml": self._make_mock_response(text_data=blacklist_yaml),
            "false_positives.yaml": self._make_mock_response(text_data=false_positives_yaml),
            "label_overrides.yaml": self._make_mock_response(text_data=label_overrides_yaml),
            "keyword_overrides.yaml": self._make_mock_response(text_data=keyword_overrides_yaml),
        }

        def get_side_effect(url):
            for key, resp in responses.items():
                if key in url:
                    return resp
            return self._make_mock_response(status=404)

        mock_session.get = MagicMock(side_effect=get_side_effect)

        client = RulesClient(session=mock_session)
        assert client.is_loaded is False

        await client.async_update()

        assert client.is_loaded is True
        assert client.is_whitelisted("trusted/repo") is True
        assert client.is_blacklisted("bad/repo") is True
        assert client.get_false_positives("noisy/repo") == {1, 2, 3}
        assert client.get_label_overrides("custom/repo") == {"bug": 10}
        assert client.get_keyword_overrides("custom/repo") == {"breaking change": 20}

    @pytest.mark.asyncio
    async def test_update_failure_keeps_cache(self, mock_session):
        """Test that a failed update keeps the existing cache."""
        client = RulesClient(session=mock_session)
        client._rules = {"whitelist": {"repositories": [{"full_name": "cached/repo", "ha_version": "*"}]}}
        client._last_update = 100.0

        mock_session.get = MagicMock(return_value=self._make_mock_response(status=500))

        await client.async_update()

        # Cache should still be intact
        assert client.is_whitelisted("cached/repo") is True

    @pytest.mark.asyncio
    async def test_update_no_assets(self, mock_session):
        """Test that a release with no assets doesn't update."""
        release_json = {"assets": []}

        def get_side_effect(url):
            if "releases/latest" in url:
                return self._make_mock_response(json_data=release_json)
            return self._make_mock_response(status=404)

        mock_session.get = MagicMock(side_effect=get_side_effect)

        client = RulesClient(session=mock_session)
        await client.async_update()

        assert client.is_loaded is False

    @pytest.mark.asyncio
    async def test_update_unchanged_checksum(self, mock_session):
        """Test that unchanged checksum skips download."""
        release_json = {
            "assets": [
                {"name": "index.json", "browser_download_url": "https://example.com/index.json"},
            ]
        }
        index_json_str = json.dumps({"checksum": "same_checksum", "updated": "2026-01-01"})

        call_count = 0

        def get_side_effect(url):
            nonlocal call_count
            call_count += 1
            if "releases/latest" in url:
                return self._make_mock_response(json_data=release_json)
            if "index.json" in url:
                return self._make_mock_response(text_data=index_json_str)
            return self._make_mock_response(status=404)

        mock_session.get = MagicMock(side_effect=get_side_effect)

        client = RulesClient(session=mock_session)
        client._etag = "same_checksum"
        client._rules = {"whitelist": {"repositories": [{"full_name": "old/repo", "ha_version": "*"}]}}

        await client.async_update()

        # Should have only called releases/latest and index.json (no YAML downloads)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_update_missing_index_asset(self, mock_session):
        """Test that a release without index.json doesn't update."""
        release_json = {
            "assets": [
                {"name": "whitelist.yaml", "browser_download_url": "https://example.com/whitelist.yaml"},
            ]
        }

        def get_side_effect(url):
            if "releases/latest" in url:
                return self._make_mock_response(json_data=release_json)
            return self._make_mock_response(status=404)

        mock_session.get = MagicMock(side_effect=get_side_effect)

        client = RulesClient(session=mock_session)
        await client.async_update()

        assert client.is_loaded is False


# --- Version Utils Integration ---


class TestVersionUtilsIntegration:
    """Tests that RulesClient integrates correctly with version_utils."""

    def test_rules_client_uses_check_version_requirement(self):
        """Verify that _match_ha_version delegates correctly."""
        client = RulesClient(session=MagicMock(), hass_version="2026.4.0")
        assert client._match_ha_version({"ha_version": ">=2026.1.0,<2026.6.0"}) is True
        assert client._match_ha_version({"ha_version": ">=2026.1.0,<2026.3.0"}) is False
