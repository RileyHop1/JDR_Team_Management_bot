# JDR Team Management Bot

A Discord assistant for a senior computer engineering project. It helps the team prepare for meetings and stay aware of work tracked in Jira. Meeting transcripts are not implemented.

**Status:** Foundation, meeting reminders, the Jira morning brief, per-guild configuration, and startup failure categories are merged on `main`. Hosted CI passed on each pull request below. The bot registers guild-scoped `/ping`, operator-only `/status`, operator-only `/meeting`, and operator-only `/config` commands. Reminders and brief jobs are stored in PostgreSQL and restored after restart. Guild time zone, channels, and brief time can be stored per guild; Jira credentials stay in the environment. Startup logs a fixed failure category and does not log secrets.

- [PR #9](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/9) (foundation, [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/38816010204)). [Decision 0001](docs/decisions/0001-development-foundation.md) is accepted. GitHub issue [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5) stays open until the live Discord smoke check passes.
- [PR #15](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/15) (meeting reminders, [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39085620688)). [Decision 0002](docs/decisions/0002-meeting-reminders.md) is provisional. Issue [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6) stays open until the team confirms that policy and a reminder is shown in the test server.
- [PR #16](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/16) (Jira morning brief, [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39097915833)). [Decision 0003](docs/decisions/0003-jira-morning-brief.md) is provisional. Issue [#7](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/7) stays open until the team confirms that policy and a brief is shown against test Jira and Discord.
- [PR #17](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/17) (guild configuration, [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39531857559)). [Decision 0004](docs/decisions/0004-guild-configuration.md) is provisional. Issue [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11) is closed. The live `/config` check and team confirmation are still outstanding.
- [PR #18](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/18) (startup failure categories, [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39537651270)). [Decision 0005](docs/decisions/0005-startup-failures.md) is accepted for this implementation. Issue [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10) is closed.

Still outstanding: the live Discord and Jira smoke checks; team confirmation of decisions 0002, 0003, and 0004; meeting capture and transcripts ([JDR-004](docs/features/meeting-transcripts.md), issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8)); and live verification that the Raspberry Pi can hold a Discord gateway session and voice UDP ([decision 0006](docs/decisions/0006-raspberry-pi-hosting.md), [production runbook](docs/operations/runbook.md), issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12)). The hosting choice and the runbook are recorded. Decision 0006 stays provisional until that Pi check is recorded. The status record is [implementation issues](docs/ISSUES.md).

## Intended capabilities

- Announce upcoming meetings at team-configured reminder intervals.
- Join supported meetings after participants receive notice and recording is authorized.
- Produce a transcript and post it to a configured Discord meetings channel.
- Post a scheduled morning brief showing Jira issues currently being worked on, their assignees, statuses, and links.

Reminders and the morning brief are implemented offline under the provisional decisions linked above. Joining a voice meeting and posting a transcript are not implemented. [PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged the planning document only.

The initial target is meetings held in a Discord voice channel. Supporting Zoom, Teams, or Google Meet would require a separate integration and design decision. Voice capture feasibility must be validated before promising automatic transcription.

## Start here

- [Project overview](docs/PROJECT_OVERVIEW.md): scope, milestones, and acceptance criteria.
- [Implementation issues](docs/ISSUES.md): feature backlog and acceptance criteria.
- [Architecture](docs/ARCHITECTURE.md): components, data flow, and failure handling.
- [Contributing](CONTRIBUTING.md): how to get oriented and submit changes.
- [Code standards](CODE_STANDARDS.md): required implementation and review practices.
- [Prerequisites](docs/PREREQUISITES.md): accounts, permissions, configuration, and open decisions.
- [Security and data handling](SECURITY.md): credentials, recording, retention, and incident response.
- [Production runbook](docs/operations/runbook.md): Raspberry Pi setup, secrets, backups, migrations, and systemd. Live gateway and voice checks are still pending ([decision 0006](docs/decisions/0006-raspberry-pi-hosting.md)).

## Development

Python 3.12.14, uv 0.12.23, and PostgreSQL 16 are the development and CI baseline. See [development instructions](docs/DEVELOPMENT.md) for installation, migrations, configuration, test commands, and the Discord, reminder, Jira, and guild-configuration smoke checks. Continuous hosting is the provisional [Raspberry Pi decision](docs/decisions/0006-raspberry-pi-hosting.md) and the [production runbook](docs/operations/runbook.md). See the accepted [foundation decision](docs/decisions/0001-development-foundation.md), the provisional [meeting-reminder decision](docs/decisions/0002-meeting-reminders.md), the provisional [Jira brief decision](docs/decisions/0003-jira-morning-brief.md), the provisional [guild-configuration decision](docs/decisions/0004-guild-configuration.md), and the accepted [startup-failure decision](docs/decisions/0005-startup-failures.md).

```sh
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -v
```

The PostgreSQL integration test needs a disposable `TEST_DATABASE_URL`; it is explicitly skipped without one. CI supplies its own database. Never use real meeting recordings or credentials as test fixtures.
