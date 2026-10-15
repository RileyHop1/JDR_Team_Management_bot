# Implementation issues

These are proposed work items, not live GitHub or Jira issues. IDs below are local planning identifiers. Feature branches begin with a scoped implementation plan; a planning PR does not deliver the feature. Replace this status with links and verification evidence as implementation proceeds.

| ID | Work item | Branch | Dependencies |
| --- | --- | --- | --- |
| JDR-001 | Development foundation and Discord commands | `feat/development-foundation` | None |
| JDR-002 | Meeting configuration and reminders | `feat/meeting-reminders` | JDR-001 |
| JDR-003 | Jira morning brief | `feat/jira-morning-brief` | JDR-001; scheduler from JDR-002 |
| JDR-004 | Meeting capture and transcripts | `feat/meeting-transcripts` | JDR-001; meeting model from JDR-002; voice feasibility |

## JDR-001: Development foundation

Provide a reproducible, testable application baseline so contributors can safely build features.

Acceptance criteria:

- Pin Python and dependencies with a manifest and lockfile; document exact setup and run commands.
- Configure Ruff, strict mypy, pytest, and CI checks; prove a fresh installation works.
- Validate configuration without exposing secrets; provide placeholder-only example configuration.
- Add an asynchronous Discord entry point, guild-scoped command registration, authorization, and graceful shutdown.
- Add PostgreSQL migrations and test isolation. Verify one command in a private test server; exercise permission denial offline.

## JDR-002: Meeting configuration and reminders

Let authorized members create, view, update, and cancel meetings with configurable reminder offsets.

Acceptance criteria:

- Validate channels, UTC-aware times, IANA time zones, and offsets; restrict commands by guild and role.
- Persist meetings and jobs, restore scheduling after restart, and document missed-job behavior.
- Test create/update/cancel, daylight saving transitions, restart recovery, duplicate windows, and delivery failures using fake clocks.
- Demonstrate a reminder in the test server and document operation and troubleshooting.

## JDR-003: Jira morning brief

Post a daily local-time brief of the team's current work without modifying Jira.

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

## Shared completion rules

Follow [code standards](../CODE_STANDARDS.md), [contributing](../CONTRIBUTING.md), and [security requirements](../SECURITY.md). Each feature needs reviewed code, meaningful tests, updated docs, and controlled integration evidence. Draft planning PRs remain incomplete until their acceptance criteria are implemented and verified.
