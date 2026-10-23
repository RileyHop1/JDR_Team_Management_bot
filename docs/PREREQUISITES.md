# Prerequisites and decisions

Foundation dependencies are declared in `pyproject.toml` and pinned in `uv.lock`. PostgreSQL 16 is the development and CI baseline. Migrations `0001` through `0004` are on `main`. Provisioning and the disposable `_test` database are in [development instructions](DEVELOPMENT.md). This checklist covers accounts, the settings the process reads, and decisions that are still open.

## Accounts and permissions

- A private Discord test server and an application/bot created in the Discord Developer Portal. A maintainer must install it using the bot and application-command scopes.
- Grant only the channel permissions required for the implemented feature: view channels, send messages, attach transcript files, and connect to the selected voice channel. Add other permissions only with a documented reason; do not grant Administrator.
- Enable gateway intents only when the selected library and feature require them. Slash commands should not require reading every message. Prove voice receive support and applicable intents before selecting the library.
- Read-only Jira Cloud access to the chosen project, including the issue fields needed for the brief. [Decision 0003](decisions/0003-jira-morning-brief.md) provisionally selects Jira Cloud (`https://<site>.atlassian.net`) and HTTP Basic authentication with `JIRA_USER_EMAIL` and `JIRA_API_TOKEN`. Self-hosted Jira is not selected. Confirm Cloud before treating that choice as final.
- An approved transcription provider, or an explicitly selected local model with adequate compute, storage, and model licensing. Confirm supported audio formats, limits, cost, and the provider's own retention. The team's retention period is a strict total of 30 days from capture end, in UTC ([decision 0007](decisions/0007-meeting-data-retention.md)). Live content is purged at capture end plus 23 days, and every dump file is deleted before it is 7 days old. No provider is selected. A provider that keeps meeting content past capture end plus 23 days does not meet that decision.
- PostgreSQL 16 for the persistence layer. CI uses the `postgres:16` image, and [development instructions](DEVELOPMENT.md) document local provisioning. The integration tests need a disposable database whose name ends in `_test`.

## Configuration contract

`Settings` reads the names below from the environment or a local `.env`. The morning brief stays off until its group is complete. When the brief is on, `JIRA_STATUS_NAMES` is required unless `JIRA_JQL` is set. `TRANSCRIPTION_API_KEY` is not read; transcription is not implemented. Store secret values in environment settings or an approved secret manager; never place them in this document or committed examples.

| Name | Purpose | Sensitive? |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | Authenticate the bot. | Yes |
| `DISCORD_OPERATOR_ROLE_ID` | Role required for management commands, including `/status`. | No |
| `DISCORD_GUILD_ID` | Restrict initial command registration and operation to the test/team server. | No |
| `MEETINGS_CHANNEL_ID` | Optional meetings-channel default when `/config` has not stored one. | No |
| `BRIEF_CHANNEL_ID` | Morning brief destination, unless a brief channel is stored. | No |
| `BOT_TIMEZONE` | IANA time zone used when the guild has not stored one. | No |
| `BRIEF_TIME` | Local `HH:MM` brief time, unless a brief time is stored. | No |
| `DATABASE_URL` | PostgreSQL connection string. | Usually contains credentials |
| `JIRA_BASE_URL` | Jira Cloud site, `https://<site>.atlassian.net`. Required when the brief is on. | No |
| `JIRA_PROJECT_KEY` | Project key. Required when the brief is on. | No |
| `JIRA_STATUS_NAMES` | Comma-separated exact status names. Required when the brief is on unless `JIRA_JQL` is set. | Treat as internal configuration |
| `JIRA_JQL` | Optional query that replaces the project/status query. Not posted or logged. | Treat as internal configuration |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` | Provisional Jira Cloud HTTP Basic authentication ([decision 0003](decisions/0003-jira-morning-brief.md)). Required when the brief is on. | Token is secret; email is personal data |
| `TRANSCRIPTION_API_KEY` | Not read. Provider authentication if remote transcription is selected later. | Yes |

A meeting stores its voice channel, start, time zone, and reminder offsets. Guild configuration stores the meetings channel, brief channel, IANA zone, and brief time ([decision 0004](decisions/0004-guild-configuration.md)). Allowed operators stay in `DISCORD_OPERATOR_ROLE_ID`. Jira credentials, the project key, status names, and JQL stay in the process environment ([decision 0003](decisions/0003-jira-morning-brief.md)). Do not guess channel IDs, credentials, Jira status names, or the team's time zone. The recording retention period is the strict 30-day total in [decision 0007](decisions/0007-meeting-data-retention.md): live content at capture end plus 23 days, and dump files deleted before they are 7 days old. Do not guess a different period.

## Networking

Runtime needs Discord HTTPS and gateway WebSocket access, Jira HTTPS access when the brief is enabled, and database connectivity on the same machine. The hosting choice is the team's Raspberry Pi in provisional [decision 0006](decisions/0006-raspberry-pi-hosting.md). That record lists the outbound allowlist: Discord gateway, API, and CDN on TCP 443; Jira Cloud `https://<site>.atlassian.net` only while the brief group is set; PostgreSQL on loopback; install-time package indexes. Discord's voice documentation uses a separate UDP flow and a voice WebSocket whose host and port arrive per session. HTTPS egress does not prove voice. Voice UDP on the Pi is pending the verification procedure in decision 0006. No transcription provider is selected.

The production env file is `/etc/jdr-bot/env`, mode `0600`, injected by systemd. See the [production runbook](operations/runbook.md). Proxy-injected HTTPS secrets may not work for gateway identification, voice connections, or database clients that need actual credentials. The Pi passes `DATABASE_URL` and `DISCORD_BOT_TOKEN` in that environment. `Settings` reads both. Alembic reads `DATABASE_URL` only.

## Decisions to resolve before the relevant feature

1. Are all meetings held in Discord voice channels? Third-party meeting platforms need separate authorization and adapters.
2. What time zone, morning time, weekend policy, reminder offsets, and missed-job behavior should the team use? Reminder offsets, the `BOT_TIMEZONE` default, and missed-reminder behavior are provisionally recorded in [decision 0002](decisions/0002-meeting-reminders.md). The brief's explicit `BRIEF_TIME`, weekday-only schedule, and same-day recovery are provisionally recorded in [decision 0003](decisions/0003-jira-morning-brief.md). Operators can store a guild zone, channels, and brief time over those environment defaults; see [decision 0004](decisions/0004-guild-configuration.md).
3. Which Jira deployment, project/filter, and exact statuses mean “being worked on”? Should the brief include all project issues or just the team's assigned work? Decision 0003 provisionally uses Jira Cloud, an explicit status list or `JIRA_JQL`, and every matching issue in the project (no assignee filter). Confirm that before treating it as final.
4. Who may configure schedules, start recording, stop recording, access transcripts, and request deletion? How will notice and consent work for late arrivals? Meeting create, list, view, update, and cancel are provisionally limited to `DISCORD_OPERATOR_ROLE_ID` ([decision 0002](decisions/0002-meeting-reminders.md)). `/config view` and `/config set` use that same role ([decision 0004](decisions/0004-guild-configuration.md)). Recording and transcript access remain open. Deletion on request is required by [decision 0007](decisions/0007-meeting-data-retention.md) and uses the same purge as the live deadline (capture end plus 23 days). Who may make that request remains open with the rest of recording access. The start notice says meeting content is deleted within 30 days of capture end. Late-arrival handling remains open.
5. What recording/transcript retention, provider data policy, language support, budget, and maximum meeting duration are acceptable? Retention is approved in [decision 0007](decisions/0007-meeting-data-retention.md): no copy of meeting content remains more than 30 days after capture end, in UTC. Live content is purged at capture end plus 23 days, and every dump file is deleted before it is 7 days old. Provider data policy, language support, budget, and maximum meeting duration remain open. A provider that keeps meeting content past capture end plus 23 days does not meet that decision.
6. Where will the bot run continuously, and does that environment support Discord voice networking? The continuous host is the team's Raspberry Pi, recorded in provisional [decision 0006](decisions/0006-raspberry-pi-hosting.md) and operated with the [production runbook](operations/runbook.md). Gateway WebSocket and voice UDP on that Pi are not verified. Issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12) stays open until the procedure in decision 0006 is run there. Voice capture still depends on that result.

Record decisions before implementation depends on them. Their absence should not prevent work on tooling, offline domain tests, or the basic reminder pipeline.
