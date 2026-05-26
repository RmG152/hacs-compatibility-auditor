# HACS Compatibility Auditor

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-blue.svg)](https://hacs.xyz)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![CI](https://github.com/RmG152/hacs-compatibility-auditor/actions/workflows/ci.yaml/badge.svg)](https://github.com/RmG152/hacs-compatibility-auditor/actions/workflows/ci.yaml)
[![Build](https://img.shields.io/github/actions/workflow/status/RmG152/hacs-compatibility-auditor/ci.yaml?branch=main)](https://github.com/RmG152/hacs-compatibility-auditor/actions)
[![Release](https://img.shields.io/github/v/release/RmG152/hacs-compatibility-auditor)](https://github.com/RmG152/hacs-compatibility-auditor/releases)

Home Assistant integration that detects the current and next version of Home Assistant, lists all integrations and cards installed via HACS, and checks each package's compatibility by querying their GitHub issues and metadata.

## Features

- **Automatic version detection**: Identifies the current Home Assistant version and the next available version (including release candidates).
- **HACS package enumeration**: Lists all integrations, cards, themes, and other packages installed from HACS.
- **Compatibility verification**: Evaluates each package against the current and next Home Assistant versions.
- **GitHub issue analysis**: Reviews open and recent issues for incompatibility reports, breaking change notes, and relevant PRs.
- **Notifications**: Automatic events when incompatibilities are detected with the next HA version.
- **Re-scan service**: Force an immediate compatibility check with the `hacs_compatibility_auditor.check_now` service.
- **Per-package check**: Check a single HACS package with `hacs_compatibility_auditor.check_package` without waiting for a full scan.
- **Persistent cache**: Results survive HA restarts. On restart, cached data is loaded from disk instantly and only expired entries are re-fetched.
- **Batch processing**: Packages are checked in concurrent batches (default 5), preventing timeouts in large installations. Progress is saved after each batch.
- **Community rules engine**: Downloads community-sourced rules from a GitHub repository to whitelist, blacklist, or fine-tune compatibility detection per package. → [Default rules repo](https://github.com/RmG152/hacs-compatibility-auditor-rules)
- **AI Analysis (optional)**: Integrates with AI providers (OpenAI, Gemini, Anthropic, Ollama) to validate compatibility findings and reduce false positives.
- **Multi-provider AI**: Configure 1+ AI providers with individual API keys, URLs, and models. Supports OpenAI-compatible (OpenAI, OpenRouter, Minimax, StepFun...), Google Gemini, Anthropic Claude, and Ollama (local, no API key needed).
- **AI Analysis Service**: `ai_analyze_package` — Analyzes a package using AI and returns verdict + reasoning.
- **Issue Categorization Service**: `ai_categorize_issue` — Categorizes specific GitHub issues (true positive / false positive / etc.).
- **Report to Rules**: `report_to_rules` — Creates a GitHub issue on the community rules repository with AI findings.
- **Lovelace Card**: Includes a custom card with filterable summary, repository links, and quick actions. → [Card repository](https://github.com/RmG152/hacs-compatibility-auditor-card)

## Sensors

The integration creates the following sensors:

| Sensor | Description |
|--------|-------------|
| `sensor.ha_version_current` | Current Home Assistant version |
| `sensor.ha_version_next` | Next available version (RC or stable) |
| `sensor.hacs_packages_total` | Total number of installed HACS packages |
| `sensor.hacs_incompatible_count` | Number of incompatible packages |

Additionally, one sensor is created per installed HACS package (`sensor.hacs_compatibility_auditor_package_*`).

Global sensors include the following state attributes:

| Attribute | Sensor | Description |
|-----------|--------|-------------|
| `scan_in_progress` | All | Whether a batch scan is currently running |
| `scan_progress` | All | Number of packages checked so far |
| `scan_total` | All | Total number of packages to check |
| `incompatible_packages` | `hacs_incompatible_count` | List of incompatible package names |
| `warning_packages` | `hacs_incompatible_count` | List of warning package names |
| `rules_enabled` | `hacs_incompatible_count` | Whether community rules are enabled |
| `rules_loaded` | `hacs_incompatible_count` | Whether rules were successfully loaded |

## Installation

### Via HACS (recommended)

1. Add this repository as a **custom repository** in HACS:
   - HACS → Integrations → Menu (⋮) → Custom repositories
   - URL: `https://github.com/RmG152/hacs-compatibility-auditor`
   - Category: **Integration**
2. Search for "HACS Compatibility Auditor" in HACS → Integrations.
3. Click **Install**.
4. **Restart Home Assistant**.
5. Go to **Settings → Devices & Services → Add Integration** and search for "HACS Compatibility Auditor".

### Manual installation

1. Copy the `custom_components/hacs_compatibility_auditor/` folder to your `custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration from Settings → Integrations.

## Lovelace Card

The integration includes a Lovelace card in a separate repository:

> **https://github.com/RmG152/hacs-compatibility-auditor-card**

Follow the installation and configuration instructions in that repository's README.

## Configuration

### Config Flow

1. **GitHub Token** (optional): Without a token, the GitHub API allows ~60 requests/hour. With a token, ~5000 requests/hour. Recommended for installations with many packages.
2. **Check interval**: How often the automatic scan runs (default: 12h).
3. **Cache hours**: Cache time for GitHub queries (default: 12h).
4. **GitHub timeout**: Timeout in seconds for queries (default: 15s).
5. **GitHub retries**: Number of retries on errors (default: 3).
6. **Use community rules**: Enable or disable the community rules engine (default: enabled).
7. **Rules repository**: GitHub repository for community rules in `owner/repo` format (default: `RmG152/hacs-compatibility-auditor-rules`).

### Advanced options

Access options from Settings → Integrations → HACS Compatibility Auditor → Configure:

- **Priority labels**: GitHub labels that indicate high severity (comma-separated). Default: `breaking-change,breaking,incompatible,upgrade,compatibility`.
- **Ignore list**: Repository names to ignore (comma-separated).
- **Rules repo**: GitHub repository for community rules (default: `RmG152/hacs-compatibility-auditor-rules`).
- **Batch size**: Number of packages to check concurrently (default: 5, max: 50). Larger batches speed up scans but consume more GitHub API quota simultaneously.

### GitHub Token

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens).
2. Create a new token (classic) with minimal permissions: `public_repo` (read-only).
3. Copy the token and paste it into the integration configuration.

**Issue creation (report_to_rules / ai_confirm_report):** These services try to create issues on the rules repository via the GitHub API. If the token lacks write permissions (e.g., fine-grained PATs, or classic PATs restricted by organization policy), the services return a **fallback URL** with the issue pre-filled using the correct template. Open the URL in your browser to complete the submission manually.

> For the full service API schema including response formats and frontend usage examples, see [docs/services.md](docs/services.md).

## Services

### `hacs_compatibility_auditor.check_now`

Force an immediate re-check of all HACS packages' compatibility.

```yaml
service: hacs_compatibility_auditor.check_now
```

### `hacs_compatibility_auditor.check_package`

Check a single HACS package's compatibility by selecting its sensor.

```yaml
service: hacs_compatibility_auditor.check_package
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
```

Returns the compatibility result for that package.

### `hacs_compatibility_auditor.ai_analyze_package`

Uses an AI provider to analyze if a HACS package has real compatibility issues.

```yaml
service: hacs_compatibility_auditor.ai_analyze_package
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
  provider: "My OpenAI"  # optional, uses first configured provider
```

### `hacs_compatibility_auditor.ai_categorize_issue`

Categorizes a specific GitHub issue using AI.

```yaml
service: hacs_compatibility_auditor.ai_categorize_issue
data:
  repository: "owner/repo-name"
  issue_number: 42
  provider: "My OpenAI"  # optional
```

### `hacs_compatibility_auditor.report_to_rules`

Creates a GitHub issue on the community rules repository with AI analysis.

```yaml
service: hacs_compatibility_auditor.report_to_rules
data:
  repository: "owner/repo-name"
  issue_number: 42
  category: "false_positive"
  reasoning: "The AI determined this issue is a user configuration problem"
  action: "add_false_positive"  # or "report_incompatibility"
```

### `hacs_compatibility_auditor.ai_analyze_all`

Runs AI analysis on all packages that are not compatible or ignored.

```yaml
service: hacs_compatibility_auditor.ai_analyze_all
data:
  provider: "My OpenAI"  # optional
```

### `hacs_compatibility_auditor.ai_confirm_report`

Creates a GitHub issue using stored AI analysis for a package.

```yaml
service: hacs_compatibility_auditor.ai_confirm_report
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
  action: "add_false_positive"  # optional, derived from verdict if omitted
```

## Caching

The integration uses a **two-layer cache** to minimize GitHub API calls and survive restarts:

1. **In-memory cache** (GitHubClient): Stores raw API responses for the configured TTL (default 12h). Cleared on forced refresh.
2. **Persistent disk cache** (CacheManager): Stores individual package compatibility results in `.storage/hacs_compatibility_auditor_cache.json`. Survives HA restarts.

**On restart:**
1. The disk cache is loaded first — no internet access needed.
2. For each package, if the cached result is still valid (TTL not expired AND HA version unchanged), it is used directly.
3. Only packages with expired, missing, or invalidated cache entries are fetched from GitHub.
4. Packages are checked in batches (default 5 concurrent) and disk cache is updated after each batch.

**Cache invalidation:**
- TTL can be configured via `cache_hours` option (default: 12h).
- If the Home Assistant version changes, all cached entries are invalidated (results may differ per HA version).
- Calling `check_now` clears both cache layers and forces a full refresh.

## Community Rules

The integration includes a community-driven rules engine that downloads compatibility overrides from a GitHub repository. This allows fine-tuning detection without updating the integration.

- **Default repository**: [`RmG152/hacs-compatibility-auditor-rules`](https://github.com/RmG152/hacs-compatibility-auditor-rules)
- **Enabled by default**: Can be disabled in integration options.
- **Rule types**:
  - **Whitelist / Blacklist**: Force-mark packages as compatible or incompatible per HA version.
  - **False positives**: Ignore specific GitHub issues that incorrectly trigger warnings.
  - **Label / Keyword overrides**: Adjust priority weights for issue labels and keywords on a per-repository basis.
- **Update frequency**: Rules are downloaded from the latest GitHub release every 12 hours.

> For details on the compatibility check algorithm, see [docs/compatibility-flow.md](docs/compatibility-flow.md).

## Events

The integration fires a `hacs_compatibility_auditor_incompatibility_detected` event when incompatibilities are found:

```yaml
- trigger:
    - platform: event
      event_type: hacs_compatibility_auditor_incompatibility_detected
  action:
    - service: notify.mobile_app
      data:
        title: "HACS Incompatibility Detected"
        message: >
          {{ trigger.event.data.incompatible_count }} packages are
          incompatible with the next version of Home Assistant.
```

## Requirements

- Home Assistant >= 2024.1.0
- HACS installed and configured
- Internet connection (to query the GitHub API)
- GitHub Token (optional but recommended)

## License

MIT
