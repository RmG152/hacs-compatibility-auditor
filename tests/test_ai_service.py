"""Tests for AI service orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.hacs_compatibility_auditor.ai_provider import (
    IssueCategoryResult,
)
from custom_components.hacs_compatibility_auditor.ai_service import AIManager
from custom_components.hacs_compatibility_auditor.const import (
    PROVIDER_TYPE_OLLAMA,
    PROVIDER_TYPE_OPENAI,
)


@pytest.fixture
def mock_provider_configs():
    """Return sample provider configs."""
    return [
        {
            "provider_type": PROVIDER_TYPE_OPENAI,
            "name": "Test OpenAI",
            "api_key": "sk-test",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "max_tokens": 1024,
            "temperature": 0.1,
        },
        {
            "provider_type": PROVIDER_TYPE_OLLAMA,
            "name": "Local Ollama",
            "api_key": "",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3.2",
            "max_tokens": 512,
            "temperature": 0.5,
        },
    ]


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant."""
    hass = MagicMock()
    return hass


class TestAIManager:
    """Test AIManager class."""

    def test_init_no_providers(self, mock_hass):
        manager = AIManager(mock_hass)
        assert manager.provider_count == 0
        assert manager.provider_names == []

    def test_init_with_providers(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        assert manager.provider_count == 2
        assert "Test OpenAI" in manager.provider_names
        assert "Local Ollama" in manager.provider_names

    def test_get_provider_found(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        provider = manager.get_provider("Test OpenAI")
        assert provider is not None
        assert provider._config.name == "Test OpenAI"

    def test_get_provider_not_found(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        provider = manager.get_provider("Non Existent")
        assert provider is None

    def test_get_first_enabled(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        provider = manager.get_first_enabled()
        assert provider is not None
        assert provider._config.name == "Test OpenAI"

    def test_get_first_enabled_empty(self, mock_hass):
        manager = AIManager(mock_hass)
        assert manager.get_first_enabled() is None

    def test_load_providers_reload(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        assert manager.provider_count == 2

        new_configs = [
            {
                "provider_type": PROVIDER_TYPE_OPENAI,
                "name": "Replaced Provider",
                "api_key": "new-key",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4",
                "max_tokens": 2048,
                "temperature": 0.3,
            }
        ]
        manager.load_providers(new_configs)
        assert manager.provider_count == 1
        assert manager.provider_names == ["Replaced Provider"]

    def test_resolve_provider_by_name(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        provider = manager._resolve_provider("Test OpenAI")
        assert provider is not None

    def test_resolve_provider_first(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        provider = manager._resolve_provider(None)
        assert provider is not None
        assert provider._config.name == "Test OpenAI"

    def test_resolve_provider_not_found_fallback(self, mock_hass, mock_provider_configs):
        manager = AIManager(mock_hass, mock_provider_configs)
        provider = manager._resolve_provider("Unknown")
        assert provider is not None
        assert provider._config.name == "Test OpenAI"

    def test_resolve_provider_no_providers(self, mock_hass):
        manager = AIManager(mock_hass)
        assert manager._resolve_provider(None) is None

    @patch("custom_components.hacs_compatibility_auditor.ai_provider.aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_analyze_package_success(self, mock_session_cls, mock_hass, mock_provider_configs):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_response.text = AsyncMock(return_value='{"verdict": "affected"}')
        mock_response.json = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": '{"verdict": "affected", "reasoning": "Has breaking issues", "confidence": 0.88}'
                        }
                    }
                ]
            }
        )

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        manager = AIManager(mock_hass, mock_provider_configs)
        result = await manager.analyze_package(
            package_name="Test Package",
            package_repo="owner/repo",
            installed_version="1.0.0",
            ha_current="2026.5.0",
            ha_next="2026.6.0",
            manifest_ha=">=2026.1.0",
            current_status="incompatible",
            issues=[{"title": "Bug", "priority": 20, "labels": ["breaking"], "body": "It broke"}],
        )
        assert result.verdict == "affected"
        assert result.reasoning == "Has breaking issues"
        assert result.confidence == 0.88
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_analyze_package_no_provider(self, mock_hass):
        manager = AIManager(mock_hass)
        result = await manager.analyze_package(
            package_name="Test",
            package_repo="owner/repo",
            installed_version="1.0.0",
            ha_current="2026.5.0",
            ha_next=None,
            manifest_ha="",
            current_status="compatible",
            issues=[],
        )
        assert result.error == "No AI provider configured"

    @patch("custom_components.hacs_compatibility_auditor.ai_provider.aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_categorize_issue_success(self, mock_session_cls, mock_hass, mock_provider_configs):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_response.text = AsyncMock(return_value='{"category": "false_positive"}')
        mock_response.json = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": '{"category": "false_positive", "confidence": 0.95, "reasoning": "User error"}'
                        }
                    }
                ]
            }
        )

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        manager = AIManager(mock_hass, mock_provider_configs)
        result = await manager.categorize_issue(
            package_name="Test Package",
            package_repo="owner/repo",
            issue_title="Not working",
            issue_body="It broke after update",
            issue_labels=["bug"],
            issue_number=42,
            ha_current="2026.5.0",
            ha_next="2026.6.0",
        )
        assert result.category == "false_positive"
        assert result.confidence == 0.95
        assert result.reasoning == "User error"

    @pytest.mark.asyncio
    async def test_categorize_issue_no_provider(self, mock_hass):
        manager = AIManager(mock_hass)
        result = await manager.categorize_issue(
            package_name="Test",
            package_repo="owner/repo",
            issue_title="Bug",
            issue_body="Details",
            issue_labels=[],
            issue_number=1,
            ha_current="2026.5.0",
            ha_next=None,
        )
        assert result.error == "No AI provider configured"


class TestBuildPrompts:
    """Test prompt building logic."""

    def test_build_analysis_prompt_with_issues(self, mock_hass):
        manager = AIManager(mock_hass)
        system, user = manager._build_analysis_prompt(
            package_name="Test Pkg",
            package_repo="owner/repo",
            installed_version="1.0.0",
            ha_current="2026.5.0",
            ha_next="2026.6.0",
            manifest_ha=">=2026.1.0",
            current_status="warning",
            issues=[
                {"title": "Breaking change", "priority": 25, "labels": ["breaking-change"], "body": "HA changed API"}
            ],
        )
        assert "Test Pkg" in user
        assert "owner/repo" in user
        assert "2026.5.0" in user
        assert "2026.6.0" in user
        assert "Breaking change" in user
        assert "affected|not_affected|uncertain" in user
        assert system != ""

    def test_build_analysis_prompt_no_issues(self, mock_hass):
        manager = AIManager(mock_hass)
        system, user = manager._build_analysis_prompt(
            package_name="Test Pkg",
            package_repo="owner/repo",
            installed_version="1.0.0",
            ha_current="2026.5.0",
            ha_next=None,
            manifest_ha="",
            current_status="compatible",
            issues=[],
        )
        assert "No issues found" in user
        assert "answer ONLY with JSON" in user.lower() or "only with json" in user.lower()

    def test_build_categorize_prompt(self, mock_hass):
        manager = AIManager(mock_hass)
        system, user = manager._build_categorize_prompt(
            package_name="Test Pkg",
            package_repo="owner/repo",
            issue_title="Broken after update",
            issue_body="It stopped working",
            issue_labels=["bug"],
            issue_number=42,
            ha_current="2026.5.0",
            ha_next="2026.6.0",
        )
        assert "#42" in user or "42" in user
        assert "Broken after update" in user
        assert "false_positive" in user
        assert system != ""

    def test_build_report_body(self, mock_hass):
        manager = AIManager(mock_hass)
        body = manager.build_report_body(
            package_repo="owner/repo",
            issue_number=42,
            category="false_positive",
            reasoning="User configuration issue.",
            provider_name="OpenAI",
        )
        assert "owner/repo" in body
        assert "42" in body
        assert "false_positive" in body
        assert "OpenAI" in body
        assert "User configuration issue" in body


class TestParseCategoryResult:
    """Test category result parsing."""

    def test_parse_valid_json(self):
        result = IssueCategoryResult()
        result = AIManager._parse_category_result(
            '{"category": "true_positive", "confidence": 0.8, "reasoning": "Real issue"}',
            result,
        )
        assert result.category == "true_positive"
        assert result.confidence == 0.8
        assert result.reasoning == "Real issue"

    def test_parse_json_with_markdown_wrapper(self):
        result = IssueCategoryResult()
        result = AIManager._parse_category_result(
            'Some text\n```json\n{"category": "false_positive", "confidence": 0.9, "reasoning": "No issue"}\n```',
            result,
        )
        assert result.category == "false_positive"
        assert result.confidence == 0.9

    def test_parse_invalid_fallback(self):
        result = IssueCategoryResult()
        result = AIManager._parse_category_result("Not valid JSON at all", result)
        assert result.category == "uncertain"

    def test_parse_empty_fallback(self):
        result = IssueCategoryResult()
        result = AIManager._parse_category_result("", result)
        assert result.category == "uncertain"
