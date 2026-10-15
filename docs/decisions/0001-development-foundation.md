# 0001: Single-guild Python foundation

Status: accepted for the initial implementation; live Discord validation pending.

Use Python 3.12.14, uv with a committed lockfile, discord.py 2.x for guild-scoped slash commands, Pydantic Settings for configuration, SQLAlchemy/psycopg for asynchronous PostgreSQL access, and Alembic migrations. PostgreSQL 16 is the development/CI baseline.

Use Ruff for formatting/lint, strict mypy for production modules, and pytest with pytest-asyncio. CI runs these checks plus a real disposable PostgreSQL migration test. Role-based management authorization requires the configured operator role and guild, even for administrators. Basic `/ping` is available to members of the configured guild.

Start with no privileged gateway intents and no global commands. Deployment is single guild and single process on Linux/macOS; multi-guild administration and Windows signal integration need separate work. No voice receive library or transcription provider is selected by this decision: command support does not establish voice capture compatibility.
