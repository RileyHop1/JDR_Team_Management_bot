# 0004: Persisted guild configuration

Status: provisional. The behavior below is what [PR #17](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/17) merged. Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39531857559)). GitHub issue [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11) is closed. The team still needs to confirm this before treating it as final, and the live `/config` check has not been run. It was chosen so JDR-006 could store the non-secret settings in issue #11 without moving Jira credentials, or the process-wide Jira query, into PostgreSQL.

## What is stored

Migration `0004` adds nullable columns to `guild_configurations`:

| Column | Meaning |
| --- | --- |
| `meetings_channel_id` | Discord text channel id, or null |
| `brief_channel_id` | Discord text channel id, or null |
| `timezone` | IANA name, 1 to 64 characters, or null |
| `brief_time` | Local wall time as `HH:MM` in 24-hour form, or null |

Null means that field falls back to the environment. `created_at` stays a UTC timestamp. `brief_time` is a wall-clock string, not a UTC instant: the zone can change, and the UTC instant moves with the offset. The database rejects a non-canonical time, a non-positive channel id, an empty zone, and a zone longer than 64 characters.

There is no column for a Jira token, email, base URL, project key, status list, or JQL. The architecture's later list (allowed operators, Jira project/filter, and status mapping) is not stored here.

## Environment defaults

Startup does not insert a guild row and does not copy environment values into the table. A missing row is the same as a row whose new columns are null. A row created by the first meeting has null settings, so it uses the environment until an operator stores a value.

| Environment | Used when the stored field is null |
| --- | --- |
| `BOT_TIMEZONE` | Guild IANA zone. Required. |
| `MEETINGS_CHANNEL_ID` | Meetings channel. Optional. |
| `BRIEF_CHANNEL_ID` | Brief channel, and only when the brief group from decision 0003 is complete |
| `BRIEF_TIME` | Brief `HH:MM`, under the same brief group |

A stored non-null field wins over the environment for that field only. Changing the environment later does not replace a stored value. `/config set` with `clear` sets that column back to null, and the environment applies on the next read. A row for a guild other than `DISCORD_GUILD_ID` is ignored.

## Commands

`/config view` and `/config set` are guild-scoped, ephemeral, and require `DISCORD_OPERATOR_ROLE_ID` through `can_manage`. An administrator without that role is rejected.

`/config set` can change the meetings channel, brief channel, IANA zone, and brief time. At least one change is required. `clear` removes one stored field. Setting and clearing the same field is rejected.

A channel must be a text channel in `DISCORD_GUILD_ID` that the bot can view and send in. The service checks the channel directory; the slash-command channel type is not the only check. Invalid zones and times are rejected with a fixed message that does not repeat the input. Logs record the guild id and the field names. They do not record values, tokens, or exception text.

## Effect on jobs

Meetings that are already stored keep the zone and channels saved on the meeting. `/meeting create` uses the stored zone only when the operator omits the zone. An explicit zone still wins. The stored meetings channel is not copied into `/meeting create` and does not move existing reminders. It is the configured meetings destination for a later transcript feature.

`Settings.brief_schedule()` builds the morning brief from the stored channel, time, and zone, then from the environment for any field that is still null. The Jira token, email, base URL, project, statuses, and JQL stay in the environment. The schedule object still has no secrets.

On each poll the brief scheduler reloads that schedule:

- A future brief that has never been attempted is rewritten to the current channel, zone, and UTC instant for the same local date before it can be claimed.
- A scheduled retry (`attempt_count > 0`) moves to the new channel. Its due instant and retry wait stay, so the retry does not become a new local date.
- Claimed, delivered, skipped, failed, and unreconciled rows are not edited and are not sent again. A claim already in progress keeps the channel captured when it was claimed.
- Moving today's time earlier can make that same local day due immediately, which is the existing same-day recovery. Moving it later waits. Older local dates are not backfilled.
- A spring-forward gap marks that never-attempted row `skipped` / `dst_gap`. Changing the time later does not reopen that local date.
- If the stored override cannot be read or fails validation, that poll does not plan, send, or unreconcile brief rows. Reminder jobs still run. The log line is `brief_schedule_invalid` or `brief_schedule_lookup_failed`, without the submitted value.

Weekday delivery stays the code policy in decision 0003. It is not a column.

Downgrading from `0004` to `0003` drops these columns and the values in them. The guild row and the brief jobs remain.

## What this does not decide

Whether the stored meetings channel should become the default reminder text channel and the transcript destination. Whether operators, the Jira project, filter, status names, or JQL should move out of the environment. Whether a skipped daylight-saving date should be reopened after the time is corrected. Whether 09:00, weekdays-only, and one shared guild zone match the team. Those need confirmation before this decision is final.
