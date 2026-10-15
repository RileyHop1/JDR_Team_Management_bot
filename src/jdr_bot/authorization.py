"""Pure authorization policy shared by management commands."""

from collections.abc import Collection


def can_manage(
    *, guild_id: int | None, allowed_guild_id: int, role_ids: Collection[int], operator_role_id: int
) -> bool:
    """Require the configured guild and explicit operator role, including for administrators."""
    return guild_id == allowed_guild_id and operator_role_id in role_ids
