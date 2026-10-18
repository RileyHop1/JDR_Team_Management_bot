# Jira morning brief

Status: implemented and covered by offline tests. A live read-only query and brief in the test Jira site and Discord server have not been demonstrated, so JDR-003 is not complete. The query, schedule, and recovery rules are provisional and need team confirmation; see [decision 0003](../decisions/0003-jira-morning-brief.md).

Backlog item: [JDR-003](../ISSUES.md#jdr-003-jira-morning-brief).

The bot posts a weekday morning brief of Jira issues that match a configured read-only query. It does not edit Jira, invent blockers, or describe progress beyond the issue key, title, assignee, status, and URL returned by Jira.

## Configuration

The brief stays off until every required setting is present. A partial group fails startup and names the missing fields without printing values. `Settings.brief_schedule()` is the only runtime seam; issue #11 can later build that same object from guild configuration. Credentials are not part of the schedule and are not stored in PostgreSQL.

| Name | Required when the brief is on | Notes |
| --- | --- | --- |
| `BRIEF_CHANNEL_ID` | Yes | Discord text channel that receives the brief. |
| `BRIEF_TIME` | Yes | Local `HH:MM`, 24-hour. The example uses `09:00`. |
| `BOT_TIMEZONE` | Already required | IANA zone for `BRIEF_TIME`. |
| `JIRA_BASE_URL` | Yes | `https://<site>.atlassian.net` only. |
| `JIRA_PROJECT_KEY` | Yes | Uppercase project key. |
| `JIRA_STATUS_NAMES` | Yes, unless `JIRA_JQL` is set | Comma-separated exact status names. |
| `JIRA_JQL` | Optional override | Replaces the default query. Not posted or logged. |
| `JIRA_USER_EMAIL` | Yes | Jira Cloud account email. Not logged. |
| `JIRA_API_TOKEN` | Yes | Secret. A `replace-` prefix is rejected. |

The default query is `project = "<key>" AND status IN (...) ORDER BY key ASC`. It does not filter by assignee.

## Schedule and recovery

Jobs are rows in `brief_jobs`. The reminder scheduler does not own them. One process polls both job types on one background task after the schema check, and shutdown cancels that task.

A brief is sent on its local weekday once it is due, including later the same local day if the process was down. It is not sent on Saturday or Sunday, and a missed weekday is not sent on a later day. A spring-forward gap is skipped (`dst_gap`). A fall-back overlap uses the earlier UTC instant.

Empty Jira results are delivered as `No issues match the configured Jira query.` A failed query, after the retry budget, is `The morning brief could not be loaded (<category>).` Transient Jira HTTP 429, timeouts, and HTTP 5xx retry twice more (15 seconds, then 30 seconds). Access denial does not retry. A claim whose receipt was not stored is not sent again (`unreconciled` / `receipt_unknown`).

## Operation

Apply migration `0003` (`uv run --env-file .env alembic upgrade head`). The process checks that revision even when the brief is disabled. Run one bot process. Logs record job ids, issue counts, and error categories. They do not record JQL, issue titles, assignee names, tokens, or response bodies.

Two processes on the same database can deliver the same brief twice. Discord and PostgreSQL cannot commit together: a crash after the send can leave one message in the channel and an `unreconciled` row.

## Troubleshooting

- `brief_scheduler_disabled`: the brief environment group is unset. Reminders still run.
- `missing brief settings`: at least one brief variable is set and another is missing. Names only; values are omitted.
- `JIRA_BASE_URL must be an https://<site>.atlassian.net URL`: the URL is not Cloud-shaped, or it contains credentials or a path.
- `The morning brief could not be loaded (access_denied)`: Jira rejected the credentials or the query permission. The job is failed and is not retried that day.
- `The morning brief could not be loaded (rate_limited)` or `(timeout)`: the retry budget was used up the same day.
- `No issues match the configured Jira query.`: the query succeeded and returned nothing.
- `Showing the first N matching issues.`: the page or issue cap was reached. The rest are not invented.
- `skipped (missed_day)`: the local date ended before a successful send. It will not be posted the next day.
- `skipped (dst_gap)`: that local time did not exist.
- `unreconciled (receipt_unknown)`: the message may already be in the channel. The bot will not send another copy.
- `failed (partial_delivery)`: the first Discord chunk was accepted and a later chunk was not. The job is not resent.

## Verification

Offline tests cover the default and custom queries, pagination, the page and issue caps, rate limits, denied access, timeouts, malformed payloads, empty results versus failures, mention suppression, split messages, weekday and weekend scheduling, Los Angeles and Sydney daylight-saving offsets, gap and overlap instants, same-day recovery, missed-day skip, restart, receipt loss, and partial delivery. PostgreSQL tests use a disposable database whose name ends in `_test`.

The live Jira and Discord check in [development instructions](../DEVELOPMENT.md) has not been run.
