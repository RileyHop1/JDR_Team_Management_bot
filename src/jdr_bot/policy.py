"""Provisional limits for meetings and reminders.

See docs/decisions/0002-meeting-reminders.md. Change these only with that decision.
"""

from datetime import timedelta

MAX_TITLE_LENGTH = 100
MAX_TIMEZONE_LENGTH = 64
MAX_OFFSET_TEXT_LENGTH = 64
MIN_OFFSET_MINUTES = 1
MAX_OFFSET_MINUTES = 7 * 24 * 60
MAX_REMINDER_OFFSETS = 5
LIST_LIMIT = 10

# A reminder is sent only while it is due and no older than this grace period.
# Older scheduled reminders are skipped on recovery instead of arriving late.
DELIVERY_GRACE = timedelta(seconds=60)
POLL_INTERVAL_SECONDS = 5.0
MAX_DELIVERY_ATTEMPTS = 3
RETRY_BASE_SECONDS = 15
CLAIM_BATCH_LIMIT = 10


def retry_delay(attempt_count: int) -> timedelta:
    """Return the wait after a failed attempt. Attempt 1 waits 15s, then 30s."""
    if attempt_count < 1:
        raise ValueError("attempt_count must be positive")
    return timedelta(seconds=RETRY_BASE_SECONDS * (2 ** (attempt_count - 1)))
