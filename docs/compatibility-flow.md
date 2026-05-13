# HACS Compatibility Auditor — Compatibility Determination Flow

## Overview

The integration determines whether each installed HACS package is compatible with the **current** Home Assistant version and the **next** (upcoming) Home Assistant version. It combines three signals:

1. **Manifest version requirements** — the `homeassistant` field in the package's `hacs.json` / `manifest.json`
2. **Open GitHub issues** — filtered by labels and keywords, then scored by priority
3. **Release notes** — scanned for breaking-change keywords

These signals are combined into a final status per package: `compatible`, `warning`, `incompatible`, or `unknown`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Coordinator                            │
│  (HacsCompatibilityCoordinator)                         │
│                                                         │
│  1. Read HA current version (from HA core)              │
│  2. Read HA next version (from GitHub releases API)     │
│  3. Enumerate installed HACS packages                   │
│  4. For each package → CompatibilityChecker             │
│  5. Aggregate summary statistics                        │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│              CompatibilityChecker                       │
│  (check_package)                                        │
│                                                         │
│  Step 1: Fetch manifest → extract HA version req.       │
│  Step 2: Fetch releases → get latest stable version     │
│  Step 3: Parse version requirement vs. HA versions      │
│  Step 4: Fetch issues → score by priority               │
│  Step 5: Scan release notes for breaking keywords       │
│  Step 6: Combine all signals → final status             │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│                GitHubClient                              │
│  (rate-limited, cached, retry-aware)                    │
│                                                         │
│  • get_manifest()     — hacs.json / manifest.json       │
│  • get_releases()     — repo releases                   │
│  • get_issues()       — label + keyword search          │
│  • get_ha_releases()  — home-assistant/core releases    │
└─────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Flow

### Phase 1 — Data Collection (Coordinator)

The `HacsCompatibilityCoordinator._async_update_data()` orchestrates the scan:

| Step | Action | Source |
|------|--------|--------|
| 1 | Get current HA version | `homeassistant.const.__version__` |
| 2 | Get next HA version | GitHub releases API for `home-assistant/core` (first non-prerelease tag) |
| 3 | Enumerate installed packages | HACS internal data → `.storage` file → repositories directory (3 fallback approaches) |
| 4 | Check each package | Delegates to `CompatibilityChecker.check_package()` |
| 5 | Aggregate counts | Tallies `compatible`, `warning`, `incompatible`, `unknown` |

### Phase 2 — Per-Package Check (`CompatibilityChecker.check_package`)

For each HACS package, the following steps execute sequentially:

#### Step 1: Fetch Manifest

```
GET repos/{owner}/{repo}/contents/hacs.json
Fallback: repos/{owner}/{repo}/contents/custom_components/{repo}/manifest.json
```

Extracts:
- `homeassistant` — the minimum HA version requirement (e.g., `"2024.1.0"`)
- `version` — the package's declared version

#### Step 2: Fetch Releases

```
GET repos/{owner}/{repo}/releases?per_page=5
```

Finds the latest **stable** (non-prerelease) release tag. This becomes the `latest_version` for the package.

#### Step 3: Version Requirement Parsing

The manifest's `homeassistant` field is parsed and compared against both the current and next HA versions.

**Supported constraint formats:**

| Format | Meaning |
|--------|---------|
| `2024.1.0` | Minimum version (implicit `>=`) |
| `>=2024.1.0` | Minimum version (explicit) |
| `>=2024.1.0,<2025.0.0` | Range (comma-separated) |
| `>2024.1.0` | Strictly greater than |
| `<=2024.6.0` | Maximum version |
| `==2024.1.0` | Exact version |
| `!=2024.1.0` | Any version except |
| `~=2024.1.0` | Compatible release (same major.minor) |

The parser strips `dev`, `b`, and `rc` suffixes before comparison using `packaging.version.Version`.

**Result:** Two booleans — `manifest_compatible_current` and `manifest_compatible_next`.

#### Step 4: Fetch and Score Issues

Issues are fetched through **two parallel strategies**, then merged and deduplicated:

**Strategy A — Label-based search:**

```
GET repos/{owner}/{repo}/issues?state=open&labels={label}&per_page=30&since={90_days_ago}
```

Iterates over up to 5 labels from the priority list: `breaking-change`, `breaking`, `incompatible`, `upgrade`, `compatibility`, etc.

**Strategy B — Keyword-based search (GitHub Search API):**

```
GET search/issues?q=repo:{owner}/{repo} is:issue is:open {keyword}&per_page=30
```

Iterates over up to 3 keywords: `"breaking change"`, `"incompatible"`, `"not compatible"`, etc.

**Issue Priority Scoring:**

Label-matched issues start with a base score of **5**, keyword-matched with **2**. Additional points:

| Signal | Points |
|--------|--------|
| Label: `breaking-change` | +20 |
| Label: `breaking` | +15 |
| Label: `incompatible` | +15 |
| Label: `deprecation` | +10 |
| Label: `upgrade` | +8 |
| Label: `compatibility` | +8 |
| Keyword: `"breaking change"` | +10 |
| Keyword: `"incompatible"` | +8 |
| Keyword: `"deprecated"` | +6 |
| Keyword: `"stopped working"` | +5 |

Issues are sorted by priority (highest first), deduplicated by URL, and capped at the **top 20**.

#### Step 5: Scan Release Notes for Breaking Keywords

The body text of the 3 most recent releases is scanned for breaking-change indicators:

- `breaking change`, `breaking-change`, `**breaking**`
- `## breaking`, `### breaking`
- `not compatible`, `incompatible`
- `removed:`, `deprecated:`, `migration required`

If any match is found, `release_breaking = True`.

#### Step 6: Determine Final Status

The final status is determined by combining all signals:

```
IF manifest NOT compatible with current
   OR has high-priority issue (priority >= 15):
    → INCOMPATIBLE
    → compatible_with_current = False
    → compatible_with_next = manifest_compatible_next AND no high-priority issues

ELIF manifest NOT compatible with next
   OR has medium-priority issue (5 <= priority < 15)
   OR release notes mention breaking changes:
    → WARNING
    → compatible_with_current = manifest_compatible AND no medium-priority issues
    → compatible_with_next = manifest_compatible_next AND no breaking release notes

ELSE:
    → COMPATIBLE
    → compatible_with_current = True
    → compatible_with_next = True
```

**Status summary:**

| Status | `compatible_with_current` | `compatible_with_next` | Meaning |
|--------|:------------------------:|:----------------------:|---------|
| `compatible` | ✅ True | ✅ True | Safe to use now and after upgrade |
| `warning` | ✅/⚠️ | ⚠️/❌ | Works now but may break after upgrade |
| `incompatible` | ❌ False | ❌/⚠️ | Already broken or will break |
| `unknown` | `None` | `None` | Could not be determined (error) |
| `ignored` | ✅ True | ✅ True | Package is on the ignore list |

---

## Caching and Rate Limiting

- All GitHub API responses are cached for **12 hours** (configurable via `cache_hours` option).
- The client tracks `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers.
- When remaining calls drop to ≤ 5, the client waits until the reset time (up to 60 seconds).
- Failed requests are retried up to **3 times** with exponential backoff (`2^attempt` seconds).

---

## Data Flow Diagram

```
HA Core Version ──┐
                  │
HA Next Version ──┤  (from GitHub releases)
                  │
HACS Packages ────┤  (from HACS storage)
                  │
                  ▼
        ┌─────────────────┐
        │  For each pkg:  │
        │                 │
        │  Manifest ──┐   │
        │  Releases ──┤   │
        │  Issues ────┤   │
        │             ▼   │
        │  Evaluate:      │
        │  • version req  │
        │  • issue scores │
        │  • release notes│
        │             │   │
        │             ▼   │
        │  Final Status   │
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐
        │  Summary Stats  │
        │  • total        │
        │  • incompatible │
        │  • warning      │
        │  • compatible   │
        │  • unknown      │
        └─────────────────┘
                 │
                 ▼
        Sensor Entities
        (per-package + global)
```

---

## Key Files

| File | Role |
|------|------|
| `coordinator.py` | Orchestrates periodic scans, aggregates results |
| `compatibility.py` | Core algorithm: version parsing, issue scoring, status determination |
| `github_client.py` | GitHub API client with caching, rate limiting, retries |
| `hacs_repository.py` | Reads installed HACS packages from multiple sources |
| `const.py` | Default labels, keywords, status constants |
| `sensor.py` | Exposes results as HA sensor entities (global + per-package) |
