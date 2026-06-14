"""Cross-app defaults used by URL builders and access control."""

# Demo account: read-only in profile and scrape submission flows.
DEMO_READ_ONLY_USERNAME = 'testuser'

# Fallback `project_name` URL segment when TargetSite.project is unset.
DEFAULT_PROJECT_LIST_SLUG = 'av-aim'

# Former primary project slug — kept for redirects and API aliases.
LEGACY_AIM_PROJECT_SLUG = 'aim-dealers'
