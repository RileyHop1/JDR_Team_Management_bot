# Implementation issues

Work is tracked in GitHub issues. Each `JDR-NNN` ID below is a planning identifier for one of those issues. IDs are three digits and zero-padded. It is not a Jira ticket. Jira is the external tracker the morning brief reads, not the board for this repository. Branch names use the planning ID; see [contributing](../CONTRIBUTING.md).

A row is "merged" only when the pull request is on `main` and hosted CI passed. A live Discord or Jira smoke check, and team confirmation of a provisional decision, stay outstanding until they happen. A planning note does not deliver a feature.

| ID | Work item | GitHub issue | Delivery | Dependencies |
| --- | --- | --- | --- | --- |
| JDR-001 | Development foundation and Discord commands | [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5) (open) | [PR #9](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/9) merged; [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/38816010204) | None |
| JDR-002 | Meeting configuration and reminders | [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6) (open) | [PR #15](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/15) merged; [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39085620688) | JDR-001 |
| JDR-003 | Jira morning brief | [#7](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/7) (open) | [PR #16](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/16) merged; [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39097915833) | JDR-001; scheduler from JDR-002 |
| JDR-004 | Meeting capture and transcripts | [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) (open) | [PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged the planning document only; implementation not started | JDR-001; meeting model from JDR-002; voice feasibility |
| JDR-005 | Actionable startup failure categories | [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10) (closed) | [PR #18](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/18) merged; [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39537651270) | JDR-001; brief settings from JDR-003; guild schema from JDR-006 |
| JDR-006 | Persisted guild configuration | [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11) (closed) | [PR #17](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/17) merged; [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39531857559) | JDR-001; consumed by JDR-002 and JDR-003 |
| JDR-007 | Hosting decision and production deployment runbook | [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12) (open) | [Decision 0006](decisions/0006-raspberry-pi-hosting.md) and the [production runbook](operations/runbook.md) are recorded; live Pi verification of gateway and voice UDP is pending | JDR-001; informs JDR-004 |
| JDR-008 | Documentation status sync | [#13](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/13) (closed) | [PR #19](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/19) merged; [CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39544748635) | None |
| JDR-009 | GitHub issue and pull request templates | [#14](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/14) (closed) | [PR #20](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/20) adds the templates | None |

Still outstanding after the merged pull requests above: the live Discord smoke check for JDR-001, the live reminder check and team confirmation of [decision 0002](decisions/0002-meeting-reminders.md), the live Jira brief check and team confirmation of [decision 0003](decisions/0003-jira-morning-brief.md), the live `/config` check and team confirmation of [decision 0004](decisions/0004-guild-configuration.md), meeting-transcript implementation (JDR-004; [PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged the planning document only), and live verification of the Raspberry Pi gateway session and voice UDP (JDR-007). The hosting choice and the runbook are recorded. [Decision 0001](decisions/0001-development-foundation.md) and [decision 0005](decisions/0005-startup-failures.md) are accepted for the merged implementation. Decision 0005 does not ask for a further team confirmation. Issue [#13](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/13) is closed. [PR #19](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/19) merged this status record, and hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39544748635)).

## JDR-001: Development foundation

Merged in [PR #9](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/9) on 2026-10-15. Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/38816010204)). That pull request includes the pinned toolchain, CI, secret-safe configuration, guild-scoped commands, graceful shutdown, PostgreSQL migrations, test isolation, and offline permission denial. The live Discord smoke check in [development instructions](DEVELOPMENT.md) has not been run, so GitHub issue [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5) stays open. See [development foundation](features/development-foundation.md).

Provide a reproducible, testable application baseline so contributors can safely build features.

Acceptance criteria:

- Pin Python and dependencies with a manifest and lockfile; document exact setup and run commands.
- Configure Ruff, strict mypy, pytest, and CI checks; prove a fresh installation works.
- Validate configuration without exposing secrets; provide placeholder-only example configuration.
- Add an asynchronous Discord entry point, guild-scoped command registration, authorization, and graceful shutdown.
- Add PostgreSQL migrations and test isolation. Verify one command in a private test server; exercise permission denial offline.

The private test-server command check in the last criterion is the part still open. The migration, test-isolation, and offline permission-denial parts are in the merged pull request.

## JDR-002: Meeting configuration and reminders

Merged in [PR #15](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/15). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39085620688)). Offline behavior follows the provisional policy in [decision 0002](decisions/0002-meeting-reminders.md): operator-only commands, validated schedules, durable jobs, restart recovery, and fake-clock tests. Team confirmation of that policy and a reminder demonstrated in the test server are still outstanding, so GitHub issue [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6) stays open. See [meeting reminders](features/meeting-reminders.md).

Let authorized members create, view, update, and cancel meetings with configurable reminder offsets.

Acceptance criteria:

- Validate channels, UTC-aware times, IANA time zones, and offsets; restrict commands by guild and role.
- Persist meetings and jobs, restore scheduling after restart, and document missed-job behavior.
- Test create/update/cancel, daylight saving transitions, restart recovery, duplicate windows, and delivery failures using fake clocks.
- Demonstrate a reminder in the test server and document operation and troubleshooting.

Operation and troubleshooting are documented. The test-server demonstration has not been run.

## JDR-003: Jira morning brief

Merged in [PR #16](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/16). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39097915833)). Offline behavior follows the provisional policy in [decision 0003](decisions/0003-jira-morning-brief.md): a read-only Jira Cloud search, a separate brief job type on the existing scheduler, weekday delivery, same-day recovery, and fake-adapter tests. Team confirmation of that policy and a brief demonstrated against test Jira and Discord are still outstanding, so GitHub issue [#7](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/7) stays open. See [Jira morning brief](features/jira-morning-brief.md).

Acceptance criteria:

- Confirm Jira deployment, authentication, project/filter, and exact in-progress statuses with the team.
- Query with read-only access and pagination; include issue key, title, assignee, status, and URL.
- Make schedule, time zone, and destination configurable; suppress unintended mentions and split long output.
- Distinguish no matching issues from query failure; test rate limits, denied access, timeouts, pagination, and scheduling recovery.
- Demonstrate a read-only query and brief in test resources. Never fabricate progress or blockers.

The team confirmation in the first criterion and the test-resource demonstration in the last criterion have not been done. The offline query, schedule, and failure tests are in the merged pull request. The provisional choices are Jira Cloud, an explicit status list or `JIRA_JQL`, and no assignee filter.

## JDR-004: Meeting capture and transcripts

[PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged the planning document on 2026-10-15 and included no application code. Implementation has not started. GitHub issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) is open. See [meeting transcripts](features/meeting-transcripts.md).

Capture explicitly authorized meetings and deliver transcripts to the approved meetings channel.

Acceptance criteria:

- First prove Discord voice receive/decryption, runtime UDP connectivity, audio format compatibility, and selected provider behavior with synthetic audio.
- Record the provider/library decision and stop implementation if unsupported; assess alternatives separately.
- Define consent, late-arrival handling, stop controls, access, retention/deletion, duration limits, and budget before recording real meetings.
- Implement explicit lifecycle states, bounded capture, cancellation, disconnect recovery, transcription failures, and cleanup.
- Deliver long transcripts privately with attachments; never fall back to a public channel.
- Test with synthetic audio and demonstrate the full path in a private server with consenting participants; verify deletion of local artifacts and document external retention limits.

## JDR-005: Actionable startup failure categories

Merged in [PR #18](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/18). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39537651270)). GitHub issue [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10) is closed. [Decision 0005](decisions/0005-startup-failures.md) is accepted for this implementation and does not leave a team-confirmation step open. No live Discord smoke check was required, and none was run.

Startup logs a fixed category for invalid configuration, invalid Jira brief settings, an unreachable database, a role that cannot read the schema, an outdated schema, Discord login failure, and forbidden guild command sync. Unexpected failures keep a generic category and the exception class name. Logs omit secrets and driver text. See the troubleshooting section of [development instructions](DEVELOPMENT.md).

## JDR-006: Persisted guild configuration

Merged in [PR #17](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/17). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39531857559)). GitHub issue [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11) is closed. Offline behavior follows the provisional policy in [decision 0004](decisions/0004-guild-configuration.md): nullable guild settings, operator `/config` commands, environment fallback when a field is unset, and future brief jobs that pick up a new channel and time. Team confirmation of that policy and a `/config` check in the test server are still outstanding. Closing the issue did not run that check. See [guild configuration](features/guild-configuration.md).

Acceptance criteria:

- Add a reviewed migration extending guild configuration with meetings channel id, brief channel id, IANA time zone, and brief local time (`HH:MM`). Bump `SCHEMA_REVISION` to `0004`.
- Add operator-only, guild-scoped slash commands to view and update these settings, enforced with `can_manage`. Validate that channels exist in the guild and the bot can view and send there. Reject invalid IANA zones and times with useful messages.
- Document how `BOT_TIMEZONE`, `MEETINGS_CHANNEL_ID`, and `BRIEF_CHANNEL_ID` relate to stored values. The environment is the fallback when no row or value is stored.
- Never store Jira credentials in configuration rows.
- Test permission denial, invalid channels and zones, persistence round-trips against PostgreSQL, and upgrade/downgrade of migration `0004`.
- Update `docs/DEVELOPMENT.md` and `.env.example` with placeholders only.

The merged pull request covers these criteria. Team confirmation of decision 0004 is a separate outstanding step. The live `/config` check in [development instructions](DEVELOPMENT.md) has not been run.

## JDR-007: Hosting decision and production deployment runbook

The hosting choice is recorded in provisional [decision 0006](decisions/0006-raspberry-pi-hosting.md): one process on the team's Raspberry Pi, with PostgreSQL 16 on an SSD. The [production runbook](operations/runbook.md) covers OS setup, secrets, backups, migrations, systemd, the single scheduler, logs, and rollback. GitHub issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12) stays open. A gateway session and voice UDP have not been verified on the Pi. Decision 0006 tells the operator which commands to run there and which result is still pending. Voice capture (JDR-004) must not treat the Pi as proven until that voice check is recorded.

## JDR-008: Documentation status

Merged in [PR #19](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/19). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39544748635)). GitHub issue [#13](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/13) is closed. The issue asked these status lines to match merged work. This page is that record. No product behavior is in scope.

## JDR-009: GitHub issue and pull request templates

Added by [PR #20](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/20). GitHub issue [#14](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/14) is closed by that pull request because the templates complete the issue. The feature or task template is [`.github/ISSUE_TEMPLATE/feature_task.md`](../.github/ISSUE_TEMPLATE/feature_task.md). Its title form is `JDR-NNN: Title`. IDs are three digits and zero-padded. The next free ID is the next three-digit ID after the highest `JDR-NNN` in this file. The body asks for the user outcome, scope, an acceptance-criteria checklist, dependencies, how to verify, and the delivery workflow. The pull request template is [`.github/pull_request_template.md`](../.github/pull_request_template.md). It asks for the linked issue (`Refs #N`, or `Closes #N` only when the pull request fully completes the issue), a summary, the behavior change, validation evidence, configuration or migration requirements, known limitations, and a security checklist. Both tell the author not to post secrets or real meeting content. [Contributing](../CONTRIBUTING.md) references both files. The pull request template also reminds the author that only one implementation pull request may be open at a time.

## Shared completion rules

Follow [code standards](../CODE_STANDARDS.md), [contributing](../CONTRIBUTING.md), and [security requirements](../SECURITY.md). Each feature needs reviewed code, meaningful tests, updated docs, and controlled integration evidence. A planning document does not complete a feature. Passing hosted CI on a merged pull request covers the automated checks. A live smoke check or team confirmation named above stays outstanding until it is done. Closing a GitHub issue does not by itself mean those remaining checks passed.
