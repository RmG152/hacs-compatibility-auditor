"""Tests for AI provider implementations."""

import json
from unittest.mock import AsyncMock, MagicMock

from custom_components.hacs_compatibility_auditor.ai_provider import (
    AIAnalysisResult,
    AIProviderConfig,
    AnthropicProvider,
    GeminiProvider,
    IssueCategoryResult,
    OllamaProvider,
    OpenAICompatibleProvider,
    create_provider,
)
from custom_components.hacs_compatibility_auditor.const import (
    CONF_AI_API_KEY,
    DEFAULT_PROVIDER_MODELS,
    DEFAULT_PROVIDER_URLS,
    PROVIDER_TYPE_ANTHROPIC,
    PROVIDER_TYPE_GEMINI,
    PROVIDER_TYPE_OLLAMA,
    PROVIDER_TYPE_OPENAI,
)
import pytest


def _make_config(provider_type: str, **overrides) -> AIProviderConfig:
    """Create a test AI provider config."""
    config = {
        "provider_type": provider_type,
        "name": "Test Provider",
        "api_key": "test-key-123",
        "base_url": DEFAULT_PROVIDER_URLS.get(provider_type, "https://test.api/v1"),
        "model": "test-model",
    }
    config.update(overrides)
    return AIProviderConfig.from_dict(config)


class TestAIProviderConfig:
    """Test AIProviderConfig serialization."""

    def test_from_dict_openai(self):
        config = AIProviderConfig.from_dict(
            {
                "provider_type": PROVIDER_TYPE_OPENAI,
                "name": "My OpenAI",
                "api_key": "sk-123",
                "base_url": "https://custom.api.com/v1",
                "model": "gpt-4",
                "max_tokens": 2048,
                "temperature": 0.5,
            }
        )
        assert config.provider_type == PROVIDER_TYPE_OPENAI
        assert config.name == "My OpenAI"
        assert config.api_key == "sk-123"
        assert config.base_url == "https://custom.api.com/v1"
        assert config.model == "gpt-4"
        assert config.max_tokens == 2048
        assert config.temperature == 0.5

    def test_from_dict_ollama_defaults(self):
        config = AIProviderConfig.from_dict(
            {
                "provider_type": PROVIDER_TYPE_OLLAMA,
                "name": "Local Ollama",
            }
        )
        assert config.provider_type == PROVIDER_TYPE_OLLAMA
        assert config.api_key == ""
        assert config.base_url == DEFAULT_PROVIDER_URLS[PROVIDER_TYPE_OLLAMA]
        assert config.model == DEFAULT_PROVIDER_MODELS[PROVIDER_TYPE_OLLAMA]

    def test_to_dict_excludes_api_key(self):
        """to_dict() must never serialise api_key (security: no secrets in logs/cache)."""
        original = AIProviderConfig(
            provider_type=PROVIDER_TYPE_GEMINI,
            name="Gemini Test",
            api_key="gemini-key",
            base_url="https://gemini.api.com",
            model="gemini-pro",
            max_tokens=512,
            temperature=0.2,
        )
        d = original.to_dict()
        # api_key must NOT appear in serialised output
        assert CONF_AI_API_KEY not in d
        # Non-secret fields must still round-trip correctly
        restored = AIProviderConfig.from_dict(d)
        assert restored.provider_type == original.provider_type
        assert restored.name == original.name
        assert restored.base_url == original.base_url
        assert restored.model == original.model
        assert restored.max_tokens == original.max_tokens
        assert restored.temperature == original.temperature

    def test_ollama_api_key_empty_by_default(self):
        config = AIProviderConfig.from_dict(
            {
                "provider_type": PROVIDER_TYPE_OLLAMA,
                "name": "Ollama",
            }
        )
        assert config.api_key == ""


class TestOpenAICompatibleProvider:
    """Test OpenAI-compatible provider."""

    def test_build_headers_with_key(self):
        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer test-key-123"
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_without_key(self):
        config = _make_config(PROVIDER_TYPE_OPENAI, api_key="")
        provider = OpenAICompatibleProvider(config)
        headers = provider._build_headers()
        assert "Authorization" not in headers

    def test_build_request_url(self):
        config = _make_config(PROVIDER_TYPE_OPENAI, base_url="https://openrouter.ai/api/v1")
        provider = OpenAICompatibleProvider(config)
        url = provider._build_request_url()
        assert url == "https://openrouter.ai/api/v1/chat/completions"

    def test_build_request_body(self):
        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        body = provider._build_request_body("Hello", "System prompt")
        assert body["model"] == "test-model"
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["content"] == "System prompt"
        assert body["messages"][1]["role"] == "user"
        assert body["messages"][1]["content"] == "Hello"
        assert body["max_tokens"] == 1024
        assert body["temperature"] == 0.1

    def test_build_request_body_no_system(self):
        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        body = provider._build_request_body("Hello", "")
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"

    def test_parse_response(self):
        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        data = {"choices": [{"message": {"content": "Hello world"}}]}
        assert provider._parse_response(data) == "Hello world"

    def test_parse_response_empty(self):
        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        assert provider._parse_response({}) == ""
        assert provider._parse_response({"choices": []}) == ""

    @pytest.mark.asyncio
    async def test_analyze_success(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_response.text = AsyncMock(
            return_value=json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"verdict": "not_affected", "reasoning": "All good", "confidence": 0.9}'
                            }
                        }
                    ]
                }
            )
        )
        mock_response.json = AsyncMock(
            return_value={
                "choices": [
                    {"message": {"content": '{"verdict": "not_affected", "reasoning": "All good", "confidence": 0.9}'}}
                ]
            }
        )

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)

        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        result = await provider.analyze("Hello", "", session=mock_session)
        assert result.verdict == "not_affected"
        assert result.reasoning == "All good"
        assert result.confidence == 0.9
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_analyze_http_error(self):
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_response.text = AsyncMock(return_value="Unauthorized")

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)

        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        result = await provider.analyze("Hello", "", session=mock_session)
        assert result.error != ""
        assert "401" in result.error

    @pytest.mark.asyncio
    async def test_analyze_timeout(self):
        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=TimeoutError("Connection timed out"))

        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = OpenAICompatibleProvider(config)
        result = await provider.analyze("Hello", "", session=mock_session)
        assert result.error != ""


class TestOllamaProvider:
    """Test Ollama provider (OpenAI-compatible, no auth)."""

    def test_build_headers_no_auth(self):
        config = _make_config(PROVIDER_TYPE_OLLAMA)
        provider = OllamaProvider(config)
        headers = provider._build_headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_build_request_url(self):
        config = _make_config(PROVIDER_TYPE_OLLAMA, base_url="http://localhost:11434/v1")
        provider = OllamaProvider(config)
        url = provider._build_request_url()
        assert url == "http://localhost:11434/v1/chat/completions"


class TestGeminiProvider:
    """Test Google Gemini provider."""

    def test_build_headers(self):
        config = _make_config(PROVIDER_TYPE_GEMINI)
        provider = GeminiProvider(config)
        headers = provider._build_headers()
        assert headers["x-goog-api-key"] == "test-key-123"

    def test_build_request_url(self):
        config = _make_config(
            PROVIDER_TYPE_GEMINI,
            base_url="https://gemini.test/v1beta",
            model="gemini-2.0-flash",
        )
        provider = GeminiProvider(config)
        url = provider._build_request_url()
        assert "gemini.test/v1beta/models/gemini-2.0-flash:generateContent" in url

    def test_build_request_body_with_system(self):
        config = _make_config(PROVIDER_TYPE_GEMINI)
        provider = GeminiProvider(config)
        body = provider._build_request_body("Hello", "Be helpful")
        assert body["contents"][0]["parts"][0]["text"] == "Hello"
        assert body["systemInstruction"]["parts"][0]["text"] == "Be helpful"
        assert body["generationConfig"]["maxOutputTokens"] == 1024

    def test_build_request_body_no_system(self):
        config = _make_config(PROVIDER_TYPE_GEMINI)
        provider = GeminiProvider(config)
        body = provider._build_request_body("Hello", "")
        assert "systemInstruction" not in body

    def test_parse_response(self):
        config = _make_config(PROVIDER_TYPE_GEMINI)
        provider = GeminiProvider(config)
        data = {"candidates": [{"content": {"parts": [{"text": "Hi there"}]}}]}
        assert provider._parse_response(data) == "Hi there"

    def test_parse_response_no_candidates(self):
        config = _make_config(PROVIDER_TYPE_GEMINI)
        provider = GeminiProvider(config)
        assert provider._parse_response({}) == ""
        assert provider._parse_response({"candidates": []}) == ""


class TestAnthropicProvider:
    """Test Anthropic Claude provider."""

    def test_build_headers(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC)
        provider = AnthropicProvider(config)
        headers = provider._build_headers()
        assert headers["x-api-key"] == "test-key-123"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_build_request_url(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC)
        provider = AnthropicProvider(config)
        url = provider._build_request_url()
        assert url.endswith("/v1/messages")

    def test_build_request_body_with_system(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC, model="claude-sonnet-4-20250514")
        provider = AnthropicProvider(config)
        body = provider._build_request_body("Hello", "System prompt")
        assert body["messages"][0]["content"] == "Hello"
        assert body["system"] == "System prompt"
        assert "model" in body

    def test_build_request_body_no_system(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC)
        provider = AnthropicProvider(config)
        body = provider._build_request_body("Hello", "")
        assert "system" not in body

    def test_parse_response(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC)
        provider = AnthropicProvider(config)
        data = {"content": [{"type": "text", "text": "Hello Claude"}]}
        assert provider._parse_response(data) == "Hello Claude"

    def test_parse_response_empty(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC)
        provider = AnthropicProvider(config)
        assert provider._parse_response({}) == ""
        assert provider._parse_response({"content": []}) == ""


class TestCreateProvider:
    """Test provider factory function."""

    def test_create_openai(self):
        config = _make_config(PROVIDER_TYPE_OPENAI)
        provider = create_provider(config)
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_create_gemini(self):
        config = _make_config(PROVIDER_TYPE_GEMINI)
        provider = create_provider(config)
        assert isinstance(provider, GeminiProvider)

    def test_create_anthropic(self):
        config = _make_config(PROVIDER_TYPE_ANTHROPIC)
        provider = create_provider(config)
        assert isinstance(provider, AnthropicProvider)

    def test_create_ollama(self):
        config = _make_config(PROVIDER_TYPE_OLLAMA)
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)

    def test_create_unknown(self):
        config = _make_config("unknown_type")
        provider = create_provider(config)
        assert provider is None


class TestAIAnalysisResult:
    """Test AIAnalysisResult dataclass."""

    def test_to_dict(self):
        result = AIAnalysisResult(
            verdict="affected",
            reasoning="Breaking changes detected",
            confidence=0.85,
            provider_used="OpenAI",
            raw_response='{"verdict": "affected"}',
        )
        d = result.to_dict()
        assert d["verdict"] == "affected"
        assert d["reasoning"] == "Breaking changes detected"
        assert d["confidence"] == 0.85
        assert d["provider_used"] == "OpenAI"

    def test_to_dict_with_error(self):
        result = AIAnalysisResult(error="API error")
        d = result.to_dict()
        assert d["error"] == "API error"
        assert d["verdict"] is None


class TestIssueCategoryResult:
    """Test IssueCategoryResult dataclass."""

    def test_to_dict(self):
        result = IssueCategoryResult(
            category="false_positive",
            confidence=0.95,
            reasoning="User error",
            provider_used="Claude",
        )
        d = result.to_dict()
        assert d["category"] == "false_positive"
        assert d["confidence"] == 0.95
        assert d["reasoning"] == "User error"
