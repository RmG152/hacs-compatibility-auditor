# HACS Compatibility Auditor

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-blue.svg)](https://hacs.xyz)
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

### Advanced options

Access options from Settings → Integrations → HACS Compatibility Auditor → Configure:

- **Priority labels**: GitHub labels that indicate high severity (comma-separated). Default: `breaking-change,breaking,incompatible,upgrade,compatibility`.
- **Ignore list**: Repository names to ignore (comma-separated).

### GitHub Token

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens).
2. Create a new token (classic) with minimal permissions: `public_repo` (read-only).
3. Copy the token and paste it into the integration configuration.

## Service

### `hacs_compatibility_auditor.check_now`

Force an immediate re-check of all HACS packages' compatibility.

```yaml
service: hacs_compatibility_auditor.check_now
```

## Check Algorithm

1. Gets the current HA version from the internal API.
2. Queries releases from the `home-assistant/core` repository on GitHub to determine the next version.
3. Enumerates HACS packages from multiple sources (HACS internal data, `.storage`, repository directory).
4. For each package:
   - Checks `hacs.json` / `manifest.json` for declared HA version requirements.
   - Fetches the latest releases/tags from the repository.
   - Searches open/recent issues with compatibility labels and keywords.
   - Analyzes release notes for breaking changes.
   - Determines final status: `compatible`, `warning`, or `incompatible`.
5. Exposes results in sensors and events.

### Status criteria

| Status | Criteria |
|--------|----------|
| `compatible` | Manifest compatible, no relevant issues |
| `warning` | Open compatibility issues (medium priority) or breaking changes in recent releases |
| `incompatible` | Manifest incompatible with current version or confirmed issue with high-severity label |
| `unknown` | Error fetching package data |

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
