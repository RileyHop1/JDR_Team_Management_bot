# 0007: Meeting data retention

Status: approved by the maintainer. Recorded in [PR #22](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/22). Daniil, project maintainer and security contact (daniil.nahl@protonmail.com), approved this retention period. This record does not leave a team-confirmation step open for the period. It does not implement capture or transcription. GitHub issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) stays open. Voice UDP on the Pi is still pending in [decision 0006](0006-raspberry-pi-hosting.md), and implementation has not started.

The repository required this decision before capture could be implemented:

- [Security policy](../../SECURITY.md) required an approved retention and deletion policy before recording is enabled, covering temporary audio, transcripts, Discord attachments, backups, and external providers. That policy is this record.
- [Prerequisites](../PREREQUISITES.md) asked what recording and transcript retention is acceptable and told contributors not to guess a default. That page now points here.
- [JDR-004](../ISSUES.md#jdr-004-meeting-capture-and-transcripts) and issue #8 require retention and deletion to be defined before real meetings are recorded. This record defines the period. The rest of that acceptance criterion stays open.
- [Architecture](../ARCHITECTURE.md) stores a deletion deadline on the recording session and a retention deadline on the transcript artifact, and it allows bounded retention of failed-job audio only once that retention is approved.

## Policy

Meeting content is retained for at most 30 days. A day is 24 hours. The clock is UTC. It starts at capture end: the instant a recording session leaves `recording` because of a stop, a cancellation, a disconnect that ends the capture, or a failure. The session's deletion deadline and the transcript artifact's retention deadline are that same instant plus 30 days. Finishing transcription or delivery does not start a new clock.

The 30 days are a maximum. Content is deleted when its deadline passes. It is deleted earlier where the documents already require that.

The period applies to the meeting content the feature documents describe:

- Temporary audio. After successful processing or cancellation, [architecture](../ARCHITECTURE.md) already requires deleting it in that transition. Failed-job audio may remain until the same deadline. The architecture allowed that hold only if it was approved. This decision is that approval. The documents do not set a shorter period for failed-job audio, and they do not require discarding failed-job audio immediately, so this record does not add either rule.
- Transcript text and local transcript files. They are deleted by the deadline. The architecture says to avoid retaining transcript content in the database by default. Any copy that is stored anyway is meeting content and is deleted by the same deadline.
- Discord messages and attachments the bot posted. They are deleted by the deadline. Deleting a local file does not delete the Discord copy. A copy a recipient saved is outside the bot. The start notice says so.
- Summaries and derived notes. This feature does not store them. The [project overview](../PROJECT_OVERVIEW.md) treats transcript summaries and action-item extraction as optional later features that need their own decision, and the documents do not set a retention period for them. If a later decision stores them, they are meeting content and this same 30-day maximum applies. That later decision is what would allow storing them. It does not extend this period.
- Copies held by an external transcription provider. They must be deleted or expired by the same deadline.
- `pg_dump` copies of the database. Every dump file is deleted by the time it is 30 days old, including copies kept off the Pi and dumps kept for rollback. The Pi's local rotation remains `find -mtime +7`, which removes a dump once it is eight days old. That is inside this cap. The [production runbook](../operations/runbook.md) has the commands.

These records are not meeting content. The documents do not set a 30-day deletion for them, and this decision does not add one:

- Recording-session metadata: the meeting it belongs to, authorization and notice metadata, lifecycle state, and the deletion deadline. The bounded storage reference is cleared when the bytes are deleted.
- Transcript-artifact metadata: the session, a provider job reference when one exists, the delivery receipt, the retention deadline, and the failure category.
- Live meeting, reminder, and guild-configuration rows from the implemented features. Those rows keep their titles, times, channels, and settings.

Metadata fields must not hold audio or transcript text.

The future implementation deletes due content with the purge below. A deletion request uses that same path and does not wait for the deadline. Logs for both carry identifiers and fixed categories. They never contain meeting content.

## Clock

Store the capture-end instant and both deadlines as UTC-aware timestamps. Add 30 times 24 hours to capture end. Do not compute the deadline in the guild's IANA zone, and do not use a civil calendar date.

The implementation writes capture end when the session leaves `recording`. If capture has ended and that write is missing, the deadline is the meeting row's stored UTC start plus 30 days. Every meeting already stores that start. A session that is still `recording` has not reached capture end, so this retention purge does not delete it. This decision does not set the maximum capture duration. Duration, budget, and language remain open in the prerequisites.

## Purge

The future implementation runs one purge on the existing single-process scheduler. It does not add a second process or a broker. On each poll it selects recording sessions and transcript artifacts whose deletion deadline or retention deadline is at or before the current UTC instant. It does not use the reminder grace window. A purge that became due while the process was down still runs. It is not marked `missed_window`.

For each due session the purge does the following, in order:

1. Delete local temporary audio and local transcript files. A missing file is success.
2. Delete the Discord message identified by the stored delivery receipt. That delete removes the attachment Discord stored for that message. An unknown message or an already-deleted message is success. The purge does not search channel history and does not post to another channel.
3. Ask the transcription provider to delete its copy when a provider job reference is stored. An object the provider has already removed is success.
4. Clear content fields and the storage reference. Leave the metadata listed above.

Step 4 runs only after the deletes that apply to that session have succeeded. A failed delete leaves the row due and logs `meeting_content_purge_failed`. A crash between steps is safe to repeat. The database update is last, so a row whose bytes are already gone stays due until the update succeeds. The next run treats the missing file and the missing Discord message as success. A second run after success finds nothing further to delete.

A session that never posted a transcript has no Discord copy to delete. That is success. A delivery that was attempted without a stored receipt may still have a Discord copy, and the bot cannot address it. Local content is still deleted. The artifact stays due, and the log category is `discord_receipt_missing`. The purge does not read the channel to find the message.

No transcription provider is selected. When a later decision selects one, the purge calls that provider's delete. A provider that cannot delete or expire this content by the deadline is not acceptable under this decision. Until a provider exists, issue #8's requirement to document that provider's external retention limit stays open.

## Deletion on request

A deletion request for one session runs the same purge immediately. It removes the same content the deadline would remove: temporary audio still held, local transcript text and files, Discord messages and attachments the bot posted, and the provider copy when a job reference is stored. It does not delete a copy a recipient already saved. It does not delete the live meeting row.

Who may request deletion is still open. [Prerequisites](../PREREQUISITES.md) item 4 asks who may start recording, stop recording, access transcripts, and request deletion. This decision does not choose that role. The request path stays unavailable until that decision names the role. The scheduled purge does not depend on that name.

## Backups

A `pg_dump` file is a copy of the database. The [production runbook](../operations/runbook.md) already treats dumps as meeting data. Local files under `/var/backups/jdr` are deleted by `find -mtime +7`. GNU `find` ignores the fractional part of a 24-hour period, so `+7` removes a dump once it is eight days old. That rotation stays.

Copies that leave the Pi, including a dump kept for rollback, are deleted once they are 30 days old. The runbook uses `find -mtime +29` on the backup host. GNU `find` ignores the fractional part of a 24-hour period, so `+29` matches a file that is 30 days old or older, and `+30` would leave it into the next day. `rsync -a` preserves the modification time written when `pg_dump` finished. Operators do not keep a further copy past that age.

A dump file younger than 30 days can still hold capture rows that were already days old when the dump was taken. The file-age cap is the control the runbook can apply without splitting a dump by table. A restore is not a way to keep meeting-capture content past its deletion deadline. After a restore, the purge deletes capture content whose deadline has passed. This decision does not expire live meeting, reminder, or guild-configuration rows.

## Notice

Recording stays visible and explicitly authorized, as the security policy and the architecture already require. The start notice tells participants that meeting content is deleted within 30 days of capture end, that temporary audio is deleted sooner after successful processing or cancellation, that a deletion request can run earlier once access is defined, and that a transcript posted in Discord can be copied by a recipient and that copy is outside the bot.

Late arrivals, withdrawals, the detailed stop control, and who may start, stop, or read transcripts remain open. If notice or authorization cannot be maintained, capture stops. This decision does not replace that rule and does not finish the consent policy.

## Logs

Logs never contain meeting content. A purge or a deletion request logs identifiers and a fixed category only:

- `meeting_content_purged`, with the session id and the artifact id
- `meeting_content_deleted_on_request`, with the session id, the artifact id, and the requester's Discord user id
- `meeting_content_purge_failed`, with the session id, the artifact id, and a fixed category such as `discord_receipt_missing` or `provider_delete_unsupported`

The line omits audio, transcript text, summaries, titles, participant speech, file contents, channel message text, and any free-text reason. The same omission already applies to reminder, brief, and startup logs.

## What this does not decide

Who may start or stop capture, who may read transcripts, or who may request deletion. How late arrivals and withdrawals are handled. The maximum capture duration, the budget, the language, and which transcription provider or local model is used. Whether a future voice library installs on the Pi. Whether summaries are implemented. Whether non-content session rows should later be expired. Voice UDP on the Pi, which remains pending in decision 0006. This record does not implement the purge, and it does not complete issue #8.
