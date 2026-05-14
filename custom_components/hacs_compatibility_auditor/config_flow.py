"""Config flow for HACS Compatibility Auditor integration."""

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_CACHE_HOURS,
    CONF_CHECK_INTERVAL,
    CONF_GITHUB_RETRIES,
    CONF_GITHUB_TIMEOUT,
    CONF_GITHUB_TOKEN,
    CONF_IGNORE_LIST,
    CONF_ISSUE_LABELS_PRIORITY,
    CONF_RULES_ENABLED,
    CONF_RULES_REPO,
    DEFAULT_CACHE_HOURS,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_GITHUB_RETRIES,
    DEFAULT_GITHUB_TIMEOUT,
    DEFAULT_RULES_ENABLED,
    DEFAULT_RULES_REPO,
    DOMAIN,
)
from .github_client import GitHubClient

_LOGGER = logging.getLogger(__name__)


async def _validate_github_token(
    hass: HomeAssistant, token: str | None
) -> tuple[bool, str | None]:
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


class HacsCompatibilityAuditorOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for HACS Compatibility Auditor."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
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
                    issue_labels = [
                        label.strip()
                        for label in issue_labels.split(",")
                        if label.strip()
                    ]

                ignore_list = user_input.get(CONF_IGNORE_LIST, "")
                if isinstance(ignore_list, str):
                    ignore_list = [
                        p.strip() for p in ignore_list.split(",") if p.strip()
                    ]

                return self.async_create_entry(
                    title="",
                    data={
                        CONF_GITHUB_TOKEN: token
                        or self.config_entry.data.get(CONF_GITHUB_TOKEN, ""),
                        CONF_CHECK_INTERVAL: user_input.get(
                            CONF_CHECK_INTERVAL,
                            self.config_entry.options.get(
                                CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL
                            ),
                        ),
                        CONF_CACHE_HOURS: user_input.get(
                            CONF_CACHE_HOURS,
                            self.config_entry.options.get(
                                CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS
                            ),
                        ),
                        CONF_ISSUE_LABELS_PRIORITY: issue_labels,
                        CONF_IGNORE_LIST: ignore_list,
                        CONF_GITHUB_TIMEOUT: user_input.get(
                            CONF_GITHUB_TIMEOUT,
                            self.config_entry.options.get(
                                CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT
                            ),
                        ),
                        CONF_GITHUB_RETRIES: user_input.get(
                            CONF_GITHUB_RETRIES,
                            self.config_entry.options.get(
                                CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES
                            ),
                        ),
                        CONF_RULES_ENABLED: user_input.get(
                            CONF_RULES_ENABLED,
                            self.config_entry.options.get(
                                CONF_RULES_ENABLED, DEFAULT_RULES_ENABLED
                            ),
                        ),
                        CONF_RULES_REPO: rules_repo,
                    },
                )

        current_options = self.config_entry.options
        current_data = self.config_entry.data

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_GITHUB_TOKEN,
                    default=current_data.get(CONF_GITHUB_TOKEN, ""),
                ): str,
                vol.Optional(
                    CONF_CHECK_INTERVAL,
                    default=current_options.get(
                        CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL
                    ),
                ): vol.All(int, vol.Range(min=1, max=168)),
                vol.Optional(
                    CONF_CACHE_HOURS,
                    default=current_options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS),
                ): vol.All(int, vol.Range(min=1, max=72)),
                vol.Optional(
                    CONF_ISSUE_LABELS_PRIORITY,
                    default=",".join(
                        current_options.get(CONF_ISSUE_LABELS_PRIORITY, [])
                    ),
                ): str,
                vol.Optional(
                    CONF_IGNORE_LIST,
                    default=",".join(current_options.get(CONF_IGNORE_LIST, [])),
                ): str,
                vol.Optional(
                    CONF_GITHUB_TIMEOUT,
                    default=current_options.get(
                        CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT
                    ),
                ): vol.All(int, vol.Range(min=5, max=120)),
                vol.Optional(
                    CONF_GITHUB_RETRIES,
                    default=current_options.get(
                        CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES
                    ),
                ): vol.All(int, vol.Range(min=0, max=10)),
                vol.Optional(
                    CONF_RULES_ENABLED,
                    default=current_options.get(
                        CONF_RULES_ENABLED, DEFAULT_RULES_ENABLED
                    ),
                ): bool,
                vol.Optional(
                    CONF_RULES_REPO,
                    default=current_options.get(CONF_RULES_REPO, DEFAULT_RULES_REPO),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )


class HacsCompatibilityAuditorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HACS Compatibility Auditor."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
                    return self.async_create_entry(
                        title="HCA",
                        data={
                            CONF_GITHUB_TOKEN: token or "",
                        },
                        options={
                            CONF_CHECK_INTERVAL: user_input.get(
                                CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL
                            ),
                            CONF_CACHE_HOURS: user_input.get(
                                CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS
                            ),
                            CONF_GITHUB_TIMEOUT: user_input.get(
                                CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT
                            ),
                            CONF_GITHUB_RETRIES: user_input.get(
                                CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES
                            ),
                        },
                    )

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_GITHUB_TOKEN): str,
                vol.Optional(
                    CONF_CHECK_INTERVAL, default=DEFAULT_CHECK_INTERVAL
                ): vol.All(int, vol.Range(min=1, max=168)),
                vol.Optional(CONF_CACHE_HOURS, default=DEFAULT_CACHE_HOURS): vol.All(
                    int, vol.Range(min=1, max=72)
                ),
                vol.Optional(
                    CONF_GITHUB_TIMEOUT, default=DEFAULT_GITHUB_TIMEOUT
                ): vol.All(int, vol.Range(min=5, max=120)),
                vol.Optional(
                    CONF_GITHUB_RETRIES, default=DEFAULT_GITHUB_RETRIES
                ): vol.All(int, vol.Range(min=0, max=10)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HacsCompatibilityAuditorOptionsFlow:
        """Get the options flow for this handler."""
        return HacsCompatibilityAuditorOptionsFlow(config_entry)
