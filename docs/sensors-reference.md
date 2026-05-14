# HACS Compatibility Auditor — Sensor Attributes Reference

This document describes every sensor entity and its available attributes for frontend/card developers.

---

## Entity Naming

| Pattern | Example | Description |
|---------|---------|-------------|
| `sensor.hca_ha_version_current` | `sensor.hca_ha_version_current` | Current HA version |
| `sensor.hca_ha_version_next` | `sensor.hca_ha_version_next` | Next HA version |
| `sensor.hca_hacs_packages_total` | `sensor.hca_hacs_packages_total` | Total package count |
| `sensor.hca_hacs_incompatible_count` | `sensor.hca_hacs_incompatible_count` | Incompatible count |
| `sensor.hca_package_{owner}_{repo}` | `sensor.hca_package_rmg152_hacs_compatibility_auditor` | Per-package status |

---

## 1. `sensor.hca_ha_version_current`

Current Home Assistant version string.

| Attribute | Type | Always | Description |
|-----------|------|--------|-------------|
| `state` | `string` | yes | e.g. `"2026.6.0.dev0"` |
| `last_scan` | `string` | yes | ISO 8601 timestamp of last scan |
| `scan_in_progress` | `boolean` | yes | Whether a batch scan is currently running |
| `scan_progress` | `integer` | yes | Packages processed so far |
| `scan_total` | `integer` | yes | Total packages to process |

---

## 2. `sensor.hca_ha_version_next`

Next Home Assistant version string. May be a beta/RC.

| Attribute | Type | Always | Description |
|-----------|------|--------|-------------|
| `state` | `string` | yes | e.g. `"2026.7.0b1"` |
| `is_release_candidate` | `boolean` | yes | `true` if next version is an RC/beta (not a stable release) |
| `last_scan` | `string` | yes | ISO 8601 timestamp of last scan |
| `scan_in_progress` | `boolean` | yes | Whether a batch scan is currently running |
| `scan_progress` | `integer` | yes | Packages processed so far |
| `scan_total` | `integer` | yes | Total packages to process |

---

## 3. `sensor.hca_hacs_packages_total`

Total number of HACS packages found.

| Attribute | Type | Always | Description |
|-----------|------|--------|-------------|
| `state` | `integer` | yes | Total package count |
| `by_type` | `object` | yes | Breakdown by package type, e.g. `{"integration": 12, "plugin": 3, "theme": 1}` |
| `last_scan` | `string` | yes | ISO 8601 timestamp of last scan |
| `scan_in_progress` | `boolean` | yes | Whether a batch scan is currently running |
| `scan_progress` | `integer` | yes | Packages processed so far |
| `scan_total` | `integer` | yes | Total packages to process |

### `by_type` possible keys

| Key | Description |
|-----|-------------|
| `integration` | Home Assistant integration |
| `plugin` | Lovelace plugin |
| `theme` | Theme |
| `appdaemon` | AppDaemon app |
| `netdaemon` | NetDaemon app |
| `python_script` | Python script |

---

## 4. `sensor.hca_hacs_incompatible_count`

Count of incompatible packages. **Most feature-rich global sensor.**

| Attribute | Type | Always | Description |
|-----------|------|--------|-------------|
| `state` | `integer` | yes | Number of `incompatible` packages |
| `warning_count` | `integer` | yes | Number of `warning` packages |
| `compatible_count` | `integer` | yes | Number of `compatible` packages |
| `unknown_count` | `integer` | yes | Number of `unknown` packages |
| `incompatible_packages` | `string[]` | yes | List of package **names** with `incompatible` status |
| `warning_packages` | `string[]` | yes | List of package **names** with `warning` status |
| `rules_enabled` | `boolean` | yes | Whether community rules are enabled |
| `rules_loaded` | `boolean` | yes | Whether rules were successfully loaded |
| `last_scan` | `string` | yes | ISO 8601 timestamp of last scan |
| `scan_in_progress` | `boolean` | yes | Whether a batch scan is currently running |
| `scan_progress` | `integer` | yes | Packages processed so far |
| `scan_total` | `integer` | yes | Total packages to process |

### Icon behavior

| Condition | Icon |
|-----------|------|
| Incompatible count > 0 | `mdi:alert-circle-outline` |
| No incompatibilities | `mdi:check-circle-outline` |

---

## 5. Per-Package Sensors `sensor.hca_package_*`

One sensor per HACS package. The entity ID is derived from the repository name with `/` replaced by `_` and lowercased.

**Entity ID example:**
```
sensor.hca_package_rmg152_hacs_compatibility_auditor
```
(From repository `RmG152/hacs-compatibility-auditor`)

### State

| Value | Meaning |
|-------|---------|
| `compatible` | No compatibility issues detected |
| `warning` | Possible future incompatibility (may break after upgrade) |
| `incompatible` | Confirmed incompatible |
| `unknown` | Could not be determined (timeout, network error) |
| `ignored` | In user's ignore list |

### Attributes

| Attribute | Type | Always | Description |
|-----------|------|--------|-------------|
| `name` | `string` | yes | Package display name |
| `repository` | `string` | yes | Full repository name (`owner/repo`) |
| `type` | `string` | yes | Package type (`integration`, `plugin`, `theme`, ...) |
| `installed_version` | `string` | yes | Currently installed version tag |
| `latest_version` | `string` | yes | Latest available version tag |
| `compatible_with_current` | `boolean` or `null` | yes | `true`/`false`/`null` (unknown) |
| `compatible_with_next` | `boolean` or `null` | yes | `true`/`false`/`null` (unknown) |
| `manifest_ha_requirement` | `string` | yes | HA version requirement from manifest (e.g. `>=2026.1.0`) |
| `issues_relevant` | `array` | yes | List of relevant GitHub issues (see below) |
| `last_checked` | `string` | yes | ISO 8601 timestamp of last check |
| `error` | `string` | yes | Error message if the check failed |
| `reason` | `string` | yes | Human-readable explanation of the algorithm's status decision |
| `repository_url` | `string` | yes | Direct GitHub URL for this repository |
| `ai_verdict` | `string` or `null` | yes* | AI analysis result: `"affected"`, `"not_affected"`, or `"uncertain"` |
| `ai_confidence` | `float` or `null` | yes* | AI confidence score (0.0 – 1.0) |
| `ai_reasoning` | `string` | yes* | Full AI reasoning text |
| `ai_provider` | `string` | yes* | Name of the AI provider that performed the analysis |
| `ai_analysis` | `object` | yes* | Complete raw AI result dict |

*\* `null`/empty when no AI analysis has been performed yet.*

### `issues_relevant` item schema

Each entry in the `issues_relevant` array:

| Field | Type | Description |
|-------|------|-------------|
| `title` | `string` | GitHub issue title |
| `url` | `string` | Direct URL to the GitHub issue |
| `state` | `string` | `"open"` or `"closed"` |
| `labels` | `string[]` | GitHub labels on the issue |
| `priority` | `integer` | Computed priority score (0–50+, higher = more relevant) |
| `updated_at` | `string` | ISO 8601 timestamp of last update |

### `ai_analysis` object schema

Present when AI analysis has been run on this package:

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | `string` or `null` | `"affected"`, `"not_affected"`, or `"uncertain"` |
| `reasoning` | `string` | Full AI reasoning text |
| `confidence` | `float` | Confidence score between 0.0 and 1.0 |
| `provider_used` | `string` | Name of the AI provider |
| `raw_response` | `string` | Raw AI response text (truncated to 2000 chars) |
| `error` | `string` | Error message if the AI request failed |

### Icon behavior

| Status | Icon |
|--------|------|
| `compatible` | `mdi:check-circle` |
| `warning` | `mdi:alert` |
| `incompatible` | `mdi:close-circle` |
| `ignored` | `mdi:eye-off` |
| `unknown` (default) | `mdi:help-circle` |

---

## 6. Reading Attributes from the Frontend

### JavaScript / TypeScript

```javascript
// Read a global sensor
const globalSensor = hass.states['sensor.hca_hacs_incompatible_count'];
console.log('Incompatible:', globalSensor.state);
console.log('Warnings:', globalSensor.attributes.warning_count);
console.log('Scan progress:', globalSensor.attributes.scan_progress, '/', globalSensor.attributes.scan_total);

// Read a per-package sensor by entity ID
const pkgSensor = hass.states['sensor.hca_package_kalkih_mini_graph_card'];
console.log('Status:', pkgSensor.state);
console.log('Reason:', pkgSensor.attributes.reason);
console.log('AI verdict:', pkgSensor.attributes.ai_verdict);
console.log('AI confidence:', pkgSensor.attributes.ai_confidence);
console.log('AI reasoning:', pkgSensor.attributes.ai_reasoning);

// Iterate all package sensors
const packageSensors = Object.keys(hass.states)
  .filter(key => key.startsWith('sensor.hca_package_'))
  .map(key => hass.states[key]);

for (const entity of packageSensors) {
  const attrs = entity.attributes;
  const aiVerdict = attrs.ai_verdict;
  const aiConfidence = attrs.ai_confidence;
  // render row ...
}
```

### Lovelace YAML examples

**AI verdict badge:**

```yaml
type: entity
entity: sensor.hca_package_owner_repo
attribute: ai_verdict
name: AI Verdict
```

**AI confidence as gauge:**

```yaml
type: gauge
entity: sensor.hca_package_owner_repo
attribute: ai_confidence
name: AI Confidence
min: 0
max: 1
severity:
  green: 0.8
  yellow: 0.5
  red: 0
```

**Combined status card:**

```yaml
type: entity
entity: sensor.hca_package_owner_repo
name: Package Status
show_name: true
show_state: true
state_display: >
  [[[
    const attrs = states['sensor.hca_package_owner_repo'].attributes;
    let lines = [`Algorithm: ${state}`];
    if (attrs.reason) lines.push(attrs.reason);
    if (attrs.ai_verdict) lines.push(`AI: ${attrs.ai_verdict} (${Math.round(attrs.ai_confidence * 100)}%)`);
    return lines.join(' \\\n');
  ]]]
```

---

## 7. Conditional Rendering Guidelines for Cards

### When to show AI data

| Condition | Recommendation |
|-----------|---------------|
| `ai_verdict` is `null` | Show a call-to-action button ("Analyze with AI") |
| `ai_verdict` matches algorithm status | Show as confirmation (green indicator) |
| `ai_verdict` differs from algorithm | Show as potential reclassification (yellow/blue indicator) |

Example logic:

```javascript
const status = entity.state;
const aiVerdict = entity.attributes.ai_verdict;

if (!aiVerdict) {
  // No AI analysis — prompt user
  renderAnalyzeButton();
} else if (
  (status === 'compatible' && aiVerdict === 'not_affected') ||
  (status === 'incompatible' && aiVerdict === 'affected')
) {
  // AI agrees with algorithm
  renderMatchedStatus(aiVerdict, entity.attributes.ai_confidence);
} else if (
  (status === 'warning' || status === 'incompatible') &&
  aiVerdict === 'not_affected'
) {
  // AI says it's a false positive — suggest confirmation
  renderFalsePositiveSuggestion(entity.attributes);
} else if (
  (status === 'compatible' || status === 'warning') &&
  aiVerdict === 'affected'
) {
  // AI found an issue the algorithm missed — high priority
  renderPriorityAlert(entity.attributes);
}
```

### Scan progress for loading states

Poll `sensor.hca_hacs_incompatible_count` attributes while a scan is running:

```javascript
const scanAttrs = hass.states['sensor.hca_hacs_incompatible_count'].attributes;

if (scanAttrs.scan_in_progress) {
  const progress = scanAttrs.scan_progress;
  const total = scanAttrs.scan_total;
  const pct = total > 0 ? Math.round(progress / total * 100) : 0;
  renderLoadingBar(pct);
}
```
