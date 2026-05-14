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

# AI Provider configuration
CONF_AI_ENABLED = "ai_enabled"
CONF_AI_AUTO_ANALYZE = "ai_auto_analyze"
CONF_AI_PROVIDERS = "ai_providers"

DEFAULT_AI_ENABLED = False
DEFAULT_AI_AUTO_ANALYZE = False

PROVIDER_TYPE_OPENAI = "openai_compatible"
PROVIDER_TYPE_GEMINI = "gemini"
PROVIDER_TYPE_ANTHROPIC = "anthropic"
PROVIDER_TYPE_OLLAMA = "ollama"

DEFAULT_PROVIDER_URLS: dict[str, str] = {
    PROVIDER_TYPE_OPENAI: "https://api.openai.com/v1",
    PROVIDER_TYPE_GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    PROVIDER_TYPE_ANTHROPIC: "https://api.anthropic.com",
    PROVIDER_TYPE_OLLAMA: "http://localhost:11434/v1",
}

DEFAULT_PROVIDER_MODELS: dict[str, str] = {
    PROVIDER_TYPE_OPENAI: "gpt-4o-mini",
    PROVIDER_TYPE_GEMINI: "gemini-2.0-flash",
    PROVIDER_TYPE_ANTHROPIC: "claude-sonnet-4-20250514",
    PROVIDER_TYPE_OLLAMA: "llama3.2",
}

CONF_AI_PROVIDER_TYPE = "provider_type"
CONF_AI_PROVIDER_NAME = "name"
CONF_AI_API_KEY = "api_key"
CONF_AI_BASE_URL = "base_url"
CONF_AI_MODEL = "model"
CONF_AI_MAX_TOKENS = "max_tokens"
CONF_AI_TEMPERATURE = "temperature"

DEFAULT_AI_MAX_TOKENS = 1024
DEFAULT_AI_TEMPERATURE = 0.1

# AI categorization categories
AI_CATEGORY_TRUE_POSITIVE = "true_positive"
AI_CATEGORY_FALSE_POSITIVE = "false_positive"
AI_CATEGORY_CONFIG_ISSUE = "config_issue"
AI_CATEGORY_FEATURE_REQUEST = "feature_request"
AI_CATEGORY_UNRELATED = "unrelated"
AI_CATEGORY_UNCERTAIN = "uncertain"

AI_CATEGORIES = [
    AI_CATEGORY_TRUE_POSITIVE,
    AI_CATEGORY_FALSE_POSITIVE,
    AI_CATEGORY_CONFIG_ISSUE,
    AI_CATEGORY_FEATURE_REQUEST,
    AI_CATEGORY_UNRELATED,
    AI_CATEGORY_UNCERTAIN,
]

# AI verdicts
AI_VERDICT_AFFECTED = "affected"
AI_VERDICT_NOT_AFFECTED = "not_affected"
AI_VERDICT_UNCERTAIN = "uncertain"

# Service names
SERVICE_AI_ANALYZE_PACKAGE = "ai_analyze_package"
SERVICE_AI_CATEGORIZE_ISSUE = "ai_categorize_issue"
SERVICE_REPORT_TO_RULES = "report_to_rules"

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
