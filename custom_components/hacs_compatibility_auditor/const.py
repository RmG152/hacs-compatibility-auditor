"""Constants for the HACS Compatibility Auditor integration."""

DOMAIN = "hacs_compatibility_auditor"
CONF_GITHUB_TOKEN = "github_token"
CONF_CHECK_INTERVAL = "check_interval"
CONF_ISSUE_LABELS_PRIORITY = "issue_labels_priority"
CONF_IGNORE_LIST = "ignore_list"
CONF_CACHE_HOURS = "cache_hours"
CONF_GITHUB_TIMEOUT = "github_timeout"
CONF_GITHUB_RETRIES = "github_retries"

DEFAULT_CHECK_INTERVAL = 12  # hours
DEFAULT_CACHE_HOURS = 12
DEFAULT_GITHUB_TIMEOUT = 15  # seconds
DEFAULT_GITHUB_RETRIES = 3

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

# Platform
PLATFORMS = ["sensor"]

# Signals
SIGNAL_COMPATIBILITY_UPDATED = f"{DOMAIN}_compatibility_updated"
