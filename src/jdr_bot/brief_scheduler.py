"""Deliver one durable morning-brief job type. Restarts rebuild work from rows."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from jdr_bot.brief import (
    BriefJobRecord,
    BriefSchedule,
    ClaimedBrief,
    plan_brief,
    redirect_retry_channels,
    refresh_unattempted_briefs,
    render_brief,
    render_failure,
    zone_local_date,
)
from jdr_bot.brief_service import BriefService
from jdr_bot.domain import JobState, as_utc
from jdr_bot.policy import CLAIM_BATCH_LIMIT, MAX_DELIVERY_ATTEMPTS, retry_delay
from jdr_bot.ports import (
    BriefDelivery,
    BriefMessage,
    BriefQueryError,
    BriefScheduleSource,
    BriefStore,
    Clock,
    DeliveryError,
    PartialDelivery,
)

logger = logging.getLogger(__name__)


class BriefScheduler:
    """Plan the next weekday brief and deliver a due job.

    A crash after Discord accepts a message but before the receipt is stored
    leaves the job claimed. The next poll marks that claim unreconciled and
    does not send it again. Cancellation during the Jira read, before any
    send, releases that claim so the same local day can still be delivered.
    When a schedule source is injected, each poll reloads it and rewrites
    future never-attempted jobs before planning. An unavailable schedule
    skips the poll and leaves existing rows unchanged.
    See docs/decisions/0003-jira-morning-brief.md and
    docs/decisions/0004-guild-configuration.md.
    """

    def __init__(
        self,
        store: BriefStore,
        delivery: BriefDelivery,
        service: BriefService,
        clock: Clock,
        schedule: BriefSchedule,
        *,
        schedule_source: BriefScheduleSource | None = None,
        max_attempts: int = MAX_DELIVERY_ATTEMPTS,
        batch_limit: int = CLAIM_BATCH_LIMIT,
    ) -> None:
        self._store = store
        self._delivery = delivery
        self._service = service
        self._clock = clock
        self._schedule = schedule
        self._schedule_source = schedule_source
        self._schedule_available = True
        self._max_attempts = max_attempts
        self._batch_limit = batch_limit

    async def run_once(self) -> None:
        """Skip missed days, ensure the next occurrence, and deliver today's job."""
        schedule = await self._resolved_schedule()
        if schedule is None:
            return
        now = as_utc(self._clock.now())
        local_today = zone_local_date(now, schedule.timezone_name)
        unreconciled = await self._store.unreconcile_claims(schedule.guild_id)
        if unreconciled:
            logger.info("briefs_unreconciled count=%s", unreconciled)
        existing = await self._store.list_relevant(schedule.guild_id, local_today)
        await self._apply_schedule(schedule, existing, now)
        existing = await self._store.list_relevant(schedule.guild_id, local_today)
        plan = plan_brief(now, schedule, existing)
        for skip in plan.skips:
            await self._store.apply_skip(skip.job_id, skip.state, skip.category)
            logger.info("brief_not_sent job_id=%s category=%s", skip.job_id, skip.category)
        for draft in plan.inserts:
            inserted = await self._store.insert_job(draft)
            if inserted is None:
                continue
            if draft.failure_category is None:
                logger.info("brief_scheduled job_id=%s", inserted)
            else:
                logger.info(
                    "brief_not_sent job_id=%s category=%s",
                    inserted,
                    draft.failure_category,
                )
        claimed = await self._store.claim_due(
            guild_id=schedule.guild_id,
            now=now,
            local_today=local_today,
            limit=self._batch_limit,
        )
        for job in claimed:
            try:
                await self._deliver(job, now)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "brief_delivery_unhandled job_id=%s error_type=%s",
                    job.job_id,
                    type(exc).__name__,
                )

    async def _resolved_schedule(self) -> BriefSchedule | None:
        if self._schedule_source is None:
            return self._schedule
        try:
            loaded = await self._schedule_source.current_schedule()
        except Exception as exc:
            logger.error("brief_schedule_lookup_failed error_type=%s", type(exc).__name__)
            loaded = None
        if loaded is None and self._schedule_available:
            logger.info("brief_schedule_unavailable")
        elif loaded is not None and not self._schedule_available:
            logger.info("brief_schedule_ready")
        self._schedule_available = loaded is not None
        return loaded

    async def _apply_schedule(
        self, schedule: BriefSchedule, jobs: Sequence[BriefJobRecord], now: datetime
    ) -> None:
        for refresh in refresh_unattempted_briefs(now, schedule, jobs):
            changed = await self._store.apply_refresh(refresh)
            if not changed:
                continue
            if refresh.state is JobState.SKIPPED:
                category = refresh.failure_category or "dst_gap"
                logger.info("brief_not_sent job_id=%s category=%s", refresh.job_id, category)
            else:
                logger.info("brief_rescheduled job_id=%s", refresh.job_id)
        for redirect in redirect_retry_channels(now, schedule, jobs):
            changed = await self._store.redirect_channel(redirect.job_id, redirect.channel_id)
            if changed:
                logger.info("brief_channel_updated job_id=%s", redirect.job_id)

    async def _deliver(self, job: ClaimedBrief, now: datetime) -> None:
        try:
            document = await self._service.collect()
        except asyncio.CancelledError:
            await self._release_unsent(job)
            raise
        except BriefQueryError as error:
            await self._query_failed(job, error, now)
            return
        parts = render_brief(document, local_date=job.local_date, timezone_name=job.timezone_name)
        try:
            receipt = await self._delivery.send_brief(
                BriefMessage(guild_id=job.guild_id, channel_id=job.channel_id, parts=parts)
            )
        except PartialDelivery as error:
            await self._store.record_failure(
                job.job_id,
                job.claim_token,
                category=error.category,
                transient=False,
                max_attempts=self._max_attempts,
                retry_at=None,
                receipt=error.message_id,
            )
            logger.error("brief_partial_delivery job_id=%s", job.job_id)
            return
        except DeliveryError as error:
            await self._retry_or_fail(job, error.category, error.transient, now, receipt=None)
            return
        try:
            stored = await self._store.mark_delivered(
                job.job_id,
                job.claim_token,
                receipt.message_id,
                issue_count=len(document.issues),
            )
        except Exception as exc:
            logger.error(
                "brief_receipt_failed job_id=%s error_type=%s",
                job.job_id,
                type(exc).__name__,
            )
            return
        if not stored:
            logger.error("brief_receipt_rejected job_id=%s", job.job_id)
            return
        logger.info("brief_delivered job_id=%s issue_count=%s", job.job_id, len(document.issues))

    async def _query_failed(self, job: ClaimedBrief, error: BriefQueryError, now: datetime) -> None:
        logger.error(
            "brief_query_failed job_id=%s category=%s transient=%s",
            job.job_id,
            error.category,
            error.transient,
        )
        if error.transient and job.attempt_count < self._max_attempts:
            await self._store.record_failure(
                job.job_id,
                job.claim_token,
                category=error.category,
                transient=True,
                max_attempts=self._max_attempts,
                retry_at=_retry_at(now, job.attempt_count, error.retry_after),
                receipt=None,
            )
            return
        receipt_id: str | None = None
        category = error.category
        try:
            sent = await self._delivery.send_brief(
                BriefMessage(
                    guild_id=job.guild_id,
                    channel_id=job.channel_id,
                    parts=render_failure(
                        project_key=self._schedule.project_key,
                        local_date=job.local_date,
                        timezone_name=job.timezone_name,
                        category=error.category,
                    ),
                )
            )
        except PartialDelivery as delivery_error:
            receipt_id = delivery_error.message_id
            category = delivery_error.category
        except DeliveryError as delivery_error:
            logger.error(
                "brief_failure_notice_failed job_id=%s jira_category=%s discord_category=%s",
                job.job_id,
                error.category,
                delivery_error.category,
            )
            await self._retry_or_fail(
                job,
                error.category,
                delivery_error.transient,
                now,
                receipt=None,
            )
            return
        else:
            receipt_id = sent.message_id
        await self._store.record_failure(
            job.job_id,
            job.claim_token,
            category=category,
            transient=False,
            max_attempts=self._max_attempts,
            retry_at=None,
            receipt=receipt_id,
        )

    async def _retry_or_fail(
        self,
        job: ClaimedBrief,
        category: str,
        transient: bool,
        now: datetime,
        *,
        receipt: str | None,
    ) -> None:
        retry_at = None
        if transient and job.attempt_count < self._max_attempts:
            retry_at = now + retry_delay(job.attempt_count)
        await self._store.record_failure(
            job.job_id,
            job.claim_token,
            category=category,
            transient=transient,
            max_attempts=self._max_attempts,
            retry_at=retry_at,
            receipt=receipt,
        )
        logger.error(
            "brief_delivery_failed job_id=%s category=%s transient=%s",
            job.job_id,
            category,
            transient,
        )

    async def _release_unsent(self, job: ClaimedBrief) -> None:
        """Drop a claim that never reached Discord, even if this task is cancelling."""
        task = asyncio.current_task()
        paused = 0
        if task is not None:
            while task.cancelling():
                task.uncancel()
                paused += 1
        try:
            await self._store.release_claim(job.job_id, job.claim_token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "brief_claim_release_failed job_id=%s error_type=%s",
                job.job_id,
                type(exc).__name__,
            )
        finally:
            if task is not None:
                for _ in range(paused):
                    task.cancel()


def _retry_at(now: datetime, attempt_count: int, retry_after: timedelta | None) -> datetime:
    """Wait at least the provider delay, and at least the usual backoff."""
    delay = retry_delay(attempt_count)
    if retry_after is not None and retry_after > delay:
        delay = retry_after
    return now + delay
