"""Local brief schedule, including weekday policy and daylight-saving instants."""

from datetime import UTC, date, datetime

import pytest

from jdr_bot.brief import (
    BriefChannelRedirect,
    BriefJobRecord,
    build_default_jql,
    compile_schedule,
    parse_status_names,
    plan_brief,
    redirect_retry_channels,
    refresh_unattempted_briefs,
    resolve_brief_instant,
    validated_base_url,
    validated_jql,
)
from jdr_bot.domain import JobState
from tests.brief_fakes import utc_schedule

UTC_TZ = UTC


def test_default_jql_is_project_and_status_without_assignee():
    query = build_default_jql("JDR", ("In Progress", "Review"))
    assert query == ('project = "JDR" AND status IN ("In Progress", "Review") ORDER BY key ASC')
    assert "assignee" not in query.lower()


def test_custom_jql_replaces_statuses_and_stays_out_of_the_schedule_label():
    schedule = compile_schedule(
        guild_id=123,
        channel_id=10,
        timezone_name="America/Los_Angeles",
        brief_time="09:00",
        base_url="https://example.atlassian.net/",
        project_key="JDR",
        status_names="In Progress",
        custom_jql=" filter = 100 AND project = JDR ",
    )
    assert schedule.jql == "filter = 100 AND project = JDR"
    assert schedule.status_names is None
    assert schedule.browse_base_url == "https://example.atlassian.net"
    assert schedule.weekdays_only is True


def test_status_names_and_urls_reject_unsafe_values():
    assert parse_status_names("In Progress, Review") == ("In Progress", "Review")
    with pytest.raises(ValueError, match="status names"):
        parse_status_names('In "Progress"')
    with pytest.raises(ValueError, match="atlassian.net"):
        validated_base_url("https://user:secret-pass@evil.example/path")
    with pytest.raises(ValueError, match="atlassian.net"):
        validated_base_url("https://example.atlassian.net.evil.com")
    with pytest.raises(ValueError, match="single line"):
        validated_jql("project = JDR\norder by key")


def test_weekday_policy_skips_the_weekend_and_schedules_monday():
    plan = plan_brief(datetime(2026, 6, 6, 12, tzinfo=UTC_TZ), utc_schedule(), ())
    assert [(item.local_date, item.state) for item in plan.inserts] == [
        (date(2026, 6, 8), JobState.SCHEDULED)
    ]
    assert plan.inserts[0].due_at == datetime(2026, 6, 8, 9, tzinfo=UTC_TZ)


def test_same_day_recovery_inserts_today_when_the_morning_has_passed():
    plan = plan_brief(datetime(2026, 6, 1, 11, tzinfo=UTC_TZ), utc_schedule(), ())
    assert plan.inserts[0].local_date == date(2026, 6, 1)
    assert plan.inserts[0].due_at == datetime(2026, 6, 1, 9, tzinfo=UTC_TZ)
    assert plan.inserts[0].state is JobState.SCHEDULED


def test_delivered_today_schedules_the_next_weekday():
    delivered = _job(local_date=date(2026, 6, 1), state=JobState.DELIVERED)
    plan = plan_brief(datetime(2026, 6, 1, 11, tzinfo=UTC_TZ), utc_schedule(), (delivered,))
    assert [item.local_date for item in plan.inserts] == [date(2026, 6, 2)]
    assert plan.skips == ()


def test_missed_previous_day_is_skipped_and_not_backfilled():
    friday = _job(local_date=date(2026, 6, 5), state=JobState.SCHEDULED)
    attempted = _job(
        job_id=2,
        local_date=date(2026, 6, 4),
        state=JobState.SCHEDULED,
        attempt_count=1,
        failure_category="rate_limited",
    )
    plan = plan_brief(datetime(2026, 6, 8, 8, tzinfo=UTC_TZ), utc_schedule(), (friday, attempted))
    assert {(skip.job_id, skip.state, skip.category) for skip in plan.skips} == {
        (1, JobState.SKIPPED, "missed_day"),
        (2, JobState.FAILED, "rate_limited"),
    }
    assert [item.local_date for item in plan.inserts] == [date(2026, 6, 8)]


def test_los_angeles_weekday_offset_changes_across_spring_forward():
    schedule = utc_schedule(timezone_name="America/Los_Angeles")
    before = plan_brief(datetime(2026, 3, 6, 16, tzinfo=UTC_TZ), schedule, ())
    after = plan_brief(datetime(2026, 3, 9, 15, tzinfo=UTC_TZ), schedule, ())
    assert before.inserts[0].due_at == datetime(2026, 3, 6, 17, tzinfo=UTC_TZ)
    assert after.inserts[0].due_at == datetime(2026, 3, 9, 16, tzinfo=UTC_TZ)


def test_los_angeles_weekday_offset_changes_across_fall_back():
    schedule = utc_schedule(timezone_name="America/Los_Angeles")
    before = plan_brief(datetime(2026, 10, 30, 15, tzinfo=UTC_TZ), schedule, ())
    after = plan_brief(datetime(2026, 11, 2, 16, tzinfo=UTC_TZ), schedule, ())
    assert before.inserts[0].due_at == datetime(2026, 10, 30, 16, tzinfo=UTC_TZ)
    assert after.inserts[0].due_at == datetime(2026, 11, 2, 17, tzinfo=UTC_TZ)


def test_sydney_monday_after_spring_forward_uses_the_new_offset():
    schedule = utc_schedule(timezone_name="Australia/Sydney")
    plan = plan_brief(datetime(2026, 10, 4, 21, tzinfo=UTC_TZ), schedule, ())
    assert plan.inserts[0].local_date == date(2026, 10, 5)
    assert plan.inserts[0].due_at == datetime(2026, 10, 4, 22, tzinfo=UTC_TZ)


def test_gap_is_skipped_and_overlap_uses_the_earlier_instant():
    assert resolve_brief_instant(date(2026, 3, 8), "America/Los_Angeles", 2, 30) is None
    assert resolve_brief_instant(date(2026, 10, 4), "Australia/Sydney", 2, 30) is None
    assert resolve_brief_instant(date(2026, 11, 1), "America/Los_Angeles", 1, 30) == datetime(
        2026, 11, 1, 8, 30, tzinfo=UTC_TZ
    )
    assert resolve_brief_instant(date(2026, 4, 5), "Australia/Sydney", 2, 30) == datetime(
        2026, 4, 4, 15, 30, tzinfo=UTC_TZ
    )
    schedule = utc_schedule(
        timezone_name="America/Los_Angeles", hour=2, minute=30, weekdays_only=False
    )
    plan = plan_brief(datetime(2026, 3, 8, 12, tzinfo=UTC_TZ), schedule, ())
    assert [(item.local_date, item.state, item.failure_category) for item in plan.inserts] == [
        (date(2026, 3, 8), JobState.SKIPPED, "dst_gap"),
        (date(2026, 3, 9), JobState.SCHEDULED, None),
    ]
    assert plan.inserts[1].due_at == datetime(2026, 3, 9, 9, 30, tzinfo=UTC_TZ)


def _job(
    *,
    job_id: int = 1,
    local_date: date,
    state: JobState,
    attempt_count: int = 0,
    failure_category: str | None = None,
    channel_id: int = 10,
    timezone_name: str = "UTC",
    due_at: datetime | None = None,
) -> BriefJobRecord:
    return BriefJobRecord(
        id=job_id,
        guild_id=123,
        channel_id=channel_id,
        local_date=local_date,
        due_at=(
            datetime(local_date.year, local_date.month, local_date.day, 9, tzinfo=UTC_TZ)
            if due_at is None
            else due_at
        ),
        timezone_name=timezone_name,
        state=state,
        attempt_count=attempt_count,
        retry_at=None,
        claim_token=None,
        delivery_receipt=None,
        failure_category=failure_category,
        issue_count=None,
    )


def test_future_brief_picks_up_channel_zone_and_time():
    schedule = utc_schedule(channel_id=20, timezone_name="America/Los_Angeles", hour=10, minute=30)
    job = _job(local_date=date(2026, 6, 1), state=JobState.SCHEDULED)
    changes = refresh_unattempted_briefs(datetime(2026, 6, 1, 8, tzinfo=UTC_TZ), schedule, (job,))
    assert len(changes) == 1
    assert changes[0].channel_id == 20
    assert changes[0].timezone_name == "America/Los_Angeles"
    assert changes[0].due_at == datetime(2026, 6, 1, 17, 30, tzinfo=UTC_TZ)
    assert changes[0].state is JobState.SCHEDULED
    assert changes[0].failure_category is None


def test_refresh_leaves_finished_claimed_and_past_jobs():
    schedule = utc_schedule(channel_id=20, hour=10, minute=30)
    now = datetime(2026, 6, 2, 8, tzinfo=UTC_TZ)
    jobs = (
        _job(job_id=1, local_date=date(2026, 6, 1), state=JobState.SCHEDULED),
        _job(job_id=2, local_date=date(2026, 6, 2), state=JobState.DELIVERED),
        _job(job_id=3, local_date=date(2026, 6, 2), state=JobState.CLAIMED),
        _job(job_id=4, local_date=date(2026, 6, 2), state=JobState.SKIPPED),
        _job(job_id=5, local_date=date(2026, 6, 2), state=JobState.FAILED),
        _job(job_id=6, local_date=date(2026, 6, 2), state=JobState.UNRECONCILED),
    )
    assert refresh_unattempted_briefs(now, schedule, jobs) == ()
    assert redirect_retry_channels(now, schedule, jobs) == ()


def test_retry_changes_channel_without_a_new_due_instant():
    schedule = utc_schedule(channel_id=20, hour=11)
    job = _job(
        local_date=date(2026, 6, 1),
        state=JobState.SCHEDULED,
        attempt_count=1,
        failure_category="rate_limited",
    )
    now = datetime(2026, 6, 1, 9, 1, tzinfo=UTC_TZ)
    assert refresh_unattempted_briefs(now, schedule, (job,)) == ()
    assert redirect_retry_channels(now, schedule, (job,)) == (BriefChannelRedirect(1, 20),)
    past = _job(job_id=2, local_date=date(2026, 6, 1), state=JobState.SCHEDULED, attempt_count=1)
    assert redirect_retry_channels(datetime(2026, 6, 2, 8, tzinfo=UTC_TZ), schedule, (past,)) == ()


def test_refresh_marks_a_daylight_saving_gap_and_skips_an_unchanged_job():
    gap = utc_schedule(timezone_name="America/Los_Angeles", hour=2, minute=30, weekdays_only=False)
    job = _job(
        local_date=date(2026, 3, 8),
        state=JobState.SCHEDULED,
        timezone_name="America/Los_Angeles",
        due_at=datetime(2026, 3, 8, 16, tzinfo=UTC_TZ),
    )
    changes = refresh_unattempted_briefs(datetime(2026, 3, 8, 12, tzinfo=UTC_TZ), gap, (job,))
    assert changes[0].state is JobState.SKIPPED
    assert changes[0].failure_category == "dst_gap"
    current = utc_schedule()
    unchanged = _job(local_date=date(2026, 6, 1), state=JobState.SCHEDULED)
    assert (
        refresh_unattempted_briefs(datetime(2026, 6, 1, 8, tzinfo=UTC_TZ), current, (unchanged,))
        == ()
    )
