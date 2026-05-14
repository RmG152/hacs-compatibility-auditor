"""Constants for the HACS Compatibility Auditor integration."""

DOMAIN = "hacs_compatibility_auditor"
CONF_GITHUB_TOKEN = "github_token"
CONF_CHECK_INTERVAL = "check_interval"
CONF_ISSUE_LABELS_PRIORITY = "issue_labels_priority"
CONF_IGNORE_LIST = "ignore_list"
CONF_CACHE_HOURS = "cache_hours"
CONF_GITHUB_TIMEOUT = "github_timeout"
CONF_GITHUB_RETRIES = "github_retries"
CONF_BATCH_SIZE = "batch_size"

DEFAULT_CHECK_INTERVAL = 12  # hours
DEFAULT_CACHE_HOURS = 12
DEFAULT_GITHUB_TIMEOUT = 15  # seconds
DEFAULT_GITHUB_RETRIES = 3
DEFAULT_BATCH_SIZE = 5

DEFAULT_ISSUE_LABELS_PRIORITY = [
    "breaking-change",
    "breaking",
    "incompatible",
    "upgrade",
    "compatibility",
    "hacs",
    "home-assistant",
    "ha-version",
    "deprecation",
]

DEFAULT_ISSUE_KEYWORDS = [
    "breaking change",
    "incompatible",
    "not compatible",
    "no longer works",
    "stopped working",
    "does not work",
    "broken after update",
    "upgrade issue",
    "migration required",
    "deprecated",
    "removed in",
    "removed from",
]

# GitHub API
GITHUB_API_BASE = "https://api.github.com"
GITHUB_RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
GITHUB_RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"

# HA version endpoints
HA_RELEASES_URL = "https://api.github.com/repos/home-assistant/core/releases"
HA_PYPI_URL = "https://pypi.org/pypi/homeassistant/json"

# Sensor entity IDs
SENSOR_HA_VERSION_CURRENT = "sensor.ha_version_current"
SENSOR_HA_VERSION_NEXT = "sensor.ha_version_next"
SENSOR_HACS_PACKAGES_TOTAL = "sensor.hacs_packages_total"
SENSOR_HACS_INCOMPATIBLE_COUNT = "sensor.hacs_incompatible_count"

# Compatibility statuses
STATUS_COMPATIBLE = "compatible"
STATUS_WARNING = "warning"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_UNKNOWN = "unknown"
STATUS_IGNORED = "ignored"

# Package types from HACS
PACKAGE_TYPE_INTEGRATION = "integration"
PACKAGE_TYPE_PLUGIN = "plugin"
PACKAGE_TYPE_THEME = "theme"
PACKAGE_TYPE_APPDAEMON = "appdaemon"
PACKAGE_TYPE_NETDAEMON = "netdaemon"
PACKAGE_TYPE_PYTHON_SCRIPT = "python_script"

# Service names
SERVICE_CHECK_NOW = "check_now"
SERVICE_CHECK_PACKAGE = "check_package"

# Platform
PLATFORMS = ["sensor"]

# Signals
SIGNAL_COMPATIBILITY_UPDATED = f"{DOMAIN}_compatibility_updated"

# Rules repository
CONF_RULES_REPO = "rules_repo"
DEFAULT_RULES_REPO = "RmG152/hacs-compatibility-auditor-rules"
CONF_RULES_ENABLED = "rules_enabled"
DEFAULT_RULES_ENABLED = True

RULES_INDEX_FILE = "index.json"
RULES_FILES = [
    "whitelist.yaml",
    "blacklist.yaml",
    "false_positives.yaml",
    "label_overrides.yaml",
    "keyword_overrides.yaml",
]

RULES_CACHE_TTL_SECONDS = 43200  # 12 hours (same interval as the coordinator)

# Default weights (reference for label_overrides and keyword_overrides)
DEFAULT_LABEL_WEIGHTS: dict[str, int] = {
    "breaking-change": 20,
    "breaking": 15,
    "incompatible": 15,
    "deprecation": 10,
    "upgrade": 8,
    "compatibility": 8,
    "bug": 5,
}

DEFAULT_KEYWORD_WEIGHTS: dict[str, int] = {
    "breaking change": 10,
    "incompatible": 8,
    "not compatible": 8,
    "deprecated": 6,
    "stopped working": 5,
    "no longer works": 5,
}
