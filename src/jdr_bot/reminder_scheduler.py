"""Durable reminder delivery. One process claims jobs; restarts rebuild work from rows."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from jdr_bot.domain import ClaimedReminder, MeetingState, as_utc
from jdr_bot.policy import (
    CLAIM_BATCH_LIMIT,
    DELIVERY_GRACE,
    MAX_DELIVERY_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    retry_delay,
)
from jdr_bot.ports import (
    Clock,
    DeliveryError,
    MeetingStore,
    ReminderDelivery,
    ReminderNotice,
)

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class ReminderScheduler:
    """Poll durable jobs until cancelled.

    A crash after Discord accepts a message but before the receipt is stored leaves
    the job claimed. That claim is not sent again; once the grace period passes it
    is marked unreconciled. See docs/decisions/0002-meeting-reminders.md.
    """

    def __init__(
        self,
        store: MeetingStore,
        delivery: ReminderDelivery,
        clock: Clock,
        *,
        grace: timedelta = DELIVERY_GRACE,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        max_attempts: int = MAX_DELIVERY_ATTEMPTS,
        batch_limit: int = CLAIM_BATCH_LIMIT,
        sleeper: Sleep | None = None,
    ) -> None:
        self._store = store
        self._delivery = delivery
        self._clock = clock
        self._grace = grace
        self._poll_interval = poll_interval
        self._max_attempts = max_attempts
        self._batch_limit = batch_limit
        self._sleep = asyncio.sleep if sleeper is None else sleeper

    async def serve(self) -> None:
        """Run until the task is cancelled. Storage errors are logged by type only."""
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("reminder_scheduler_failed error_type=%s", type(exc).__name__)
            await self._sleep(self._poll_interval)

    async def run_once(self) -> None:
        """Skip missed reminders, close stale claims, and deliver the due batch."""
        now = as_utc(self._clock.now())
        cutoff = now - self._grace
        skipped = await self._store.skip_missed(due_before=cutoff)
        if skipped:
            logger.info("reminders_skipped count=%s", skipped)
        unreconciled = await self._store.unreconcile_claims(due_before=cutoff)
        if unreconciled:
            logger.info("reminders_unreconciled count=%s", unreconciled)
        claimed = await self._store.claim_due(now=now, due_after=cutoff, limit=self._batch_limit)
        for job in claimed:
            try:
                await self._deliver(job, now)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "reminder_delivery_unhandled job_id=%s error_type=%s",
                    job.job_id,
                    type(exc).__name__,
                )

    async def _deliver(self, job: ClaimedReminder, now: datetime) -> None:
        if job.meeting_state is not MeetingState.SCHEDULED:
            await self._store.mark_claim_cancelled(job.job_id, job.claim_token)
            return
        notice = ReminderNotice(
            meeting_id=job.meeting_id,
            job_id=job.job_id,
            guild_id=job.guild_id,
            text_channel_id=job.text_channel_id,
            voice_channel_id=job.voice_channel_id,
            title=job.title,
            starts_at=job.starts_at,
            timezone_name=job.timezone_name,
            offset_minutes=job.offset_minutes,
        )
        try:
            receipt = await self._delivery.send_reminder(notice)
        except DeliveryError as error:
            retry_at = None
            if error.transient and job.attempt_count < self._max_attempts:
                retry_at = now + retry_delay(job.attempt_count)
            await self._store.record_delivery_failure(
                job.job_id,
                job.claim_token,
                category=error.category,
                transient=error.transient,
                max_attempts=self._max_attempts,
                retry_at=retry_at,
            )
            logger.error(
                "reminder_delivery_failed job_id=%s meeting_id=%s category=%s transient=%s",
                job.job_id,
                job.meeting_id,
                error.category,
                error.transient,
            )
            return
        try:
            stored = await self._store.mark_delivered(
                job.job_id, job.claim_token, receipt.message_id
            )
        except Exception as exc:
            # Discord may already have the message. Leave the claim so it is not sent again.
            logger.error(
                "reminder_receipt_failed job_id=%s error_type=%s",
                job.job_id,
                type(exc).__name__,
            )
            return
        if not stored:
            logger.error("reminder_receipt_rejected job_id=%s", job.job_id)
            return
        logger.info("reminder_delivered job_id=%s meeting_id=%s", job.job_id, job.meeting_id)
