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

Checks a single HACS package by selecting its sensor. Useful for refreshing one specific package without waiting for a full scan.

### Request

```yaml
service: hacs_compatibility_auditor.check_package
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | `string` | **Yes** | Entity ID of the package sensor to check |

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

---

## `hacs_compatibility_auditor.ai_analyze_package`

Uses an AI provider to analyze if a HACS package has real compatibility issues. Runs the full compatibility check and then sends the context (issues, manifest, versions) to the configured AI for analysis.

### Request

```yaml
service: hacs_compatibility_auditor.ai_analyze_package
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
  # provider: "My OpenAI"  # optional, uses first configured if omitted
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | `string` | **Yes** | Entity ID of the package sensor to analyze |
| `provider` | `string` | No | Name of the AI provider to use (uses first configured if omitted) |

### Response

```json
{
  "success": true,
  "result": {
    "verdict": "not_affected",
    "reasoning": "The issues found are related to user configuration, not HA compatibility.",
    "confidence": 0.87,
    "provider_used": "My OpenAI",
    "raw_response": "...",
    "error": ""
  },
  "algorithm_status": "warning"
}
```

### Result Fields

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | `string` | `affected`, `not_affected`, or `uncertain` |
| `reasoning` | `string` | AI explanation for the verdict |
| `confidence` | `float` | AI confidence score (0.0 - 1.0) |
| `provider_used` | `string` | Name of the AI provider that processed the request |
| `raw_response` | `string` | Raw AI response (truncated) |
| `error` | `string` | Error message if the AI request failed |

---

## `hacs_compatibility_auditor.ai_categorize_issue`

Categorizes a specific GitHub issue using AI to determine if it's a real compatibility problem.

### Request

```yaml
service: hacs_compatibility_auditor.ai_categorize_issue
data:
  repository: "owner/repo-name"
  issue_number: 42
  # provider: "My OpenAI"  # optional
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repository` | `string` | **Yes** | Full repository name in `owner/repo` format |
| `issue_number` | `integer` | **Yes** | GitHub issue number |
| `provider` | `string` | No | Name of the AI provider to use |

### Response

```json
{
  "success": true,
  "result": {
    "category": "false_positive",
    "confidence": 0.92,
    "reasoning": "The issue is about a configuration error, not a compatibility problem.",
    "provider_used": "My OpenAI",
    "error": ""
  }
}
```

### Categories

| Category | Meaning |
|----------|---------|
| `true_positive` | Actually affects compatibility |
| `false_positive` | Does not affect compatibility |
| `config_issue` | User configuration problem |
| `feature_request` | Feature request, not a bug |
| `unrelated` | Not related to compatibility |
| `uncertain` | Cannot be determined |

---

## `hacs_compatibility_auditor.report_to_rules`

Creates a GitHub issue on the community rules repository ([RmG152/hacs-compatibility-auditor-rules](https://github.com/RmG152/hacs-compatibility-auditor-rules)) with the AI analysis results. 

**Token requirements:** If a GitHub token with write permissions is configured, the issue is created via API. If the API call fails (e.g., token lacks write permissions) or no token is configured, the service returns a fallback URL for manual issue creation using the correct template.

### Request

```yaml
service: hacs_compatibility_auditor.report_to_rules
data:
  repository: "owner/repo-name"
  issue_number: 42
  category: "false_positive"
  reasoning: "The AI determined this issue is a user configuration problem"
  action: "add_false_positive"
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repository` | `string` | **Yes** | Full repository name of the affected package |
| `issue_number` | `integer` | **Yes** | GitHub issue number being reported |
| `category` | `string` | **Yes** | AI categorization result (one of the categories above) |
| `reasoning` | `string` | **Yes** | AI reasoning for the categorization |
| `action` | `string` | **Yes** | `add_false_positive` or `report_incompatibility`. Determines the issue template used |

### Response (API success)

```json
{
  "success": true,
  "issue_url": "https://github.com/RmG152/hacs-compatibility-auditor-rules/issues/1",
  "issue_number": 1
}
```

### Response (API failure — fallback)

When the API cannot create the issue (token lacks write permissions or no token configured), the service returns a fallback response with a pre-filled URL:

```json
{
  "success": false,
  "fallback": true,
  "fallback_url": "https://github.com/RmG152/hacs-compatibility-auditor-rules/issues/new?template=false_positive_report.yml&title=...",
  "fallback_title": "[AI Report] owner/repo#42 - false_positive",
  "fallback_body": "## AI Report: ...",
  "template": "false_positive_report.yml",
  "error": "Could not create issue via API. Use the fallback URL to create it manually."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `fallback_url` | `string` | Pre-filled GitHub URL with the correct template and title |
| `fallback_title` | `string` | Issue title for reference |
| `fallback_body` | `string` | Full issue body in markdown (copy into the template fields) |
| `template` | `string` | Template file name (`false_positive_report.yml` or `blacklist_request.yml`) |

The `action` field determines which template is used:
- `add_false_positive` → [`false_positive_report.yml`](https://github.com/RmG152/hacs-compatibility-auditor-rules/blob/main/.github/ISSUE_TEMPLATE/false_positive_report.yml)
- `report_incompatibility` → [`blacklist_request.yml`](https://github.com/RmG152/hacs-compatibility-auditor-rules/blob/main/.github/ISSUE_TEMPLATE/blacklist_request.yml)

---

## `hacs_compatibility_auditor.ai_analyze_all`

Runs AI analysis on **all packages** that are not in `compatible` or `ignored` status. Reuses the same analysis pipeline as `ai_analyze_package` for each package.

### Request

```yaml
service: hacs_compatibility_auditor.ai_analyze_all
data:
  # provider: "My OpenAI"  # optional
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provider` | `string` | No | Name of the AI provider to use (uses first configured if omitted) |

### Response

```json
{
  "success": true,
  "total": 7,
  "analyzed": 5,
  "errors": 0,
  "results": [
    {
      "repository": "owner/repo-name",
      "status": "warning",
      "ai_result": {
        "verdict": "not_affected",
        "reasoning": "...",
        "confidence": 0.95,
        "provider_used": "Stepfun",
        "raw_response": "...",
        "error": ""
      }
    }
  ],
  "error_details": []
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `total` | `integer` | Total packages evaluated |
| `analyzed` | `integer` | Packages successfully analyzed |
| `errors` | `integer` | Packages that failed analysis |
| `results` | `array` | Array of per-package results (same schema as `ai_analyze_package` result) |
| `error_details` | `array` | Array of `{ repository, error }` for failed packages |

### Behavior

1. Iterates through all stored results
2. Skips packages with `compatible` or `ignored` status
3. For each remaining package, runs `check_package` and then `analyze_package`
4. Updates the stored result with the AI analysis (visible via sensors)
5. Returns aggregated results

---

## `hacs_compatibility_auditor.ai_confirm_report`

Creates a GitHub issue on the community rules repository using **stored AI analysis** for a given package. This allows users to confirm AI verdicts and contribute them to the shared rules database.

**Token requirements:** Same as `report_to_rules` — if the API call fails or no token is configured, returns a fallback URL for manual issue creation.

### Request

```yaml
service: hacs_compatibility_auditor.ai_confirm_report
data:
  repository: "owner/repo-name"
  # action: "add_false_positive"  # optional, derived from verdict if omitted
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repository` | `string` | **Yes** | Full repository name in `owner/repo` format |
| `action` | `string` | No | Override action. Derived from verdict when omitted: `not_affected` → `add_false_positive`, `affected` → `report_incompatibility`. Determines the issue template used |

### Response (API success)

```json
{
  "success": true,
  "issue_url": "https://github.com/RmG152/hacs-compatibility-auditor-rules/issues/5",
  "issue_number": 5,
  "verdict": "not_affected",
  "action": "add_false_positive"
}
```

### Response (API failure — fallback)

```json
{
  "success": false,
  "fallback": true,
  "fallback_url": "https://github.com/RmG152/hacs-compatibility-auditor-rules/issues/new?template=false_positive_report.yml&title=...",
  "fallback_title": "[AI Confirmed] owner/repo - not_affected (95%)",
  "fallback_body": "## AI Confirmed Report...",
  "template": "false_positive_report.yml",
  "verdict": "not_affected",
  "action": "add_false_positive",
  "error": "Could not create issue via API. Use the fallback URL to create it manually."
}
```

### Behavior

1. Looks up the stored AI analysis for the given repository
2. If no AI analysis exists, returns an error (run `ai_analyze_package` or `ai_analyze_all` first)
3. Tries to create a GitHub issue on the rules repo via API
4. On API success, returns the issue URL and number
5. On API failure (or no token), returns a fallback URL pre-filled with the correct template and content for manual creation

---

# AI Data & Frontend Integration

## How AI Data is Stored

AI analysis results are stored in two places:

### 1. In-service response (temporary)

When calling `ai_analyze_package` or `ai_analyze_all`, the AI verdict is returned directly in the service response. This data is not persisted across restarts unless stored via the sensor attributes.

### 2. In sensor attributes (persistent)

After AI analysis runs (either via auto-analyze during batch scan, or via `ai_analyze_package`/`ai_analyze_all` services), the result is stored in the per-package sensor's attributes. Each `sensor.hca_package_*` entity exposes these AI-related attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `ai_verdict` | `string` or `null` | `"affected"`, `"not_affected"`, or `"uncertain"` |
| `ai_confidence` | `float` or `null` | Confidence score (0.0 – 1.0) |
| `ai_reasoning` | `string` | Full AI reasoning text |
| `ai_provider` | `string` | Name of the AI provider used |
| `ai_analysis` | `object` | Complete raw AI result dict (includes all fields above plus `raw_response`) |

These attributes persist in the sensor state until the next scan overwrites them. They survive HA restarts if the underlying result is cached.

### 3. In coordinator data (in-memory)

The AI analysis is also stored in `coordinator.data.results[].ai_analysis` and is included in the global sensor's extra attributes at the `results` key. This is the authoritative source during a session.

## Retrieving AI Data from the Frontend

### Via sensor attributes (recommended)

The simplest way to display AI results in Lovelace is to read the per-package sensor attributes. Each `sensor.hca_package_*` exposes `ai_verdict`, `ai_confidence`, `ai_reasoning`, and `ai_provider`.

Example Lovelace YAML showing a package's AI analysis:

```yaml
type: entity
entity: sensor.hca_package_owner_repo
attribute: ai_verdict
name: AI Verdict
```

For a custom Lovelace card using JavaScript:

```javascript
const entity = hass.states['sensor.hca_package_owner_repo'];
const aiVerdict = entity.attributes.ai_verdict;
const aiConfidence = entity.attributes.ai_confidence;
const aiReasoning = entity.attributes.ai_reasoning;
const aiProvider = entity.attributes.ai_provider;
const aiFull = entity.attributes.ai_analysis;
```

### Via service response (on-demand)

When calling `ai_analyze_package` from a card, the response contains the AI result directly:

```javascript
const result = await hass.callService(
  'hacs_compatibility_auditor',
  'ai_analyze_package',
  { repository: 'owner/repo-name' },
  { returnResponse: true }
);

if (result.success) {
  console.log('Verdict:', result.result.verdict);
  console.log('Confidence:', result.result.confidence);
  console.log('Reasoning:', result.result.reasoning);
}
```

## Adding an AI Analysis Button to Lovelace

To add a button that triggers AI analysis for a specific package and displays the result:

### Button Card (YAML)

```yaml
type: button
name: Analyze with AI
tap_action:
  action: call-service
  service: hacs_compatibility_auditor.ai_analyze_package
  service_data:
    repository: "owner/repo-name"
  confirmation:
    text: "Run AI analysis on this package?"
show_state: true
state_display: >
  [[[
    const ai = states['sensor.hca_package_owner_repo'].attributes;
    if (ai.ai_verdict) return `${ai.ai_verdict} (${Math.round(ai.ai_confidence * 100)}%)`;
    return 'No AI data';
  ]]]
```

### For a per-package card (dynamic repository)

If building a custom card, loop through `hass.states` for entities matching `sensor.hca_package_*`:

```javascript
const packageSensors = Object.keys(hass.states)
  .filter(key => key.startsWith('sensor.hca_package_'))
  .map(key => hass.states[key]);

for (const entity of packageSensors) {
  const attrs = entity.attributes;
  const status = entity.state;
  const repository = attrs.repository;
  const aiVerdict = attrs.ai_verdict;
  const aiConfidence = attrs.ai_confidence;
  const aiReasoning = attrs.ai_reasoning;
  // render card ...
}
```

## Confirmation & Reporting Flow

The intended workflow for users to contribute AI findings to the community rules repository:

### Flow Diagram

```
1. Run AI analysis
   → ai_analyze_all OR ai_analyze_package
   → AI data stored in sensor attributes

2. Review AI verdict in frontend
   → Read ai_verdict, ai_reasoning from sensor attributes
   → User decides if the AI is correct

3. Confirm and report
   → Call ai_confirm_report with the repository name
   → Creates GitHub issue on rules repository
   → Issue URL returned in response

4. (Optional) Use report_to_rules directly
   → For fine-grained control over the report content
```

### Example: Button to confirm and report

```yaml
type: button
name: Confirm AI & Report
tap_action:
  action: call-service
  service: hacs_compatibility_auditor.ai_confirm_report
  service_data:
    repository: "owner/repo-name"
  confirmation:
    text: "Create a GitHub issue on the rules repository with this AI finding?"
show_state: true
state_display: >
  [[[
    return states['sensor.hca_package_owner_repo'].attributes.ai_verdict || '—';
  ]]]
```

### Using Automations

You can also automate confirmation by combining services in a script:

```yaml
alias: "Confirm AI finding for package"
sequence:
  - service: hacs_compatibility_auditor.ai_confirm_report
    data:
      repository: "owner/repo-name"
  - service: notify.persistent_notification
    data:
      title: "AI Report Created"
      message: "Issue created: {{ result.issue_url }}"
    response_variable: result
```

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
