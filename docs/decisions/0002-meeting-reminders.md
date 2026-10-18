# 0002: Meeting reminders

Status: provisional. The team still needs to confirm this before treating it as final. It was chosen so JDR-002 could be implemented without inventing a broader permission model or a late-delivery policy. It follows the conservative recovery default already proposed in the architecture: skip reminder offsets that are already past, and keep future ones.

## Who can manage meetings

Only a member who holds `DISCORD_OPERATOR_ROLE_ID` in `DISCORD_GUILD_ID` can create, list, view, update, or cancel a meeting. An administrator without that role is rejected. No separate viewer role is introduced here. Recording and transcript permissions remain open in the prerequisites.

## What a meeting is

Meetings are one-shot. Recurrence is out of scope. The voice channel is stored and named in the reminder; this feature does not join voice.

The operator supplies:

- a title of at most 100 characters, with surrounding and repeated whitespace collapsed;
- a local start as `YYYY-MM-DD HH:MM` (`T` is accepted in place of the space);
- an IANA time zone, or an empty zone so the command uses `BOT_TIMEZONE`;
- a text channel the bot can view and send in, and a different voice channel the bot can view;
- one to five unique offsets of 1 to 10080 minutes (7 days).

Ambiguous local times (clocks fall back) and nonexistent local times (clocks spring forward) are rejected. Offsets are subtracted from the resolved UTC instant. They are not computed by subtracting minutes from the wall clock.

## Delivery

One process polls every 5 seconds. A scheduled reminder is eligible only when `due_at <= now` and `due_at >= now - 60 seconds`. The scheduler claims up to 10 jobs, sends, then stores the Discord message id.

- A never-attempted reminder older than the 60-second grace becomes `skipped` with `missed_window`.
- A scheduled reminder that already failed at least once and is now outside the grace becomes `failed`. Its category is kept, or set to `retry_window_elapsed` when none was stored.
- Transient Discord HTTP 429 and 5xx responses retry up to 3 attempts, waiting 15 seconds and then 30 seconds. HTTP 403 and 404 fail immediately.
- If the send succeeds and storing the receipt fails, the job stays `claimed` and is not sent again. After the grace period that claim becomes `unreconciled` with `receipt_unknown`. Exactly-once delivery is not possible across Discord and PostgreSQL.

Changing only the title keeps reminder job ids. Changing the start, zone, offsets, or channels cancels still-scheduled jobs and inserts occurrences that have not already finished. A delivered, skipped, failed, or unreconciled row for the same offset and UTC instant is not recreated. Changing the zone requires a new start time. A claimed job blocks update and cancel until the claim finishes. A cancelled meeting cannot be changed, and cancelling it again reports that it is already cancelled. `/meeting list` shows scheduled meetings only, at most 10. View hides cancelled reminder rows.

## Deployment

The scheduler starts after the schema check and stops during shutdown. If its task ends while the gateway session is still up, `on_ready` starts it again. Two processes against the same database are not coordinated and can both deliver. The morning brief is a separate job type on the same poll task; its policy is [decision 0003](0003-jira-morning-brief.md), not this one.
