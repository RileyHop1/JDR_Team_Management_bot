# JDR Team Management Bot

A planned Discord assistant for a senior computer engineering project. It will help the team prepare for meetings, retain meeting records, and stay aware of work tracked in Jira.

**Status:** foundation implemented with guild-scoped `/ping` and operator-only `/status`, validated configuration, PostgreSQL migrations, automated tests, and CI configuration. Live Discord validation is pending. Reminders, Jira integration, and transcription are not implemented.

## Intended capabilities

- Announce upcoming meetings at team-configured reminder intervals.
- Join supported meetings after participants receive notice and recording is authorized.
- Produce a transcript and post it to a configured Discord meetings channel.
- Post a scheduled morning brief showing Jira issues currently being worked on, their assignees, statuses, and links.

The initial target is meetings held in a Discord voice channel. Supporting Zoom, Teams, or Google Meet would require a separate integration and design decision. Voice capture feasibility must be validated before promising automatic transcription.

## Start here

- [Project overview](docs/PROJECT_OVERVIEW.md): scope, milestones, and acceptance criteria.
- [Implementation issues](docs/ISSUES.md): feature backlog and acceptance criteria.
- [Architecture](docs/ARCHITECTURE.md): proposed components, data flow, and failure handling.
- [Contributing](CONTRIBUTING.md): how to get oriented and submit changes.
- [Code standards](CODE_STANDARDS.md): required implementation and review practices.
- [Prerequisites](docs/PREREQUISITES.md): accounts, permissions, configuration, and open decisions.
- [Security and data handling](SECURITY.md): credentials, recording, retention, and incident response.

## Development

Python 3.12.14, uv 0.12.23, and PostgreSQL 16 are the initial baseline. See [development instructions](docs/DEVELOPMENT.md) for installation, migrations, configuration, test commands, and the required Discord smoke check. See the [foundation decision](docs/decisions/0001-development-foundation.md) for selected libraries and scope.

```sh
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -v
```

The PostgreSQL integration test needs a disposable `TEST_DATABASE_URL`; it is explicitly skipped without one. CI supplies its own database. Never use real meeting recordings or credentials as test fixtures.
