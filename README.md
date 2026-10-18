# JDR Team Management Bot

A planned Discord assistant for a senior computer engineering project. It will help the team prepare for meetings, retain meeting records, and stay aware of work tracked in Jira.

**Status:** foundation, meeting reminders, and the Jira morning brief are implemented offline. The bot registers guild-scoped `/ping`, operator-only `/status`, and operator-only `/meeting` commands. Reminders and brief jobs are stored in PostgreSQL and restored after restart. The reminder policy in [decision 0002](docs/decisions/0002-meeting-reminders.md) and the brief policy in [decision 0003](docs/decisions/0003-jira-morning-brief.md) are provisional and need team confirmation. Live Discord validation, including a reminder and a Jira brief in the test server, is pending. Transcription is not implemented.

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

Python 3.12.14, uv 0.12.23, and PostgreSQL 16 are the initial baseline. See [development instructions](docs/DEVELOPMENT.md) for installation, migrations, configuration, test commands, and the Discord smoke checks. See the [foundation decision](docs/decisions/0001-development-foundation.md), the provisional [meeting-reminder decision](docs/decisions/0002-meeting-reminders.md), and the provisional [Jira brief decision](docs/decisions/0003-jira-morning-brief.md).

```sh
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -v
```

The PostgreSQL integration test needs a disposable `TEST_DATABASE_URL`; it is explicitly skipped without one. CI supplies its own database. Never use real meeting recordings or credentials as test fixtures.
