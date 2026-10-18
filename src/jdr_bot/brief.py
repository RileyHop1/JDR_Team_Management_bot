"""Morning-brief schedule, query text, and Discord rendering.

No Discord, Jira, or database I/O. See docs/decisions/0003-jira-morning-brief.md.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jdr_bot.brief_policy import (
    MAX_ASSIGNEE_LENGTH,
    MAX_JQL_LENGTH,
    MAX_STATUS_LENGTH,
    MAX_STATUS_NAMES,
    MAX_SUMMARY_LENGTH,
    MESSAGE_LIMIT,
    PLAN_HORIZON_DAYS,
    WEEKDAYS_ONLY,
)
from jdr_bot.domain import JobState, as_utc

_PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9]{1,9}\Z")
_ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9]{1,9}-\d{1,18}\Z")
_STATUS_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/()'+-]{0,39}\Z")
_BRIEF_TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)\Z")
_MENTION = re.compile(r"(?i)@(everyone|here)")
_SAFE_CATEGORY = re.compile(r"[a-z0-9_]{1,64}\Z")

EMPTY_BRIEF_LINE = "No issues match the configured Jira query."
FAILURE_BRIEF_PREFIX = "The morning brief could not be loaded"

_OPEN_STATES = frozenset({JobState.SCHEDULED, JobState.CLAIMED})
_OCCUPYING_STATES = frozenset(
    {
        JobState.SCHEDULED,
        JobState.CLAIMED,
        JobState.DELIVERED,
        JobState.SKIPPED,
        JobState.FAILED,
        JobState.UNRECONCILED,
    }
)


@dataclass(frozen=True)
class BriefSchedule:
    """One guild's brief timing and read-only query. No credentials."""

    guild_id: int
    channel_id: int
    timezone_name: str
    hour: int
    minute: int
    project_key: str
    browse_base_url: str
    jql: str
    status_names: tuple[str, ...] | None
    weekdays_only: bool = WEEKDAYS_ONLY


@dataclass(frozen=True)
class BriefIssueView:
    """One issue as the brief will describe it. No description or comments."""

    key: str
    summary: str
    status_name: str
    assignee_display_name: str | None


@dataclass(frozen=True)
class BriefDocument:
    """A successful query. An empty issue list is success, not a failure."""

    project_key: str
    browse_base_url: str
    status_names: tuple[str, ...] | None
    issues: tuple[BriefIssueView, ...]
    truncated: bool


@dataclass(frozen=True)
class BriefJobRecord:
    """One stored brief occurrence. Issue text is not stored."""

    id: int
    guild_id: int
    channel_id: int
    local_date: date
    due_at: datetime
    timezone_name: str
    state: JobState
    attempt_count: int
    retry_at: datetime | None
    claim_token: str | None
    delivery_receipt: str | None
    failure_category: str | None
    issue_count: int | None


@dataclass(frozen=True)
class NewBriefJob:
    guild_id: int
    channel_id: int
    local_date: date
    due_at: datetime
    timezone_name: str
    state: JobState
    failure_category: str | None


@dataclass(frozen=True)
class BriefSkip:
    job_id: int
    state: JobState
    category: str


@dataclass(frozen=True)
class BriefPlan:
    skips: tuple[BriefSkip, ...]
    inserts: tuple[NewBriefJob, ...]


@dataclass(frozen=True)
class ClaimedBrief:
    """Snapshot taken when a worker claims a job, before Jira is called."""

    job_id: int
    claim_token: str
    attempt_count: int
    guild_id: int
    channel_id: int
    local_date: date
    due_at: datetime
    timezone_name: str


def validated_project_key(value: str) -> str:
    """Return a Jira project key, or raise ValueError without echoing it."""
    key = value.strip()
    if _PROJECT_KEY.fullmatch(key) is None:
        raise ValueError("JIRA_PROJECT_KEY must be an uppercase project key")
    return key


def validated_base_url(value: str) -> str:
    """Return ``https://<site>.atlassian.net`` with no credentials or path."""
    parts = urlsplit(value.strip())
    host = parts.hostname
    if (
        parts.scheme != "https"
        or host is None
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
        or not host.endswith(".atlassian.net")
        or host == ".atlassian.net"
        or ".." in host
        or host.startswith(".")
        or parts.port not in (None, 443)
    ):
        raise ValueError("JIRA_BASE_URL must be an https://<site>.atlassian.net URL")
    return f"https://{host}"


def validated_email(value: str) -> str:
    """Return a single email address, or raise ValueError without echoing it."""
    email = value.strip()
    if len(email) > 254 or email.count("@") != 1 or any(char.isspace() for char in email):
        raise ValueError("JIRA_USER_EMAIL must be a single email address")
    local, _, domain = email.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("JIRA_USER_EMAIL must be a single email address")
    return email


def validated_jql(value: str) -> str:
    """Return a single-line JQL string. The caller must not log it."""
    jql = value.strip()
    if not jql or len(jql) > MAX_JQL_LENGTH or any(ord(char) < 32 for char in jql):
        raise ValueError("JIRA_JQL must be a single line up to 500 characters")
    return jql


def parse_brief_time(value: str) -> tuple[int, int]:
    """Parse ``HH:MM`` in 24-hour form."""
    match = _BRIEF_TIME.fullmatch(value.strip())
    if match is None:
        raise ValueError("BRIEF_TIME must be HH:MM in 24-hour time")
    return int(match.group(1)), int(match.group(2))


def parse_status_names(value: str | None) -> tuple[str, ...]:
    """Parse comma-separated status names. Empty input returns no names."""
    if value is None or not value.strip():
        return ()
    names = tuple(part.strip() for part in value.split(","))
    if len(names) > MAX_STATUS_NAMES:
        raise ValueError("JIRA_STATUS_NAMES accepts at most 10 statuses")
    if any(not name or _STATUS_NAME.fullmatch(name) is None for name in names):
        raise ValueError("JIRA_STATUS_NAMES must be comma-separated status names")
    if len(set(names)) != len(names):
        raise ValueError("JIRA_STATUS_NAMES must not repeat a status")
    return names


def issue_key_is_safe(value: str) -> bool:
    """True when a key can be placed in a browse path."""
    return _ISSUE_KEY.fullmatch(value) is not None


def build_default_jql(project_key: str, status_names: Sequence[str]) -> str:
    """Build the provisional project-and-status query. It does not filter assignees."""
    quoted = ", ".join(f'"{name}"' for name in status_names)
    return f'project = "{project_key}" AND status IN ({quoted}) ORDER BY key ASC'


def compile_schedule(
    *,
    guild_id: int,
    channel_id: int,
    timezone_name: str,
    brief_time: str,
    base_url: str,
    project_key: str,
    status_names: str | None,
    custom_jql: str | None,
) -> BriefSchedule:
    """Validate brief settings into a schedule. Raises ValueError with no secret text."""
    if channel_id <= 0 or channel_id >= 2**63:
        raise ValueError("brief_channel_id must be a positive Discord channel id")
    if not timezone_name or len(timezone_name) > 64:
        raise ValueError("use an IANA time zone such as America/Los_Angeles")
    hour, minute = parse_brief_time(brief_time)
    key = validated_project_key(project_key)
    browse = validated_base_url(base_url)
    custom = None
    if custom_jql is not None and custom_jql.strip():
        custom = validated_jql(custom_jql)
    names = None if custom is not None else parse_status_names(status_names)
    if custom is None and not names:
        raise ValueError("set JIRA_STATUS_NAMES or JIRA_JQL")
    jql = custom if custom is not None else build_default_jql(key, names or ())
    return BriefSchedule(
        guild_id=guild_id,
        channel_id=channel_id,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        project_key=key,
        browse_base_url=browse,
        jql=jql,
        status_names=names,
        weekdays_only=WEEKDAYS_ONLY,
    )


def resolve_brief_instant(
    local_date: date, timezone_name: str, hour: int, minute: int
) -> datetime | None:
    """Return the UTC instant for a local wall time.

    A spring-forward gap returns None. A fall-back overlap returns the earlier
    instant. Both folds are checked so the result is not a guess.
    """
    naive = datetime(local_date.year, local_date.month, local_date.day, hour, minute)
    zone = ZoneInfo(timezone_name)
    first = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    second = naive.replace(tzinfo=zone, fold=1).astimezone(UTC)
    first_matches = first.astimezone(zone).replace(tzinfo=None) == naive
    second_matches = second.astimezone(zone).replace(tzinfo=None) == naive
    if not first_matches or not second_matches:
        return None
    if first <= second:
        return first
    return second


def zone_local_date(now: datetime, timezone_name: str) -> date:
    """Return the calendar date of an aware instant in an IANA zone."""
    return as_utc(now).astimezone(ZoneInfo(timezone_name)).date()


def plan_brief(now: datetime, schedule: BriefSchedule, jobs: Sequence[BriefJobRecord]) -> BriefPlan:
    """Choose skips and the next insert. Does not backfill days that have no row.

    A scheduled row from an earlier local date is skipped or failed. At most one
    new occurrence is added, except a daylight-saving gap which is recorded as
    skipped and followed by the next schedulable date.
    """
    current = as_utc(now)
    local_today = zone_local_date(current, schedule.timezone_name)
    skips: list[BriefSkip] = []
    for job in jobs:
        if job.state is not JobState.SCHEDULED:
            continue
        if job.local_date < local_today:
            if job.attempt_count == 0:
                skips.append(BriefSkip(job.id, JobState.SKIPPED, "missed_day"))
            else:
                category = job.failure_category or "retry_window_elapsed"
                skips.append(BriefSkip(job.id, JobState.FAILED, category))
        elif schedule.weekdays_only and job.local_date.weekday() >= 5:
            skips.append(BriefSkip(job.id, JobState.SKIPPED, "weekend"))
    skip_ids = {skip.job_id for skip in skips}
    occupied = {job.local_date for job in jobs if job.state in _OCCUPYING_STATES}
    open_dates = {
        job.local_date for job in jobs if job.state in _OPEN_STATES and job.id not in skip_ids
    }
    inserts: list[NewBriefJob] = []
    cursor = local_today
    for _ in range(PLAN_HORIZON_DAYS):
        if schedule.weekdays_only and cursor.weekday() >= 5:
            cursor += timedelta(days=1)
            continue
        if cursor in occupied:
            if cursor in open_dates:
                break
            cursor += timedelta(days=1)
            continue
        due = resolve_brief_instant(cursor, schedule.timezone_name, schedule.hour, schedule.minute)
        if due is None:
            inserts.append(_skipped_gap(schedule, cursor))
            occupied.add(cursor)
            cursor += timedelta(days=1)
            continue
        if cursor == local_today or due > current:
            inserts.append(_scheduled(schedule, cursor, due))
            break
        cursor += timedelta(days=1)
    return BriefPlan(skips=tuple(skips), inserts=tuple(inserts))


def render_brief(
    document: BriefDocument,
    *,
    local_date: date,
    timezone_name: str,
    limit: int = MESSAGE_LIMIT,
) -> tuple[str, ...]:
    """Render a successful query, including the explicit empty result."""
    lines = [_header(document.project_key, local_date, timezone_name, continued=False)]
    if document.status_names is None:
        lines.append("Using the configured Jira query.")
    else:
        lines.append("Statuses: " + ", ".join(document.status_names))
    if not document.issues:
        lines.append(EMPTY_BRIEF_LINE)
    else:
        lines.append(f"{len(document.issues)} issues:")
        for issue in document.issues:
            lines.extend(_issue_lines(issue, document.browse_base_url))
    if document.truncated:
        lines.append(f"Showing the first {len(document.issues)} matching issues.")
    return _pack(lines, limit, document.project_key, local_date, timezone_name)


def render_failure(
    *, project_key: str, local_date: date, timezone_name: str, category: str
) -> tuple[str, ...]:
    """Render a terminal query failure. The category is a stable label, not Jira text."""
    safe = category if _SAFE_CATEGORY.fullmatch(category) else "query_failed"
    body = (
        f"{_header(project_key, local_date, timezone_name, continued=False)}\n"
        f"{FAILURE_BRIEF_PREFIX} ({safe})."
    )
    return (body,)


def suppress_mentions(text: str) -> str:
    """Break mention syntax. Discord delivery also sets allowed mentions to none."""
    visible = "".join(char if ord(char) >= 32 else " " for char in text)
    hidden = visible.replace("<@", "<\u200b@").replace("<#", "<\u200b#")
    return _MENTION.sub(lambda match: "@\u200b" + match.group(1), hidden)


def clean_issue_text(value: str, limit: int) -> str:
    """Collapse whitespace, suppress mentions, and truncate a displayed field."""
    collapsed = " ".join(suppress_mentions(value).split())
    if len(collapsed) <= limit:
        return collapsed
    if limit <= 3:
        return collapsed[:limit]
    return collapsed[: limit - 3] + "..."


def _scheduled(schedule: BriefSchedule, local_date: date, due_at: datetime) -> NewBriefJob:
    return NewBriefJob(
        guild_id=schedule.guild_id,
        channel_id=schedule.channel_id,
        local_date=local_date,
        due_at=due_at,
        timezone_name=schedule.timezone_name,
        state=JobState.SCHEDULED,
        failure_category=None,
    )


def _skipped_gap(schedule: BriefSchedule, local_date: date) -> NewBriefJob:
    return NewBriefJob(
        guild_id=schedule.guild_id,
        channel_id=schedule.channel_id,
        local_date=local_date,
        due_at=_gap_due_at(local_date, schedule.timezone_name),
        timezone_name=schedule.timezone_name,
        state=JobState.SKIPPED,
        failure_category="dst_gap",
    )


def _gap_due_at(local_date: date, timezone_name: str) -> datetime:
    """Store local midnight for a skipped gap. The row is never claimed."""
    midnight = resolve_brief_instant(local_date, timezone_name, 0, 0)
    if midnight is not None:
        return midnight
    return datetime(local_date.year, local_date.month, local_date.day, tzinfo=UTC)


def _header(project_key: str, local_date: date, timezone_name: str, *, continued: bool) -> str:
    suffix = " (continued)" if continued else ""
    return f"Morning brief for {project_key}{suffix} - {local_date.isoformat()} {timezone_name}"


def _issue_lines(issue: BriefIssueView, browse_base_url: str) -> tuple[str, str]:
    summary = clean_issue_text(issue.summary, MAX_SUMMARY_LENGTH)
    status = clean_issue_text(issue.status_name, MAX_STATUS_LENGTH)
    if issue.assignee_display_name is None or not issue.assignee_display_name.strip():
        assignee = "unassigned"
    else:
        assignee = clean_issue_text(issue.assignee_display_name, MAX_ASSIGNEE_LENGTH)
    return (
        f"- {issue.key}: {summary} | {assignee} | {status}",
        f"  {browse_base_url}/browse/{issue.key}",
    )


def _pack(
    lines: list[str],
    limit: int,
    project_key: str,
    local_date: date,
    timezone_name: str,
) -> tuple[str, ...]:
    chunks: list[str] = []
    current: list[str] = []
    opening = True

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append("\n".join(current))
            current = []

    def append_line(line: str) -> None:
        nonlocal current
        if len(line) > limit:
            flush()
            start = 0
            while start < len(line):
                chunks.append(line[start : start + limit])
                start += limit
            return
        if current and not _fits(current, line, limit):
            flush()
        current.append(line)

    for line in lines:
        if current and not _fits(current, line, limit):
            flush()
            if not opening:
                continuation = _header(project_key, local_date, timezone_name, continued=True)
                append_line(continuation)
                if current and not _fits(current, line, limit):
                    flush()
        append_line(line)
        opening = False
    flush()
    if not chunks:
        chunks.append(_header(project_key, local_date, timezone_name, continued=False))
    return tuple(chunks)


def _fits(current: list[str], line: str, limit: int) -> bool:
    if not current:
        return len(line) <= limit
    return len("\n".join(current)) + 1 + len(line) <= limit
