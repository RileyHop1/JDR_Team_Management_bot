# Persisted guild configuration

Status: implemented and covered by offline tests. A live `/config` check in the Discord test server has not been run, so JDR-006 is not complete. The storage and job rules are provisional and need team confirmation; see [decision 0004](../decisions/0004-guild-configuration.md).

Backlog item: [JDR-006](../ISSUES.md#jdr-006-persisted-guild-configuration).

Operators can view and update the guild's meetings channel, brief channel, IANA time zone, and morning-brief time. The values live in `guild_configurations`. Jira credentials and the Jira query stay in the environment.

## Commands

`/config view` and `/config set` are guild-scoped, ephemeral, and require `DISCORD_OPERATOR_ROLE_ID` in `DISCORD_GUILD_ID`. An administrator without that role is rejected.

| Command | Behavior |
| --- | --- |
| `/config view` | Shows the effective time zone, meetings channel, brief channel, and brief time, and whether each value is stored or taken from the environment. |
| `/config set` | Updates any of those fields. At least one field is required. `clear` removes one stored override so the environment default applies again. |

A channel must be a text channel in the configured guild that the bot can view and send in. A zone must be an IANA name such as `America/Los_Angeles`, at most 64 characters. Brief time is `HH:MM` in 24-hour form, for example `09:00`. Invalid input is rejected with a fixed message and is not stored.

## Environment and startup

There is no automatic copy from the environment into the table. A missing row, or a null column, uses the environment:

| Stored column | Environment fallback |
| --- | --- |
| `timezone` | `BOT_TIMEZONE` |
| `meetings_channel_id` | `MEETINGS_CHANNEL_ID`, when set |
| `brief_channel_id` | `BRIEF_CHANNEL_ID`, when the brief group is complete |
| `brief_time` | `BRIEF_TIME`, when the brief group is complete |

A stored value wins over the environment until it is cleared. Changing the environment afterward does not overwrite the row. The first meeting still creates a guild row if one is missing; that insert does not erase settings that are already stored.

## What the settings change

`/meeting create` uses the stored zone when the zone option is omitted. An explicit zone on the command still wins. Meetings that already exist keep their own zone and channels. The stored meetings channel is not applied to existing reminders and is not filled in when `/meeting create` omits a text channel.

The morning brief reads the stored channel, time, and zone through `Settings.brief_schedule()` on each poll. The Jira token and email are not read from the row. Future brief jobs that have not been attempted pick up a new channel, zone, and time on the next poll, for the same local date. A retry moves to the new channel and keeps its due instant. Delivered, skipped, failed, unreconciled, and claimed rows are not sent again. Moving today's brief earlier can post it later the same local day. Moving it later waits. A time that does not exist because clocks spring forward is `skipped (dst_gap)` and is not reopened by a later edit. Older local dates are not backfilled.

If the stored zone or time cannot be validated, that poll does not plan, send, or unreconcile a brief. Reminders continue. The log says `brief_schedule_invalid` and does not include the value, then `brief_schedule_unavailable` when the scheduler loses a usable schedule. A failed settings read logs `brief_schedule_lookup_failed` with the exception type only, and the same `brief_schedule_unavailable` line. That poll also skips plan, send, and unreconcile.

## Operation

Apply migration `0004` with `uv run --env-file .env alembic upgrade head`. The process rejects an older schema. Downgrading to `0003` deletes the stored settings and leaves the guild row. Run one bot process. Two processes on the same database can both deliver a reminder or a brief.

Logs for a successful update contain the guild id and the field names (`guild_config_updated`). They do not contain channel ids, the zone, the brief time, Jira tokens, or email addresses.

## Troubleshooting

- `Operator role required.`: the member is outside the configured guild or does not hold `DISCORD_OPERATOR_ROLE_ID`. Administrator is not sufficient.
- `Provide at least one setting to change.`: `/config set` was sent with every option omitted.
- `Choose either a new value or clear for each setting.`: the same field was both set and cleared.
- `Use an IANA time zone such as America/Los_Angeles.`: the zone is empty, unknown, or longer than 64 characters.
- `Use HH:MM in 24-hour time, for example 09:00.`: the brief time is not a zero-padded 24-hour minute.
- `Choose a text channel in this server that the bot can view and send messages in.`: the channel is the wrong type, is in another guild, or the bot cannot view and send there.
- `The bot cannot view that channel.`: Discord refused the channel lookup.
- `Could not verify the channel. Try again shortly.`: the channel lookup failed for another reason.
- `The config command could not be completed.`: an unexpected failure. The log line `config_command_failed` contains the command name and exception type only.
- `brief_schedule_invalid`: a stored zone or time could not be used. The value is not logged.
- `brief_schedule_lookup_failed`: the stored settings could not be read. The log contains the exception type only.
- `brief_schedule_unavailable`: the scheduler has no usable brief schedule. That poll does not plan, send, or unreconcile brief rows. Reminders still run.
- `skipped (dst_gap)`: the brief's local time did not exist on that date. Editing the time does not send that date later.

## Verification

Offline tests cover operator denial, including an administrator who does not hold the operator role, invalid zones, times, and channels, a channel the bot cannot post in, a channel in another guild, environment fallback, clearing a stored zone, persistence of the other fields, a meeting insert that does not wipe settings, a stored-zone lookup failure on `/meeting create`, upgrade and downgrade of migration `0004`, and brief jobs that pick up a new channel and time without resending a delivered day. Moving today's brief earlier can send that same local day. A `dst_gap` date stays skipped after the time is corrected. PostgreSQL tests use a disposable database whose name ends in `_test`, including `apply_refresh` and `redirect_channel`.

The live test-server check in [development instructions](../DEVELOPMENT.md) has not been run.
