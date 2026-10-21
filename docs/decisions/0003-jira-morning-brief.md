# 0003: Jira morning brief

Status: provisional. The team still needs to confirm this before treating it as final. It was chosen so JDR-003 could be implemented without guessing a Jira deployment, status names, or a weekend policy. Where the prerequisites left a choice open, the narrower option is used.

## Jira access

Jira Cloud only. `JIRA_BASE_URL` must be `https://<site>.atlassian.net` with no userinfo, path, query, or fragment. Authentication is HTTP Basic with `JIRA_USER_EMAIL` and `JIRA_API_TOKEN`. The API token is a secret. The email is personal data. Neither is written to PostgreSQL, logs, or the brief.

The adapter calls `GET /rest/api/3/search/jql` and requests only `summary`, `status`, and `assignee`. It does not create, transition, comment on, or otherwise edit issues. Self-hosted Jira is out of scope until the team selects it. The token should belong to a Jira user that cannot edit issues; this process cannot prove that scope by itself.

A 200 body is a search result only when `issues` is an array. A payload such as `{}` or `{"errorMessages": [...]}` is `malformed_response`, not an empty brief. The response body is read with a byte cap and is not logged. HTTP 429 uses `Retry-After` when that header is a delay or an HTTP date, and the wait is capped at 15 minutes so one brief cannot be postponed for hours. A missing or invalid header keeps the usual 15-second then 30-second backoff. The retry waits at least as long as the longer of those two.

Credentials are process-wide environment settings. `Settings.brief_schedule()` is the seam that turns settings into a `BriefSchedule` with no secrets. Issue #11, recorded in [decision 0004](0004-guild-configuration.md), fills the channel, time, and zone from stored guild settings when those fields are set. The token and email stay in the environment, as do the base URL, project, statuses, and JQL.

## Query

There is no guessed status list and no assignee filter. When the brief is enabled, set either:

- `JIRA_PROJECT_KEY` and `JIRA_STATUS_NAMES` (comma-separated exact names), which become `project = "<key>" AND status IN (...) ORDER BY key ASC`, or
- `JIRA_JQL`, which replaces that query verbatim. `JIRA_PROJECT_KEY` is still required. The JQL text is not posted to Discord and is not logged.

The default query includes every matching issue in the project, not a guessed set of teammates. Pages use `nextPageToken`, stop at 5 pages or 100 issues, and say when the result was cut off. A blank `nextPageToken` is treated as missing and is not sent. If Jira says the page is not the last one and there is no token, the brief is marked truncated and says `Showing the first N matching issues.` Descriptions, comments, and changelog are not requested.

A missing or null `assignee` is rendered as `unassigned`. An assignee object with no `displayName` (an account id only, or an empty object) is rendered as `assignee name unavailable`. That issue is still assigned.

## Schedule

`BRIEF_TIME` is required when the brief is on. It is `HH:MM` in 24-hour local time. The zone is `BOT_TIMEZONE`. There is no implicit clock time in code. `.env.example` shows `09:00` as the provisional morning to confirm.

The brief runs Monday through Friday in that zone. Saturday and Sunday are not posted. A missed weekday is not backfilled on a later day.

The due instant is the UTC conversion of that local wall time. After a daylight-saving change the wall time stays the same and the UTC instant moves with the offset. If the wall time does not exist (spring forward), that local date is stored as `skipped` / `dst_gap` and is not sent. If the wall time happens twice (fall back), the earlier UTC instant is used. With the weekday policy, US and Australian transition Sundays are not brief days; the resolver is still tested for a later change to that policy.

## Delivery and recovery

Brief jobs are their own table, `brief_jobs`, not reminder rows. One process polls reminders and briefs on the same tracked task. A job is eligible on its local date once `due_at <= now`. The window lasts until the next local midnight, not the 60-second reminder grace.

- Same-day recovery sends a brief that is still due today and has not finished.
- A scheduled row whose local date has passed becomes `skipped` (`missed_day`), or `failed` (`retry_window_elapsed`, or the stored category) if a delivery was already attempted.
- Transient Jira and Discord failures retry up to 3 attempts, waiting 15 seconds and then 30 seconds, or longer when Jira sends a longer `Retry-After` within the 15-minute cap. HTTP 401/403 and a rejected query fail immediately.
- An empty query posts `No issues match the configured Jira query.` A terminal query failure posts `The morning brief could not be loaded (<category>).` and does not include issue text. Those two messages are different. A transient Discord error while posting that failure notice retries and keeps the Jira category. A non-transient Discord error on that notice fails the job and still keeps the Jira category.
- The brief is posted only to a text channel in the configured guild. A channel in another guild is `channel_wrong_guild` and is not retried.
- A crash after Discord accepts a message but before the receipt is stored leaves the job claimed. The next poll marks it `unreconciled` (`receipt_unknown`) and does not send it again. A later chunk that fails after the first chunk was accepted is `failed` (`partial_delivery`) and is not resent.
- Cancellation during the Jira read, before any Discord send, releases the claim and does not consume the attempt, so that local day can still be sent. Cancellation after a send has started leaves the claim in place.

Issue titles, assignees, and the JQL string are not logged. Jobs store the issue count, not issue content. Mentions are broken in the text and Discord allowed-mentions are set to none. Output longer than 2000 characters is split.

## What this does not decide

Whether 09:00, weekdays-only, the earlier overlap instant, same-day-only recovery, and the project-wide status query match the team. Whether assignees should be limited to the team. Whether a self-hosted Jira deployment will replace Cloud. Those need confirmation before this decision is final.
