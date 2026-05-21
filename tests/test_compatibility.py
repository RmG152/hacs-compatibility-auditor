"""Unit tests for compatibility checking logic."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.hacs_compatibility_auditor.compatibility import (
    CompatibilityChecker,
    CompatibilityResult,
)
from custom_components.hacs_compatibility_auditor.const import (
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_WARNING,
)
from custom_components.hacs_compatibility_auditor.github_client import (
    GitHubClient,
    GitHubIssue,
    GitHubManifest,
    GitHubRelease,
)
from custom_components.hacs_compatibility_auditor.hacs_repository import HacsPackage
from custom_components.hacs_compatibility_auditor.rules_client import RulesClient


# --- Fixtures ---


@pytest.fixture
def mock_github_client():
    """Create a mock GitHub client."""
    client = AsyncMock(spec=GitHubClient)
    return client


@pytest.fixture
def checker(mock_github_client):
    """Create a CompatibilityChecker with a mock client."""
    return CompatibilityChecker(
        github_client=mock_github_client,
        issue_labels_priority=["breaking-change", "incompatible", "upgrade"],
        issue_keywords=["breaking change", "not compatible"],
        ignore_list=["ignored/repo"],
    )


@pytest.fixture
def sample_package():
    """Create a sample HACS package."""
    return HacsPackage(
        id="123",
        full_name="custom-cards/button-card",
        name="Button Card",
        category="plugin",
        installed_version="4.1.0",
        available_version="4.2.0",
        installed=True,
        owner="custom-cards",
        repo="button-card",
    )


@pytest.fixture
def incompatible_package():
    """Create a sample HACS package with incompatibility."""
    return HacsPackage(
        id="456",
        full_name="some-dev/broken-integration",
        name="Broken Integration",
        category="integration",
        installed_version="1.0.0",
        available_version="1.0.0",
        installed=True,
        owner="some-dev",
        repo="broken-integration",
    )


@pytest.fixture
def ignored_package():
    """Create a sample HACS package that should be ignored."""
    return HacsPackage(
        id="789",
        full_name="ignored/repo",
        name="Ignored Repo",
        category="theme",
        installed_version="2.0.0",
        available_version="2.0.0",
        installed=True,
        owner="ignored",
        repo="repo",
    )


@pytest.fixture
def mock_rules_client():
    """Create a mock RulesClient with pre-loaded test data."""
    client = MagicMock(spec=RulesClient)
    client.is_whitelisted.return_value = False
    client.is_blacklisted.return_value = False
    client.get_false_positives.return_value = set()
    client.get_label_overrides.return_value = {}
    client.get_keyword_overrides.return_value = {}
    return client


@pytest.fixture
def checker_with_rules(mock_github_client, mock_rules_client):
    """Create a CompatibilityChecker with a mock rules client."""
    return CompatibilityChecker(
        github_client=mock_github_client,
        issue_labels_priority=["breaking-change", "incompatible", "upgrade"],
        issue_keywords=["breaking change", "not compatible"],
        ignore_list=["ignored/repo"],
        rules_client=mock_rules_client,
    )


@pytest.fixture
def whitelisted_package():
    """Create a sample package that is whitelisted."""
    return HacsPackage(
        id="111",
        full_name="trusted/package",
        name="Trusted Package",
        category="integration",
        installed_version="1.0.0",
        installed=True,
        owner="trusted",
        repo="package",
    )


@pytest.fixture
def blacklisted_package():
    """Create a sample package that is blacklisted."""
    return HacsPackage(
        id="222",
        full_name="bad/package",
        name="Bad Package",
        category="integration",
        installed_version="1.0.0",
        installed=True,
        owner="bad",
        repo="package",
    )


# --- Version Requirement Tests ---


class TestVersionRequirements:
    """Tests for version requirement parsing and checking."""

    def test_simple_minimum_version_match(self):
        """Test that a version meeting minimum requirement passes."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0", "2024.1.0")

    def test_simple_minimum_version_fail(self):
        """Test that a version below minimum requirement fails."""
        assert not CompatibilityChecker._check_version_requirement("2023.12.0", "2024.1.0")

    def test_exact_version_match(self):
        """Test that exact version matches."""
        assert CompatibilityChecker._check_version_requirement("2024.1.0", "2024.1.0")

    def test_greater_than_operator(self):
        """Test >= operator."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0", ">=2024.1.0")

    def test_less_than_operator(self):
        """Test < operator."""
        assert not CompatibilityChecker._check_version_requirement("2024.6.0", "<2024.1.0")
        assert CompatibilityChecker._check_version_requirement("2023.12.0", "<2024.1.0")

    def test_range_constraint(self):
        """Test range constraint with comma separator."""
        assert CompatibilityChecker._check_version_requirement("2024.3.0", ">=2024.1.0,<2025.0.0")
        assert not CompatibilityChecker._check_version_requirement("2025.1.0", ">=2024.1.0,<2025.0.0")

    def test_empty_requirement(self):
        """Test that empty requirement always passes."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0", "")
        assert CompatibilityChecker._check_version_requirement("2024.6.0", None)

    def test_major_minor_format(self):
        """Test major.minor format (without patch)."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0", "2024.1")

    def test_beta_version(self):
        """Test handling of beta versions."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0b1", "2024.1.0")

    def test_dev_version(self):
        """Test handling of dev versions."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0dev0", "2024.1.0")

    def test_invalid_requirement_version(self):
        """Test that invalid requirement versions default to compatible."""
        assert CompatibilityChecker._check_version_requirement("2024.6.0", "not-a-version")

    def test_compatible_release_operator(self):
        """Test ~= (compatible release) operator."""
        assert CompatibilityChecker._check_version_requirement("2024.1.5", "~=2024.1.0")
        assert not CompatibilityChecker._check_version_requirement("2024.2.0", "~=2024.1.0")


# --- Breaking Keyword Detection Tests ---


class TestBreakingKeywords:
    """Tests for breaking change keyword detection."""

    def test_contains_breaking_change(self):
        """Test detection of 'breaking change' keyword."""
        assert CompatibilityChecker._contains_breaking_keywords("## Breaking Change\nThis feature has been removed.")

    def test_contains_deprecated(self):
        """Test detection of 'deprecated' keyword."""
        assert CompatibilityChecker._contains_breaking_keywords("Deprecated: use new_api instead.")

    def test_contains_incompatible(self):
        """Test detection of 'not compatible' keyword."""
        assert CompatibilityChecker._contains_breaking_keywords("This version is not compatible with HA 2024.x")

    def test_no_breaking_keywords(self):
        """Test that normal text doesn't trigger."""
        assert not CompatibilityChecker._contains_breaking_keywords("Bug fix and performance improvements.")

    def test_empty_text(self):
        """Test that empty text returns False."""
        assert not CompatibilityChecker._contains_breaking_keywords("")
        assert not CompatibilityChecker._contains_breaking_keywords(None)

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert CompatibilityChecker._contains_breaking_keywords("BREAKING CHANGE: something changed")

    def test_contains_end_of_life(self):
        """Test detection of 'end of life' keyword."""
        assert CompatibilityChecker._contains_breaking_keywords("END OF LIFE Latest")
        assert CompatibilityChecker._contains_breaking_keywords("This project is end of life")

    def test_contains_use_this_instead(self):
        """Test detection of 'use this instead' keyword."""
        assert CompatibilityChecker._contains_breaking_keywords("USE THIS INSTEAD")
        assert CompatibilityChecker._contains_breaking_keywords("use this instead of")

    def test_contains_merged_into(self):
        """Test detection of 'merged into' keyword."""
        assert CompatibilityChecker._contains_breaking_keywords("merged into weather-heatmap")


# --- Deprecation Keyword Detection Tests ---


class TestDeprecationKeywords:
    """Tests for deprecation keyword detection."""

    def test_contains_deprecated(self):
        """Test detection of 'deprecated' keyword."""
        assert CompatibilityChecker._contains_deprecation_keywords("This card has been deprecated")
        assert CompatibilityChecker._contains_deprecation_keywords("deprecated card")

    def test_contains_end_of_life(self):
        """Test detection of 'end of life' keyword."""
        assert CompatibilityChecker._contains_deprecation_keywords("END OF LIFE Latest")
        assert CompatibilityChecker._contains_deprecation_keywords("This project is end of life")

    def test_contains_use_this_instead(self):
        """Test detection of 'use this instead' keyword."""
        assert CompatibilityChecker._contains_deprecation_keywords("USE THIS INSTEAD")
        assert CompatibilityChecker._contains_deprecation_keywords("use this instead of")

    def test_contains_merged_into(self):
        """Test detection of 'merged into' keyword."""
        assert CompatibilityChecker._contains_deprecation_keywords("merged into weather-heatmap")

    def test_contains_migrated_to(self):
        """Test detection of 'migrated to' keyword."""
        assert CompatibilityChecker._contains_deprecation_keywords("migrated to new-card")

    def test_contains_has_been_deprecated(self):
        """Test detection of 'has been deprecated' phrase."""
        assert CompatibilityChecker._contains_deprecation_keywords("This card has been deprecated")

    def test_contains_please_use(self):
        """Test detection of 'please use' keyword."""
        assert CompatibilityChecker._contains_deprecation_keywords("please use new-card instead")

    def test_no_deprecation_keywords(self):
        """Test that normal text doesn't trigger."""
        assert not CompatibilityChecker._contains_deprecation_keywords("Bug fix and improvements")

    def test_empty_text(self):
        """Test that empty text returns False."""
        assert not CompatibilityChecker._contains_deprecation_keywords("")
        assert not CompatibilityChecker._contains_deprecation_keywords(None)

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert CompatibilityChecker._contains_deprecation_keywords("END OF LIFE")


# --- Compatibility Check Tests ---


class TestCompatibilityCheck:
    """Tests for the full compatibility check logic."""

    @pytest.mark.asyncio
    async def test_compatible_package(self, checker, mock_github_client, sample_package):
        """Test a fully compatible package."""
        mock_github_client.get_manifest.return_value = GitHubManifest(
            name="Button Card",
            version="4.2.0",
            homeassistant="2024.1.0",
        )
        mock_github_client.get_releases.return_value = [
            GitHubRelease(
                tag_name="v4.2.0",
                name="4.2.0",
                published_at="2024-05-01T00:00:00Z",
                prerelease=False,
                html_url="https://github.com/custom-cards/button-card/releases/tag/v4.2.0",
                body="Bug fixes and improvements",
            )
        ]
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(sample_package, ha_current="2024.6.0", ha_next="2024.7.0")

        assert result.status == STATUS_COMPATIBLE
        assert result.compatible_with_current is True
        assert result.compatible_with_next is True
        assert result.latest_version == "4.2.0"
        assert len(result.issues_relevant) == 0

    @pytest.mark.asyncio
    async def test_incompatible_package_manifest(self, checker, mock_github_client, incompatible_package):
        """Test a package with incompatible manifest requirement."""
        mock_github_client.get_manifest.return_value = GitHubManifest(
            name="Broken Integration",
            version="1.0.0",
            homeassistant=">=2025.1.0",  # Requires future version
        )
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(incompatible_package, ha_current="2024.6.0", ha_next="2024.7.0")

        assert result.status == STATUS_INCOMPATIBLE
        assert result.compatible_with_current is False
        assert result.compatible_with_next is False

    @pytest.mark.asyncio
    async def test_warning_package_with_issues(self, checker, mock_github_client, sample_package):
        """Test a package with warning-level issues."""
        mock_github_client.get_manifest.return_value = GitHubManifest(
            name="Button Card",
            version="4.2.0",
            homeassistant="",
        )
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = [
            GitHubIssue(
                title="Upgrade issues with HA 2024.7",
                url="https://github.com/custom-cards/button-card/issues/123",
                state="open",
                labels=["upgrade"],
                priority=8,
            )
        ]

        result = await checker.check_package(sample_package, ha_current="2024.6.0", ha_next="2024.7.0")

        assert result.status == STATUS_WARNING
        assert len(result.issues_relevant) > 0

    @pytest.mark.asyncio
    async def test_incompatible_package_with_breaking_issue(self, checker, mock_github_client, incompatible_package):
        """Test a package with a breaking-change issue."""
        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = [
            GitHubIssue(
                title="Breaking change: API removed in HA 2024.7",
                url="https://github.com/some-dev/broken-integration/issues/1",
                state="open",
                labels=["breaking-change"],
                priority=20,
            )
        ]

        result = await checker.check_package(incompatible_package, ha_current="2024.6.0", ha_next="2024.7.0")

        assert result.status == STATUS_INCOMPATIBLE

    @pytest.mark.asyncio
    async def test_ignored_package(self, checker, mock_github_client, ignored_package):
        """Test that ignored packages are handled correctly."""
        result = await checker.check_package(ignored_package, ha_current="2024.6.0")

        assert result.status == "ignored"
        assert result.compatible_with_current is True
        assert result.compatible_with_next is True
        # Should not have called GitHub
        mock_github_client.get_manifest.assert_not_called()

    @pytest.mark.asyncio
    async def test_package_with_no_manifest(self, checker, mock_github_client, sample_package):
        """Test a package with no manifest or releases."""
        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(sample_package, ha_current="2024.6.0")

        # Without manifest or issues, should be compatible (no evidence of incompatibility)
        assert result.status == STATUS_COMPATIBLE
        assert result.compatible_with_current is True

    @pytest.mark.asyncio
    async def test_package_with_breaking_release_notes(self, checker, mock_github_client, sample_package):
        """Test a package with breaking changes in release notes."""
        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = [
            GitHubRelease(
                tag_name="v5.0.0",
                name="5.0.0",
                published_at="2024-06-01T00:00:00Z",
                prerelease=False,
                html_url="https://github.com/example/repo/releases/tag/v5.0.0",
                body="## Breaking Change\nRemoved old API. Not compatible with HA < 2024.7.",
            )
        ]
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(sample_package, ha_current="2024.6.0", ha_next="2024.7.0")

        assert result.status == STATUS_WARNING

    @pytest.mark.asyncio
    async def test_check_all_packages(self, checker, mock_github_client, sample_package, incompatible_package):
        """Test checking all packages at once."""
        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = []

        results = await checker.check_all_packages(
            [sample_package, incompatible_package],
            ha_current="2024.6.0",
        )

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_package_with_deprecated_release_notes(self, checker, mock_github_client, sample_package):
        """Test a package with deprecation indicators in release notes.

        This tests the case like sxdjt/ha-windspeed-heatmap that says
        'END OF LIFE', 'This card has been deprecated', 'USE THIS INSTEAD'.
        """
        mock_github_client.get_manifest.return_value = GitHubManifest(
            name="Windspeed Heatmap",
            version="1.0.0",
            homeassistant="2024.1.0",
        )
        mock_github_client.get_releases.return_value = [
            GitHubRelease(
                tag_name="v1.0.0",
                name="1.0.0",
                published_at="2024-06-01T00:00:00Z",
                prerelease=False,
                html_url="https://github.com/sxdjt/ha-windspeed-heatmap/releases/tag/v1.0.0",
                body="""END OF LIFE Latest
                IMPORTANT!! This card has been deprecated.
                The temperature and windspeed heatmap cards have always shared most of their code,
                with just small differences between them. Rather than keep maintaining two nearly-identical
                cards, I've merged them into one: weather-heatmap. Same functionality, less clutter
                in your dashboard setup.
                USE THIS INSTEAD""",
            )
        ]
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(sample_package, ha_current="2024.6.0", ha_next="2024.7.0")

        # Deprecated packages should be marked as INCOMPATIBLE
        assert result.status == STATUS_INCOMPATIBLE
        assert result.compatible_with_current is False
        assert result.compatible_with_next is False
        assert "deprecated" in result.reason.lower() or "end of life" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_deprecated_release_marks_incompatible_not_warning(self, checker, mock_github_client, sample_package):
        """Test that deprecation marks a package as incompatible, not just warning."""
        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = [
            GitHubRelease(
                tag_name="v2.0.0",
                name="2.0.0",
                published_at="2024-06-01T00:00:00Z",
                prerelease=False,
                html_url="https://github.com/example/repo/releases/tag/v2.0.0",
                body="This project has been deprecated. Please use new-project instead.",
            )
        ]
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(sample_package, ha_current="2024.6.0")

        # Deprecation should trigger INCOMPATIBLE, not WARNING
        assert result.status == STATUS_INCOMPATIBLE
        assert result.compatible_with_current is False


# --- Result Serialization Tests ---


class TestCompatibilityResult:
    """Tests for CompatibilityResult serialization."""

    def test_to_dict(self):
        """Test that to_dict produces expected keys."""
        pkg = HacsPackage(
            id="test",
            full_name="test/repo",
            name="Test",
            category="integration",
            installed_version="1.0.0",
            installed=True,
            owner="test",
            repo="repo",
        )
        result = CompatibilityResult(
            package=pkg,
            compatible_with_current=True,
            compatible_with_next=True,
            status=STATUS_COMPATIBLE,
            latest_version="1.1.0",
        )
        d = result.to_dict()

        assert d["name"] == "Test"
        assert d["repository"] == "test/repo"
        assert d["compatible_with_current"] is True
        assert d["compatible_with_next"] is True
        assert d["status"] == STATUS_COMPATIBLE
        assert d["latest_version"] == "1.1.0"
        assert "issues_relevant" in d
        assert "last_checked" in d


# --- Should Ignore Tests ---


class TestShouldIgnore:
    """Tests for the ignore list feature."""

    def test_ignore_by_full_name(self, checker):
        """Test ignoring by full_name."""
        pkg = HacsPackage(
            id="1",
            full_name="ignored/repo",
            name="Ignored",
            category="theme",
            installed=True,
            owner="ignored",
            repo="repo",
        )
        assert checker.should_ignore(pkg)

    def test_not_ignored(self, checker):
        """Test a package that is not ignored."""
        pkg = HacsPackage(
            id="2",
            full_name="not-ignored/repo",
            name="Not Ignored",
            category="integration",
            installed=True,
            owner="not-ignored",
            repo="repo",
        )
        assert not checker.should_ignore(pkg)


# --- Rules Integration Tests ---


class TestRulesIntegration:
    """Tests for RulesClient integration in CompatibilityChecker."""

    @pytest.mark.asyncio
    async def test_check_package_whitelisted(self, checker_with_rules, mock_github_client, whitelisted_package):
        """Test that a whitelisted package is marked compatible without API calls."""
        checker_with_rules._rules.is_whitelisted.return_value = True

        result = await checker_with_rules.check_package(whitelisted_package, ha_current="2026.4.0")

        assert result.status == STATUS_COMPATIBLE
        assert result.compatible_with_current is True
        assert result.compatible_with_next is True
        assert result.data.get("ruled_by") == "whitelist"
        mock_github_client.get_manifest.assert_not_called()
        mock_github_client.get_releases.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_package_blacklisted(self, checker_with_rules, mock_github_client, blacklisted_package):
        """Test that a blacklisted package is marked incompatible without API calls."""
        checker_with_rules._rules.is_blacklisted.return_value = True

        result = await checker_with_rules.check_package(blacklisted_package, ha_current="2026.4.0")

        assert result.status == STATUS_INCOMPATIBLE
        assert result.compatible_with_current is False
        assert result.compatible_with_next is False
        assert result.data.get("ruled_by") == "blacklist"
        mock_github_client.get_manifest.assert_not_called()
        mock_github_client.get_releases.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitelist_takes_priority_over_github(
        self, checker_with_rules, mock_github_client, whitelisted_package
    ):
        """Test that whitelist takes priority and no API calls are made."""
        checker_with_rules._rules.is_whitelisted.return_value = True

        await checker_with_rules.check_package(whitelisted_package, ha_current="2026.4.0")

        mock_github_client.get_manifest.assert_not_called()
        mock_github_client.get_releases.assert_not_called()
        mock_github_client.get_issues.assert_not_called()

    @pytest.mark.asyncio
    async def test_blacklist_takes_priority_over_github(
        self, checker_with_rules, mock_github_client, blacklisted_package
    ):
        """Test that blacklist takes priority and no API calls are made."""
        checker_with_rules._rules.is_blacklisted.return_value = True

        await checker_with_rules.check_package(blacklisted_package, ha_current="2026.4.0")

        mock_github_client.get_manifest.assert_not_called()
        mock_github_client.get_releases.assert_not_called()
        mock_github_client.get_issues.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignore_list_takes_priority_over_whitelist(self, checker_with_rules, mock_github_client):
        """Test that ignore list takes priority over whitelist."""
        pkg = HacsPackage(
            id="333",
            full_name="ignored/repo",
            name="Ignored Repo",
            category="theme",
            installed=True,
            owner="ignored",
            repo="repo",
        )
        # Even if whitelisted, the ignore list should win
        checker_with_rules._rules.is_whitelisted.return_value = True

        result = await checker_with_rules.check_package(pkg, ha_current="2026.4.0")

        assert result.status == "ignored"
        mock_github_client.get_manifest.assert_not_called()

    @pytest.mark.asyncio
    async def test_false_positive_issues_filtered(self, checker_with_rules, mock_github_client, sample_package):
        """Test that false positive issues are excluded from results."""
        checker_with_rules._rules.get_false_positives.return_value = {123}

        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = [
            GitHubIssue(
                title="False positive issue",
                url="https://github.com/custom-cards/button-card/issues/123",
                state="open",
                labels=["bug"],
                number=123,
                priority=5,
            ),
            GitHubIssue(
                title="Real issue",
                url="https://github.com/custom-cards/button-card/issues/456",
                state="open",
                labels=["bug"],
                number=456,
                priority=8,
            ),
        ]

        result = await checker_with_rules.check_package(sample_package, ha_current="2026.4.0")

        # Only the real issue should appear
        issue_numbers = [int(i["url"].split("/")[-1]) for i in result.issues_relevant]
        assert 123 not in issue_numbers
        assert 456 in issue_numbers

    @pytest.mark.asyncio
    async def test_label_overrides_applied(self, checker_with_rules, mock_github_client, sample_package):
        """Test that label overrides modify weights correctly."""
        checker_with_rules._rules.get_label_overrides.return_value = {"upgrade": 12}

        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = [
            GitHubIssue(
                title="Upgrade issue",
                url="https://github.com/custom-cards/button-card/issues/1",
                state="open",
                labels=["upgrade"],
                number=1,
                priority=13,  # 5 base + 8 default for "upgrade"
            ),
        ]

        result = await checker_with_rules.check_package(sample_package, ha_current="2026.4.0")

        # With override weight 12 + base 5 = 17
        issue = result.issues_relevant[0]
        assert issue["priority"] == 17

    @pytest.mark.asyncio
    async def test_label_override_zero_ignores_label(self, checker_with_rules, mock_github_client, sample_package):
        """Test that override weight 0 causes the label to be ignored."""
        checker_with_rules._rules.get_label_overrides.return_value = {"bug": 0}

        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = [
            GitHubIssue(
                title="Bug issue",
                url="https://github.com/custom-cards/button-card/issues/1",
                state="open",
                labels=["bug"],
                number=1,
                priority=8,  # 5 base + 3 (bug default is not in high_priority_labels)
            ),
        ]

        result = await checker_with_rules.check_package(sample_package, ha_current="2026.4.0")

        # With override weight 0, the bug label contributes nothing
        issue = result.issues_relevant[0]
        assert issue["priority"] == 0

    @pytest.mark.asyncio
    async def test_keyword_overrides_applied(self, checker_with_rules, mock_github_client, sample_package):
        """Test that keyword overrides modify weights correctly."""
        checker_with_rules._rules.get_keyword_overrides.return_value = {"breaking change": 15}

        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = [
            GitHubIssue(
                title="Breaking change in API",
                url="https://github.com/custom-cards/button-card/issues/1",
                state="open",
                labels=[],
                number=1,
                priority=12,  # 2 base + 10 default keyword boost
                body="This is a breaking change that affects compatibility",
            ),
        ]

        result = await checker_with_rules.check_package(sample_package, ha_current="2026.4.0")

        # With override weight 15 + base 2 = 17
        issue = result.issues_relevant[0]
        assert issue["priority"] == 17

    @pytest.mark.asyncio
    async def test_no_rules_client_fallback(self, checker, mock_github_client, sample_package):
        """Test that without rules client, normal behavior is maintained."""
        mock_github_client.get_manifest.return_value = None
        mock_github_client.get_releases.return_value = []
        mock_github_client.get_issues.return_value = []

        result = await checker.check_package(sample_package, ha_current="2026.4.0")

        assert result.status == STATUS_COMPATIBLE
