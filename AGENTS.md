# AGENTS.md - HACS Compatibility Auditor

This is a custom Home Assistant integration that audits HACS packages for compatibility with current and next HA versions.

## Project Overview

- **Domain**: `hacs_compatibility_auditor`
- **Type**: Custom integration (cloud polling)
- **Platforms**: Sensor
- **Config Flow**: Yes (with options flow for AI providers)
- **Dependencies**: HACS integration must be installed
- **Repository**: https://github.com/RmG152/hacs-compatibility-auditor

## Repository Structure

```
hacs-compatibility-auditor/
├── custom_components/
│   └── hacs_compatibility_auditor/
│       ├── __init__.py          # Entry point, service registration
│       ├── ai_provider.py       # AI provider abstraction (OpenAI, Gemini, Anthropic, Ollama)
│       ├── ai_service.py        # AIManager orchestration, prompt building
│       ├── cache_manager.py     # Persistent disk cache (.storage/)
│       ├── compatibility.py     # Core compatibility checking algorithm
│       ├── config_flow.py       # Config flow + options flow (AI providers)
│       ├── const.py             # Constants, defaults, service names
│       ├── coordinator.py       # DataUpdateCoordinator, batch scanning
│       ├── github_client.py     # GitHub API client with rate limiting/caching
│       ├── hacs_repository.py   # HACS package enumeration
│       ├── manifest.json        # Integration manifest
│       ├── rules_client.py      # Community rules engine
│       ├── sensor.py            # Sensor platform (global + per-package)
│       ├── services.yaml        # Service definitions
│       ├── strings.json         # Legacy translations
│       ├── version_utils.py     # HA version parsing/comparison
│       └── translations/
│           ├── en.json          # English translations
│           ├── es.json          # Spanish translations
│           └── ca.json          # Catalan translations
├── tests/
│   ├── conftest.py              # pytest config with HA module mocks
│   ├── test_ai_provider.py
│   ├── test_ai_service.py
│   ├── test_compatibility.py
│   ├── test_github_client.py
│   ├── test_rules_client.py
│   └── test_sensor.py
├── docs/
│   ├── compatibility-flow.md    # Algorithm documentation
│   ├── sensors-reference.md     # Sensor reference
│   └── services.md              # Service API documentation
├── pyproject.toml               # Tool config (ruff, pytest, mypy, pylint)
└── requirements-dev.txt         # Dev dependencies
```

## Build/Lint/Test Commands

**Always run before every commit:**

```bash
# 1. Lint with ruff (fix all issues):
python -m ruff check .

# 2. Format with ruff:
python -m ruff format .

# 3. Run tests:
pytest tests/
```

Additional commands:

```bash
# Verify Python syntax only:
python -m py_compile custom_components/hacs_compatibility_auditor/__init__.py

# For type checking:
python -m mypy custom_components/hacs_compatibility_auditor/
```

**Windows caveat:** the `pytest-homeassistant-custom-component` dependency imports
`fcntl`/`resource`/`pwd`/`grp` at collection time, which does not exist on Windows.
However, the project's `tests/conftest.py` mocks the entire `homeassistant` package
hierarchy before any imports, so tests may run directly. If you encounter import
errors, use the stub approach described below.

### Running tests on Windows (if needed)

If `pytest` fails with `ImportError: No module named 'fcntl'`:

```powershell
# One-time: install the fcntl/resource/pwd/grp stub at user-site
$userSite = python -c "import site; print(site.getusersitepackages())"
New-Item -ItemType Directory -Path $userSite -Force | Out-Null
@'
import sys, types
for _n in ("fcntl", "resource", "pwd", "grp"):
    if _n in sys.modules: continue
    m = types.ModuleType(_n)
    if _n == "fcntl":
        m.LOCK_EX, m.LOCK_SH, m.LOCK_NB, m.LOCK_UN = 2, 1, 4, 8
        m.flock = lambda *a, **k: 0
        m.ioctl = lambda *a, **k: 0
    elif _n == "resource":
        m.RLIMIT_CPU, m.RLIMIT_NOFILE = 0, 7
        m.getrlimit = lambda *a, **k: (0, 0)
        m.setrlimit = lambda *a, **k: None
    elif _n == "pwd":
        m.getpwnam = lambda *a, **k: types.SimpleNamespace(pw_uid=0)
        m.getpwuid = lambda *a, **k: types.SimpleNamespace(pw_name="root")
    elif _n == "grp":
        m.getgrnam = lambda *a, **k: types.SimpleNamespace(gr_gid=0)
        m.getgrgid = lambda *a, **k: types.SimpleNamespace(gr_name="root")
    sys.modules[_n] = m
'@ | Set-Content -LiteralPath (Join-Path $userSite "sitecustomize.py") -Encoding UTF8

# Then run pytest with plugin auto-load disabled:
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest tests/ `
    --no-header --tb=line --confcutdir=. `
    -p asyncio --asyncio-mode=auto
```

**Important:**
- For HACS updates: commit to GitHub, create a new release, then use HACS to redownload
- After deploying, always restart HA with `ha core restart` and wait ~65 seconds
- Verify files compile with `python3 -m py_compile` before restarting
- manifest.json must include: `version`, `config_flow`, `requirements`, `dependencies`
- Logger name: `custom_components.hacs_compatibility_auditor`
- Log file location: `/homeassistant/homeassistant.log` (not `ha core logs`)

## Code Style Guidelines

### General

- Follow Home Assistant's integration guidelines: https://developers.home-assistant.io/docs/integration_format/
- Use async/await for all I/O operations
- Always import from `homeassistant` packages, not assume availability
- Python target version: 3.14 (per pyproject.toml)
- Line length: 120 characters (per ruff config)

### Type Annotations

- Use `from __future__ import annotations` is NOT needed (Python 3.14+)
- Use type aliases for complex types where appropriate
- Use `type: ignore` sparingly and only when absolutely necessary

### Imports

Order imports as:
1. Standard library (`logging`, `re`, etc.)
2. Third-party (`aiohttp`, `voluptuous`, `packaging`)
3. Home Assistant core (`homeassistant.*`)
4. Local relative imports (`.const`, `.config_flow`)

```python
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
```

### Naming Conventions

- **Modules**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Types**: `PascalCase` (for type aliases and generics)
- **Private members**: `_prefixed_with_underscore`

### Logging

- Get logger via `import logging` then `logging.getLogger(__name__)`
- Use appropriate log levels:
  - `_LOGGER.debug()` for detailed debugging info
  - `_LOGGER.info()` for normal operation milestones
  - `_LOGGER.warning()` for recoverable issues
  - `_LOGGER.error()` for errors that don't prevent operation
  - `_LOGGER.exception()` for errors with tracebacks

### Error Handling

Use Home Assistant's config entry exceptions where appropriate:
- `ConfigEntryNotReady` - Service not available (e.g., timeout)

Persistent cache failure: if the persistent cache fails to load or is corrupted on startup, log a warning, clear the cache file atomically, continue startup with the in-memory cache only, and surface an integration-level diagnostic sensor.

```python
from homeassistant.exceptions import ConfigEntryNotReady

try:
    await coordinator.async_config_entry_first_refresh()
except ConfigEntryNotReady:
    # Handle gracefully - cache may save us
    if coordinator.cache_manager and coordinator.cache_manager.entry_count > 0:
        coordinator.load_from_cache()
    else:
        raise
```

### Config Flow

- VERSION = 1, MINOR_VERSION = 1
- Use voluptuous schemas for data validation
- OptionsFlow for managing AI providers (add/edit/remove)
- Always handle errors gracefully with user-friendly messages
- Validate URLs with `_is_safe_url(url)`: allow only `https` schemes, disallow localhost and private IP ranges, return False for malformed URLs; add unit tests covering edge cases

### Entity Implementation

- Entity classes inherit from `CoordinatorEntity` + `SensorEntity`
- Set `_attr_unique_id` and `_attr_name` in `__init__`
- Use `@property` for dynamic values (native_value, extra_state_attributes, icon)
- Use `SensorEntityDescription` for sensor definitions
- Use `@callback` for coordinator update handlers

### API Calls

Priority checklist for all network calls:
1. Use `aiohttp.ClientSession` (not httpx) with `aiohttp.ClientTimeout(total=60, connect=10)`
2. Retry on transient 5xx/connection errors: up to 5 attempts, base backoff 1s, exponential factor 2, max backoff 30s, full jitter
3. Honor rate limits: read `X-RateLimit-Reset` headers; on HTTP 429, retry with exponential backoff up to 5 times, pause requests to that host until reset epoch + 1s, and set a sensor attribute `rate_limited_until` to that timestamp
4. Cache responses: in-memory TTL 60s, persistent disk TTL 12h (configurable in integration options); evict LRU entries from persistent cache when it exceeds 1000 entries
5. Handle all exceptions gracefully - never let exceptions propagate to HA

### Async Patterns

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HacsCompatibilityCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    # ... build entity list ...
    async_add_entities(entities, True)
```

### File Structure for New Files

When creating new platform/module files:
1. Docstring with purpose
2. Imports (stdlib, third-party, HA, local)
3. Constants/API endpoints
4. Class definitions
5. Setup functions

### Working with Translations

**Migrate to `translations/<locale>.json` format when possible; maintain `strings.json` only while legacy consumers exist.**

```
translations/
├── en.json    # English translations
├── es.json    # Spanish translations
└── ca.json    # Catalan translations
```

**Translation file structure for config flow + options flow:**

```json
{
  "config": {
    "step": { "user": { "title": "...", "data": { ... } } },
    "error": { ... },
    "abort": { ... }
  },
  "options": {
    "step": {
      "init": { "title": "...", "data": { ... } },
      "ai_providers": { ... },
      "ai_add_provider": { ... }
    },
    "error": { ... }
  },
  "entity": { "sensor": { ... } },
  "services": { ... }
}
```

**Important translation rules:**
- Field names in `data` must match the voluptuous schema field names exactly
- After changing translations, hard refresh browser (Ctrl+Shift+R) to see changes
- Logger name: `custom_components.hacs_compatibility_auditor`

### Comments

- Do not add comments unless explicitly required
- Code should be self-documenting through clear naming
- Docstrings are enforced by ruff (D rules) — use Google convention

### Constants

Define all magic numbers and strings in `const.py`:
- API endpoints
- Default values
- Configuration keys (`CONF_*`)
- Service names
- Status values
- AI provider types and defaults

### Testing

When adding tests:
- Place in `tests/` directory
- Use `pytest` and `pytest-asyncio` (asyncio_mode = "auto")
- Mock `aiohttp` responses and HA modules via `tests/conftest.py`
- Run ruff lint and format before every commit
- Aim for high coverage on new/modified lines
- Use `https://` URLs in test data to avoid security scanner warnings
- The `tests/conftest.py` mocks the entire `homeassistant` package hierarchy — tests run without a real HA instance

### Project-Specific Patterns

**Coordinator pattern:** The `HacsCompatibilityCoordinator` extends `DataUpdateCoordinator` and manages:
- Batch processing of HACS packages (configurable batch_size)
- Background scanning with progress tracking
- Two-layer caching: in-memory (default TTL 60s) + persistent disk (default TTL 12h, both configurable in integration options); evict LRU entries from persistent cache when it exceeds 1000 entries
- Community rules integration
- AI analysis orchestration

**GitHub client:** `GitHubClient` provides:
- Rate limit awareness (X-RateLimit headers)
- In-memory response caching with configurable TTL
- Retry with exponential backoff
- Issue search with label/keyword priority scoring

**Compatibility algorithm:** See `docs/compatibility-flow.md` for the full algorithm. Key points:
- Checks manifest `homeassistant` version requirement
- Searches GitHub issues for incompatibility signals
- Uses weighted scoring (labels + keywords)
- Community rules can override results (whitelist/blacklist)
- AI analysis can validate findings

**AI providers:** Multi-provider support via `AIProvider` abstract class:
- OpenAI-compatible (OpenAI, OpenRouter, StepFun, MiniMax)
- Google Gemini
- Anthropic Claude
- Ollama (local, no API key)

AI provider error handling and failover:
- If a provider returns 401/403, mark it disabled and notify via logs
- On 429/5xx, retry per the API Calls retry policy, then failover to the next configured provider; mark the failing provider as `rate_limited` and surface a sensor attribute with the cooldown expiry
- If AI output fails schema validation, treat the result as `AI_UNTRUSTED` and include the raw output in debug logs only

## Common Issues and Solutions

### Tests fail with `ImportError: No module named 'fcntl'`
- **Cause**: `pytest-homeassistant-custom-component` imports POSIX-only modules
- **Fix**: Use the Windows stub approach in [Running tests on Windows](#running-tests-on-windows)

### Config flow "already_configured" abort
- **Cause**: Only one instance of the integration is allowed
- **Fix**: This is by design — remove existing entry before reconfiguring

### Sensors show "unknown" after restart
- **Cause**: Network unavailable during first refresh and no cache exists
- **Fix**: The integration handles this gracefully by falling back to cache. If cache is empty, sensors will be "unknown" until network is available

### AI analysis returns "AI is not configured or enabled"
- **Cause**: AI is disabled in options or no providers are configured
- **Fix**: Enable AI in integration options and configure at least one provider

### GitHub API rate limit exceeded
- **Cause**: Too many API calls without authentication
- **Fix**: Configure a GitHub token in integration options (5000 req/h vs 60 req/h)

### Community rules not loading
- **Cause**: Rules repository unreachable or format changed
- **Fix**: Check `rules_repo` option, verify internet connectivity. Rules are cached for 12h.

### Background scan progress stuck
- **Cause**: Scan was cancelled (HA restart) or an error occurred mid-batch
- **Fix**: Progress is saved after each batch. Call `check_now` service to force a fresh scan.
