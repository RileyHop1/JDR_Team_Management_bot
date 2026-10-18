"""Provisional limits for the morning brief.

See docs/decisions/0003-jira-morning-brief.md. Change these only with that decision.
Delivery retries reuse the reminder attempt count and backoff in ``jdr_bot.policy``.
"""

PAGE_SIZE = 50
MAX_PAGES = 5
MAX_ISSUES = 100
MAX_SUMMARY_LENGTH = 200
MAX_ASSIGNEE_LENGTH = 80
MAX_STATUS_LENGTH = 80
MESSAGE_LIMIT = 2000
PLAN_HORIZON_DAYS = 14
WEEKDAYS_ONLY = True
REQUEST_TIMEOUT_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 1_000_000
MAX_STATUS_NAMES = 10
MAX_JQL_LENGTH = 500
SEARCH_FIELDS = ("summary", "status", "assignee")
