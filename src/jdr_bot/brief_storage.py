"""PostgreSQL persistence for morning-brief jobs. Issue text is not stored."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from jdr_bot.brief import BriefJobRecord, ClaimedBrief, NewBriefJob
from jdr_bot.domain import JobState, as_utc
from jdr_bot.storage import Base, GuildConfiguration

_OPEN = (JobState.SCHEDULED.value, JobState.CLAIMED.value)


class BriefJobRow(Base):
    """One local-date brief. Active delivery state lives here, not in reminder_jobs."""

    __tablename__ = "brief_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('scheduled', 'claimed', 'delivered', 'skipped', 'failed', 'unreconciled')",
            name="ck_brief_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_brief_attempts"),
        CheckConstraint("channel_id > 0", name="ck_brief_channel"),
        CheckConstraint("char_length(timezone) BETWEEN 1 AND 64", name="ck_brief_timezone"),
        CheckConstraint("issue_count IS NULL OR issue_count >= 0", name="ck_brief_issue_count"),
        UniqueConstraint("guild_id", "local_date", name="uq_brief_guild_date"),
        Index("ix_brief_jobs_due", "state", "due_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guild_configurations.guild_id"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    local_date: Mapped[date] = mapped_column(Date)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str] = mapped_column("timezone", String(64))
    state: Mapped[str] = mapped_column(String(32))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_receipt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SqlBriefStore:
    """Transactional brief-job persistence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def list_relevant(self, guild_id: int, local_today: date) -> list[BriefJobRecord]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(BriefJobRow)
                    .where(
                        BriefJobRow.guild_id == guild_id,
                        or_(
                            BriefJobRow.local_date >= local_today,
                            BriefJobRow.state.in_(_OPEN),
                        ),
                    )
                    .order_by(BriefJobRow.local_date, BriefJobRow.id)
                )
            ).all()
        return [_record(row) for row in rows]

    async def insert_job(self, draft: NewBriefJob) -> int | None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                pg_insert(GuildConfiguration)
                .values(guild_id=draft.guild_id)
                .on_conflict_do_nothing(index_elements=[GuildConfiguration.guild_id])
            )
            inserted = await session.scalar(
                pg_insert(BriefJobRow)
                .values(
                    guild_id=draft.guild_id,
                    channel_id=draft.channel_id,
                    local_date=draft.local_date,
                    due_at=as_utc(draft.due_at),
                    timezone_name=draft.timezone_name,
                    state=draft.state.value,
                    attempt_count=0,
                    failure_category=draft.failure_category,
                )
                .on_conflict_do_nothing(constraint="uq_brief_guild_date")
                .returning(BriefJobRow.id)
            )
        return inserted

    async def apply_skip(self, job_id: int, state: JobState, category: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(BriefJobRow)
                .where(BriefJobRow.id == job_id, BriefJobRow.state == JobState.SCHEDULED.value)
                .values(
                    state=state.value,
                    failure_category=category[:64],
                    retry_at=None,
                    claim_token=None,
                )
            )

    async def release_claim(self, job_id: int, claim_token: str) -> None:
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(BriefJobRow)
                .where(
                    BriefJobRow.id == job_id,
                    BriefJobRow.claim_token == claim_token,
                    BriefJobRow.state == JobState.CLAIMED.value,
                )
                .with_for_update()
            )
            if job is None:
                return
            if job.attempt_count > 0:
                job.attempt_count -= 1
            job.state = JobState.SCHEDULED.value
            job.claim_token = None
            job.claimed_at = None

    async def unreconcile_claims(self, guild_id: int) -> int:
        async with self._sessions() as session, session.begin():
            result = await session.scalars(
                update(BriefJobRow)
                .where(
                    BriefJobRow.guild_id == guild_id,
                    BriefJobRow.state == JobState.CLAIMED.value,
                )
                .values(
                    state=JobState.UNRECONCILED.value,
                    failure_category="receipt_unknown",
                    claim_token=None,
                    claimed_at=None,
                    retry_at=None,
                )
                .returning(BriefJobRow.id)
            )
        return len(result.all())

    async def claim_due(
        self, *, guild_id: int, now: datetime, local_today: date, limit: int
    ) -> list[ClaimedBrief]:
        current = as_utc(now)
        async with self._sessions() as session, session.begin():
            rows = (
                await session.scalars(
                    select(BriefJobRow)
                    .where(
                        BriefJobRow.guild_id == guild_id,
                        BriefJobRow.state == JobState.SCHEDULED.value,
                        BriefJobRow.local_date == local_today,
                        BriefJobRow.due_at <= current,
                        or_(BriefJobRow.retry_at.is_(None), BriefJobRow.retry_at <= current),
                    )
                    .order_by(BriefJobRow.due_at, BriefJobRow.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claimed: list[ClaimedBrief] = []
            for row in rows:
                token = uuid4().hex
                row.state = JobState.CLAIMED.value
                row.claim_token = token
                row.claimed_at = current
                row.attempt_count += 1
                row.retry_at = None
                claimed.append(
                    ClaimedBrief(
                        job_id=row.id,
                        claim_token=token,
                        attempt_count=row.attempt_count,
                        guild_id=row.guild_id,
                        channel_id=row.channel_id,
                        local_date=row.local_date,
                        due_at=as_utc(row.due_at),
                        timezone_name=row.timezone_name,
                    )
                )
            return claimed

    async def mark_delivered(
        self, job_id: int, claim_token: str, receipt: str, issue_count: int
    ) -> bool:
        async with self._sessions() as session, session.begin():
            delivered_id = await session.scalar(
                update(BriefJobRow)
                .where(
                    BriefJobRow.id == job_id,
                    BriefJobRow.claim_token == claim_token,
                    BriefJobRow.state == JobState.CLAIMED.value,
                )
                .values(
                    state=JobState.DELIVERED.value,
                    delivery_receipt=receipt[:64],
                    issue_count=issue_count,
                    claim_token=None,
                    failure_category=None,
                )
                .returning(BriefJobRow.id)
            )
        return delivered_id is not None

    async def record_failure(
        self,
        job_id: int,
        claim_token: str,
        *,
        category: str,
        transient: bool,
        max_attempts: int,
        retry_at: datetime | None,
        receipt: str | None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(BriefJobRow)
                .where(
                    BriefJobRow.id == job_id,
                    BriefJobRow.claim_token == claim_token,
                    BriefJobRow.state == JobState.CLAIMED.value,
                )
                .with_for_update()
            )
            if job is None:
                return
            safe_category = category[:64]
            terminal = (not transient) or retry_at is None or job.attempt_count >= max_attempts
            job.claim_token = None
            job.failure_category = safe_category
            if receipt is not None:
                job.delivery_receipt = receipt[:64]
            if terminal:
                job.state = JobState.FAILED.value
                job.retry_at = None
            else:
                job.state = JobState.SCHEDULED.value
                job.claimed_at = None
                job.retry_at = as_utc(retry_at) if retry_at is not None else None


def _record(row: BriefJobRow) -> BriefJobRecord:
    return BriefJobRecord(
        id=row.id,
        guild_id=row.guild_id,
        channel_id=row.channel_id,
        local_date=row.local_date,
        due_at=as_utc(row.due_at),
        timezone_name=row.timezone_name,
        state=JobState(row.state),
        attempt_count=row.attempt_count,
        retry_at=as_utc(row.retry_at) if row.retry_at is not None else None,
        claim_token=row.claim_token,
        delivery_receipt=row.delivery_receipt,
        failure_category=row.failure_category,
        issue_count=row.issue_count,
    )
