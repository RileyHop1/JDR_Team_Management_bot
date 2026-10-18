"""Create meetings and durable reminder jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_ACTIVE_JOBS = sa.text("state IN ('scheduled', 'claimed')")
_OPEN_OCCURRENCES = sa.text(
    "state IN ('scheduled', 'claimed', 'delivered', 'skipped', 'failed', 'unreconciled')"
)


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("text_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("voice_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("organizer_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_configurations.guild_id"]),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 100", name="ck_meetings_title"),
        sa.CheckConstraint("state IN ('scheduled', 'cancelled')", name="ck_meetings_state"),
        sa.CheckConstraint(
            "text_channel_id > 0 AND voice_channel_id > 0", name="ck_meetings_channels"
        ),
        sa.CheckConstraint(
            "text_channel_id <> voice_channel_id", name="ck_meetings_distinct_channels"
        ),
        sa.CheckConstraint("char_length(timezone) BETWEEN 1 AND 64", name="ck_meetings_timezone"),
        sa.CheckConstraint("organizer_id > 0", name="ck_meetings_organizer"),
    )
    op.create_index("ix_meetings_guild_start", "meetings", ["guild_id", "state", "starts_at"])
    op.create_table(
        "reminder_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("meeting_id", sa.BigInteger(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=32), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_receipt", sa.String(length=64), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.CheckConstraint("offset_minutes BETWEEN 1 AND 10080", name="ck_reminder_offset"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_reminder_attempts"),
        sa.CheckConstraint(
            "state IN ('scheduled', 'claimed', 'delivered', 'skipped', 'failed', "
            "'cancelled', 'unreconciled')",
            name="ck_reminder_state",
        ),
    )
    op.create_index(
        "uq_reminder_active_offset",
        "reminder_jobs",
        ["meeting_id", "offset_minutes"],
        unique=True,
        postgresql_where=_ACTIVE_JOBS,
    )
    op.create_index(
        "uq_reminder_occurrence",
        "reminder_jobs",
        ["meeting_id", "offset_minutes", "due_at"],
        unique=True,
        postgresql_where=_OPEN_OCCURRENCES,
    )
    op.create_index("ix_reminder_jobs_due", "reminder_jobs", ["state", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_reminder_jobs_due", table_name="reminder_jobs")
    op.drop_index("uq_reminder_occurrence", table_name="reminder_jobs")
    op.drop_index("uq_reminder_active_offset", table_name="reminder_jobs")
    op.drop_table("reminder_jobs")
    op.drop_index("ix_meetings_guild_start", table_name="meetings")
    op.drop_table("meetings")
