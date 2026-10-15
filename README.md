# JDR Team Management Bot

A planned Discord assistant for a senior computer engineering project. It will help the team prepare for meetings, retain meeting records, and stay aware of work tracked in Jira.

**Status:** planning stage. This repository contains project and contributor documentation; the bot, integrations, and automated tests are not implemented yet.

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

## Development direction

Python 3.12 is the proposed baseline, with an asynchronous Discord client, PostgreSQL for durable state, and a database-backed scheduler. These are design proposals rather than installed dependencies. Select and pin packages only after testing compatibility, especially Discord voice receive and the chosen transcription service.

There is currently no install, run, lint, or test command. The first implementation pull request must supply a dependency manifest, lockfile, runnable entry point, configuration validation, CI checks, and exact development commands. Do not use real meeting recordings or credentials as test fixtures.
