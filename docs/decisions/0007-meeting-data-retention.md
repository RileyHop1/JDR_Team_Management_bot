# 0007: Meeting data retention

Status: approved by the maintainer. Recorded in [PR #22](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/22). Daniil, project maintainer and security contact (daniil.nahl@protonmail.com), approved this retention period, including the strict total below. This record does not leave a team-confirmation step open for the period. It does not implement capture or transcription. GitHub issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) stays open. Voice UDP on the Pi is still pending in [decision 0006](0006-raspberry-pi-hosting.md), and implementation has not started.

The repository required this decision before capture could be implemented:

- [Security policy](../../SECURITY.md) required an approved retention and deletion policy before recording is enabled, covering temporary audio, transcripts, Discord attachments, backups, and external providers. That policy is this record.
- [Prerequisites](../PREREQUISITES.md) asked what recording and transcript retention is acceptable and told contributors not to guess a default. That page now points here.
- [JDR-004](../ISSUES.md#jdr-004-meeting-capture-and-transcripts) and issue #8 require retention and deletion to be defined before real meetings are recorded. This record defines the period. The rest of that acceptance criterion stays open.
- [Architecture](../ARCHITECTURE.md) stores a deletion deadline on the recording session and a retention deadline on the transcript artifact, and it allows bounded retention of failed-job audio only once that retention is approved.

## Policy

No copy of meeting content may exist more than 30 days after capture end. A day is 24 hours. The clock is UTC. Capture end is the instant a recording session leaves `recording` because of a stop, a cancellation, a disconnect that ends the capture, or a failure. Finishing transcription or delivery does not start a new clock.

The 30 days are one total for every copy: the live database, local audio and transcript files, Discord messages and attachments the bot posted, copies held by a transcription provider, and every `pg_dump` file (on the Pi, off the Pi, and any dump kept for rollback). The total is split so a backup cannot extend a row past day 30:

- Live meeting content is purged at capture end plus 23 days. The session's deletion deadline and the transcript artifact's retention deadline are that instant: 23 times 24 hours after capture end.
- Every `pg_dump` file is deleted before it is 7 days old. A dump taken immediately before the live purge therefore cannot still hold that row at capture end plus 30 days.

The 30 days are a maximum. Content is deleted when its live deadline passes, and earlier where the documents already require that. The start notice tells participants that meeting content is deleted within 30 days of capture end. That sentence is this total, not a promise that bytes remain until day 30.

The period applies to the meeting content the feature documents describe:

- Temporary audio. After successful processing or cancellation, [architecture](../ARCHITECTURE.md) already requires deleting it in that transition. Failed-job audio may remain until the live deadline (capture end plus 23 days). The architecture allowed that hold only if it was approved. This decision is that approval. The documents do not set a shorter period for failed-job audio, and they do not require discarding failed-job audio immediately, so this record does not add either rule.
- Transcript text and local transcript files. They are deleted by the live deadline. The architecture says to avoid retaining transcript content in the database by default. Any copy that is stored anyway is meeting content and is deleted by the same live deadline.
- Discord messages and attachments the bot posted. They are deleted by the live deadline. Deleting a local file does not delete the Discord copy. A copy a recipient saved is outside the bot. The start notice says so.
- Summaries and derived notes. This feature does not store them. The [project overview](../PROJECT_OVERVIEW.md) treats transcript summaries and action-item extraction as optional later features that need their own decision, and the documents do not set a retention period for them. If a later decision stores them, they are meeting content and this same total applies: the live copy is purged at capture end plus 23 days, and a dump that contains them is deleted before the dump file is 7 days old. That later decision is what would allow storing them. It does not extend this period.
- Copies held by an external transcription provider. They are live copies. The purge deletes them by the live deadline. A provider that cannot delete or expire this content by capture end plus 23 days is not acceptable.
- `pg_dump` copies of the database. Every dump file is deleted before it is 7 days old, on the Pi and off the Pi, including a dump kept for rollback. The [production runbook](../operations/runbook.md) has the rotation. The file cap is 7 days so a dump taken when a row is already 23 days old still expires by day 30.

These records are not meeting content. The documents do not set a 30-day deletion for them, and this decision does not add one. Anything in these fields that is not in the lists below is meeting content and follows the live deadline:

- Recording-session metadata, limited to: the meeting id; the lifecycle state, which is one of `requested`, `recording`, `transcribing`, `delivering`, `completed`, `failed`, or `cancelled`; the immutable creation timestamp; the capture-end timestamp when it was written; the deletion deadline; and authorization and notice metadata as restricted below. The bounded storage reference is cleared when the bytes are deleted. It is not kept.
- Authorization and notice metadata, limited to non-personal ids, UTC timestamps, and fixed tokens. Allowed ids are the meeting id, the session id, a channel id, and a message id. A Discord user id is personal data and is not exempt. Allowed tokens are the closed set `notice_recorded` and `stop_available`. A later decision may add a token to that set. It may not store free text, a display name, a participant list, or notice text under this exemption.
- Transcript-artifact metadata, limited to: the session id; the delivery receipt when one exists, which is an opaque message id and not the message text; the retention deadline; the purge attempt count and the next-attempt timestamp (an integer and a UTC timestamp); and the failure category. The failure category is one of `discord_receipt_missing`, `provider_delete_unsupported`, `provider_delete_failed`, or `local_delete_failed`. No other category string is stored.
- The provider job reference, when one exists. It is an opaque id: one token of letters, digits, `.`, `_`, and `-`, with no `://`, `@`, `/`, `?`, or whitespace. It is not a URL, a credential, or provider error text. A value that does not match is not stored. The purge then uses category `provider_delete_unsupported` rather than keeping the text.
- Live meeting, reminder, and guild-configuration rows from the implemented features. Those rows keep their titles, times, channels, and settings. They are scheduling records, not capture content.

The future implementation deletes due content with the purge below. A deletion request uses that same path and does not wait for the deadline. Logs for both carry identifiers. Only a purge failure carries a fixed category. Logs never contain meeting content, and they never contain a Discord user id.

## Clock

Store the capture-end instant and both deadlines as UTC-aware timestamps. The live deadline is capture end plus 23 times 24 hours. Do not compute the deadline in the guild's IANA zone, and do not use a civil calendar date.

The session row stores `created_at`, set once when the row is inserted and never updated. The row is inserted on entry to `requested`, or on entry to `recording` if that is when the row is created. Entry to `recording` is at or before the transition out of `recording`, so `created_at` is always at or before capture end. When the row is inserted on entry to `recording`, `created_at` is the recording-start time. Either value is a safe fallback: adding 23 days cannot land later than capture end plus 23 days.

The implementation writes capture end when the session leaves `recording`. If the state is `transcribing`, `delivering`, `completed`, `failed`, or `cancelled` and that write is missing, the deadline is `created_at` plus 23 days. Do not use the meeting row's `starts_at`. An update can move `starts_at` later, and capture can finish before the scheduled start, so `starts_at` plus any period can fall after capture end plus 23 days. A session that is still `requested` or `recording` has not reached capture end, so this retention purge does not delete it. This decision does not set the maximum capture duration. Duration, budget, and language remain open in the prerequisites.

## Purge

The future implementation runs one purge on the existing single-process scheduler. It does not add a second process or a broker. The scheduler polls every 5 seconds (`POLL_INTERVAL_SECONDS` in `src/jdr_bot/policy.py`). A poll selects a recording session or transcript artifact only when its deadline is at or before the current UTC instant, the row is not in the terminal purged state, and `next_attempt_at` is unset or has passed. It does not select a row on every poll while a retry is waiting. It does not use the reminder grace window. A purge that became due while the process was down still runs on the first poll after the process returns. It is not marked `missed_window`.

For each selected session the purge does the following:

1. Delete local temporary audio and local transcript files. A missing file is success. This step does not wait on Discord.
2. Delete the Discord message identified by the stored delivery receipt, when a receipt is stored. That delete removes the attachment Discord stored for that message. An unknown message or an already-deleted message is success. The purge does not search channel history and does not post to another channel. A session that never attempted delivery has no Discord copy. That is success.
3. Ask the transcription provider to delete its copy when a stored provider job reference exists. An object the provider has already removed is success.
4. Clear content fields, including any transcript text stored in the database, and clear the storage reference. Leave only the metadata listed above.

Step 4 runs once local deletion has succeeded and, when a provider reference is stored, the provider deletion has succeeded or reached the terminal `provider_delete_unsupported` state below. A missing Discord receipt does not block step 4. Database transcript text is cleared on that same pass. A crash between steps is safe to repeat. Bytes that are already gone stay gone. The database update is what stops the row from being selected again. A second run after the terminal purged state finds nothing further to delete.

A delivery that was attempted without a stored receipt may still have a Discord copy, and the bot cannot address it. Local files, the provider copy, and database transcript text are still removed once those deletes succeed. A missing receipt does not keep them. The Discord part is retried in case the receipt is written late, then the row becomes terminal:

- Attempt 1 deletes the local files and asks the provider to delete its copy. Step 4 then clears database transcript text and the storage reference. A transient provider failure skips that clear, uses category `provider_delete_failed`, and does not start the receipt retries. When the deletable bytes are gone and the receipt is still missing, set the attempt count to 1 and `next_attempt_at` to 60 seconds later. Do not log yet. The 5-second poll does not select the row before `next_attempt_at`.
- Attempt 2 runs only after `next_attempt_at`. If a receipt is now stored, delete that Discord message and mark the row purged. Log `meeting_content_purged` once. If the receipt is still missing, set the attempt count to 2 and `next_attempt_at` to 300 seconds later. Do not log.
- Attempt 3 runs only after that second wait. If a receipt is now stored, delete the message, mark the row purged, and log `meeting_content_purged` once. If the receipt is still missing, mark the row purged with category `discord_receipt_missing` and log `meeting_content_purge_failed` once. The row is terminal and is not selected again.

That is three attempts. The failure is logged once, on the transition to the terminal state, not on every poll and not on the earlier attempts. The purge still does not read channel history.

A local delete that fails uses category `local_delete_failed`. The row stays due because the bytes are still present. The next attempt waits 60 seconds, then 300 seconds, then 900 seconds, then 3600 seconds, and further attempts stay at 3600 seconds. Each attempt logs `meeting_content_purge_failed` once, when it runs. A poll that is waiting on `next_attempt_at` does not log. A provider delete that fails transiently uses the same backoff and category `provider_delete_failed`. A provider that cannot delete uses category `provider_delete_unsupported`: the same three-attempt bound as a missing receipt, then a terminal purged row and one log line. Local content is still cleared. A provider that needs this category does not meet this decision, and the log is the record of that.

No transcription provider is selected. When a later decision selects one, the purge calls that provider's delete. Until a provider exists, issue #8's requirement to document that provider's external retention limit stays open.

## Deletion on request

A deletion request for one session runs the same purge immediately. It removes the same content the live deadline would remove: temporary audio still held, local transcript text and files, database transcript text, Discord messages and attachments the bot posted, and the provider copy when a job reference is stored. It does not delete a copy a recipient already saved. It does not delete the live meeting row. A missing Discord receipt follows the same bounded retries and the same terminal category. It does not keep transcript text.

Who may request deletion is still open. [Prerequisites](../PREREQUISITES.md) item 4 asks who may start recording, stop recording, access transcripts, and request deletion. This decision does not choose that role. The request path stays unavailable until that decision names the role. The scheduled purge does not depend on that name.

## Backups

A `pg_dump` file is a copy of the database. The [production runbook](../operations/runbook.md) already treats dumps as meeting data. Dump rotation is a separate program from `pg_dump`. The dump script uses `set -eu` and exits when `pg_dump` fails. Rotation is not in that script, so a stretch of failed dumps still deletes old files. On the Pi, `jdr-backup-rotate.timer` runs the rotation. It does not depend on `jdr-pg-dump.service` succeeding.

The age of a dump is the UTC stamp in its filename (`jdr_bot-YYYYMMDDTHHMMSSZ`), which the dump script takes immediately before `pg_dump`. Rotation does not use file modification time. A copy that resets modification time still expires with the stamp. The same rule covers a rollback copy: it keeps that stamp in the name (for example `jdr_bot-20261023T004730Z.rollback.dump`) and lives in the rotated directory. The rotation deletes every regular file whose name ends in `.dump`, at any depth under the directory. A `.dump` file with no stamp is deleted on the next run, because its age is unknown.

The script deletes a stamped file once the stamp is 6 days old, that is 8640 minutes. That leaves 24 hours before the 7-day cap. The timer is hourly (`OnCalendar=hourly`) with `AccuracySec=1min`, `RandomizedDelaySec=5min`, and `Persistent=true`. A file can become eligible just after a run, and one run can fail. The next success is then at most two hourly slots later, plus the 5-minute randomized delay and the 1-minute accuracy window: 126 minutes. The latest deletion is 8640 + 126 = 8766 minutes of age, which is 6 days, 2 hours, and 6 minutes. The 7-day cap is 10080 minutes. The margin is 1314 minutes (21 hours and 54 minutes). `Persistent=true` runs one missed elapse after a power cut, subject to that same randomized delay. The Pi and the backup host must come back while that margin remains. A host that stays off until a dump reaches 7 days has missed the cap.

GNU `find -mtime` is not used. On GNU findutils, `-mtime +6` ignores the fractional part of a 24-hour period and becomes true only at 7 days, which is already the cap, and the next run is later than the cap. GNU `-mmin +8640` matches a file at 8640 minutes and does not match a file at 8639.5 minutes (findutils 4.9.0). That predicate is still GNU-specific. The off-Pi host is not required to provide GNU find. Both hosts run the same POSIX `sh` script in the runbook. It compares the filename stamp with a cutoff of now minus 6 days, using POSIX `date`, `awk`, and `find`. It does not use `-mmin`, `-mtime`, or `-delete`.

Where the off-Pi host has systemd, the same timer settings apply (`OnCalendar=hourly`, `AccuracySec=1min`, `Persistent=true`, `RandomizedDelaySec=5min`), aimed at the backup directory and not at `pg_dump`. Where it does not, cron runs the same script hourly and at boot (`@reboot`). The boot run is the catch-up for a missed hour. Cron has no randomized delay, so its latest deletion is earlier than the Pi's, inside the same cap.

A dump younger than that age can still hold capture rows that were already days old when the dump was taken. The live purge at 23 days is what keeps those rows inside the 30-day total: the oldest row in a dump taken immediately before the purge is about 23 days old, and the file is gone before it is 7 days old. The rotation margin means that file is gone about 22 hours before day 30. A purge that runs late because the process was down still meets day 30 for a dump taken immediately before that purge when the lateness is inside those 21 hours and 54 minutes. The process restarts under systemd and runs the purge on the first poll. A longer outage is outside this margin: bring the process back before then, and do not treat a dump as a way to keep capture content. After a restore, the purge deletes capture content whose deadline has passed. This decision does not expire live meeting, reminder, or guild-configuration rows.

Operators do not keep a further copy. A hard link or a second directory outside `/var/backups/jdr` on the Pi, or outside the one off-Pi backup directory, is another copy and is not rotated.

## Notice

Recording stays visible and explicitly authorized, as the security policy and the architecture already require. The start notice tells participants that meeting content is deleted within 30 days of capture end, that temporary audio is deleted sooner after successful processing or cancellation, that a deletion request can run earlier once access is defined, and that a transcript posted in Discord can be copied by a recipient and that copy is outside the bot.

Late arrivals, withdrawals, the detailed stop control, and who may start, stop, or read transcripts remain open. If notice or authorization cannot be maintained, capture stops. This decision does not replace that rule and does not finish the consent policy.

## Logs

Logs never contain meeting content. They never contain a Discord user id. [Code standards](../../CODE_STANDARDS.md) say not to log unnecessary personal data, and the requester's Discord user id is personal data. The event name is the record that a deletion was requested. A purge or a deletion request logs identifiers only, except the failure event, which also logs one fixed category:

- `meeting_content_purged`, with the session id and the artifact id
- `meeting_content_deleted_on_request`, with the session id and the artifact id
- `meeting_content_purge_failed`, with the session id, the artifact id, and one category from the closed set `discord_receipt_missing`, `provider_delete_unsupported`, `provider_delete_failed`, or `local_delete_failed`

The success events do not carry a category. The failure line is logged once per attempt that actually runs, or once on entry to a terminal state, as the purge section specifies. It is not logged on a 5-second poll that does not attempt the purge. The line omits audio, transcript text, summaries, titles, participant speech, file contents, channel message text, provider error text, and any free-text reason. The same omission already applies to reminder, brief, and startup logs.

## What this does not decide

Who may start or stop capture, who may read transcripts, or who may request deletion. How late arrivals and withdrawals are handled. The maximum capture duration, the budget, the language, and which transcription provider or local model is used. Whether a future voice library installs on the Pi. Whether summaries are implemented. Whether non-content session rows should later be expired. Voice UDP on the Pi, which remains pending in decision 0006. This record does not implement the purge, and it does not complete issue #8.
