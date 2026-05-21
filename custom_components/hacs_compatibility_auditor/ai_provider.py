"""AI provider abstraction and implementations for HACS Compatibility Auditor.

Supports OpenAI-compatible, Google Gemini, Anthropic Claude, and Ollama.
Each provider translates between a generic prompt interface and its own API format.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import aiohttp

from .const import (
    CONF_AI_API_KEY,
    CONF_AI_BASE_URL,
    CONF_AI_MAX_TOKENS,
    CONF_AI_MODEL,
    CONF_AI_PROVIDER_NAME,
    CONF_AI_PROVIDER_TYPE,
    CONF_AI_TEMPERATURE,
    DEFAULT_AI_MAX_TOKENS,
    DEFAULT_AI_TEMPERATURE,
    DEFAULT_PROVIDER_MODELS,
    DEFAULT_PROVIDER_URLS,
    PROVIDER_TYPE_ANTHROPIC,
    PROVIDER_TYPE_GEMINI,
    PROVIDER_TYPE_OLLAMA,
    PROVIDER_TYPE_OPENAI,
)

_LOGGER = logging.getLogger(__name__)

AI_DEFAULT_TIMEOUT = 30


def _redact_tokens(text: str) -> str:
    """Redact common API token patterns from text using non-greedy patterns."""
    # More comprehensive patterns to catch various token formats
    patterns = [
        (r'["\']?token["\']?\s*[:=]\s*["\']?[a-zA-Z0-9\-_\.]{20,}["\']?', '"token":"[REDACTED]"'),
        (r'["\']?api_key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9\-_\.]{20,}["\']?', '"api_key":"[REDACTED]"'),
        (r"Bearer\s+[a-zA-Z0-9\-_\.]{20,}", "Bearer [REDACTED]"),
        (r"sk-[a-zA-Z0-9]{32,}", "[REDACTED]"),  # OpenAI keys
        (r"AIza[a-zA-Z0-9\-_]{35}", "[REDACTED]"),  # Google API keys
        (r"xai-[a-zA-Z0-9]{50,}", "[REDACTED]"),  # Grok keys
        (r"claude-[a-zA-Z0-9\-_]{40,}", "[REDACTED]"),  # Anthropic keys
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


@dataclass
class AIProviderConfig:
    """Configuration for a single AI provider instance."""

    provider_type: str
    name: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = DEFAULT_AI_MAX_TOKENS
    temperature: float = DEFAULT_AI_TEMPERATURE

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AIProviderConfig:
        """Create config from a dict (as stored in config entry)."""
        provider_type = data.get(CONF_AI_PROVIDER_TYPE, PROVIDER_TYPE_OPENAI)
        return cls(
            provider_type=provider_type,
            name=data.get(CONF_AI_PROVIDER_NAME, ""),
            api_key=data.get(CONF_AI_API_KEY, ""),
            base_url=data.get(CONF_AI_BASE_URL, DEFAULT_PROVIDER_URLS.get(provider_type, "")),
            model=data.get(CONF_AI_MODEL, DEFAULT_PROVIDER_MODELS.get(provider_type, "")),
            max_tokens=data.get(CONF_AI_MAX_TOKENS, DEFAULT_AI_MAX_TOKENS),
            temperature=data.get(CONF_AI_TEMPERATURE, DEFAULT_AI_TEMPERATURE),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage in config entry (excludes secrets)."""
        return {
            CONF_AI_PROVIDER_TYPE: self.provider_type,
            CONF_AI_PROVIDER_NAME: self.name,
            CONF_AI_BASE_URL: self.base_url,
            CONF_AI_MODEL: self.model,
            CONF_AI_MAX_TOKENS: self.max_tokens,
            CONF_AI_TEMPERATURE: self.temperature,
        }


@dataclass
class AIAnalysisResult:
    """Result of an AI analysis request."""

    verdict: str | None = None
    reasoning: str = ""
    confidence: float = 0.0
    provider_used: str = ""
    raw_response: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "provider_used": self.provider_used,
            "error": self.error,
        }


@dataclass
class IssueCategoryResult:
    """Result of issue categorization."""

    category: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    provider_used: str = ""
    error: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "category": self.category,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "provider_used": self.provider_used,
            "error": self.error,
        }


class AIProvider(ABC):
    """Abstract base for AI providers."""

    def __init__(self, config: AIProviderConfig) -> None:
        """Initialize provider from config."""
        self._config = config
        self._timeout = aiohttp.ClientTimeout(total=AI_DEFAULT_TIMEOUT)
        _LOGGER.debug(
            "Initialized %s provider: %s (model=%s, url=%s)",
            self.__class__.__name__,
            config.name,
            config.model,
            config.base_url,
        )

    @abstractmethod
    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for the API request."""

    @abstractmethod
    def _build_request_url(self) -> str:
        """Build the full API URL."""

    @abstractmethod
    def _build_request_body(self, prompt: str, system_prompt: str) -> dict[str, Any]:
        """Build the JSON request body."""

    @abstractmethod
    def _parse_response(self, data: dict[str, Any]) -> str:
        """Extract text content from the API response."""

    async def analyze(
        self,
        prompt: str,
        system_prompt: str = "",
        session: aiohttp.ClientSession | None = None,
    ) -> AIAnalysisResult:
        """Send a prompt to the AI and return the analysis result."""
        result = AIAnalysisResult(provider_used=self._config.name)

        try:
            url = self._build_request_url()
            headers = self._build_headers()
            body = self._build_request_body(prompt, system_prompt)

            _LOGGER.debug(
                "AI request to %s (model=%s, tokens=%d)",
                url,
                self._config.model,
                self._config.max_tokens,
            )

            close_session = session is None
            if session is None:
                session = aiohttp.ClientSession()

            try:
                async with session.post(url, json=body, headers=headers, timeout=self._timeout) as resp:
                    raw = await resp.text()
                    # Redact tokens before any further use
                    raw_redacted = _redact_tokens(raw)
                    result.raw_response = raw_redacted[:2000]

                    if resp.status != 200:
                        _LOGGER.error(
                            "AI provider %s returned %d: [REDACTED]",
                            self._config.name,
                            resp.status,
                        )
                        result.error = f"HTTP {resp.status}: [REDACTED]"
                        return result

                    data = await resp.json()
                    content = self._parse_response(data)
                    if not content:
                        result.error = "Empty response from AI provider"
                        return result

                    return self._parse_structured_result(content, result)

            finally:
                if close_session:
                    await session.close()

        except (
            TimeoutError,
            aiohttp.ClientError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            _LOGGER.error("AI provider %s error: %s", self._config.name, exc)
            result.error = str(exc)
            return result

    def _parse_structured_result(self, content: str, result: AIAnalysisResult) -> AIAnalysisResult:
        """Parse a JSON-structured response from the AI."""
        content_stripped = content.strip()
        json_start = content_stripped.find("{")
        json_end = content_stripped.rfind("}")

        if json_start >= 0 and json_end > json_start:
            json_str = content_stripped[json_start : json_end + 1]
            try:
                parsed = json.loads(json_str)
                result.verdict = parsed.get("verdict", parsed.get("category", result.verdict))
                result.reasoning = parsed.get("reasoning", parsed.get("reason", ""))
                result.confidence = float(parsed.get("confidence", 0))
            except (json.JSONDecodeError, ValueError, TypeError):
                result.reasoning = content_stripped[:1000]
        else:
            result.reasoning = content_stripped[:1000]

        return result


class OpenAICompatibleProvider(AIProvider):
    """Provider for OpenAI-compatible APIs (OpenAI, OpenRouter, Minimax, StepFun)."""

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _build_request_url(self) -> str:
        base = self._config.base_url.rstrip("/")
        return f"{base}/chat/completions"

    def _build_request_body(self, prompt: str, system_prompt: str) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }

    def _parse_response(self, data: dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama provider — same API format as OpenAI, no auth, local defaults."""

    def _build_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}


class GeminiProvider(AIProvider):
    """Provider for Google Gemini API."""

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["x-goog-api-key"] = self._config.api_key
        return headers

    def _build_request_url(self) -> str:
        base = self._config.base_url.rstrip("/")
        model = self._config.model
        return f"{base}/models/{model}:generateContent"

    def _build_request_body(self, prompt: str, system_prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": self._config.max_tokens,
                "temperature": self._config.temperature,
            },
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        return body

    def _parse_response(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


class AnthropicProvider(AIProvider):
    """Provider for Anthropic Claude API."""

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self._config.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _build_request_url(self) -> str:
        base = self._config.base_url.rstrip("/")
        return f"{base}/v1/messages"

    def _build_request_body(self, prompt: str, system_prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }
        if system_prompt:
            body["system"] = system_prompt
        return body

    def _parse_response(self, data: dict[str, Any]) -> str:
        content = data.get("content", [])
        return "".join(block.get("text", "") for block in content if block.get("type") == "text")


def create_provider(config: AIProviderConfig) -> AIProvider | None:
    """Factory: create an AI provider instance from config."""
    providers = {
        PROVIDER_TYPE_OPENAI: OpenAICompatibleProvider,
        PROVIDER_TYPE_GEMINI: GeminiProvider,
        PROVIDER_TYPE_ANTHROPIC: AnthropicProvider,
        PROVIDER_TYPE_OLLAMA: OllamaProvider,
    }
    cls = providers.get(config.provider_type)
    if cls is None:
        _LOGGER.error("Unknown AI provider type: %s", config.provider_type)
        return None
    return cls(config)
