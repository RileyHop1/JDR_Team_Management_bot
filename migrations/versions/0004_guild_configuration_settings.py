"""Add non-secret guild settings to guild_configurations.

Downgrade drops the new columns and the values stored in them. Jira credentials
are not columns in this table. See docs/decisions/0004-guild-configuration.md.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_BRIEF_TIME = "brief_time IS NULL OR brief_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'"


def upgrade() -> None:
    op.add_column(
        "guild_configurations",
        sa.Column("meetings_channel_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "guild_configurations",
        sa.Column("brief_channel_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "guild_configurations",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "guild_configurations",
        sa.Column("brief_time", sa.String(length=5), nullable=True),
    )
    op.create_check_constraint(
        "ck_guild_meetings_channel",
        "guild_configurations",
        "meetings_channel_id IS NULL OR meetings_channel_id > 0",
    )
    op.create_check_constraint(
        "ck_guild_brief_channel",
        "guild_configurations",
        "brief_channel_id IS NULL OR brief_channel_id > 0",
    )
    op.create_check_constraint(
        "ck_guild_timezone",
        "guild_configurations",
        "timezone IS NULL OR char_length(timezone) BETWEEN 1 AND 64",
    )
    op.create_check_constraint("ck_guild_brief_time", "guild_configurations", _BRIEF_TIME)


def downgrade() -> None:
    op.drop_constraint("ck_guild_brief_time", "guild_configurations", type_="check")
    op.drop_constraint("ck_guild_timezone", "guild_configurations", type_="check")
    op.drop_constraint("ck_guild_brief_channel", "guild_configurations", type_="check")
    op.drop_constraint("ck_guild_meetings_channel", "guild_configurations", type_="check")
    op.drop_column("guild_configurations", "brief_time")
    op.drop_column("guild_configurations", "timezone")
    op.drop_column("guild_configurations", "brief_channel_id")
    op.drop_column("guild_configurations", "meetings_channel_id")
