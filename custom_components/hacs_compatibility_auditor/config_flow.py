"""Config flow for HACS Compatibility Auditor integration."""

import ipaddress
import logging
import re
from typing import Any
import urllib.parse

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_AI_API_KEY,
    CONF_AI_AUTO_ANALYZE,
    CONF_AI_BASE_URL,
    CONF_AI_ENABLED,
    CONF_AI_MAX_TOKENS,
    CONF_AI_MODEL,
    CONF_AI_PROVIDER_NAME,
    CONF_AI_PROVIDER_TYPE,
    CONF_AI_PROVIDERS,
    CONF_AI_TEMPERATURE,
    CONF_BATCH_SIZE,
    CONF_CACHE_HOURS,
    CONF_CHECK_INTERVAL,
    CONF_GITHUB_RETRIES,
    CONF_GITHUB_TIMEOUT,
    CONF_GITHUB_TOKEN,
    CONF_IGNORE_LIST,
    CONF_ISSUE_LABELS_PRIORITY,
    CONF_RULES_ENABLED,
    CONF_RULES_REPO,
    DEFAULT_AI_AUTO_ANALYZE,
    DEFAULT_AI_ENABLED,
    DEFAULT_AI_MAX_TOKENS,
    DEFAULT_AI_TEMPERATURE,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CACHE_HOURS,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_GITHUB_RETRIES,
    DEFAULT_GITHUB_TIMEOUT,
    DEFAULT_PROVIDER_MODELS,
    DEFAULT_PROVIDER_URLS,
    DEFAULT_RULES_ENABLED,
    DEFAULT_RULES_REPO,
    DOMAIN,
    PROVIDER_TYPE_ANTHROPIC,
    PROVIDER_TYPE_GEMINI,
    PROVIDER_TYPE_OLLAMA,
    PROVIDER_TYPE_OPENAI,
)
from .github_client import GitHubClient

_LOGGER = logging.getLogger(__name__)


async def _validate_github_token(hass: HomeAssistant, token: str | None) -> tuple[bool, str | None]:
    """Validate the GitHub token by making a test request."""
    if not token:
        return True, None  # Token is optional
    session = async_create_clientsession(hass)
    client = GitHubClient(session=session, token=token)
    try:
        valid = await client.validate_token()
    except (TimeoutError, aiohttp.ClientError) as exc:
        _LOGGER.error("Error validating GitHub token: %s", exc)
        return False, "cannot_connect"
    finally:
        await client.close()
    if not valid:
        return False, "invalid_token"
    return True, None


async def _validate_hacs(hass: HomeAssistant) -> bool:
    """Validate that HACS is available."""
    try:
        hacs = hass.data.get("hacs")
        if hacs is not None:
            return True

    except ImportError:
        return False


def _is_safe_url(url: str, provider_type: str) -> tuple[bool, str | None]:
    """Validate that base_url uses https and does not target private/reserved IPs.

    Ollama is commonly run on LAN/Local networks — allow private and link-local IPs
    as well as localhost for Ollama.  All other providers must use https and must
    not resolve to private/reserved addresses.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False, "invalid_url_format"

    if not parsed.scheme:
        return False, "https_required"

    hostname = parsed.hostname or ""
    if not hostname:
        return False, "missing_hostname"

    # Validate hostname format to prevent injection
    # Allow alphanumeric, hyphens, dots, and underscores
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_.]*[a-zA-Z0-9]$", hostname):
        return False, "invalid_hostname_format"

    # Block suspicious hostnames
    if hostname in ("localhost", "127.0.0.1", "::1"):
        if provider_type != PROVIDER_TYPE_OLLAMA:
            return False, "localhost_not_allowed"

    # Ollama: allow localhost, private IPs, link-local, and plain hostnames (LAN)
    if provider_type == PROVIDER_TYPE_OLLAMA:
        try:
            addr = ipaddress.ip_address(hostname)
            # Block only truly reserved ranges; allow private and link-local
            if addr.is_reserved and not (addr.is_private or addr.is_link_local):
                return False, "ollama_reserved_ip_not_allowed"
        except ValueError:
            pass  # hostname is a domain name (e.g. ollama.local) — allow
        return True, None

    # Non-Ollama providers: require HTTPS
    if parsed.scheme != "https":
        return False, "https_required"

    # Block private / reserved / loopback / link-local IPs for cloud providers
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_link_local:
            return False, "private_ip_not_allowed"
    except ValueError:
        pass  # hostname is a domain name, not an IP — allow

    return True, None


class HacsCompatibilityAuditorOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for HACS Compatibility Auditor."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._ai_providers: list[dict[str, Any]] = []
        self._pending_options: dict[str, Any] = {}
        self._edit_provider: dict[str, Any] | None = None

    def _init_pending_options(self) -> None:
        """Initialize pending options if not already done."""
        if not hasattr(self, "_pending_options"):
            self._pending_options = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check if user wants to manage AI providers
            if user_input.pop("manage_ai_providers", False):
                self._pending_options = dict(user_input)
                return await self.async_step_ai_providers()

            token = user_input.get(CONF_GITHUB_TOKEN)
            if token:
                valid, error = await _validate_github_token(self.hass, token)
                if not valid:
                    errors["base"] = error or "cannot_connect"

            if not errors:
                # Validate rules_repo format if provided
                rules_repo = user_input.get(CONF_RULES_REPO, DEFAULT_RULES_REPO)
                if (
                    "/" not in rules_repo
                    or len(rules_repo.split("/")) != 2
                    or not all(part.strip() for part in rules_repo.split("/"))
                ):
                    errors[CONF_RULES_REPO] = "invalid_repo_format"

            if not errors:
                # Parse comma-separated lists
                issue_labels = user_input.get(CONF_ISSUE_LABELS_PRIORITY, "")
                if isinstance(issue_labels, str):
                    issue_labels = [label.strip() for label in issue_labels.split(",") if label.strip()]

                ignore_list = user_input.get(CONF_IGNORE_LIST, "")
                if isinstance(ignore_list, str):
                    ignore_list = [p.strip() for p in ignore_list.split(",") if p.strip()]

                return self.async_create_entry(
                    title="",
                    data={
                        CONF_GITHUB_TOKEN: token or self.config_entry.data.get(CONF_GITHUB_TOKEN, ""),
                        CONF_CHECK_INTERVAL: user_input.get(
                            CONF_CHECK_INTERVAL,
                            self.config_entry.options.get(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL),
                        ),
                        CONF_CACHE_HOURS: user_input.get(
                            CONF_CACHE_HOURS,
                            self.config_entry.options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS),
                        ),
                        CONF_ISSUE_LABELS_PRIORITY: issue_labels,
                        CONF_IGNORE_LIST: ignore_list,
                        CONF_GITHUB_TIMEOUT: user_input.get(
                            CONF_GITHUB_TIMEOUT,
                            self.config_entry.options.get(CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT),
                        ),
                        CONF_GITHUB_RETRIES: user_input.get(
                            CONF_GITHUB_RETRIES,
                            self.config_entry.options.get(CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES),
                        ),
                        CONF_RULES_ENABLED: user_input.get(
                            CONF_RULES_ENABLED,
                            self.config_entry.options.get(CONF_RULES_ENABLED, DEFAULT_RULES_ENABLED),
                        ),
                        CONF_RULES_REPO: rules_repo,
                        CONF_BATCH_SIZE: user_input.get(
                            CONF_BATCH_SIZE,
                            self.config_entry.options.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE),
                        ),
                        CONF_AI_ENABLED: user_input.get(
                            CONF_AI_ENABLED,
                            self.config_entry.options.get(CONF_AI_ENABLED, DEFAULT_AI_ENABLED),
                        ),
                        CONF_AI_AUTO_ANALYZE: user_input.get(
                            CONF_AI_AUTO_ANALYZE,
                            self.config_entry.options.get(CONF_AI_AUTO_ANALYZE, DEFAULT_AI_AUTO_ANALYZE),
                        ),
                        CONF_AI_PROVIDERS: self.config_entry.options.get(CONF_AI_PROVIDERS, []),
                    },
                )

        current_options = self.config_entry.options
        current_data = self.config_entry.data

        # Build warning message if AI is enabled but no providers configured
        ai_enabled = current_options.get(CONF_AI_ENABLED, DEFAULT_AI_ENABLED)
        ai_providers = current_options.get(CONF_AI_PROVIDERS, [])
        description_extra = ""
        if ai_enabled and not ai_providers:
            description_extra = (
                "\n\n⚠️ **AI analysis is enabled but no AI providers are configured. "
                "Configure at least one provider to use AI features.**"
            )

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_GITHUB_TOKEN,
                    default=current_data.get(CONF_GITHUB_TOKEN, ""),
                ): str,
                vol.Optional(
                    CONF_CHECK_INTERVAL,
                    default=current_options.get(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL),
                ): vol.All(int, vol.Range(min=1, max=168)),
                vol.Optional(
                    CONF_CACHE_HOURS,
                    default=current_options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS),
                ): vol.All(int, vol.Range(min=1, max=72)),
                vol.Optional(
                    CONF_ISSUE_LABELS_PRIORITY,
                    default=",".join(current_options.get(CONF_ISSUE_LABELS_PRIORITY, [])),
                ): str,
                vol.Optional(
                    CONF_IGNORE_LIST,
                    default=",".join(current_options.get(CONF_IGNORE_LIST, [])),
                ): str,
                vol.Optional(
                    CONF_GITHUB_TIMEOUT,
                    default=current_options.get(CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT),
                ): vol.All(int, vol.Range(min=5, max=120)),
                vol.Optional(
                    CONF_GITHUB_RETRIES,
                    default=current_options.get(CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES),
                ): vol.All(int, vol.Range(min=0, max=10)),
                vol.Optional(
                    CONF_RULES_ENABLED,
                    default=current_options.get(CONF_RULES_ENABLED, DEFAULT_RULES_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_RULES_REPO,
                    default=current_options.get(CONF_RULES_REPO, DEFAULT_RULES_REPO),
                ): str,
                vol.Optional(
                    CONF_BATCH_SIZE,
                    default=current_options.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE),
                ): vol.All(int, vol.Range(min=1, max=50)),
                vol.Optional(
                    CONF_AI_ENABLED,
                    default=current_options.get(CONF_AI_ENABLED, DEFAULT_AI_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_AI_AUTO_ANALYZE,
                    default=current_options.get(CONF_AI_AUTO_ANALYZE, DEFAULT_AI_AUTO_ANALYZE),
                ): bool,
                vol.Optional(
                    "manage_ai_providers",
                    default=False,
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"extra_warning": description_extra or ""},
        )

    async def async_step_ai_providers(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage AI providers list."""
        errors: dict[str, str] = {}

        current_providers = self.config_entry.options.get(CONF_AI_PROVIDERS, [])
        action_options = {
            "back": "← Volver a configuración general",
            "add": "➕ Añadir proveedor de IA",
        }
        for p in current_providers:
            name = p.get(CONF_AI_PROVIDER_NAME, "?")
            ptype = p.get(CONF_AI_PROVIDER_TYPE, "?")
            action_options[f"edit:{name}"] = f"✏️ Editar: {name} ({ptype})"
            action_options[f"remove:{name}"] = f"🗑️ Eliminar: {name}"

        if user_input is not None:
            action = user_input.get("action", "back")
            if action == "back":
                # Merge pending options + current providers
                options = dict(self._pending_options) if hasattr(self, "_pending_options") else {}
                options[CONF_AI_PROVIDERS] = current_providers
                return self.async_create_entry(title="", data=options)
            if action == "add":
                return await self.async_step_ai_add_provider()
            if action and action.startswith("edit:"):
                name = action[5:]
                for p in current_providers:
                    if p.get(CONF_AI_PROVIDER_NAME) == name:
                        self._edit_provider = p
                        break
                return await self.async_step_ai_add_provider()
            if action and action.startswith("remove:"):
                name = action[7:]
                current_providers = [p for p in current_providers if p.get(CONF_AI_PROVIDER_NAME) != name]
                # Re-merge with pending options
                options = dict(self._pending_options) if hasattr(self, "_pending_options") else {}
                options[CONF_AI_PROVIDERS] = current_providers
                return self.async_create_entry(title="", data=options)

        data_schema = vol.Schema(
            {
                vol.Required("action", default="back"): vol.In(action_options),
            }
        )

        provider_count = len(current_providers)
        description = f"Tienes {provider_count} proveedor(es) configurado(s)."
        if provider_count > 0:
            provider_list = "\n".join(
                f"  • {p.get(CONF_AI_PROVIDER_NAME, '?')} ({p.get(CONF_AI_PROVIDER_TYPE, '?')})"
                for p in current_providers
            )
            description += f"\n\n{provider_list}"

        return self.async_show_form(
            step_id="ai_providers",
            data_schema=data_schema,
            description_placeholders={"providers": description},
            errors=errors,
        )

    async def async_step_ai_add_provider(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Add or edit an AI provider."""
        errors: dict[str, str] = {}
        edit_mode = hasattr(self, "_edit_provider") and self._edit_provider is not None
        defaults = self._edit_provider if edit_mode else {}

        if user_input is not None:
            provider_type = user_input.get(CONF_AI_PROVIDER_TYPE, PROVIDER_TYPE_OPENAI)
            name = user_input.get(CONF_AI_PROVIDER_NAME, "")
            api_key = user_input.get(CONF_AI_API_KEY, "")
            base_url = user_input.get(CONF_AI_BASE_URL, "")
            model = user_input.get(CONF_AI_MODEL, "")
            max_tokens = user_input.get(CONF_AI_MAX_TOKENS, DEFAULT_AI_MAX_TOKENS)
            temperature = user_input.get(CONF_AI_TEMPERATURE, DEFAULT_AI_TEMPERATURE)

            if not name:
                errors["base"] = "provider_name_required"
            elif not model:
                errors["base"] = "provider_model_required"
            elif not base_url:
                errors["base"] = "provider_url_required"
            elif provider_type != PROVIDER_TYPE_OLLAMA and not api_key:
                errors["base"] = "provider_key_required"

            if not errors:
                provider_config = {
                    CONF_AI_PROVIDER_TYPE: provider_type,
                    CONF_AI_PROVIDER_NAME: name,
                    CONF_AI_API_KEY: api_key,
                    CONF_AI_BASE_URL: base_url,
                    CONF_AI_MODEL: model,
                    CONF_AI_MAX_TOKENS: max_tokens,
                    CONF_AI_TEMPERATURE: temperature,
                }

                # Validate base_url to prevent SSRF
                url_ok, url_err = _is_safe_url(base_url, provider_type)
                if not url_ok:
                    errors["base"] = url_err or "invalid_url"
                else:
                    current_providers = list(self.config_entry.options.get(CONF_AI_PROVIDERS, []))

                    if edit_mode:
                        old_name = self._edit_provider.get(CONF_AI_PROVIDER_NAME)
                        for i, p in enumerate(current_providers):
                            if p.get(CONF_AI_PROVIDER_NAME) == old_name:
                                current_providers[i] = provider_config
                                break
                        self._edit_provider = None
                    else:
                        current_providers.append(provider_config)

                    options = dict(self._pending_options) if hasattr(self, "_pending_options") else {}
                    options[CONF_AI_PROVIDERS] = current_providers
                    return self.async_create_entry(title="", data=options)

        # Determine defaults based on edit mode or new provider
        provider_type_default = defaults.get(CONF_AI_PROVIDER_TYPE, PROVIDER_TYPE_OPENAI)
        base_url_default = defaults.get(CONF_AI_BASE_URL, DEFAULT_PROVIDER_URLS.get(provider_type_default, ""))
        model_default = defaults.get(CONF_AI_MODEL, DEFAULT_PROVIDER_MODELS.get(provider_type_default, ""))

        data_schema = vol.Schema(
            {
                vol.Required(CONF_AI_PROVIDER_TYPE, default=provider_type_default): vol.In(
                    {
                        PROVIDER_TYPE_OPENAI: "OpenAI / OpenRouter / StepFun / Minimax (API key requerida)",
                        PROVIDER_TYPE_GEMINI: "Google Gemini (API key requerida)",
                        PROVIDER_TYPE_ANTHROPIC: "Anthropic Claude (API key requerida)",
                        PROVIDER_TYPE_OLLAMA: "Ollama local (sin API key, para privacidad)",
                    }
                ),
                vol.Required(
                    CONF_AI_PROVIDER_NAME,
                    default=defaults.get(CONF_AI_PROVIDER_NAME, ""),
                ): str,
                vol.Optional(CONF_AI_API_KEY, default=defaults.get(CONF_AI_API_KEY, "")): str,
                vol.Required(CONF_AI_BASE_URL, default=base_url_default): str,
                vol.Required(CONF_AI_MODEL, default=model_default): str,
                vol.Optional(
                    CONF_AI_MAX_TOKENS,
                    default=defaults.get(CONF_AI_MAX_TOKENS, DEFAULT_AI_MAX_TOKENS),
                ): vol.All(int, vol.Range(min=64, max=32768)),
                vol.Optional(
                    CONF_AI_TEMPERATURE,
                    default=defaults.get(CONF_AI_TEMPERATURE, DEFAULT_AI_TEMPERATURE),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            }
        )

        return self.async_show_form(
            step_id="ai_add_provider",
            data_schema=data_schema,
            errors=errors,
        )


class HacsCompatibilityAuditorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HACS Compatibility Auditor."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            # Validate HACS presence
            if not await _validate_hacs(self.hass):
                errors["base"] = "hacs_not_found"
            else:
                # Validate GitHub token if provided
                token = user_input.get(CONF_GITHUB_TOKEN)
                valid, error = await _validate_github_token(self.hass, token)
                if not valid:
                    errors["base"] = error or "cannot_connect"
                else:
                    # Store validated options and ask about AI setup before creating entry
                    self._pending_options = {
                        CONF_GITHUB_TOKEN: token or "",
                        CONF_CHECK_INTERVAL: user_input.get(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL),
                        CONF_CACHE_HOURS: user_input.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS),
                        CONF_GITHUB_TIMEOUT: user_input.get(CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT),
                        CONF_GITHUB_RETRIES: user_input.get(CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES),
                    }
                    return await self.async_step_ai_setup()

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_GITHUB_TOKEN): str,
                vol.Optional(CONF_CHECK_INTERVAL, default=DEFAULT_CHECK_INTERVAL): vol.All(
                    int, vol.Range(min=1, max=168)
                ),
                vol.Optional(CONF_CACHE_HOURS, default=DEFAULT_CACHE_HOURS): vol.All(int, vol.Range(min=1, max=72)),
                vol.Optional(CONF_GITHUB_TIMEOUT, default=DEFAULT_GITHUB_TIMEOUT): vol.All(
                    int, vol.Range(min=5, max=120)
                ),
                vol.Optional(CONF_GITHUB_RETRIES, default=DEFAULT_GITHUB_RETRIES): vol.All(
                    int, vol.Range(min=0, max=10)
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_ai_setup(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask the user whether to configure AI providers now."""
        if user_input is not None:
            if user_input.get("setup_ai", False):
                # User wants to configure AI — enable AI, providers set up later in options
                options = dict(self._pending_options)
                options[CONF_AI_ENABLED] = True
                options[CONF_AI_AUTO_ANALYZE] = False
                options[CONF_AI_PROVIDERS] = []
                return self.async_create_entry(
                    title="HACS Compatibility Auditor",
                    data={
                        CONF_GITHUB_TOKEN: options.get(CONF_GITHUB_TOKEN, ""),
                    },
                    options=options,
                )
            # User skipped AI — create entry with pending options
            options = dict(self._pending_options)
            options[CONF_AI_ENABLED] = user_input.get(CONF_AI_ENABLED, user_input.get("ai_enabled", DEFAULT_AI_ENABLED))
            options[CONF_AI_AUTO_ANALYZE] = user_input.get(CONF_AI_AUTO_ANALYZE, DEFAULT_AI_AUTO_ANALYZE)
            options[CONF_AI_PROVIDERS] = user_input.get(CONF_AI_PROVIDERS, [])
            return self.async_create_entry(
                title="HACS Compatibility Auditor",
                data={
                    CONF_GITHUB_TOKEN: options.get(CONF_GITHUB_TOKEN, ""),
                },
                options=options,
            )

        data_schema = vol.Schema(
            {
                vol.Optional("setup_ai", default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="ai_setup",
            data_schema=data_schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HacsCompatibilityAuditorOptionsFlow:
        """Get the options flow for this handler."""
        return HacsCompatibilityAuditorOptionsFlow(config_entry)
