# HACS Compatibility Auditor — Service API

Documentation for the integration's services, intended for frontend/card consumption.

---

## `hacs_compatibility_auditor.check_now`

Forces a full re-check of all HACS packages. Clears both in-memory and disk caches.

### Request

```yaml
service: hacs_compatibility_auditor.check_now
```

No additional data fields required.

### Response

```json
{
  "success": true
}
```

### Behavior

1. Clears in-memory GitHub API cache (`GitHubClient.clear_cache`)
2. Clears persistent disk cache (`CacheManager.clear`)
3. Triggers `DataUpdateCoordinator.async_request_refresh`
4. The coordinator re-enumerates packages and processes them in batches
5. Sensors update progressively as each batch completes

---

## `hacs_compatibility_auditor.check_package`

Checks a single HACS package by repository name. Useful for refreshing one specific package without waiting for a full scan.

### Request

```yaml
service: hacs_compatibility_auditor.check_package
data:
  repository: "owner/repo-name"
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repository` | `string` | **Yes** | Full repository name in `owner/repo` format, e.g. `"home-assistant/core"` |

### Response

On success:

```json
{
  "success": true,
  "result": {
    "name": "Package Name",
    "repository": "owner/repo-name",
    "type": "integration",
    "installed_version": "1.0.0",
    "latest_version": "1.2.0",
    "compatible_with_current": true,
    "compatible_with_next": true,
    "status": "compatible",
    "issues_relevant": [],
    "manifest_ha_requirement": ">=2025.1.0",
    "last_checked": "2026-05-14T12:00:00+00:00",
    "error": "",
    "reason": "No compatibility issues detected"
  }
}
```

On failure (package not found):

```json
{
  "success": false,
  "error": "Package owner/repo-name not found"
}
```

### Result Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Package display name |
| `repository` | `string` | Full repository name (`owner/repo`) |
| `type` | `string` | Package type: `integration`, `plugin`, `theme`, `appdaemon`, `netdaemon`, `python_script` |
| `installed_version` | `string` | Currently installed version |
| `latest_version` | `string` | Latest available version (from GitHub releases or manifest) |
| `compatible_with_current` | `boolean` or `null` | Compatible with current HA version (`null` = unknown) |
| `compatible_with_next` | `boolean` or `null` | Compatible with next HA version (`null` = unknown) |
| `status` | `string` | One of: `compatible`, `warning`, `incompatible`, `unknown`, `ignored` |
| `issues_relevant` | `array` | List of relevant GitHub issues (see below) |
| `manifest_ha_requirement` | `string` | HA version requirement from manifest (e.g. `>=2025.1.0`) |
| `last_checked` | `string` | ISO 8601 timestamp of last check |
| `error` | `string` | Error message if check failed |
| `reason` | `string` | Human-readable explanation of the status |

### Issue Object

Each entry in `issues_relevant`:

```json
{
  "title": "Breaking change in HA 2025.5",
  "url": "https://github.com/owner/repo/issues/42",
  "state": "open",
  "labels": ["breaking-change"],
  "priority": 25,
  "updated_at": "2026-05-01T12:00:00Z"
}
```

### Status Meanings

| Status | `compatible_with_current` | `compatible_with_next` | Meaning |
|--------|:------------------------:|:----------------------:|---------|
| `compatible` | `true` | `true` | Safe to use now and after upgrade |
| `warning` | `true` / `false` | `false` / `unknown` | Works now but may break after upgrade |
| `incompatible` | `false` | `false` / `unknown` | Already broken or incompatible |
| `unknown` | `null` | `null` | Could not be determined (timeout, error) |
| `ignored` | `true` | `true` | In user's ignore list |

---

## Service Call from Frontend (JavaScript/TypeScript)

### Calling `check_now`

```javascript
const result = await hass.callService(
  'hacs_compatibility_auditor',
  'check_now',
  {},
  { returnResponse: true }
);
// result = { success: true }
```

### Calling `check_package`

```javascript
const result = await hass.callService(
  'hacs_compatibility_auditor',
  'check_package',
  { repository: 'owner/repo-name' },
  { returnResponse: true }
);

if (result.success) {
  console.log('Status:', result.result.status);
  console.log('Reason:', result.result.reason);
} else {
  console.error('Error:', result.error);
}
```

---

## Notes for Card Developers

- After calling `check_now`, the sensors update progressively as each batch completes (not all at once).
- Monitor the `scan_in_progress` attribute on any global sensor to detect when a scan is running.
- The `scan_progress` / `scan_total` attributes give real-time progress.
- `check_package` is useful for refreshing a single item the user is looking at without triggering a full scan.
