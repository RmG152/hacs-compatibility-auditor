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
┌─────────────────────────────────────────────────────────────┐
│                  Coordinator                                │
│  (HacsCompatibilityCoordinator)                             │
│                                                             │
│  1. Load persistent cache from disk                         │
│  2. Read HA current version (from HA core)                  │
│  3. Read HA next version (from GitHub releases API)         │
│  4. Enumerate installed HACS packages                       │
│  5. Separate: cached vs pending packages                    │
│  6. Return cached data immediately (fast setup)             │
│  7. Start background batch scan for pending packages        │
│  8. Aggregate summary statistics                            │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│           Background Batch Scanner                           │
│                                                             │
│  For each batch of N packages (concurrent):                 │
│    1. For each pkg → CompatibilityChecker.check_package()   │
│    2. Collect results                                       │
│    3. Update coordinator data (async_set_updated_data)      │
│    4. Save to disk cache (CacheManager.async_save)          │
│    5. Notify sensors                                        │
│  Next batch...                                              │
│  On CancelledError: save progress and exit                  │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│              CompatibilityChecker                           │
│  (check_package)                                            │
│                                                             │
│  Step 1: Fetch manifest → extract HA version req.           │
│  Step 2: Fetch releases → get latest stable version         │
│  Step 3: Parse version requirement vs. HA versions          │
│  Step 4: Fetch issues → score by priority                   │
│  Step 5: Scan release notes for breaking keywords           │
│  Step 6: Combine all signals → final status                 │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                GitHubClient                                  │
│  (rate-limited, cached, retry-aware)                        │
│                                                             │
│  • get_manifest()     — hacs.json / manifest.json           │
│  • get_releases()     — repo releases                       │
│  • get_issues()       — label + keyword search              │
│  • get_ha_releases()  — home-assistant/core releases        │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                CacheManager (disk)                           │
│                                                             │
│  File: .storage/hacs_compatibility_auditor_cache.json        │
│  • Load on startup — no internet needed                     │
│  • Each entry: {result, cached_at, ha_version}              │
│  • TTL configurable (default 12h)                           │
│  • Invalidated if HA version changes                        │
│  • Saved after each batch + on completion                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Flow

### Phase 1 — Data Collection (Coordinator)

The `HacsCompatibilityCoordinator._async_update_data()` orchestrates the scan:

| Step | Action | Source |
|------|--------|--------|
| 0 | **Load disk cache** | `.storage/hacs_compatibility_auditor_cache.json` — no internet needed |
| 1 | Get current HA version | `homeassistant.const.__version__` |
| 2 | Get next HA version | GitHub releases API for `home-assistant/core` (first non-prerelease tag) |
| 3 | Enumerate installed packages | HACS internal data → `.storage` file → repositories directory (3 fallback approaches) |
| 4 | **Separate cached vs pending** | For each pkg: ignore? → whitelist? → blacklist? → cache valid? → else pending |
| 5 | Return cached data immediately | Fast setup, no blocking |
| 6 | **Background batch scan** | Process pending packages in concurrent batches of N (default 5) |
| 7 | Aggregate counts | Tallies `compatible`, `warning`, `incompatible`, `unknown` |

### AI Analysis Integration (Optional)

When AI is **enabled** and **auto-analyze** is turned on in the options, the flow extends after Phase 2:

```
For each INCOMPATIBLE or WARNING package:
  └── Send context (issues, manifest, versions) to AI provider
       └── AI returns: verdict (affected/not_affected/uncertain)
                        + reasoning + confidence
       └── Result stored in ai_analysis field (does not override algorithm status)
```

The AI analysis can also be triggered on-demand via two services:
- `ai_analyze_package` — Full analysis of a package's compatibility
- `ai_categorize_issue` — Categorize a specific issue (true positive / false positive / etc.)

Reports can be submitted to the community rules repository via `report_to_rules`.

See [services.md](services.md) for the full service API.

---

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

#### Step 5: Scan Release Notes for Breaking Keywords and Deprecation

The body text of the 3 most recent releases is scanned for breaking-change and deprecation indicators:

**Breaking Change Keywords:**
- `breaking change`, `breaking-change`, `**breaking**`
- `## breaking`, `### breaking`
- `not compatible`, `incompatible`
- `removed:`, `deprecated:`, `migration required`
- `end of life`, `use this instead`
- `merged into`, `migrated to`

If any match is found, `release_breaking = True`.

**Deprecation Keywords (stronger signal):**
- `end of life`, `deprecated`
- `use this instead`, `use instead`
- `merged into`, `migrated to`
- `superse`, `please use`
- `has been deprecated`

If any deprecation keyword is found, `release_deprecated = True` and the package is marked as **INCOMPATIBLE** (not just WARNING), because the package author explicitly states the package is obsolete and users should migrate.

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

The integration uses a **two-layer cache**:

### Layer 1 — In-Memory Cache (GitHubClient)

- Stores raw API responses keyed by URL.
- TTL: 12 hours (configurable via `cache_hours` option).
- Cleared on forced refresh (`check_now` service).
- `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers are tracked globally.
- When remaining calls ≤ 5, the client waits until the reset time (up to 60 seconds).
- Failed requests are retried up to **3 times** with exponential backoff (`2^attempt` seconds).

### Layer 2 — Persistent Disk Cache (CacheManager)

- File: `.storage/hacs_compatibility_auditor_cache.json` in the HA config directory.
- Stores individual package compatibility results keyed by `package_full_name`.
- Each entry includes:
  - `result` — the full `CompatibilityResult` dict.
  - `cached_at` — Unix timestamp of when it was cached.
  - `ha_version` — the HA version at cache time.
- **Survives HA restarts.** On restart, the cache is loaded first — no internet required.
- **TTL:** Same as the GitHub cache (configurable, default 12h).
- **Version invalidation:** If the HA version changes, all entries are invalidated.
- **Batch saving:** Cache is written to disk after each batch completes, not at the end — so progress is never lost.

### Startup Flow

1. Load disk cache → instant, no API calls.
2. Enumerate HACS packages → local file access, fast.
3. For each package: check ignore list → whitelist → blacklist → disk cache.
4. Valid cache entry → use immediately (no API call).
5. Miss/expired → add to pending list.
6. If pending list is not empty:
   - If there are cached results, return them immediately and start background batch scan.
   - If no cached results at all, process the first batch synchronously, then start background.
7. Background processes remaining packages in batches of N (configurable, default 5).
8. After each batch: save disk cache → notify sensors via `async_set_updated_data()`.
9. If cancelled (`asyncio.CancelledError`), progress is saved to disk before exit.

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
| `coordinator.py` | Orchestrates periodic scans, batch processing, disk cache, aggregates results |
| `cache_manager.py` | Persistent disk cache (survives restarts, TTL + HA version invalidation) |
| `compatibility.py` | Core algorithm: version parsing, issue scoring, status determination |
| `github_client.py` | GitHub API client with URL-encoded queries, in-memory caching, rate limiting, retries |
| `hacs_repository.py` | Reads installed HACS packages from multiple sources |
| `const.py` | Default labels, keywords, status constants |
| `sensor.py` | Exposes results as HA sensor entities (global + per-package) with scan progress attributes |
| `ai_provider.py` | AI provider abstraction: base class + 4 implementations (OpenAI-compatible, Gemini, Anthropic, Ollama) |
| `ai_service.py` | AI orchestration: AIManager, prompt building, analysis/categorization flows |
