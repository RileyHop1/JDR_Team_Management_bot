"""Create durable morning-brief jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brief_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=32), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_receipt", sa.String(length=64), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("issue_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_configurations.guild_id"]),
        sa.CheckConstraint(
            "state IN ('scheduled', 'claimed', 'delivered', 'skipped', 'failed', 'unreconciled')",
            name="ck_brief_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_brief_attempts"),
        sa.CheckConstraint("channel_id > 0", name="ck_brief_channel"),
        sa.CheckConstraint("char_length(timezone) BETWEEN 1 AND 64", name="ck_brief_timezone"),
        sa.CheckConstraint("issue_count IS NULL OR issue_count >= 0", name="ck_brief_issue_count"),
        sa.UniqueConstraint("guild_id", "local_date", name="uq_brief_guild_date"),
    )
    op.create_index("ix_brief_jobs_due", "brief_jobs", ["state", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_brief_jobs_due", table_name="brief_jobs")
    op.drop_table("brief_jobs")
