"""PostgreSQL lifecycle, schema readiness, and meeting persistence."""

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from jdr_bot.domain import (
    ClaimedReminder,
    JobRecord,
    JobState,
    MeetingRecord,
    MeetingState,
    MeetingWrite,
    NewJob,
    NewMeeting,
    as_utc,
)
from jdr_bot.ports import MeetingConflict, MeetingNotEditable, MeetingNotFound, ReminderInProgress

SCHEMA_REVISION = "0004"

_ACTIVE_JOBS = "state IN ('scheduled', 'claimed')"
_OPEN_OCCURRENCES = (
    "state IN ('scheduled', 'claimed', 'delivered', 'skipped', 'failed', 'unreconciled')"
)


class Base(DeclarativeBase):
    """Shared migration metadata."""


class GuildConfiguration(Base):
    """Non-secret per-guild settings. Credentials are never stored in this table.

    Null columns mean "use the environment default". See docs/decisions/0004-guild-configuration.md.
    """

    __tablename__ = "guild_configurations"
    __table_args__ = (
        CheckConstraint(
            "meetings_channel_id IS NULL OR meetings_channel_id > 0",
            name="ck_guild_meetings_channel",
        ),
        CheckConstraint(
            "brief_channel_id IS NULL OR brief_channel_id > 0",
            name="ck_guild_brief_channel",
        ),
        CheckConstraint(
            "timezone IS NULL OR char_length(timezone) BETWEEN 1 AND 64",
            name="ck_guild_timezone",
        ),
        CheckConstraint(
            "brief_time IS NULL OR brief_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
            name="ck_guild_brief_time",
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    meetings_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    brief_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timezone_name: Mapped[str | None] = mapped_column("timezone", String(64), nullable=True)
    brief_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingRow(Base):
    """One scheduled or cancelled meeting."""

    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 1 AND 100", name="ck_meetings_title"),
        CheckConstraint("state IN ('scheduled', 'cancelled')", name="ck_meetings_state"),
        CheckConstraint(
            "text_channel_id > 0 AND voice_channel_id > 0", name="ck_meetings_channels"
        ),
        CheckConstraint(
            "text_channel_id <> voice_channel_id", name="ck_meetings_distinct_channels"
        ),
        CheckConstraint("char_length(timezone) BETWEEN 1 AND 64", name="ck_meetings_timezone"),
        CheckConstraint("organizer_id > 0", name="ck_meetings_organizer"),
        Index("ix_meetings_guild_start", "guild_id", "state", "starts_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guild_configurations.guild_id"))
    title: Mapped[str] = mapped_column(String(100))
    text_channel_id: Mapped[int] = mapped_column(BigInteger)
    voice_channel_id: Mapped[int] = mapped_column(BigInteger)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str] = mapped_column("timezone", String(64))
    organizer_id: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReminderJobRow(Base):
    """One reminder occurrence. Active offsets and due instants are unique."""

    __tablename__ = "reminder_jobs"
    __table_args__ = (
        CheckConstraint("offset_minutes BETWEEN 1 AND 10080", name="ck_reminder_offset"),
        CheckConstraint("attempt_count >= 0", name="ck_reminder_attempts"),
        CheckConstraint(
            "state IN ('scheduled', 'claimed', 'delivered', 'skipped', 'failed', "
            "'cancelled', 'unreconciled')",
            name="ck_reminder_state",
        ),
        Index(
            "uq_reminder_active_offset",
            "meeting_id",
            "offset_minutes",
            unique=True,
            postgresql_where=text(_ACTIVE_JOBS),
        ),
        Index(
            "uq_reminder_occurrence",
            "meeting_id",
            "offset_minutes",
            "due_at",
            unique=True,
            postgresql_where=text(_OPEN_OCCURRENCES),
        ),
        Index("ix_reminder_jobs_due", "state", "due_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("meetings.id", ondelete="CASCADE")
    )
    offset_minutes: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(32))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_receipt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)


def create_engine(database_url: str) -> AsyncEngine:
    """Create a bounded pool without connecting or exposing parameters in errors."""
    return create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 10, "options": "-c statement_timeout=10000"},
    )


async def check_database(engine: AsyncEngine) -> None:
    """Verify connectivity and migration revision before registering commands."""
    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != SCHEMA_REVISION:
            raise RuntimeError("database schema is outdated; run uv run alembic upgrade head")


class SqlMeetingStore:
    """Transactional meeting and reminder persistence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def insert_meeting(self, draft: NewMeeting, jobs: Sequence[NewJob]) -> MeetingRecord:
        try:
            async with self._sessions() as session, session.begin():
                await session.execute(
                    pg_insert(GuildConfiguration)
                    .values(guild_id=draft.guild_id)
                    .on_conflict_do_nothing(index_elements=[GuildConfiguration.guild_id])
                )
                created_at = as_utc(draft.created_at)
                meeting = MeetingRow(
                    guild_id=draft.guild_id,
                    title=draft.title,
                    text_channel_id=draft.text_channel_id,
                    voice_channel_id=draft.voice_channel_id,
                    starts_at=as_utc(draft.starts_at),
                    timezone_name=draft.timezone_name,
                    organizer_id=draft.organizer_id,
                    state=MeetingState.SCHEDULED.value,
                    created_at=created_at,
                    updated_at=created_at,
                )
                session.add(meeting)
                await session.flush()
                for job in jobs:
                    session.add(_new_job(meeting.id, job))
                await session.flush()
                return _meeting_record(meeting, await _load_jobs(session, meeting.id))
        except IntegrityError:
            raise MeetingConflict from None

    async def get_meeting(self, guild_id: int, meeting_id: int) -> MeetingRecord | None:
        async with self._sessions() as session:
            meeting = await session.scalar(
                select(MeetingRow).where(
                    MeetingRow.id == meeting_id, MeetingRow.guild_id == guild_id
                )
            )
            if meeting is None:
                return None
            return _meeting_record(meeting, await _load_jobs(session, meeting.id))

    async def list_meetings(
        self, guild_id: int, state: MeetingState | None, limit: int
    ) -> list[MeetingRecord]:
        async with self._sessions() as session:
            statement = (
                select(MeetingRow)
                .where(MeetingRow.guild_id == guild_id)
                .order_by(MeetingRow.starts_at, MeetingRow.id)
                .limit(limit)
            )
            if state is not None:
                statement = statement.where(MeetingRow.state == state.value)
            meetings = (await session.scalars(statement)).all()
            return [
                _meeting_record(meeting, await _load_jobs(session, meeting.id))
                for meeting in meetings
            ]

    async def update_meeting(
        self, guild_id: int, meeting_id: int, write: MeetingWrite
    ) -> MeetingRecord:
        try:
            async with self._sessions() as session, session.begin():
                meeting = await _lock_meeting(session, guild_id, meeting_id)
                jobs = await _lock_jobs(session, meeting.id)
                if meeting.state != MeetingState.SCHEDULED.value:
                    raise MeetingNotEditable(MeetingState(meeting.state))
                if write.replace_jobs and any(job.state == JobState.CLAIMED.value for job in jobs):
                    raise ReminderInProgress
                meeting.title = write.title
                meeting.text_channel_id = write.text_channel_id
                meeting.voice_channel_id = write.voice_channel_id
                meeting.starts_at = as_utc(write.starts_at)
                meeting.timezone_name = write.timezone_name
                meeting.updated_at = as_utc(write.updated_at)
                if write.replace_jobs:
                    cancel_ids = set(write.rewrite.cancel_ids)
                    for job in jobs:
                        if job.id in cancel_ids and job.state == JobState.SCHEDULED.value:
                            job.state = JobState.CANCELLED.value
                            job.claim_token = None
                            job.retry_at = None
                    # Flush the cancellations before inserts so the active-offset
                    # unique index does not see the old and new rows together.
                    await session.flush()
                    for draft in write.rewrite.new_jobs:
                        session.add(_new_job(meeting.id, draft))
                    await session.flush()
                return _meeting_record(meeting, await _load_jobs(session, meeting.id))
        except IntegrityError:
            raise MeetingConflict from None

    async def cancel_meeting(
        self, guild_id: int, meeting_id: int, updated_at: datetime
    ) -> MeetingRecord:
        async with self._sessions() as session, session.begin():
            meeting = await _lock_meeting(session, guild_id, meeting_id)
            jobs = await _lock_jobs(session, meeting.id)
            if meeting.state != MeetingState.SCHEDULED.value:
                raise MeetingNotEditable(MeetingState(meeting.state))
            if any(job.state == JobState.CLAIMED.value for job in jobs):
                raise ReminderInProgress
            meeting.state = MeetingState.CANCELLED.value
            meeting.updated_at = as_utc(updated_at)
            for job in jobs:
                if job.state == JobState.SCHEDULED.value:
                    job.state = JobState.CANCELLED.value
                    job.claim_token = None
                    job.retry_at = None
            return _meeting_record(meeting, jobs)

    async def skip_missed(self, *, due_before: datetime) -> int:
        """Skip never-attempted reminders. Attempted ones become failed."""
        cutoff = as_utc(due_before)
        async with self._sessions() as session, session.begin():
            skipped = await session.scalars(
                update(ReminderJobRow)
                .where(
                    ReminderJobRow.state == JobState.SCHEDULED.value,
                    ReminderJobRow.due_at < cutoff,
                    ReminderJobRow.attempt_count == 0,
                )
                .values(
                    state=JobState.SKIPPED.value,
                    failure_category="missed_window",
                    retry_at=None,
                    claim_token=None,
                )
                .returning(ReminderJobRow.id)
            )
            failed = await session.scalars(
                update(ReminderJobRow)
                .where(
                    ReminderJobRow.state == JobState.SCHEDULED.value,
                    ReminderJobRow.due_at < cutoff,
                    ReminderJobRow.attempt_count > 0,
                )
                .values(
                    state=JobState.FAILED.value,
                    failure_category=func.coalesce(
                        ReminderJobRow.failure_category, "retry_window_elapsed"
                    ),
                    retry_at=None,
                    claim_token=None,
                )
                .returning(ReminderJobRow.id)
            )
            return len(skipped.all()) + len(failed.all())

    async def unreconcile_claims(self, *, due_before: datetime) -> int:
        """Close claims whose delivery window passed without a second send."""
        cutoff = as_utc(due_before)
        async with self._sessions() as session, session.begin():
            result = await session.scalars(
                update(ReminderJobRow)
                .where(
                    ReminderJobRow.state == JobState.CLAIMED.value,
                    ReminderJobRow.due_at < cutoff,
                )
                .values(
                    state=JobState.UNRECONCILED.value,
                    failure_category="receipt_unknown",
                    claim_token=None,
                    claimed_at=None,
                    retry_at=None,
                )
                .returning(ReminderJobRow.id)
            )
            return len(result.all())

    async def claim_due(
        self, *, now: datetime, due_after: datetime, limit: int
    ) -> list[ClaimedReminder]:
        current = as_utc(now)
        earliest = as_utc(due_after)
        async with self._sessions() as session, session.begin():
            rows = (
                await session.execute(
                    select(ReminderJobRow, MeetingRow)
                    .join(MeetingRow, ReminderJobRow.meeting_id == MeetingRow.id)
                    .where(
                        ReminderJobRow.state == JobState.SCHEDULED.value,
                        MeetingRow.state == MeetingState.SCHEDULED.value,
                        ReminderJobRow.due_at >= earliest,
                        ReminderJobRow.due_at <= current,
                        or_(ReminderJobRow.retry_at.is_(None), ReminderJobRow.retry_at <= current),
                    )
                    .order_by(ReminderJobRow.due_at, ReminderJobRow.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True, of=ReminderJobRow)
                )
            ).all()
            claimed: list[ClaimedReminder] = []
            for job, meeting in rows:
                token = uuid4().hex
                job.state = JobState.CLAIMED.value
                job.claim_token = token
                job.claimed_at = current
                job.attempt_count += 1
                job.retry_at = None
                claimed.append(
                    ClaimedReminder(
                        job_id=job.id,
                        claim_token=token,
                        attempt_count=job.attempt_count,
                        meeting_id=meeting.id,
                        guild_id=meeting.guild_id,
                        title=meeting.title,
                        text_channel_id=meeting.text_channel_id,
                        voice_channel_id=meeting.voice_channel_id,
                        starts_at=as_utc(meeting.starts_at),
                        timezone_name=meeting.timezone_name,
                        offset_minutes=job.offset_minutes,
                        meeting_state=MeetingState(meeting.state),
                    )
                )
            return claimed

    async def mark_delivered(self, job_id: int, claim_token: str, receipt: str) -> bool:
        async with self._sessions() as session, session.begin():
            delivered_id = await session.scalar(
                update(ReminderJobRow)
                .where(
                    ReminderJobRow.id == job_id,
                    ReminderJobRow.claim_token == claim_token,
                    ReminderJobRow.state == JobState.CLAIMED.value,
                )
                .values(
                    state=JobState.DELIVERED.value,
                    delivery_receipt=receipt[:64],
                    claim_token=None,
                    failure_category=None,
                )
                .returning(ReminderJobRow.id)
            )
        return delivered_id is not None

    async def mark_claim_cancelled(self, job_id: int, claim_token: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(ReminderJobRow)
                .where(
                    ReminderJobRow.id == job_id,
                    ReminderJobRow.claim_token == claim_token,
                    ReminderJobRow.state == JobState.CLAIMED.value,
                )
                .values(
                    state=JobState.CANCELLED.value,
                    claim_token=None,
                    retry_at=None,
                )
            )

    async def record_delivery_failure(
        self,
        job_id: int,
        claim_token: str,
        *,
        category: str,
        transient: bool,
        max_attempts: int,
        retry_at: datetime | None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(ReminderJobRow)
                .where(
                    ReminderJobRow.id == job_id,
                    ReminderJobRow.claim_token == claim_token,
                    ReminderJobRow.state == JobState.CLAIMED.value,
                )
                .with_for_update()
            )
            if job is None:
                return
            safe_category = category[:64]
            terminal = (not transient) or retry_at is None or job.attempt_count >= max_attempts
            job.claim_token = None
            job.failure_category = safe_category
            if terminal:
                job.state = JobState.FAILED.value
                job.retry_at = None
            else:
                job.state = JobState.SCHEDULED.value
                job.claimed_at = None
                job.retry_at = as_utc(retry_at) if retry_at is not None else None


def _new_job(meeting_id: int, draft: NewJob) -> ReminderJobRow:
    return ReminderJobRow(
        meeting_id=meeting_id,
        offset_minutes=draft.offset_minutes,
        due_at=as_utc(draft.due_at),
        state=JobState.SCHEDULED.value,
        attempt_count=0,
    )


def _meeting_record(meeting: MeetingRow, jobs: list[ReminderJobRow]) -> MeetingRecord:
    ordered = sorted(jobs, key=lambda job: (job.due_at, job.id))
    return MeetingRecord(
        id=meeting.id,
        guild_id=meeting.guild_id,
        title=meeting.title,
        text_channel_id=meeting.text_channel_id,
        voice_channel_id=meeting.voice_channel_id,
        starts_at=as_utc(meeting.starts_at),
        timezone_name=meeting.timezone_name,
        organizer_id=meeting.organizer_id,
        state=MeetingState(meeting.state),
        created_at=as_utc(meeting.created_at),
        updated_at=as_utc(meeting.updated_at),
        jobs=tuple(_job_record(job) for job in ordered),
    )


def _job_record(job: ReminderJobRow) -> JobRecord:
    return JobRecord(
        id=job.id,
        meeting_id=job.meeting_id,
        offset_minutes=job.offset_minutes,
        due_at=as_utc(job.due_at),
        state=JobState(job.state),
        attempt_count=job.attempt_count,
        retry_at=as_utc(job.retry_at) if job.retry_at is not None else None,
        claim_token=job.claim_token,
        delivery_receipt=job.delivery_receipt,
        failure_category=job.failure_category,
    )


async def _lock_meeting(session: AsyncSession, guild_id: int, meeting_id: int) -> MeetingRow:
    meeting = await session.scalar(
        select(MeetingRow)
        .where(MeetingRow.id == meeting_id, MeetingRow.guild_id == guild_id)
        .with_for_update()
    )
    if meeting is None:
        raise MeetingNotFound
    return meeting


async def _lock_jobs(session: AsyncSession, meeting_id: int) -> list[ReminderJobRow]:
    return list(
        (
            await session.scalars(
                select(ReminderJobRow)
                .where(ReminderJobRow.meeting_id == meeting_id)
                .with_for_update()
            )
        ).all()
    )


async def _load_jobs(session: AsyncSession, meeting_id: int) -> list[ReminderJobRow]:
    return list(
        (
            await session.scalars(
                select(ReminderJobRow).where(ReminderJobRow.meeting_id == meeting_id)
            )
        ).all()
    )
