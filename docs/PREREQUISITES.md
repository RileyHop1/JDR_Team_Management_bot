# Prerequisites and decisions

Foundation dependencies are declared in `pyproject.toml` and pinned in `uv.lock`; see [development instructions](DEVELOPMENT.md). This checklist is for the first implementation and controlled integration tests.

## Accounts and permissions

- A private Discord test server and an application/bot created in the Discord Developer Portal. A maintainer must install it using the bot and application-command scopes.
- Grant only the channel permissions required for the implemented feature: view channels, send messages, attach transcript files, and connect to the selected voice channel. Add other permissions only with a documented reason; do not grant Administrator.
- Enable gateway intents only when the selected library and feature require them. Slash commands should not require reading every message. Prove voice receive support and applicable intents before selecting the library.
- Read-only Jira access to the chosen project or saved filter, including issue fields needed for the brief. Decide whether this is Jira Cloud or a self-hosted deployment and select supported authentication accordingly.
- An approved transcription provider, or an explicitly selected local model with adequate compute, storage, and model licensing. Confirm supported audio formats, limits, cost, and retention.
- PostgreSQL for the proposed persistence layer. Pin its supported version and document provisioning when implementation starts.

## Proposed configuration contract

The foundation reads `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_OPERATOR_ROLE_ID`, `DATABASE_URL`, and `BOT_TIMEZONE`. Other names below remain proposed for later features. Store secret values in environment settings or an approved secret manager; never place them in this document or committed examples.

| Name | Purpose | Sensitive? |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | Authenticate the bot. | Yes |
| `DISCORD_OPERATOR_ROLE_ID` | Role required for management commands, including `/status`. | No |
| `DISCORD_GUILD_ID` | Restrict initial command registration and operation to the test/team server. | No |
| `MEETINGS_CHANNEL_ID` | Default private transcript destination. | No |
| `BRIEF_CHANNEL_ID` | Morning brief destination. | No |
| `BOT_TIMEZONE` | IANA time zone for user-facing schedules. | No |
| `BRIEF_TIME` | Local daily brief time; format must be specified by implementation. | No |
| `DATABASE_URL` | PostgreSQL connection string. | Usually contains credentials |
| `JIRA_BASE_URL` | Approved Jira deployment URL. | No |
| `JIRA_PROJECT_KEY` | Initial project scope. | No |
| `JIRA_JQL` | Optional team-approved query overriding the default project/status query. | Treat as internal configuration |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` | Possible Jira Cloud authentication; deployment choice may require another method. | Token is secret; email is personal data |
| `TRANSCRIPTION_API_KEY` | Provider authentication if remote transcription is selected. | Yes |

Voice channel, meeting start, reminder offsets, allowed operators, and per-guild settings belong in validated persistent configuration. Do not guess channel IDs, credentials, Jira status names, default recording retention, or the team's time zone.

## Networking

Runtime needs Discord HTTPS and gateway WebSocket access, Jira HTTPS access, database connectivity, and the selected transcription provider. Discord voice additionally needs the UDP transport and dynamically selected voice endpoints supported by the library. HTTPS egress alone may not support voice capture in a cloud environment. Validate actual runtime transport support before committing to hosting there.

Derive concrete host allowlists from chosen services; do not enable unrestricted access as a shortcut. Proxy-injected HTTPS secrets may not work for gateway identification, voice connections, or database clients that need actual credentials. Verify the hosting platform's supported credential injection for each protocol.

## Decisions to resolve before the relevant feature

1. Are all meetings held in Discord voice channels? Third-party meeting platforms need separate authorization and adapters.
2. What time zone, morning time, weekend policy, reminder offsets, and missed-job behavior should the team use? Reminder offsets, the `BOT_TIMEZONE` default, and missed-reminder behavior are provisionally recorded in [decision 0002](decisions/0002-meeting-reminders.md). The brief's explicit `BRIEF_TIME`, weekday-only schedule, and same-day recovery are provisionally recorded in [decision 0003](decisions/0003-jira-morning-brief.md).
3. Which Jira deployment, project/filter, and exact statuses mean “being worked on”? Should the brief include all project issues or just the team's assigned work? Decision 0003 provisionally uses Jira Cloud, an explicit status list or `JIRA_JQL`, and every matching issue in the project (no assignee filter). Confirm that before treating it as final.
4. Who may configure schedules, start recording, stop recording, access transcripts, and request deletion? How will notice and consent work for late arrivals? Meeting create, list, view, update, and cancel are provisionally limited to `DISCORD_OPERATOR_ROLE_ID` ([decision 0002](decisions/0002-meeting-reminders.md)). Recording and transcript access remain open.
5. What recording/transcript retention, provider data policy, language support, budget, and maximum meeting duration are acceptable?
6. Where will the bot run continuously, and does that environment support Discord voice networking?

Record decisions before implementation depends on them. Their absence should not prevent work on tooling, offline domain tests, or the basic reminder pipeline.
