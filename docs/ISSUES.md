# Implementation issues

These work items are tracked as GitHub issues [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5), [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6), [#7](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/7), [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8), [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10), and [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11). JDR IDs below are local planning identifiers, not Jira tickets. Feature branches begin with a scoped implementation plan; a planning PR does not deliver the feature. Replace this status with links and verification evidence as implementation proceeds.

| ID | Work item | Branch | Dependencies |
| --- | --- | --- | --- |
| JDR-001 | Development foundation and Discord commands | `feat/development-foundation` | None |
| JDR-002 | Meeting configuration and reminders | `feat/meeting-reminders` | JDR-001 |
| JDR-003 | Jira morning brief | `feat/jira-morning-brief` | JDR-001; scheduler from JDR-002 |
| JDR-004 | Meeting capture and transcripts | `feat/meeting-transcripts` | JDR-001; meeting model from JDR-002; voice feasibility |
| JDR-005 | Actionable startup failure categories | `cursor/startup-failure-categories-37c6` | JDR-001; brief settings from JDR-003; guild schema from JDR-006 |
| JDR-006 | Persisted guild configuration | `cursor/guild-configuration-5ec9` | JDR-001; consumed by JDR-002 and JDR-003 |

## JDR-001: Development foundation

Implementation and local automated validation are in progress; the live Discord smoke check remains pending. See [development instructions](DEVELOPMENT.md).

Provide a reproducible, testable application baseline so contributors can safely build features.

Acceptance criteria:

- Pin Python and dependencies with a manifest and lockfile; document exact setup and run commands.
- Configure Ruff, strict mypy, pytest, and CI checks; prove a fresh installation works.
- Validate configuration without exposing secrets; provide placeholder-only example configuration.
- Add an asynchronous Discord entry point, guild-scoped command registration, authorization, and graceful shutdown.
- Add PostgreSQL migrations and test isolation. Verify one command in a private test server; exercise permission denial offline.

## JDR-002: Meeting configuration and reminders

Offline behavior is implemented under the provisional policy in [decision 0002](decisions/0002-meeting-reminders.md): operator-only commands, validated schedules, durable jobs, restart recovery, and fake-clock tests. Team confirmation of that policy and a reminder demonstrated in the test server are still outstanding, so this item is not complete. See [meeting reminders](features/meeting-reminders.md).

Let authorized members create, view, update, and cancel meetings with configurable reminder offsets.

Acceptance criteria:

- Validate channels, UTC-aware times, IANA time zones, and offsets; restrict commands by guild and role.
- Persist meetings and jobs, restore scheduling after restart, and document missed-job behavior.
- Test create/update/cancel, daylight saving transitions, restart recovery, duplicate windows, and delivery failures using fake clocks.
- Demonstrate a reminder in the test server and document operation and troubleshooting.

## JDR-003: Jira morning brief

Offline behavior is implemented under the provisional policy in [decision 0003](decisions/0003-jira-morning-brief.md): a read-only Jira Cloud search, a separate brief job type on the existing scheduler, weekday delivery, same-day recovery, and fake-adapter tests. Team confirmation of that policy and a brief demonstrated against test Jira and Discord are still outstanding, so this item is not complete. See [Jira morning brief](features/jira-morning-brief.md).

Acceptance criteria:

- Confirm Jira deployment, authentication, project/filter, and exact in-progress statuses with the team.
- Query with read-only access and pagination; include issue key, title, assignee, status, and URL.
- Make schedule, time zone, and destination configurable; suppress unintended mentions and split long output.
- Distinguish no matching issues from query failure; test rate limits, denied access, timeouts, pagination, and scheduling recovery.
- Demonstrate a read-only query and brief in test resources. Never fabricate progress or blockers.

## JDR-004: Meeting capture and transcripts

Capture explicitly authorized meetings and deliver transcripts to the approved meetings channel.

Acceptance criteria:

- First prove Discord voice receive/decryption, runtime UDP connectivity, audio format compatibility, and selected provider behavior with synthetic audio.
- Record the provider/library decision and stop implementation if unsupported; assess alternatives separately.
- Define consent, late-arrival handling, stop controls, access, retention/deletion, duration limits, and budget before recording real meetings.
- Implement explicit lifecycle states, bounded capture, cancellation, disconnect recovery, transcription failures, and cleanup.
- Deliver long transcripts privately with attachments; never fall back to a public channel.
- Test with synthetic audio and demonstrate the full path in a private server with consenting participants; verify deletion of local artifacts and document external retention limits.

## JDR-005: Actionable startup failure categories

Offline behavior is implemented. Startup logs a fixed category for invalid configuration, invalid Jira brief settings, an unreachable database, a role that cannot read the schema, an outdated schema, Discord login failure, and forbidden guild command sync. Unexpected failures keep a generic category and the exception class name. Logs omit secrets and driver text. See [decision 0005](decisions/0005-startup-failures.md) and the troubleshooting section of [development instructions](DEVELOPMENT.md).

GitHub issue: [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10).

## JDR-006: Persisted guild configuration

Offline behavior is implemented under the provisional policy in [decision 0004](decisions/0004-guild-configuration.md): nullable guild settings, operator `/config` commands, environment fallback when a field is unset, and future brief jobs that pick up a new channel and time. Team confirmation of that policy and a `/config` check in the test server are still outstanding, so this item is not complete. See [guild configuration](features/guild-configuration.md).

GitHub issue: [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11).

Acceptance criteria:

- Add a reviewed migration extending guild configuration with meetings channel id, brief channel id, IANA time zone, and brief local time (`HH:MM`). Bump `SCHEMA_REVISION` to `0004`.
- Add operator-only, guild-scoped slash commands to view and update these settings, enforced with `can_manage`. Validate that channels exist in the guild and the bot can view and send there. Reject invalid IANA zones and times with useful messages.
- Document how `BOT_TIMEZONE`, `MEETINGS_CHANNEL_ID`, and `BRIEF_CHANNEL_ID` relate to stored values. The environment is the fallback when no row or value is stored.
- Never store Jira credentials in configuration rows.
- Test permission denial, invalid channels and zones, persistence round-trips against PostgreSQL, and upgrade/downgrade of migration `0004`.
- Update `docs/DEVELOPMENT.md` and `.env.example` with placeholders only.

## Shared completion rules

Follow [code standards](../CODE_STANDARDS.md), [contributing](../CONTRIBUTING.md), and [security requirements](../SECURITY.md). Each feature needs reviewed code, meaningful tests, updated docs, and controlled integration evidence. Draft planning PRs remain incomplete until their acceptance criteria are implemented and verified.
