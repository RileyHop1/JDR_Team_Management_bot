# Meeting configuration and reminders

Status: merged in [PR #15](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/15). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39085620688)). Offline tests cover the behavior below. A live reminder in the Discord test server has not been demonstrated, and [decision 0002](../decisions/0002-meeting-reminders.md) is provisional and needs team confirmation, so GitHub issue [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6) stays open.

Backlog item: [JDR-002](../ISSUES.md#jdr-002-meeting-configuration-and-reminders).

## Commands

All `/meeting` commands are guild-scoped, ephemeral, and require the configured operator role in `DISCORD_GUILD_ID`.

| Command | Behavior |
| --- | --- |
| `/meeting create` | Title, local start, text channel, voice channel, and comma-separated minute offsets. An omitted time zone uses the stored guild zone, or `BOT_TIMEZONE` when none is stored. |
| `/meeting list` | Up to 10 scheduled meetings, soonest first. |
| `/meeting view` | One meeting and its reminder states. Cancelled reminder rows are hidden. |
| `/meeting update` | Change any stored field. At least one field is required. A new time zone also requires a new start. |
| `/meeting cancel` | Cancel the meeting and its still-scheduled reminders. |

The bot does not join the voice channel. A reminder is a text message in the chosen text channel, with mentions suppressed. It names the meeting, the local start, the offset, and the voice channel.

## Schedule rules

Starts are stored in UTC. The IANA zone is stored with the meeting and used to display the wall time. Local times that do not exist or that occur twice because of daylight saving are rejected. A start or reminder that is already due is rejected. Offsets are whole minutes before the UTC instant, from 1 to 10080, at most five, all unique.

## Delivery and restart

Jobs live in PostgreSQL. After a restart the scheduler rebuilds its work from those rows; it does not keep an in-memory timetable.

A reminder is sent only during a 60-second grace period after it becomes due. Older never-attempted reminders are marked `skipped` (`missed_window`). Future reminders for the same meeting stay scheduled. Transient Discord failures retry twice more (15 seconds, then 30 seconds). A crash after Discord accepts the message but before the receipt is stored leaves the job claimed. That claim is not sent again; once the grace period passes it is marked `unreconciled` (`receipt_unknown`). The channel may already contain the message.

## Operation

Apply migrations through `0004` with the documented Alembic command. No new environment variable is required. When `/meeting create` omits the zone, the stored guild zone is used, and `BOT_TIMEZONE` is used when that column is null. Changing the guild zone does not rewrite meetings that already exist. Run one bot process. Logs record meeting and job ids, states, and error categories. They do not record titles, message text, tokens, or exception strings.

Shutdown cancels the scheduler task before the Discord connection closes. A claimed job that does not finish is left claimed and follows the receipt rule above on the next start.

## Troubleshooting

- `Operator role required.`: the member is outside the configured guild or does not hold `DISCORD_OPERATOR_ROLE_ID`. Administrator is not sufficient.
- `Use the start format YYYY-MM-DD HH:MM.`: the start was not a minute-precision local time.
- `Use an IANA time zone such as America/Los_Angeles.`: the zone is empty, unknown, or longer than 64 characters. An omitted command option uses the stored guild zone, or `BOT_TIMEZONE` when that is unset.
- `That local time does not exist` or `happens twice`: choose a wall time outside the daylight-saving gap or overlap.
- `The meeting start must be in the future` or `would already be due`: move the start later or shorten the offset.
- `Choose a text channel` or `Choose a voice channel`: the channel is the wrong type, is outside the guild, or the bot cannot view it. The text channel also needs Send Messages.
- `A reminder is currently being delivered; try again shortly.`: a job is claimed. Wait for delivery, skip, or unreconcile, then retry the update or cancel.
- `skipped (missed_window)`: the process was down, or the poll ran more than 60 seconds after the due time. It will not be sent late.
- `unreconciled (receipt_unknown)`: the message may already be in the channel. The bot will not send another copy. Compare the channel with `/meeting view`.
- `failed (channel_forbidden)` or `failed (channel_missing)`: channel permissions or the channel changed after the meeting was created. Create a new reminder occurrence only by updating the meeting onto a future due time; a finished occurrence is not recreated.
- `The meeting command could not be completed.`: an unexpected failure. The log line `meeting_command_failed` contains the command name and exception type only.

## Verification

Offline tests cover create, update, and cancel; guild and role denial; invalid zones and offsets; Los Angeles and Sydney daylight-saving gaps and overlaps; absolute offsets across those transitions; restart recovery; the grace boundary; duplicate suppression when a receipt cannot be stored; and transient versus permanent delivery failure. PostgreSQL tests use a disposable database whose name ends in `_test`.

The live test-server reminder in [development instructions](../DEVELOPMENT.md) has not been run.
